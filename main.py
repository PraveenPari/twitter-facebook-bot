"""
Twitter to Facebook Bot - OPTIMIZED PARALLEL VERSION
Uses concurrent execution for faster performance
"""
import json
import os
import random
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
import requests
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Import browser scraper
from twitter_browser_scraper import TwitterBrowserScraper

try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    HAS_YTDLP = False

# Gemini AI for caption enhancement
try:
    from google import genai
    from google.genai import types
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

import base64
import mimetypes

# Fix encoding for console
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Settings
DEFAULT_POST_WINDOW_MINUTES = 60
DEFAULT_SCHEDULE_GAP_MINUTES = 10
DEFAULT_MIN_CONTENT_LENGTH = 50


def load_config():
    """Load config from file or environment"""
    if os.path.exists('config.json'):
        with open('config.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    
    config_str = os.environ.get('CONFIG_JSON')
    if config_str:
        return json.loads(config_str)
    
    raise Exception("No config found! Create config.json or set CONFIG_JSON env var")


def load_state():
    """Load state from file"""
    if os.path.exists('state.json'):
        try:
            with open('state.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {'last_posted_ids': {}}


def save_state(state):
    """Save state to file"""
    with open('state.json', 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)


def clean_text(raw_content):
    """Clean and extract plain text from tweet content"""
    if not raw_content:
        return ''
    
    text = raw_content
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'^(@\w+\s*)+', '', text)
    text = re.sub(r' +', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()


# TVK Positive Hashtags
TVK_POSITIVE_HASHTAGS = [
    "#TVK", "#ThamizhagaVetriKazhagam", "#Vijay", "#ThalapathyVijay",
    "#TVKForTamilNadu", "#TVKForPeople", "#TVKVision", "#TVKMovement",
    "#TamilNaduPolitics", "#TVKLeader", "#VijayPolitics", "#TVKSupport",
    "#TVKForChange", "#TVKForProgress", "#TVKForDevelopment",
    "#TVKArmy", "#TVKFamily", "#ThalapathyPolitics", "#TVKWave",
    "#TVKRevolution", "#TVKForYouth", "#TVKForFuture", "#TVKRising",
    "#TamilNaduFuture", "#TVKVictory", "#TVKPower", "#TVKStrong"
]

GENERAL_SEO_HASHTAGS = [
    "#TamilNadu", "#TNPolitics", "#TamilNews", "#Chennai",
    "#TamilNaduNews", "#PoliticalNews", "#IndianPolitics",
    "#SouthIndia", "#TamilPolitics", "#Breaking", "#Trending",
    "#ViralNews", "#LatestNews", "#TamilNaduUpdates"
]


def generate_seo_hashtags(content="", max_hashtags=10):
    """Generate SEO-optimized hashtags"""
    hashtags = []
    
    core_tvk = ["#TVK", "#ThamizhagaVetriKazhagam", "#ThalapathyVijay"]
    hashtags.extend(core_tvk)
    
    remaining_tvk = [h for h in TVK_POSITIVE_HASHTAGS if h not in core_tvk]
    hashtags.extend(random.sample(remaining_tvk, min(3, len(remaining_tvk))))
    
    if content:
        keyword_mapping = {
            "election": "#TNElection2026",
            "rally": "#TVKRally",
            "speech": "#TVKSpeech",
            "meeting": "#TVKMeeting",
            "youth": "#TVKYouth",
            "farmer": "#FarmersSupport",
            "education": "#EducationForAll",
            "job": "#EmploymentForYouth",
            "development": "#TNDevelopment",
            "vijay": "#Vijay",
            "thalapathy": "#Thalapathy",
            "announcement": "#TVKAnnouncement",
            "welfare": "#PeopleWelfare",
            "protest": "#TVKStand",
            "support": "#TVKSupport"
        }
        
        content_lower = content.lower()
        for keyword, hashtag in keyword_mapping.items():
            if keyword in content_lower and hashtag not in hashtags:
                hashtags.append(hashtag)
                if len(hashtags) >= max_hashtags - 2:
                    break
    
    while len(hashtags) < max_hashtags:
        remaining = [h for h in GENERAL_SEO_HASHTAGS if h not in hashtags]
        if not remaining:
            break
        hashtags.append(random.choice(remaining))
    
    seen = set()
    unique_hashtags = []
    for h in hashtags:
        h_lower = h.lower()
        if h_lower not in seen:
            seen.add(h_lower)
            unique_hashtags.append(h)
    
    return unique_hashtags[:max_hashtags]


def format_post_with_hashtags(message, hashtags):
    """Format final post with hashtags"""
    hashtag_text = " ".join(hashtags)
    formatted = f"{message}\n\n{'─' * 30}\n{hashtag_text}"
    return formatted


def enhance_caption_with_gemini(original_caption, media_path=None, media_type='text'):
    """Use Gemini AI to enhance caption (synchronous for thread pool)"""
    if not HAS_GEMINI:
        return original_caption
    
    api_key = os.environ.get('GEMINI_API_KEY', '')
    if not api_key:
        try:
            if os.path.exists('config.json'):
                with open('config.json', 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    api_key = config.get('gemini', {}).get('api_key', '')
        except:
            pass
    
    if not api_key:
        return original_caption
    
    try:
        client = genai.Client(api_key=api_key)
        
        prompt = f"""You are a Tamil political social media expert for TVK (Thamizhaga Vetri Kazhagam) party led by Vijay.

TASK: Enhance this caption for maximum Facebook engagement while keeping it POSITIVE about TVK.

ORIGINAL CAPTION:
{original_caption}

REQUIREMENTS:
1. Keep the core message intact
2. Add powerful Tamil words and phrases (transliterated)
3. Make it emotionally inspiring and hopeful
4. Add call-to-action phrases
5. Keep it concise (under 300 words)
6. Ensure ONLY POSITIVE tone about TVK and Vijay
7. Include 2-3 Tamil SEO words naturally

ENHANCED CAPTION (respond with ONLY the enhanced caption, no explanations):"""
        
        parts = [types.Part.from_text(text=prompt)]
        
        response = client.models.generate_content(
            model='gemini-2.0-flash-exp',
            contents=parts
        )
        
        if response and response.text:
            enhanced = response.text.strip()
            if len(enhanced) > 50 and len(enhanced) < 2000:
                return enhanced
        
        return original_caption
            
    except Exception as e:
        return original_caption


def post_to_facebook(page_id, token, message, media_path=None, scheduled_time=None, media_type='text'):
    """Post to Facebook page (synchronous for thread pool)"""
    try:
        if media_path and media_type == 'video':
            url = f"https://graph.facebook.com/v22.0/{page_id}/videos"
            data = {'description': message, 'access_token': token}
            if scheduled_time:
                data['published'] = 'false'
                data['scheduled_publish_time'] = int(scheduled_time)
            with open(media_path, 'rb') as f:
                response = requests.post(url, data=data, files={'source': f})
        
        elif media_path and media_type == 'image':
            url = f"https://graph.facebook.com/v22.0/{page_id}/photos"
            data = {'caption': message, 'access_token': token}
            if scheduled_time:
                data['published'] = 'false'
                data['scheduled_publish_time'] = int(scheduled_time)
            with open(media_path, 'rb') as f:
                response = requests.post(url, data=data, files={'source': f})
        
        else:
            url = f"https://graph.facebook.com/v22.0/{page_id}/feed"
            data = {'message': message, 'access_token': token}
            if scheduled_time:
                data['published'] = 'false'
                data['scheduled_publish_time'] = int(scheduled_time)
            response = requests.post(url, data=data)
        
        result = response.json()
        if 'id' in result or 'post_id' in result:
            return True, result.get('id') or result.get('post_id')
        else:
            return False, result.get('error', {}).get('message', str(result))
    except Exception as e:
        return False, str(e)


async def check_account_parallel(scraper, account_config, state, post_window, min_length):
    """Check a single account for new tweets (parallel execution)"""
    if not account_config.get('enabled', True):
        return None
    
    account_id = account_config.get('id', 'unknown')
    username = account_config.get('username', '').replace('@', '')
    
    if not username:
        return None
    
    print(f"Checking: @{username}")
    
    try:
        # Fetch latest tweet using browser
        tweets = await scraper.get_latest_tweets(username, count=1)
        
        if not tweets:
            print(f"  [{username}] No tweets found")
            return None
        
        latest_tweet = tweets[0]
        tweet_id = str(latest_tweet['id'])
        
        # Skip if not from target username (filters out promoted/sponsored tweets)
        tweet_user = latest_tweet.get('user', '').lower()
        if tweet_user != username.lower():
            print(f"  [{username}] SKIP: Sponsored (from @{tweet_user})")
            return None
        
        # Skip if already posted
        last_id = state.get('last_posted_ids', {}).get(account_id)
        if last_id == tweet_id:
            print(f"  [{username}] Already posted")
            return None
        
        # Check time window
        tweet_time = latest_tweet['created_at']
        now = datetime.now(timezone.utc)
        if tweet_time.tzinfo is None:
            tweet_time = tweet_time.replace(tzinfo=timezone.utc)
        
        age_minutes = (now - tweet_time).total_seconds() / 60
        if age_minutes > post_window:
            print(f"  [{username}] Too old ({age_minutes:.0f}min)")
            return None
        
        # Skip retweets and replies
        if latest_tweet['is_retweet']:
            print(f"  [{username}] SKIP: Retweet")
            return None
        
        if latest_tweet['is_reply']:
            print(f"  [{username}] SKIP: Reply")
            return None
        
        # Clean and check message
        message = clean_text(latest_tweet['text'])
        
        if len(message) < min_length:
            print(f"  [{username}] SKIP: Too short ({len(message)} chars)")
            return None
        
        print(f"  [{username}] OK! Valid tweet ({len(message)} chars)")
        
        return {
            'account_id': account_id,
            'tweet_id': tweet_id,
            'message': message,
            'tweet_url': latest_tweet['url'],
            'media': latest_tweet['media'],
            'has_video': latest_tweet['has_video']
        }
        
    except Exception as e:
        print(f"  [{username}] Error: {e}")
        return None


async def download_media_async(media_url, media_type):
    """Download media asynchronously"""
    loop = asyncio.get_event_loop()
    
    def download():
        try:
            response = requests.get(media_url, timeout=30, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            response.raise_for_status()
            
            ext = '.jpg' if media_type == 'image' else '.mp4'
            if media_type == 'image':
                ct = response.headers.get('content-type', '')
                if 'png' in ct:
                    ext = '.png'
                elif 'gif' in ct:
                    ext = '.gif'
                elif 'webp' in ct:
                    ext = '.webp'
            
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
            temp_file.write(response.content)
            temp_file.close()
            
            return temp_file.name
        except Exception as e:
            print(f"  [Download Error] {e}")
            return None
    
    return await loop.run_in_executor(None, download)


async def main_async():
    """Main async function - OPTIMIZED FOR SPEED"""
    print("="*60)
    print("Twitter to Facebook Bot - PARALLEL OPTIMIZED")
    print(f"Time: {datetime.now().isoformat()}")
    print("="*60)
    
    # Load config and state
    config = load_config()
    state = load_state()
    
    # Get settings
    settings = config.get('settings', {})
    post_window = settings.get('post_window_minutes', DEFAULT_POST_WINDOW_MINUTES)
    schedule_gap = settings.get('schedule_gap_minutes', DEFAULT_SCHEDULE_GAP_MINUTES)
    min_length = settings.get('min_content_length', DEFAULT_MIN_CONTENT_LENGTH)
    
    # Get Facebook credentials
    page_id = os.environ.get('FB_PAGE_ID') or config['facebook']['page_id']
    token = os.environ.get('FB_ACCESS_TOKEN') or config['facebook']['access_token']
    
    # Get Twitter accounts to monitor
    twitter_accounts = config.get('twitter_accounts', [])
    
    print(f"Settings: window={post_window}min, gap={schedule_gap}min, min_len={min_length}")
    
    # **STEP 1: TRY YOUTUBE LIVE STREAMING**
    print("\n" + "="*60)
    print("STEP 1: CHECKING YOUTUBE LIVE FOR RE-STREAMING")
    print("="*60 + "\n")
    
    youtube_config = config.get('youtube_restream', {})
    if youtube_config.get('enabled', False):
        try:
            from youtube_facebook_restream_cron import monitor_and_restream_once
            
            print("[YouTube] Attempting to start re-streaming...")
            restream_started = monitor_and_restream_once(config, state)
            
            if restream_started:
                # Re-streaming is running - this will take hours
                # Save state and exit (Twitter will be checked next run)
                save_state(state)
                return
            else:
                print("[YouTube] No live stream detected or streaming not started")
                print("[YouTube] Continuing to Twitter monitoring...")
        except Exception as e:
            error_msg = str(e)
            if 'Permissions error' in error_msg or 'code": 200' in error_msg:
                print("\n⚠️  FACEBOOK LIVE API ERROR - PAGE NOT YET ELIGIBLE")
                print("   Your page needs to cross 60 days to use Live Video API")
                print("   Re-streaming will auto-enable when permissions are granted")
            else:
                print(f"\n⚠️  YouTube streaming error: {e}")
            print("\n   Continuing to Twitter monitoring...\n")
    else:
        print("[YouTube] Re-streaming disabled in config")
        print("[YouTube] Continuing to Twitter monitoring...\n")
    
    # **STEP 2: TWITTER MONITORING**
    print("\n" + "="*60)
    print("STEP 2: CHECKING TWITTER ACCOUNTS")
    print("="*60)
    print(f"Accounts to check: {len(twitter_accounts)}\n")
    
    if not twitter_accounts:
        print("No Twitter accounts configured!")
        return
    
    # Initialize browser scraper
    scraper = TwitterBrowserScraper(headless=True)
    await scraper.start()
    
    # Login to Twitter
    twitter_auth = config.get('twitter_auth', {})
    twitter_email = os.environ.get('TWITTER_EMAIL') or twitter_auth.get('email')
    twitter_password = os.environ.get('TWITTER_PASSWORD') or twitter_auth.get('password')
    twitter_username = os.environ.get('TWITTER_USERNAME') or twitter_auth.get('username')
    
    # Try to load saved session first
    session_loaded = await scraper.load_session()
    
    if not session_loaded and twitter_email and twitter_password:
        print("\nLogging in to Twitter...")
        login_success = await scraper.login(twitter_email, twitter_password, twitter_username)
        if login_success:
            print("[OK] Logged in!")
        else:
            print("[WARNING] Login failed - using guest mode")
    elif session_loaded:
        print("[OK] Using saved session")
    else:
        print("[WARNING] No credentials - using guest mode")
    
    # **PARALLEL EXECUTION: Check all accounts concurrently**
    print(f"\n{'='*60}")
    print(f"CHECKING ALL {len(twitter_accounts)} ACCOUNTS IN PARALLEL...")
    print(f"{'='*60}\n")
    
    tasks = [
        check_account_parallel(scraper, account_config, state, post_window, min_length)
        for account_config in twitter_accounts
    ]
    
    # Run all checks concurrently
    results = await asyncio.gather(*tasks)
    
    # Filter out None results
    posts = [post for post in results if post is not None]
    
    await scraper.close()
    
    print(f"\n{'='*60}")
    print(f"Found {len(posts)} posts to publish")
    print(f"{'='*60}\n")
    
    if not posts:
        save_state(state)
        return
    
    # Post them with thread pool for parallel FB posting
    base_time = datetime.now(timezone.utc)
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        for i, post in enumerate(posts):
            account_id = post['account_id']
            message = post['message']
            
            print(f"\nProcessing {i+1}/{len(posts)}: {account_id}")
            
            # STEP 1: Download media (async)
            media_path = None
            media_type = 'text'
            
            if post.get('media'):
                images = [m for m in post['media'] if m['type'] == 'image']
                if images:
                    print(f"  Downloading image...")
                    media_path = await download_media_async(images[0]['url'], 'image')
                    if media_path:
                        media_type = 'image'
                        print(f"  [OK] Image downloaded")
            
            # STEP 2: Enhance caption (in thread pool)
            print(f"  Enhancing caption...")
            loop = asyncio.get_event_loop()
            enhanced_message = await loop.run_in_executor(
                executor,
                enhance_caption_with_gemini,
                message, media_path, media_type
            )
            
            # STEP 3: Generate SEO hashtags
            hashtags = generate_seo_hashtags(content=enhanced_message, max_hashtags=10)
            
            # STEP 4: Format final message
            final_message = format_post_with_hashtags(enhanced_message, hashtags)
            
            # STEP 5: Post to Facebook (in thread pool)
            sched = None
            if i > 0:
                sched_dt = base_time + timedelta(minutes=schedule_gap * i)
                sched = int(sched_dt.timestamp())
            
            print(f"  Posting to Facebook...")
            success, result = await loop.run_in_executor(
                executor,
                post_to_facebook,
                page_id, token, final_message, media_path, sched, media_type
            )
            
            # Cleanup
            if media_path and os.path.exists(media_path):
                os.remove(media_path)
            
            if success:
                status = 'SCHEDULED' if i > 0 else 'POSTED'
                print(f"  [SUCCESS] {status}: {result}")
                state.setdefault('last_posted_ids', {})[account_id] = post['tweet_id']
            else:
                print(f"  [FAILED] {result}")
    
    # Save state
    save_state(state)
    print("\nDone!")


def main():
    """Main entry point"""
    asyncio.run(main_async())


if __name__ == '__main__':
    main()
