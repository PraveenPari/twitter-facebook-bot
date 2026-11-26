"""
Twitter to Facebook & Instagram Bot
Monitors X/Twitter accounts via multi-channel fetcher (FxTwitter API/RSS, optional cookies,
X Guest GraphQL, X Syndication) + YouTube Live Monitor
"""
import asyncio
import json
import os
import random
import re
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

# 3rd party
import requests
import yt_dlp
import logging

from twitter_fetcher import TwitterFetcher, UserSuspendedError, parse_timestamp

# Configure Logging
# Force UTF-8 for stdout on Windows to support emojis
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("bot_run.log", mode='w', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Gemini AI removed - not needed

# Import YouTube monitor
try:
    import youtube_live_monitor
    HAS_YOUTUBE = True
except ImportError:
    HAS_YOUTUBE = False


def load_config():
    if os.path.exists('config.json'):
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
    else:
        config_str = os.environ.get('CONFIG_JSON')
        if not config_str:
            raise Exception("No config found!")
        config = json.loads(config_str)

    return merge_extra_twitter_accounts(config)


def load_state():
    state = {
        'last_posted_ids': {},
        'posted_tweet_ids': {},
        'global_posted_ids': [],
        'user_ids': {},
    }
    if os.path.exists('state.json'):
        try:
            with open('state.json', 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    state.update(loaded)
        except Exception:
            pass
    if not isinstance(state.get('last_posted_ids'), dict):
        state['last_posted_ids'] = {}
    if not isinstance(state.get('posted_tweet_ids'), dict):
        state['posted_tweet_ids'] = {}
    if not isinstance(state.get('global_posted_ids'), list):
        state['global_posted_ids'] = []
    if not isinstance(state.get('user_ids'), dict):
        state['user_ids'] = {}
    return state


def save_state(state):
    with open('state.json', 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)


def is_already_posted(state, feed_id, tweet_id):
    if state.get('last_posted_ids', {}).get(feed_id) == tweet_id:
        return True
    if tweet_id in state.get('posted_tweet_ids', {}).get(feed_id, []):
        return True
    if tweet_id in state.get('global_posted_ids', []):
        return True
    return False


def record_posted_tweet(state, feed_id, tweet_id, max_per_feed=50, max_global=300):
    state.setdefault('last_posted_ids', {})[feed_id] = tweet_id
    posted_map = state.setdefault('posted_tweet_ids', {})
    feed_hist = posted_map.setdefault(feed_id, [])
    if tweet_id not in feed_hist:
        feed_hist.append(tweet_id)
    if len(feed_hist) > max_per_feed:
        posted_map[feed_id] = feed_hist[-max_per_feed:]
    global_hist = state.setdefault('global_posted_ids', [])
    if tweet_id not in global_hist:
        global_hist.append(tweet_id)
    if len(global_hist) > max_global:
        state['global_posted_ids'] = global_hist[-max_global:]


def clean_text(text):
    if not text:
        return ''
    # Remove all URLs (including t.co / x.com / nitter links)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'(?:nitter|pic\.(?:twitter|x))\.\S+', '', text)
    text = re.sub(r'^(@\w+\s*)+', '', text)
    text = re.sub(r' +', ' ', text)
    return text.strip()


def extract_username(acc):
    username = (acc.get('username') or '').strip().lstrip('@')
    if not username and 'url' in acc:
        parts = [p for p in acc['url'].strip('/').split('/') if p]
        if parts:
            username = parts[-2] if parts[-1] == 'rss' and len(parts) >= 2 else parts[-1]
    return username


def merge_extra_twitter_accounts(config, raw_extra=None):
    """Merge workflow-managed extra accounts into the configured feed list once.

    GitHub Actions stores the main configuration in CONFIG_JSON. This separate environment
    value lets small source-controlled account additions take effect without needing access
    to (or replacing) that secret.
    """
    raw_extra = os.environ.get('EXTRA_TWITTER_ACCOUNTS') if raw_extra is None else raw_extra
    if not raw_extra:
        return config

    try:
        extra_accounts = json.loads(raw_extra) if isinstance(raw_extra, str) else raw_extra
    except json.JSONDecodeError as exc:
        raise ValueError("EXTRA_TWITTER_ACCOUNTS must contain valid JSON") from exc

    if isinstance(extra_accounts, dict):
        extra_accounts = [extra_accounts]
    if not isinstance(extra_accounts, list):
        raise ValueError("EXTRA_TWITTER_ACCOUNTS must be a JSON list of account objects")
    if not isinstance(config, dict):
        raise ValueError("Bot configuration must be a JSON object")

    # Match main_async's source selection: non-empty `feeds` takes precedence.
    account_key = 'feeds' if config.get('feeds') else 'twitter_accounts'
    accounts = config.setdefault(account_key, [])
    if not isinstance(accounts, list):
        raise ValueError(f"Configuration field {account_key!r} must be a list")

    seen_handles = {
        extract_username(account).casefold()
        for account in accounts
        if isinstance(account, dict) and extract_username(account)
    }
    for item in extra_accounts:
        if not isinstance(item, dict):
            raise ValueError("Each EXTRA_TWITTER_ACCOUNTS entry must be an object")
        candidate = dict(item)
        handle = extract_username(candidate)
        if not handle:
            raise ValueError("Each extra Twitter account must define a username or URL")
        if handle.casefold() in seen_handles:
            continue
        accounts.append(candidate)
        seen_handles.add(handle.casefold())

    return config


def resolve_effective_lookback(config, state, now_ts=None):
    """Widen the lookback window when the scheduler ran late.

    GitHub's shared runners frequently delay the 30-minute cron by hours, so a fixed 60-minute
    window silently drops every tweet published in the gap: the run only sees what happens to
    be inside the last hour. Widening to the real time since the previous run (bounded by
    ``settings.max_lookback_minutes``) lets the bot catch up without re-posting old content —
    posted tweet IDs are still deduplicated through ``state``.
    """
    lookback_minutes = resolve_lookback_minutes(config)
    settings = config.get('settings', {}) if isinstance(config, dict) else {}

    try:
        max_minutes = float(settings.get('max_lookback_minutes', 24 * 60))
    except (TypeError, ValueError):
        max_minutes = float(24 * 60)
    max_minutes = max(lookback_minutes, max_minutes)

    now_ts = time.time() if now_ts is None else float(now_ts)
    last_run_ts = state.get('last_run_ts') if isinstance(state, dict) else None
    try:
        last_run_ts = float(last_run_ts)
    except (TypeError, ValueError):
        last_run_ts = None

    if last_run_ts is None or last_run_ts > now_ts:
        return lookback_minutes

    # 5 minutes of slack absorbs small clock/ordering differences between runs.
    gap_minutes = (now_ts - last_run_ts) / 60.0 + 5.0
    effective = min(max(lookback_minutes, gap_minutes), max_minutes)
    if effective > lookback_minutes:
        logger.info(
            f"[CATCHUP] Previous run was {gap_minutes - 5:.0f} min ago; "
            f"widening lookback from {lookback_minutes:.0f} to {effective:.0f} min"
        )
    return effective


def resolve_max_posts_per_account(config):
    """Max number of posts to publish per source per run (bounded 1..10)."""
    settings = config.get('settings', {}) if isinstance(config, dict) else {}
    env_val = os.environ.get('MAX_POSTS_PER_ACCOUNT')
    raw = env_val if env_val is not None else settings.get('max_posts_per_account', 3)
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return 3
    return max(1, min(parsed, 10))


def resolve_max_posts_per_run(config):
    """Max number of posts to publish in a single run across all sources (bounded 1..30)."""
    settings = config.get('settings', {}) if isinstance(config, dict) else {}
    env_val = os.environ.get('MAX_POSTS_PER_RUN')
    raw = env_val if env_val is not None else settings.get('max_posts_per_run', 10)
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return 10
    return max(1, min(parsed, 30))


def extract_hashtags(config):
    """Collect hashtag/keyword search sources from config.

    Accepts either plain strings ("#TVK") or objects ({"query": "#TVK", "id": "tvk_tag"}).
    Returns a de-duplicated list of {"id", "query"} dicts.
    """
    if not isinstance(config, dict):
        return []

    settings = config.get('settings', {})
    search_cfg = config.get('hashtag_search') or settings.get('hashtag_search') or {}
    if isinstance(search_cfg, dict) and not search_cfg.get('enabled', True):
        return []

    raw = None
    if isinstance(search_cfg, dict):
        raw = (
            search_cfg.get('queries')
            or search_cfg.get('hashtag_feeds')
            or search_cfg.get('feeds')
        )
    elif isinstance(search_cfg, (str, list)):
        raw = search_cfg
    if raw is None:
        raw = (
            config.get('hashtag_feeds')
            or settings.get('hashtag_feeds')
            or config.get('hashtags')
            or config.get('searches')
        )
    # Keep TVK discovery enabled for existing CONFIG_JSON secrets that predate the new setting.
    # Users can explicitly turn it off with hashtag_search.enabled = false.
    if not raw:
        raw = [{'id': 'hashtag_tvk', 'query': '#TVK'}]
    if isinstance(raw, (str, dict)):
        raw = [raw]

    out = []
    seen = set()
    for idx, item in enumerate(raw):
        if isinstance(item, str):
            query = item.strip()
            feed_id = f"hashtag_{re.sub(r'[^A-Za-z0-9]+', '_', query.strip('#')) or idx}"
        elif isinstance(item, dict):
            query = (item.get('query') or item.get('q') or item.get('hashtag') or '').strip()
            feed_id = (item.get('id') or '').strip() or (
                f"hashtag_{re.sub(r'[^A-Za-z0-9]+', '_', query.strip('#')) or idx}"
            )
        else:
            continue

        if not query:
            continue
        # Bare single words are treated as hashtags; phrases/operators are passed through as-is.
        if (
            ' ' not in query
            and not query.startswith(('#', '@'))
            and ':' not in query
        ):
            query = f"#{query}"

        key = query.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({'id': feed_id, 'query': query})

    return out


def select_tweets_for_posting(
    tweets,
    feed_id,
    state,
    max_age_seconds,
    now_ts,
    max_per_feed,
    return_backlog=False,
):
    """Pick the publishable tweets for one source, newest usable first.

    Previously only ``posts_within_window[0]`` was ever queued, so every source contributed a
    single post per run and anything posted afterwards was silently dropped: the next run's
    lookback window had already moved past it. Now up to ``max_per_feed`` distinct media posts
    are returned so a source with several new videos/photos is not throttled to one item.
    """
    publishable = []

    for tweet in tweets:
        tweet_id = str(tweet.get('id') or '').strip()
        if not tweet_id:
            continue

        if tweet.get('is_pinned'):
            continue

        if is_already_posted(state, feed_id, tweet_id):
            continue

        if not tweet.get('has_video') and not tweet.get('media_url'):
            continue

        within_window, age_str = is_tweet_within_window(tweet, max_age_seconds, now_ts=now_ts)
        if not within_window:
            continue

        media_type = "VIDEO" if tweet.get('has_video') else "IMAGE"
        candidate = dict(tweet)
        candidate['id'] = tweet_id
        candidate['media_type'] = media_type
        candidate['age_seconds'] = _tweet_age_seconds(tweet, now_ts)
        publishable.append((candidate, age_str))

    # Newest first, then trim to the per-source cap. Tell the caller if the run must keep its
    # catch-up watermark so older eligible posts can be fetched again on the next invocation.
    publishable.sort(key=lambda pair: pair[0]['age_seconds'])
    truncated = len(publishable) > max_per_feed
    selected = publishable[:max_per_feed]
    return (selected, truncated) if return_backlog else selected


def _tweet_age_seconds(tweet, now_ts):
    ts = tweet.get('created_timestamp')
    if ts is None:
        ts = parse_timestamp(tweet.get('date_str'), tweet.get('id'))
    if ts is None:
        return float('inf')
    return max(0.0, float(now_ts) - float(ts))


def trim_posts_for_run(posts, max_posts):
    """Keep a balanced, newest-first slice of the queue for a single run.

    Videos keep their traditional priority, but no single source may take more than one slot
    in this run while other sources still have queued posts waiting, so one busy account cannot
    starve the rest.
    """
    remainder = sorted(
        posts,
        key=lambda item: (
            not bool(item['tweet'].get('has_video')),
            item.get('age_seconds') if item.get('age_seconds') is not None else float('inf'),
        ),
    )

    selected = []
    deferred = []
    used_feeds = set()

    for item in remainder:
        if len(selected) >= max_posts:
            deferred.append(item)
            continue
        if item['feed_id'] in used_feeds:
            deferred.append(item)
            continue
        selected.append(item)
        used_feeds.add(item['feed_id'])

    for item in deferred:
        if len(selected) >= max_posts:
            break
        selected.append(item)

    return selected


def resolve_lookback_minutes(config):
    """Resolve lookback window in minutes, honoring env override while keeping a 60-min safety floor."""
    env_val = os.environ.get('POST_WINDOW_MINUTES')
    if env_val is not None:
        try:
            parsed = float(env_val)
            if parsed > 0:
                return parsed
        except ValueError:
            logger.warning(f"Invalid POST_WINDOW_MINUTES={env_val!r}; ignoring.")

    settings = config.get('settings', {}) if isinstance(config, dict) else {}
    configured = settings.get('post_window_minutes')
    if configured is None:
        configured = settings.get('lookback_minutes')

    if configured is not None:
        try:
            parsed = float(configured)
            if parsed > 0:
                # Preserve 60-min default floor for legacy 10-min templates on 30-min cron
                return max(parsed, 60.0)
        except (TypeError, ValueError):
            pass

    return 60.0


def is_tweet_within_window(tweet, max_age_seconds, now_ts=None):
    """Check whether a tweet falls within the lookback window. Returns (within_window, age_str)."""
    now_ts = time.time() if now_ts is None else float(now_ts)
    ts = tweet.get('created_timestamp')
    if ts is None:
        ts = parse_timestamp(tweet.get('date_str'), tweet.get('id'))
    if ts is None:
        return True, tweet.get('date_str') or 'unknown'
    age_sec = max(0.0, float(now_ts) - float(ts))
    age_td = timedelta(seconds=int(age_sec))
    return age_sec <= max_age_seconds, str(age_td)


# Fixed TVK Hashtags - 25 hashtags for all posts
TVK_HASHTAGS = [
    "#TVK", "#ThamizhagaVetriKazhagam", "#ThalapathyVijay", "#TamilNadu",
    "#tvkvijayofficial", "#tvkvijay", "#tvkfortn", "#tvkmaanadu", "#tvkvijayspeech",
    "#tvkvijayhq", "#actorvijay", "#actorvijayfansclub", "#actorvijayteam",
    "#actorvijayofficial", "#actorvijayanna", "#Vijay", "#VijayPolitics",
    "#TNPolitics", "#TamilNadu2026", "#VijayForCM", "#TamilPolitics",
    "#VijayFans", "#VijayArmy", "#ThalapathyForever", "#TVKParty"
]

def generate_hashtags(content=None):
    """Return the fixed 25 TVK hashtags for all posts."""
    return TVK_HASHTAGS.copy()

# Caption enhancement removed - using original caption


def download_media(url, is_video=False, tweet_link=None):
    """Download media directly via requests, falling back to yt-dlp for videos."""
    temp_dir = tempfile.gettempdir()
    unique_tag = f"{int(time.time() * 1000)}_{os.getpid()}_{random.randint(100, 999)}"
    try:
        if is_video:
            # 1. Fast path: direct MP4 URL from FxTwitter / GraphQL / twikit
            if url and ('.mp4' in url.split('?')[0] or 'video.twimg.com' in url):
                logger.info(f"Downloading direct MP4 video from {url}...")
                try:
                    with requests.get(
                        url,
                        stream=True,
                        timeout=120,
                        headers={'User-Agent': 'Mozilla/5.0'},
                    ) as r:
                        if r.status_code == 200:
                            path = os.path.join(temp_dir, f"temp_vid_{unique_tag}.mp4")
                            with open(path, 'wb') as f:
                                for chunk in r.iter_content(chunk_size=65536):
                                    if chunk:
                                        f.write(chunk)
                            if os.path.exists(path) and os.path.getsize(path) > 1024:
                                logger.info(f"Video downloaded directly: {path}")
                                return path
                            if os.path.exists(path):
                                os.unlink(path)
                        else:
                            logger.warning(f"Direct MP4 download returned HTTP {r.status_code}; trying yt-dlp fallback")
                except Exception as e:
                    logger.warning(f"Direct MP4 download failed ({e}); trying yt-dlp fallback")

            # 2. Fallback: yt-dlp against canonical tweet URL
            target_url = tweet_link or url
            if target_url:
                if 'nitter' in target_url:
                    target_url = re.sub(r'https?://nitter\.[^/]+', 'https://x.com', target_url)
                logger.info(f"Downloading video via yt-dlp from {target_url}...")
                out_tmpl = os.path.join(temp_dir, 'temp_ytdlp_%(id)s.%(ext)s')
                ydl_opts = {
                    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                    'outtmpl': out_tmpl,
                    'quiet': True,
                    'merge_output_format': 'mp4',
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(target_url, download=True)
                    if info:
                        path = ydl.prepare_filename(info)
                        if not os.path.exists(path):
                            vid_id = str(info.get('id') or '')
                            potential_files = [
                                f for f in os.listdir(temp_dir)
                                if vid_id and vid_id in f
                            ]
                            if potential_files:
                                path = os.path.join(temp_dir, potential_files[0])
                            else:
                                logger.error(f"Downloaded file not found for ID {vid_id}")
                                return None
                        logger.info(f"Video downloaded via yt-dlp: {path}")
                        return path
        else:
            if not url:
                return None
            logger.info(f"Downloading image from {url}...")
            r = requests.get(url, timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
            if r.status_code == 200 and r.content:
                ctype = (r.headers.get('Content-Type') or '').lower()
                ext = '.png' if 'png' in ctype else '.jpg'
                path = os.path.join(temp_dir, f"temp_img_{unique_tag}{ext}")
                with open(path, 'wb') as f:
                    f.write(r.content)
                logger.info(f"Image downloaded: {path}")
                return path
            logger.warning(f"Image download returned HTTP {r.status_code} for {url}")
    except Exception as e:
        logger.error(f"Media download fail: {e}")
    return None

def post_facebook(page_id, token, msg, media_path=None, is_video=False, is_sched=False, sched_time=None):
    """Post content to Facebook with proper file handling"""
    url = f"https://graph.facebook.com/v22.0/{page_id}/feed"
    data = {'message': msg, 'access_token': token}
    file_handle = None
    
    if media_path:
        if not os.path.exists(media_path):
            logger.error(f"Media file not found: {media_path} - Skipping Facebook post")
            return {'error': 'Media file missing'}
        
        # Check file size
        file_size = os.path.getsize(media_path)
        logger.info(f"Media file size: {file_size / 1024 / 1024:.2f} MB")
             
        try:
            if is_video:
                url = url.replace('/feed', '/videos')
                data['description'] = msg
                # Remove 'message' as videos use 'description'
                if 'message' in data:
                    del data['message']
                logger.info(f"Posting VIDEO to Facebook...")
            else:
                url = url.replace('/feed', '/photos')
                data['caption'] = msg
                # Remove 'message' as photos use 'caption'
                if 'message' in data:
                    del data['message']
                logger.info(f"Posting IMAGE to Facebook...")
        except Exception as e:
            logger.error(f"Error preparing media upload: {e}")
            return {'error': f"Preparation error: {e}"}
    else:
        logger.info(f"Posting TEXT to Facebook...")
            
    if is_sched and sched_time:
        data['published'] = 'false'
        data['scheduled_publish_time'] = sched_time
        logger.info(f"Scheduling post for {sched_time}")
        
    try:
        if media_path:
            # Use context manager for proper file handling
            with open(media_path, 'rb') as file_handle:
                files = {'source': file_handle}
                timeout_seconds = 600 if is_video else 120  # 10 min for video, 2 min for image
                r = requests.post(url, data=data, files=files, timeout=timeout_seconds)
        else:
            r = requests.post(url, data=data, timeout=60)
        
        res = r.json()
        if 'error' in res:
            error_msg = res.get('error', {})
            if isinstance(error_msg, dict):
                logger.error(f"Facebook API Error: Code={error_msg.get('code')} Type={error_msg.get('type')} Message={error_msg.get('message')}")
            else:
                logger.error(f"Facebook API Error: {error_msg}")
        else:
            logger.info(f"Facebook Post Success: {res}")
        return res
    except requests.exceptions.Timeout:
        logger.error(f"Facebook Request Timeout (media too large or slow connection)")
        return {'error': 'Request timeout'}
    except Exception as e:
        logger.error(f"Facebook Request Failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {'error': str(e)}

def post_instagram(ig_user_id, token, msg, media_path=None, is_video=False, is_sched=False, sched_time=None):
    """Post content to Instagram using Graph API with proper container flow"""
    if not media_path:
        logger.warning("Instagram requires media - skipping text-only post")
        return {'error': 'Instagram requires media'}
        
    if not os.path.exists(media_path):
        logger.error(f"Media file not found for Instagram: {media_path} - Skipping")
        return {'error': 'Media file missing'}
    
    try:
        container_id = None
        
        # Step 1: Create media container
        if is_video:
            # Check video duration first to determine media type
            video_duration = None
            try:
                import subprocess
                result = subprocess.run(
                    ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', 
                     '-of', 'default=noprint_wrappers=1:nokey=1', media_path],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0:
                    video_duration = float(result.stdout.strip())
                    logger.info(f"Video duration: {video_duration:.1f} seconds ({video_duration/60:.1f} minutes)")
            except FileNotFoundError:
                logger.warning("ffprobe not found - defaulting to REELS")
            except Exception as e:
                logger.warning(f"Could not check video duration: {e} - defaulting to REELS")
            
            # Determine media type based on duration:
            # Instagram deprecated VIDEO type in 2024 - ALL videos must now use REELS
            # - REELS: 3 seconds to 15 minutes (was 90 seconds, now extended)
            # - Skip: Over 15 minutes
            
            if video_duration is not None:
                if video_duration > 900:  # Over 15 minutes (REELS max)
                    logger.warning(f"Video too long for Instagram REELS: {video_duration/60:.1f} minutes (max 15 min) - SKIPPING Instagram")
                    return {'error': 'Video too long for Instagram REELS (max 15 minutes)', 'skipped': True}
                elif video_duration < 3:  # Under 3 seconds
                    logger.warning(f"Video too short for Instagram REELS: {video_duration:.1f}s (min 3s) - SKIPPING Instagram")
                    return {'error': 'Video too short for Instagram REELS (min 3 seconds)', 'skipped': True}
                else:
                    media_type = 'REELS'
                    logger.info(f"Creating Instagram REELS container (duration: {video_duration:.1f}s)...")
            else:
                # Default to REELS if we couldn't determine duration
                media_type = 'REELS'
                logger.info(f"Creating Instagram REELS container (duration unknown)...")
            
            # Read the video file
            with open(media_path, 'rb') as f:
                video_data = f.read()
            
            file_size = len(video_data)
            logger.info(f"Video file size: {file_size} bytes ({file_size / 1024 / 1024:.2f} MB)")
            
            # Check video file size (max 1GB for REELS)
            max_size_mb = 1000
            if file_size > max_size_mb * 1024 * 1024:
                logger.error(f"Video too large for Instagram REELS: {file_size / 1024 / 1024:.2f} MB (max {max_size_mb}MB)")
                return {'error': f'Video too large for Instagram REELS (max {max_size_mb}MB)'}
            
            # Method: Resumable Upload (Directly upload local file bytes to FB)
            # This is the most reliable method as it avoids 3rd party hosts.
            logger.info(f"Using Resumable Upload (Direct) for Instagram {media_type}...")
            init_url = f"https://graph.facebook.com/v22.0/{ig_user_id}/media"
            init_data = {
                'media_type': media_type,
                'caption': msg,
                'access_token': token,
                'upload_type': 'resumable'
            }
            
            if is_sched and sched_time:
                init_data['scheduled_publish_time'] = sched_time
                logger.info(f"Scheduling Instagram {media_type} (Resumable) for {sched_time}")
            
            init_resp = requests.post(init_url, data=init_data)
            init_result = init_resp.json()
            
            if 'id' not in init_result:
                logger.error(f"Instagram container init failed: {init_result}")
                return init_result
            
            container_id = init_result['id']
            logger.info(f"Container created: {container_id}")
            
            # Get upload URI from response
            upload_url = init_result.get('uri', f"https://rupload.facebook.com/ig-api-upload/v22.0/{container_id}")
            logger.info(f"Upload URL: {upload_url}")
            
            # Upload the video bytes with correct headers
            headers = {
                'Authorization': f'OAuth {token}',
                'offset': '0',
                'file_size': str(file_size),
                'Content-Type': 'application/octet-stream'
            }
            
            upload_resp = requests.post(upload_url, headers=headers, data=video_data, timeout=600)
            logger.info(f"Video upload response: {upload_resp.status_code}")
            
            if upload_resp.status_code != 200:
                logger.error(f"Upload failed: {upload_resp.text}")
                return {'error': f'Upload failed: {upload_resp.status_code}', 'details': upload_resp.text}
            
            upload_result = upload_resp.json() if upload_resp.text else {}
            logger.info(f"Upload result: {upload_result}")
            
        else:
            # For images - Instagram requires public URL
            logger.info(f"Creating Instagram IMAGE container...")
            
            # Option 1: Try using imgbb.com free hosting (no API key needed for anon uploads)
            # Option 2: Use catbox.moe or other free hosts
            # Option 3: Try to extract URL from Facebook upload
            
            image_url = None
            
            # Read image data once
            with open(media_path, 'rb') as f:
                image_bytes = f.read()
            
            # Method: Freeimage.host (High speed, ImgBB/Chevereto compatible API)
            # This aligns with the user's request for a fast "Developer API" service.
            # Freeimage.host is known for speed and reliability compared to Catbox.
            image_url = None
            if not image_url:
                try:
                    logger.info("Uploading image to Freeimage.host (Fast API)...")
                    import base64
                    image_data = base64.b64encode(image_bytes).decode('utf-8')
                    
                    # Freeimage.host uses the Chevereto API (same as ImgBB)
                    # This public key is widely available for anonymous uploads
                    api_key = "6d207e02198a847aa98d0a2a901485a5" 
                    
                    upload_url = "https://freeimage.host/api/1/upload"
                    payload = {
                        'key': api_key,
                        'image': image_data,
                        'expiration': 600 # 10 minutes (sufficient for IG processing)
                    }
                    
                    resp = requests.post(upload_url, data=payload, timeout=60)
                    result = resp.json()
                    
                    if result.get('status_code') == 200:
                        image_url = result['image']['url']
                        logger.info(f"Image hosted at Freeimage.host: {image_url}")
                    else:
                        logger.error(f"Freeimage.host upload failed: {result}")
                        
                except Exception as e:
                    logger.warning(f"Freeimage.host upload error: {e}")

            # Fallback: Tmpfiles.org (Extremely fast, temporary storage)
            if not image_url:
                try:
                    logger.info("Fallback: Uploading to Tmpfiles.org...")
                    # Tmpfiles API
                    files = {'file': image_bytes}
                    resp = requests.post('https://tmpfiles.org/api/v1/upload', files=files, timeout=60)
                    result = resp.json()
                    
                    if result.get('status') == 'success':
                        # Convert partial URL to direct download URL
                        # URL format: https://tmpfiles.org/12345/image.jpg -> https://tmpfiles.org/dl/12345/image.jpg
                        raw_url = result['data']['url']
                        direct_url = raw_url.replace('.org/', '.org/dl/')
                        image_url = direct_url
                        logger.info(f"Image hosted at Tmpfiles.org: {image_url}")
                except Exception as e:
                     logger.warning(f"Tmpfiles upload error: {e}")

            # Method 2: Fallback to imgbb upload
            if not image_url:
                try:
                    import base64
                    image_data = base64.b64encode(image_bytes).decode('utf-8')
                    
                    imgbb_url = "https://api.imgbb.com/1/upload"
                    imgbb_key = os.environ.get('IMGBB_API_KEY', '6d207e02198a847aa98d0a2a901485a5')  # Free public key
                    
                    imgbb_data = {
                        'key': imgbb_key,
                        'image': image_data,
                        'expiration': 600  # 10 minutes
                    }
                    
                    imgbb_resp = requests.post(imgbb_url, data=imgbb_data, timeout=60)
                    imgbb_result = imgbb_resp.json()
                    
                    if imgbb_result.get('success'):
                        image_url = imgbb_result['data']['url']
                        logger.info(f"Image hosted at imgbb: {image_url}")
                    else:
                        logger.warning(f"imgbb upload failed: {imgbb_result}")
                except Exception as e:
                    logger.warning(f"imgbb upload error: {e}")
            

            
            if not image_url:
                logger.error("Failed to host image for Instagram - all upload services failed")
                return {'error': 'Could not host image for Instagram - all hosting services failed'}
            
            # Create container with image URL
            container_url = f"https://graph.facebook.com/v22.0/{ig_user_id}/media"
            container_data = {
                'image_url': image_url,
                'caption': msg,
                'access_token': token
            }
            
            if is_sched and sched_time:
                container_data['scheduled_publish_time'] = sched_time
                logger.info(f"Scheduling Instagram Post for {sched_time}")
            
            container_resp = requests.post(container_url, data=container_data)
            container_result = container_resp.json()
            
            if 'id' not in container_result:
                logger.error(f"Instagram container failed: {container_result}")
                return container_result
            
            container_id = container_result['id']
            logger.info(f"Image container created: {container_id}")
        
        # Step 2: Wait for container to be ready
        logger.info("Waiting for Instagram media processing...")
        max_wait = 60 if not is_video else 30  # More retries for video
        
        for attempt in range(max_wait):
            status_url = f"https://graph.facebook.com/v22.0/{container_id}"
            status_resp = requests.get(status_url, params={
                'fields': 'status_code,status',
                'access_token': token
            }, timeout=30)
            status = status_resp.json()
            
            status_code = status.get('status_code', '')
            logger.info(f"Container status [{attempt+1}/{max_wait}]: {status_code}")
            
            if status_code == 'FINISHED':
                logger.info("Instagram media ready for publishing!")
                break
            elif status_code == 'ERROR':
                error_msg = status.get('status', 'Unknown error')
                logger.error(f"Instagram processing failed: {error_msg}")
                return {'error': error_msg, 'status': status}
            elif status_code == 'IN_PROGRESS':
                time.sleep(5)  # Wait 5 seconds before next check
            else:
                time.sleep(3)  # Unknown status, wait a bit
        else:
            logger.error("Timeout waiting for Instagram media processing")
            return {'error': 'Timeout waiting for media processing'}
        
        # Step 3: Publish the container
        if is_sched and sched_time:
            logger.info("Content scheduled - skipping immediate publish")
            return {'id': container_id, 'scheduled': True}
            
        logger.info("Publishing to Instagram...")
        
        publish_url = f"https://graph.facebook.com/v22.0/{ig_user_id}/media_publish"
        publish_data = {
            'creation_id': container_id,
            'access_token': token
        }
        
        publish_resp = requests.post(publish_url, data=publish_data, timeout=60)
        result = publish_resp.json()
        
        if 'id' in result:
            logger.info(f"Instagram Post Success: {result}")
        else:
            logger.error(f"Instagram Post Failed: {result}")
        
        return result
        
    except Exception as e:
        logger.error(f"Instagram Request Failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {'error': str(e)}

async def main_async():
    logger.info("=" * 60)
    logger.info("Bot Started: Multi-Channel X/Twitter Fetcher + YouTube Live")
    logger.info("=" * 60)

    config = load_config()
    state = load_state()

    # 1. Check YouTube Live
    if HAS_YOUTUBE and config.get('youtube_restream', {}).get('enabled'):
        logger.info("Checking YouTube Live...")
        if youtube_live_monitor.check_and_restream(config):
            logger.info("Re-streaming started. Stopping Twitter check.")
            return  # Stop if re-streaming

    # 2. Fetch X/Twitter timelines (FxTwitter API/RSS -> optional twikit -> X Guest GraphQL -> Syndication)
    settings = config.get('settings', {}) if isinstance(config, dict) else {}
    lookback_minutes = resolve_effective_lookback(config, state)
    max_age_seconds = lookback_minutes * 60.0
    schedule_gap_minutes = max(1, int(settings.get('schedule_gap_minutes', 10) or 10))
    include_retweets = settings.get('include_retweets', True)
    max_posts_per_account = resolve_max_posts_per_account(config)
    max_per_run = resolve_max_posts_per_run(config)
    twitter_cfg = config.get('twitter', {}) if isinstance(config, dict) else {}

    fetcher = TwitterFetcher(
        user_id_cache=state['user_ids'],
        cookies=twitter_cfg.get('cookies'),
        include_retweets=include_retweets,
    )

    accounts = config.get('feeds', []) or config.get('twitter_accounts', [])
    account_count = len(accounts)
    hashtag_sources = extract_hashtags(config)
    logger.info(
        f"Loaded {len(accounts)} accounts and {len(hashtag_sources)} hashtag searches "
        f"(lookback: {lookback_minutes:.0f} min, max {max_per_run} posts/run)."
    )

    usernames = [extract_username(acc) for acc in accounts]
    results_list = [[] for _ in accounts]
    fetch_sources = ['none' for _ in accounts]
    failed_indices = []

    BATCH_SIZE = 3

    async def fetch_one(username):
        if not username:
            return [], 'invalid_username'
        return await fetcher.afetch_user_tweets(username, limit=20)

    # First pass - fetch accounts in batches of 3
    for batch_start in range(0, len(usernames), BATCH_SIZE):
        batch_indices = list(range(batch_start, min(batch_start + BATCH_SIZE, len(usernames))))
        batch_names = [usernames[idx] for idx in batch_indices]
        logger.info(f"[BATCH] Fetching {len(batch_names)} accounts: {batch_names}")

        tasks = [fetch_one(usernames[idx]) for idx in batch_indices]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        for idx, res in zip(batch_indices, batch_results):
            username = usernames[idx]
            if isinstance(res, Exception):
                logger.error(f"[ERROR] {username}: {res}")
                failed_indices.append(idx)
                fetch_sources[idx] = 'none'
            else:
                tweets, source = res
                results_list[idx] = tweets
                fetch_sources[idx] = source
                if source == 'suspended':
                    logger.warning(f"[SUSPENDED] {username}: Account is suspended on X (skipping)")
                elif source == 'none':
                    logger.warning(f"[FAIL] {username}: All fetch channels returned nothing")
                    failed_indices.append(idx)
                elif not tweets:
                    logger.info(f"[OK] {username} ({source}): 0 tweets")
                else:
                    logger.info(f"[OK] {username} ({source}): Got {len(tweets)} tweets")

        if batch_start + BATCH_SIZE < len(usernames):
            await asyncio.sleep(1.5)

    # Retry pass for transient failures only (skip suspended/empty/invalid)
    if failed_indices:
        retry_names = [usernames[idx] for idx in failed_indices]
        logger.info(f"[RETRY] Retrying {len(failed_indices)} failed accounts: {retry_names}")
        await asyncio.sleep(3)

        for idx in failed_indices:
            username = usernames[idx]
            logger.info(f"[RETRY] Retrying {username}...")
            try:
                tweets, source = await fetch_one(username)
                results_list[idx] = tweets
                fetch_sources[idx] = source
                if tweets:
                    logger.info(f"[RETRY OK] {username} ({source}): Got {len(tweets)} tweets")
                elif source == 'suspended':
                    logger.warning(f"[RETRY SUSPENDED] {username}: Account is suspended on X")
                else:
                    logger.warning(f"[RETRY FAIL] {username} ({source}): Still no tweets")
            except Exception as e:
                logger.error(f"[RETRY ERROR] {username}: {e}")
            await asyncio.sleep(1.5)

    success_count = sum(1 for src in fetch_sources if src not in ('none', 'suspended', 'invalid_username'))
    logger.info(f"[DONE] Checked {success_count}/{len(accounts)} reachable accounts successfully")

    # Hashtag / keyword searches (e.g. #TVK). These are extra sources appended to the same
    # result lists so they flow through the identical filtering, dedupe and posting pipeline.
    search_cfg = config.get('hashtag_search') or settings.get('hashtag_search') or {}
    try:
        hashtag_limit = max(1, min(int(search_cfg.get('limit', 40)), 100))
    except (AttributeError, TypeError, ValueError):
        hashtag_limit = 40
    hashtag_media_only = bool(search_cfg.get('media_only', False)) if isinstance(search_cfg, dict) else False
    hashtag_fetch_failed = False

    if hashtag_sources:
        for item in hashtag_sources:
            query = item['query']
            feed_id = item['id']
            logger.info(f"[SEARCH] Fetching posts for {query}...")
            try:
                tweets, source = await fetcher.asearch_tweets(
                    query,
                    limit=hashtag_limit,
                    media_only=hashtag_media_only,
                )
            except Exception as e:
                logger.error(f"[SEARCH ERROR] {query}: {e}")
                tweets, source = [], 'none'

            accounts.append({'id': feed_id, 'username': feed_id})
            usernames.append(query)
            results_list.append(tweets or [])
            fetch_sources.append(source)
            if source in ('none', 'search_unavailable'):
                hashtag_fetch_failed = True

            if tweets:
                logger.info(f"[SEARCH OK] {query} ({source}): Got {len(tweets)} tweets")
            elif source == 'search_unavailable':
                logger.warning(
                    f"[SEARCH UNAVAILABLE] {query}: public search did not return results. "
                    f"Check FxTwitter availability or set TWITTER_COOKIES (auth_token + ct0) "
                    f"for authenticated X search."
                )
            else:
                logger.info(f"[SEARCH] {query} ({source}): 0 tweets")

            await asyncio.sleep(1.5)

    # Persist newly cached user_ids right away
    save_state(state)

    # Process results
    now_ts = time.time()
    posts_to_make = []
    has_post_backlog = False
    incomplete_fetch = hashtag_fetch_failed or any(
        source in ('none', 'search_unavailable')
        for source in fetch_sources[:account_count]
    )

    for i, tweets in enumerate(results_list):
        acc = accounts[i]
        feed_id = acc.get('id') or extract_username(acc) or 'unknown'
        source = fetch_sources[i]

        if source == 'suspended':
            continue

        if not tweets:
            if source == 'none':
                logger.warning(f"[{feed_id}] No tweets fetched (all channels failed)")
            else:
                logger.info(f"[{feed_id}] No tweets returned ({source})")
            continue

        selected, source_truncated = select_tweets_for_posting(
            tweets,
            feed_id,
            state,
            max_age_seconds,
            now_ts,
            max_posts_per_account,
            return_backlog=True,
        )
        has_post_backlog = has_post_backlog or source_truncated
        for tweet, age_str in selected:
            logger.info(f"[FOUND] [{feed_id}] {tweet['media_type']} {tweet['id']} (Age: {age_str}, via {source})")
            posts_to_make.append({
                'feed_id': feed_id,
                'tweet': tweet,
                'age_seconds': tweet.get('age_seconds'),
            })

    # Deduplicate same tweet ID across multiple accounts (e.g. retweets), preferring non-retweet
    deduped_posts = {}
    for item in posts_to_make:
        tid = str(item['tweet']['id'])
        existing = deduped_posts.get(tid)
        if existing is None or (existing['tweet'].get('is_retweet') and not item['tweet'].get('is_retweet')):
            deduped_posts[tid] = item
    posts_to_make = list(deduped_posts.values())

    logger.info(f"Found {len(posts_to_make)} new posts with media (limit {max_per_run} per run).")

    # Cap the number of posts per run so a backlog never floods the page. Keep the old
    # catch-up watermark if anything remains unselected; the posted-ID set will remove the
    # already delivered items on the next run and let the remaining backlog drain safely.
    if len(posts_to_make) > max_per_run:
        has_post_backlog = True
        logger.info(f"[CAP] Keeping {max_per_run} of {len(posts_to_make)} posts for this run")
        posts_to_make = trim_posts_for_run(posts_to_make, max_per_run)

    logger.info(f"Found {len(posts_to_make)} new posts with media.")

    # Separate videos (priority) and images
    video_posts = [p for p in posts_to_make if p['tweet'].get('has_video')]
    image_posts = [p for p in posts_to_make if not p['tweet'].get('has_video')]
    all_posts = video_posts + image_posts

    logger.info(f"[QUEUE] {len(video_posts)} videos + {len(image_posts)} images = {len(all_posts)} total")

    # 3. Post to Facebook & Instagram
    fb_cfg = config.get('facebook', {}) if isinstance(config, dict) else {}
    page_id = os.environ.get('FB_PAGE_ID') or fb_cfg.get('page_id')
    token = os.environ.get('FB_ACCESS_TOKEN') or fb_cfg.get('access_token')

    ig_cfg = config.get('instagram', {}) if isinstance(config, dict) else {}
    ig_enabled = ig_cfg.get('enabled', False)
    ig_user_id = os.environ.get('IG_USER_ID') or ig_cfg.get('user_id')
    ig_token = os.environ.get('IG_ACCESS_TOKEN') or ig_cfg.get('access_token')

    post_stats = []
    downloaded_files = []
    ready_post_count = 0
    has_unposted_failures = False

    for item in all_posts:
        tweet = item['tweet']
        is_video = tweet.get('has_video', False)
        media_type = "VIDEO" if is_video else "IMAGE"

        # Download media
        if is_video:
            media_path = download_media(tweet.get('video_url'), is_video=True, tweet_link=tweet.get('link'))
        else:
            media_path = download_media(tweet.get('media_url'), is_video=False)

        if not media_path:
            logger.error(f"Failed to download {media_type} for {item['feed_id']}")
            has_unposted_failures = True
            post_stats.append({
                'id': item['feed_id'],
                'type': media_type.lower(),
                'status': 'failed',
                'error': 'download_failed',
            })
            continue

        downloaded_files.append(media_path)

        # First deliverable post = immediate, subsequent posts = spaced by schedule_gap_minutes (min +20m)
        if ready_post_count == 0:
            is_scheduled = False
            sched_time = None
            logger.info(f"[NOW] Posting {media_type} for {item['feed_id']}...")
        else:
            is_scheduled = True
            current_time = int(time.time())
            offset_seconds = 1200 + (ready_post_count - 1) * schedule_gap_minutes * 60
            sched_time = current_time + offset_seconds
            logger.info(f"[SCHEDULE +{offset_seconds // 60}min] {media_type} for {item['feed_id']}...")
        ready_post_count += 1

        # Build caption with hashtags
        msg = clean_text(tweet.get('text', ''))
        tags = generate_hashtags(msg)
        final_msg = f"{msg}\n\n{' '.join(tags)}" if msg else ' '.join(tags)

        # Post to Facebook
        res = post_facebook(page_id, token, final_msg, media_path, is_video=is_video, is_sched=is_scheduled, sched_time=sched_time)
        fb_success = 'id' in res or 'post_id' in res
        post_stats.append({
            'id': item['feed_id'],
            'type': media_type.lower(),
            'platform': 'facebook',
            'status': 'success' if fb_success else 'failed',
            'error': res.get('error'),
        })

        # Post to Instagram
        ig_success = False
        ig_res = {}
        if ig_enabled and ig_user_id:
            logger.info(f"[IG] Posting {media_type} to Instagram for {item['feed_id']}...")
            ig_res = post_instagram(ig_user_id, ig_token, final_msg, media_path, is_video=is_video, is_sched=False, sched_time=None)
            ig_success = 'id' in ig_res

        if ig_res.get('skipped'):
            logger.info(f"[IG SKIP] {item['feed_id']}: {ig_res.get('error')}")
        elif ig_success:
            logger.info(f"[IG OK] {media_type} posted to Instagram for {item['feed_id']}")
            post_stats.append({
                'id': item['feed_id'],
                'type': media_type.lower(),
                'platform': 'instagram',
                'status': 'success',
            })
        elif ig_enabled and ig_user_id:
            logger.error(f"[IG FAIL] {item['feed_id']}: {ig_res.get('error')}")
            post_stats.append({
                'id': item['feed_id'],
                'type': media_type.lower(),
                'platform': 'instagram',
                'status': 'failed',
                'error': ig_res.get('error'),
            })

        if not fb_success and not ig_success:
            has_unposted_failures = True

        if fb_success or ig_success:
            record_posted_tweet(state, item['feed_id'], str(tweet['id']))
            save_state(state)
            if is_scheduled:
                ig_status_str = "posted" if ig_success else "failed/skipped"
                logger.info(f"[OK] FB scheduled, IG {ig_status_str} for {item['feed_id']}")
            else:
                ig_status_str = "IG:OK" if ig_success else "IG:FAIL/SKIP"
                logger.info(f"[OK] {media_type} posted (FB:OK {ig_status_str}) for {item['feed_id']}")

    # Advance the catch-up watermark only when every source was checked and no post is still
    # queued or failed. On the first run, retain the start of the attempted window instead.
    should_advance_watermark = not incomplete_fetch and not has_post_backlog and not has_unposted_failures
    previous_run_ts = state.get('last_run_ts')
    if should_advance_watermark:
        state['last_run_ts'] = now_ts
    elif previous_run_ts is None:
        state['last_run_ts'] = max(0.0, now_ts - max_age_seconds)
        logger.info("[CATCHUP] Holding the initial lookback watermark because work remains pending")
    else:
        logger.info("[CATCHUP] Holding the previous watermark; pending sources/posts will be retried")
    save_state(state)

    # Save Reports
    run_timestamp = datetime.now().isoformat()

    report = {
        'timestamp': run_timestamp,
        'accounts_checked': account_count,
        'searches_checked': len(hashtag_sources),
        'hashtag_queries': [item['query'] for item in hashtag_sources],
        'lookback_minutes': lookback_minutes,
        'new_posts_found': len(posts_to_make),
        'fetch_sources': {
            (usernames[idx] or accounts[idx].get('id', f'account_{idx}')): fetch_sources[idx]
            for idx in range(len(accounts))
        },
        'suspended_accounts': [
            usernames[idx]
            for idx in range(len(accounts))
            if fetch_sources[idx] == 'suspended'
        ],
        'facebook_actions': post_stats,
    }
    with open('run_report.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)

    cucumber_features = []

    elements = []
    for idx, acc in enumerate(accounts):
        username = usernames[idx] or acc.get('id', 'unknown')
        src = fetch_sources[idx]
        if src == 'suspended':
            step_status = 'skipped'
        elif src in ('none', 'invalid_username'):
            step_status = 'failed'
        else:
            step_status = 'passed'

        elements.append({
            "name": f"Check Account: {username}",
            "type": "scenario",
            "steps": [
                {
                    "name": f"Fetch {username} ({src})",
                    "result": {"status": step_status, "duration": 1000000},
                }
            ],
        })

    cucumber_features.append({
        "name": "Twitter Timeline Fetch",
        "description": "Fetch tweets via multi-channel X/Twitter fetcher",
        "uri": "main.py",
        "elements": elements,
    })

    fb_elements = []
    for action in post_stats:
        status = "passed" if action['status'] == 'success' else "failed"
        fb_elements.append({
            "name": f"Post to FB: {action['id']}",
            "type": "scenario",
            "steps": [
                {
                    "name": "Upload and Post",
                    "result": {"status": status, "error_message": action.get('error', '')},
                }
            ],
        })

    if fb_elements:
        cucumber_features.append({
            "name": "Facebook Publishing",
            "description": "Upload content to Facebook Page",
            "uri": "main.py",
            "elements": fb_elements,
        })

    with open('cucumber_report.json', 'w', encoding='utf-8') as f:
        json.dump(cucumber_features, f, indent=2)

    # Cleanup Temp Files
    try:
        for file_path in downloaded_files:
            try:
                if file_path and os.path.isfile(file_path):
                    os.unlink(file_path)
            except Exception:
                pass
        cleanup_dir = tempfile.gettempdir()
        for file in os.listdir(cleanup_dir):
            if file.startswith('temp_') or file.endswith('.mp4'):
                file_path = os.path.join(cleanup_dir, file)
                try:
                    if os.path.isfile(file_path):
                        os.unlink(file_path)
                except Exception:
                    pass
        logger.info("Temp files cleaned.")
    except Exception as e:
        logger.warning(f"Error cleaning temp files: {e}")

    logger.info("Bot Run Completed. Reports generated: run_report.json, cucumber_report.json")

    if account_count and success_count == 0 and any(
        src != 'suspended' for src in fetch_sources[:account_count]
    ):
        logger.error("All reachable X/Twitter accounts failed to fetch across all channels.")
        raise SystemExit(1)

if __name__ == '__main__':
    asyncio.run(main_async())
