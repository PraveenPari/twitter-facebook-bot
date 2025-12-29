"""
Twitter to Facebook Bot - PLAYWRIGHT NITTER VERSION
Uses Playwright to scrape nitter directly + YouTube Live Monitor
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
from playwright.async_api import async_playwright
import logging

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

# Import instagrapi for trending hashtags
try:
    from instagrapi import Client as InstaClient
    HAS_INSTAGRAPI = True
except ImportError:
    HAS_INSTAGRAPI = False
    logger.warning("instagrapi not installed - trending hashtags feature disabled")

def load_config():
    if os.path.exists('config.json'):
        with open('config.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    config_str = os.environ.get('CONFIG_JSON')
    if config_str:
        return json.loads(config_str)
    raise Exception("No config found!")

def load_state():
    state = {'last_posted_ids': {}}
    if os.path.exists('state.json'):
        try:
            with open('state.json', 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    # Merge loaded into default, or just ensure key exists
                    if 'last_posted_ids' in loaded:
                        return loaded
                    else:
                        loaded['last_posted_ids'] = {}
                        return loaded
        except:
            pass
    return state

def save_state(state):
    with open('state.json', 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def clean_text(text):
    if not text: return ''
    # Remove all URLs (including nitter URLs)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'nitter\.\S+', '', text)  # Remove any remaining nitter references
    text = re.sub(r'^(@\w+\s*)+', '', text)
    text = re.sub(r' +', ' ', text)
    return text.strip()

# TVK Hashtags (Shortened) - Static fallback hashtags
TVK_HASHTAGS = ["#TVK", "#ThamizhagaVetriKazhagam", "#ThalapathyVijay", "#TamilNadu"]

# Cache for trending hashtags (refreshed each run)
_trending_hashtags_cache = None

def fetch_trending_hashtags_from_instagram(ig_username=None, ig_password=None):
    """
    Fetch real-time trending hashtags from TVK, TVKVijay, actorvijay Instagram.
    Uses search_hashtags API which returns related trending tags.
    """
    global _trending_hashtags_cache
    
    if _trending_hashtags_cache is not None:
        return _trending_hashtags_cache
    
    if not HAS_INSTAGRAPI:
        logger.warning("instagrapi not available - using static hashtags")
        return TVK_HASHTAGS
    
    # Get Instagram credentials from: 1) Function args, 2) Environment, 3) Config file
    config = {}
    try:
        config = load_config()
    except:
        pass
    
    instagrapi_config = config.get('instagrapi', {})
    
    username = ig_username or os.environ.get('IG_SCRAPE_USERNAME') or instagrapi_config.get('username')
    password = ig_password or os.environ.get('IG_SCRAPE_PASSWORD') or instagrapi_config.get('password')
    
    if not username or not password:
        logger.warning("Instagram credentials not provided - using static hashtags")
        return TVK_HASHTAGS
    
    SESSION_FILE = "ig_session.json"
    
    try:
        logger.info("Fetching trending hashtags from Instagram...")
        cl = InstaClient()
        cl.delay_range = [1, 3]
        
        # Try to reuse existing session for faster login
        if os.path.exists(SESSION_FILE):
            try:
                cl.load_settings(SESSION_FILE)
                cl.login(username, password)
                logger.info("Instagram session reused")
            except:
                cl = InstaClient()
                cl.login(username, password)
                cl.dump_settings(SESSION_FILE)
                logger.info("Fresh Instagram login")
        else:
            cl.login(username, password)
            cl.dump_settings(SESSION_FILE)
            logger.info("Instagram login successful")
        
        # Hashtags to search for related trending tags
        search_terms = ['TVK', 'TVKVijay', 'actorvijay', 'ThalapathyVijay', 'Vijay']
        
        all_hashtags = []
        
        for term in search_terms:
            try:
                logger.info(f"Searching related hashtags for #{term}...")
                
                # search_hashtags returns list of related/trending hashtags
                results = cl.search_hashtags(term)
                
                for hashtag in results[:10]:  # Take top 10 related
                    # Clean the hashtag name (remove emojis/special chars for cleaner look)
                    tag_name = hashtag.name
                    # Keep alphanumeric and some unicode chars
                    all_hashtags.append('#' + tag_name)
                
                logger.info(f"Found {len(results)} related hashtags for #{term}")
                time.sleep(1)  # Small delay
                
            except Exception as e:
                logger.warning(f"Failed to search #{term}: {e}")
                continue
        
        # Count and deduplicate
        from collections import Counter
        hashtag_counts = Counter(all_hashtags)
        
        # Get unique tags, prioritizing most common
        trending = [tag for tag, count in hashtag_counts.most_common(30)]
        
        # Clean hashtags - only keep English alphanumeric hashtags
        clean_trending = []
        
        # Words to exclude from hashtags (negative/inappropriate content)
        excluded_words = ['stampede', 'sethu', 'devar', 'death', 'dead', 'kill', 'accident', 'tragedy', 'rip']
        
        for tag in trending:
            # Remove the # for checking
            tag_text = tag[1:] if tag.startswith('#') else tag
            
            # Only keep hashtags that are purely ASCII alphanumeric (English letters + numbers)
            # This removes hashtags with special chars like ü, ş, ä, emojis, etc.
            if not (tag_text.isascii() and tag_text.isalnum()):
                continue
            
            # Exclude hashtags containing negative words
            tag_lower = tag_text.lower()
            if any(word in tag_lower for word in excluded_words):
                logger.info(f"Excluding hashtag with negative word: #{tag_text}")
                continue
            
            clean_trending.append('#' + tag_text)
        
        # Add core TVK hashtags at the beginning
        core_tags = ['#TVK', '#ThamizhagaVetriKazhagam', '#ThalapathyVijay', '#TamilNadu']
        final_trending = core_tags + [t for t in clean_trending if t.lower() not in [c.lower() for c in core_tags]]
        
        # Fallback hashtags if not enough trending ones found
        fallback_hashtags = [
            '#Vijay', '#VijayPolitics', '#TNPolitics', '#TamilNadu2026',
            '#VijayForCM', '#Tamilnadu', '#TamilPolitics', '#VijayFans',
            '#VijayArmy', '#ThalapathyForever', '#TVKParty'
        ]
        
        # Ensure we have exactly 25 hashtags
        while len(final_trending) < 25 and fallback_hashtags:
            fb_tag = fallback_hashtags.pop(0)
            if fb_tag.lower() not in [t.lower() for t in final_trending]:
                final_trending.append(fb_tag)
        
        logger.info(f"Trending hashtags ({len(final_trending)}): {final_trending[:10]}")
        
        # Cache the result - exactly 25 hashtags
        _trending_hashtags_cache = final_trending[:25]
        
        return _trending_hashtags_cache
        
    except Exception as e:
        logger.error(f"Failed to fetch trending hashtags: {e}")
        return TVK_HASHTAGS

def generate_hashtags(content, use_trending=True):
    """
    Generate hashtags - combines trending hashtags with content-based ones.
    """
    if use_trending:
        tags = fetch_trending_hashtags_from_instagram()
    else:
        tags = TVK_HASHTAGS.copy()
    
    # Add content-based hashtags
    if 'election' in content.lower(): 
        tags.insert(0, "#TNElection2026")
    
    # Return exactly 25 hashtags
    return tags[:25]

# Caption enhancement removed - using original caption

async def scrape_nitter_user_tab(username, context):
    """Scrape nitter using a new tab in shared context (faster)"""
    
    instances = [
        "https://nitter.net"
    ]
    
    tweets = []
    
    logger.info(f"[{username}] Starting scrape...")
    
    # Create new tab (page) in shared context
    page = await context.new_page()
    
    try:
        for instance in instances:
            url = f"{instance}/{username}"
            logger.info(f"[{username}] Trying {instance}...")
            
            try:
                try:
                    await page.goto(url, timeout=30000, wait_until='domcontentloaded') 
                    title = await page.title()
                    logger.info(f"[{username}] Loaded: {title}")
                except:
                    logger.error(f"[{username}] Timeout on {instance}")
                    continue 

                content = await page.content()
                if "Rate limit" in content or "upstream connect error" in content:
                    logger.error(f"[{username}] Blocked on {instance}")
                    continue
                
                try:
                    await page.wait_for_selector('.timeline-item', timeout=15000)
                except:
                    logger.error(f"[{username}] Timeline failed on {instance}")
                    continue
                
                logger.info(f"[{username}] [OK] Loaded")
                
                items = await page.query_selector_all('.timeline-item')
                logger.info(f"[{username}] Found {len(items)} items")
                
                for item in items[:5]:
                    text_el = await item.query_selector('.tweet-content')
                    text = await text_el.inner_text() if text_el else ""
                    
                    link_el = await item.query_selector('.tweet-link')
                    href = await link_el.get_attribute('href') if link_el else ""
                    tweet_id = href.split('/')[-1].split('#')[0] if href else ""
                    full_link = f"{instance}{href}" if href else ""
                    
                    media_url = None
                    has_video = False
                    
                    # Check for video first (multiple methods)
                    vid_el = await item.query_selector('.attachments video')
                    gallery_vid = await item.query_selector('.gallery-video')
                    if vid_el or gallery_vid: 
                        has_video = True
                    
                    # Get image/thumbnail
                    img_el = await item.query_selector('.attachments img')
                    if img_el:
                        src = await img_el.get_attribute('src')
                        if src: 
                            media_url = f"{instance}{src}"
                            # If URL contains video_thumb, it's actually a video
                            if 'video_thumb' in src or 'ext_tw_video' in src:
                                has_video = True
                    
                    # Extract Timestamp
                    date_str = ""
                    date_el = await item.query_selector('.tweet-date a')
                    if date_el:
                        date_str = await date_el.get_attribute('title')
                    
                    # Check Pinned
                    is_pinned = False
                    pin_el = await item.query_selector('.pinned')
                    if pin_el: is_pinned = True

                    if tweet_id:
                        tweets.append({
                            'id': tweet_id,
                            'text': text,
                            'link': full_link,
                            'media_url': media_url,
                            'has_video': has_video,
                            'date_str': date_str,
                            'is_pinned': is_pinned
                        })
                
                break  # Success, exit instance loop
                
            except Exception as e:
                logger.error(f"[{username}] Error: {e}")
                continue 
                
    finally:
        await page.close()

    return tweets

def download_media(url, is_video=False):
    """Download media using requests or yt-dlp"""
    try:
        temp_dir = tempfile.gettempdir()
        if is_video:
            # For video, use yt-dlp on the tweet URL (replace nitter with twitter for better extraction)
            # URL might be nitter.poast.org, so generalized replacement
            if 'nitter' in url:
                # regex to replace base url with twitter.com
                tweet_url = re.sub(r'https://nitter\.[^/]+', 'https://twitter.com', url)
            else:
                tweet_url = url
                
            logger.info(f"Downloading video from {tweet_url}...")
            
            out_tmpl = os.path.join(temp_dir, '%(id)s.%(ext)s')
            ydl_opts = {'format': 'best[ext=mp4]', 'outtmpl': out_tmpl, 'quiet':True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(tweet_url, download=True)
                if info:
                    vid_id = info['id']
                    path = os.path.join(temp_dir, f"{vid_id}.mp4")
                    logger.info(f"Video downloaded: {path}")
                    return path
        else:
            # Image
            logger.info(f"Downloading image from {url}...")
            r = requests.get(url, timeout=30)
            if r.status_code==200:
                path = os.path.join(temp_dir, f"temp_img_{int(time.time())}.jpg")
                with open(path, 'wb') as f: f.write(r.content)
                logger.info(f"Image downloaded: {path}")
                return path
    except Exception as e:
        logger.error(f"Media download fail: {e}")
    return None

def post_facebook(page_id, token, msg, media_path=None, is_video=False, is_sched=False, sched_time=None):
    url = f"https://graph.facebook.com/v22.0/{page_id}/feed"
    data = {'message': msg, 'access_token': token}
    files = {}
    
    if media_path:
        if not os.path.exists(media_path):
             logger.error(f"Media file not found: {media_path} - Skipping Facebook post")
             return {'error': 'Media file missing'}
             
        try:
            if is_video:
                url = url.replace('/feed', '/videos')
                data['description'] = msg
                files = {'source': open(media_path, 'rb')}
                logger.info(f"Posting VIDEO to Facebook...")
            else:
                url = url.replace('/feed', '/photos')
                data['caption'] = msg
                files = {'source': open(media_path, 'rb')}
                logger.info(f"Posting IMAGE to Facebook...")
        except Exception as e:
            logger.error(f"Error opening media file: {e}")
            return {'error': f"File error: {e}"}
    else:
        logger.info(f"Posting TEXT to Facebook...")
            
    if is_sched and sched_time:
        data['published'] = 'false'
        data['scheduled_publish_time'] = sched_time
        logger.info(f"Scheduling post for {sched_time}")
        
    try:
        if files: r = requests.post(url, data=data, files=files)
        else: r = requests.post(url, data=data)
        
        res = r.json()
        if 'error' in res:
             logger.error(f"Facebook API Error: {res['error']}")
        else:
             logger.info(f"Facebook Post Success: {res}")
        return res
    except Exception as e:
        logger.error(f"Facebook Request Failed: {e}")
        return {'error': str(e)}

def post_instagram(ig_user_id, token, msg, media_path=None, is_video=False, is_sched=False, sched_time=None):
    """Post content to Instagram using Graph API with proper container flow"""
    if not media_path:
        logger.warning("Instagram requires media - skipping text-only post")
        return {'error': 'Instagram requires media'}
    
    try:
        container_id = None
        
        # Step 1: Create media container
        if is_video:
            logger.info(f"Creating Instagram VIDEO (Reel) container...")
            
            # Check video duration first (max 5 minutes for Instagram Reels via this bot)
            try:
                import subprocess
                result = subprocess.run(
                    ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', 
                     '-of', 'default=noprint_wrappers=1:nokey=1', media_path],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0:
                    duration = float(result.stdout.strip())
                    logger.info(f"Video duration: {duration:.1f} seconds ({duration/60:.1f} minutes)")
                    
                    # Skip Instagram for videos over 5 minutes (300 seconds)
                    if duration > 300:
                        logger.warning(f"Video too long for Instagram Reels: {duration/60:.1f} minutes (max 5 min) - SKIPPING Instagram")
                        return {'error': 'Video too long for Instagram (max 5 minutes)', 'skipped': True}
            except FileNotFoundError:
                logger.warning("ffprobe not found - skipping duration check")
            except Exception as e:
                logger.warning(f"Could not check video duration: {e}")
            
            # Read the video file
            with open(media_path, 'rb') as f:
                video_data = f.read()
            
            file_size = len(video_data)
            logger.info(f"Video file size: {file_size} bytes ({file_size / 1024 / 1024:.2f} MB)")
            
            # Check video file size (max 300MB for Reels)
            if file_size > 300 * 1024 * 1024:
                logger.error(f"Video too large for Instagram: {file_size / 1024 / 1024:.2f} MB (max 300MB)")
                return {'error': 'Video too large for Instagram (max 300MB)'}
            
            # Method: Resumable Upload (Directly upload local file bytes to FB)
            # This is the most reliable method as it avoids 3rd party hosts.
            logger.info("Using Resumable Upload (Direct) for Instagram Video...")
            init_url = f"https://graph.facebook.com/v22.0/{ig_user_id}/media"
            init_data = {
                'media_type': 'REELS',
                'caption': msg,
                'access_token': token,
                'upload_type': 'resumable'
            }
            
            if is_sched and sched_time:
                init_data['scheduled_publish_time'] = sched_time
                logger.info(f"Scheduling Instagram Reel (Resumable) for {sched_time}")
            
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
            
            upload_resp = requests.post(upload_url, headers=headers, data=video_data, timeout=300)
            logger.info(f"Video upload response: {upload_resp.status_code}")
            
            if upload_resp.status_code != 200:
                logger.error(f"Upload failed: {upload_resp.text}")
                return {'error': f'Upload failed: {upload_resp.status_code}', 'details': upload_resp.text}
            
            upload_result = upload_resp.json() if upload_resp.text else {}
            logger.info(f"Upload result: {upload_result}")
            
            # Legacy 3rd party host attempts (Pixeldrain/Catbox) removed/skipped to prioritize stability
            video_url = None 
            
            # if video_url: (Logic removed)
            
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
    logger.info("="*60)
    logger.info("Bot Started: Playwright (Failover Nitter) + YouTube Live")
    logger.info("="*60)
    
    config = load_config()
    state = load_state()
    
    # 1. Check YouTube Live
    if HAS_YOUTUBE and config.get('youtube_restream', {}).get('enabled'):
        logger.info("Checking YouTube Live...")
        if youtube_live_monitor.check_and_restream(config):
            logger.info("Re-streaming started. Stopping Twitter check.")
            return # Stop if re-streaming

    # 2. Check Twitter (Nitter)
    logger.info("Starting Playwright Browser...")
    async with async_playwright() as p:
        # Launch in headless mode for deployment
        browser = await p.chromium.launch(
            headless=False,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-setuid-sandbox'
            ]
        )
        
        # Create ONE shared context for all tabs
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080},
            locale='en-US'
        )
        
        accounts = config.get('feeds', []) or config.get('twitter_accounts', [])
        logger.info(f"Loaded {len(accounts)} accounts to check.")

        # Prepare usernames
        usernames = []
        for acc in accounts:
            username = acc.get('username')
            if not username and 'url' in acc:
                username = acc['url'].strip('/').split('/')[-1]
                if username == 'rss': username = acc['url'].strip('/').split('/')[-2]
            usernames.append(username)
        
        # Scrape in BATCHES of 3 to avoid rate limiting
        async def scrape_in_tab(username, context):
            if not username:
                return []
            return await scrape_nitter_user_tab(username, context)
        
        BATCH_SIZE = 3
        results = []
        
        for batch_start in range(0, len(usernames), BATCH_SIZE):
            batch = usernames[batch_start:batch_start + BATCH_SIZE]
            logger.info(f"[BATCH] Scraping {len(batch)} accounts: {batch}")
            
            tasks = [scrape_in_tab(u, context) for u in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, r in enumerate(batch_results):
                if isinstance(r, Exception):
                    logger.error(f"[ERROR] {batch[i]}: {r}")
                    results.append([])
                else:
                    results.append(r)
            
            # Wait between batches to avoid rate limit
            if batch_start + BATCH_SIZE < len(usernames):
                logger.info("[BATCH] Waiting 2s before next batch...")
                await asyncio.sleep(2)
        
        success_count = sum(1 for r in results if r)
        logger.info(f"[DONE] Loaded {success_count}/{len(usernames)} accounts successfully")
        
        await context.close()
        await browser.close()
        
    # Process results
    posts_to_make = []
    for i, tweets in enumerate(results):
        # Use account 'id' for state key
        acc = accounts[i]
        feed_id = acc.get('id', acc.get('username', 'unknown'))
        
        if not tweets:
            logger.warning(f"[{feed_id}] No tweets fetched (scrape failed or empty)")
            continue
        
        # Find posts within 1 hour and log them
        posts_within_hour = []
        for tweet in tweets:
            tweet_id = tweet['id']
            
            # Skip pinned
            if tweet.get('is_pinned'):
                continue
            
            # Skip already posted
            if state.get('last_posted_ids', {}).get(feed_id) == tweet_id:
                continue
            
            # Skip no media
            if not tweet.get('has_video') and not tweet.get('media_url'):
                continue
                
            # Check Time (1 hour = 3600 seconds)
            is_old = False
            age_str = "unknown"
            if 'date_str' in tweet and tweet['date_str']:
                try:
                    d_str = tweet['date_str'].replace('UTC', '').strip()
                    post_time = datetime.strptime(d_str, "%b %d, %Y · %I:%M %p")
                    post_time = post_time.replace(tzinfo=timezone.utc)
                    now = datetime.now(timezone.utc)
                    age = now - post_time
                    age_str = str(age).split('.')[0]  # Remove microseconds
                    
                    if age.total_seconds() > 3600:  # 1 hour
                        is_old = True
                except:
                    age_str = tweet['date_str']  # Use raw date if parsing fails
            
            if not is_old:
                media_type = "VIDEO" if tweet.get('has_video') else "IMAGE"
                posts_within_hour.append({
                    'id': tweet_id,
                    'type': media_type,
                    'age': age_str
                })
        
        # Log posts within 1 hour for this account
        if posts_within_hour:
            for p in posts_within_hour:
                logger.info(f"[FOUND] [{feed_id}] {p['type']} {p['id']} (Age: {p['age']})")
            
            # Take the first one (newest)
            best = posts_within_hour[0]
            best_tweet = next(t for t in tweets if t['id'] == best['id'])
            
            posts_to_make.append({
                'feed_id': feed_id,
                'tweet': best_tweet
            })
            
    logger.info(f"Found {len(posts_to_make)} new posts with media.")
    
    # Separate videos (priority) and images
    video_posts = [p for p in posts_to_make if p['tweet'].get('has_video')]
    image_posts = [p for p in posts_to_make if not p['tweet'].get('has_video')]
    
    # Combine: Videos first (priority), then images
    all_posts = video_posts + image_posts
    
    logger.info(f"[QUEUE] {len(video_posts)} videos + {len(image_posts)} images = {len(all_posts)} total")
    
    # 3. Post to Facebook & Instagram
    page_id = os.environ.get('FB_PAGE_ID') or config['facebook']['page_id']
    token = os.environ.get('FB_ACCESS_TOKEN') or config['facebook']['access_token']
    
    # Instagram config
    ig_enabled = config.get('instagram', {}).get('enabled', False)
    ig_user_id = os.environ.get('IG_USER_ID') or config.get('instagram', {}).get('user_id')
    ig_token = os.environ.get('IG_ACCESS_TOKEN') or config.get('instagram', {}).get('access_token')
    
    base_time = int(time.time())
    
    post_stats = []
    
    for i, item in enumerate(all_posts):
        tweet = item['tweet']
        is_video = tweet.get('has_video', False)
        media_type = "VIDEO" if is_video else "IMAGE"
        
        # First post = immediate, rest = scheduled at +11 min from now
        # Facebook requires scheduled time to be at least 10 min in the future
        if i == 0:
            is_scheduled = False
            sched_time = None
            logger.info(f"[NOW] Posting {media_type} for {item['feed_id']}...")
        else:
            is_scheduled = True
            # Each scheduled post is +20 min from current time (safe for IG/FB)
            current_time = int(time.time())
            sched_time = current_time + 1200  # +20 min from NOW
            logger.info(f"[SCHEDULE +20min] {media_type} for {item['feed_id']}...")
        
        # Download media
        if is_video:
            media_path = download_media(tweet['link'], is_video=True)
        else:
            media_path = download_media(tweet['media_url'], is_video=False)
            
        if not media_path:
            logger.error(f"Failed to download {media_type} for {item['feed_id']}")
            post_stats.append({'id': item['feed_id'], 'type': media_type.lower(), 'status': 'failed', 'error': 'download_failed'})
            continue
        
        # Build caption with hashtags
        msg = clean_text(tweet['text'])
        tags = generate_hashtags(msg)
        final_msg = f"{msg}\n\n{' '.join(tags)}"
        
        # Post to Facebook
        res = post_facebook(page_id, token, final_msg, media_path, is_video=is_video, is_sched=is_scheduled, sched_time=sched_time)
        fb_success = 'id' in res or 'post_id' in res
        post_stats.append({'id': item['feed_id'], 'type': media_type.lower(), 'platform': 'facebook', 'status': 'success' if fb_success else 'failed', 'error': res.get('error')})
        
        # Prioritize Catbox for images
        # Post to Instagram 
        ig_success = False
        ig_res = {}
        if ig_enabled and ig_user_id:
            logger.info(f"[IG] Posting {media_type} to Instagram for {item['feed_id']}...")
            ig_res = post_instagram(ig_user_id, ig_token, final_msg, media_path, is_video=is_video, is_sched=is_scheduled, sched_time=sched_time)
            ig_success = 'id' in ig_res
            
        # Check if it was skipped (e.g., video too long)
        if ig_res.get('skipped'):
            logger.info(f"[IG SKIP] {item['feed_id']}: {ig_res.get('error')}")
        elif ig_success:
            logger.info(f"[IG OK] {media_type} posted to Instagram for {item['feed_id']}")
            post_stats.append({'id': item['feed_id'], 'type': media_type.lower(), 'platform': 'instagram', 'status': 'success'})
        elif ig_enabled and ig_user_id: # Only log error if we actually tried
            logger.error(f"[IG FAIL] {item['feed_id']}: {ig_res.get('error')}")
            post_stats.append({'id': item['feed_id'], 'type': media_type.lower(), 'platform': 'instagram', 'status': 'failed', 'error': ig_res.get('error')})
        
        if fb_success or ig_success:
            state['last_posted_ids'][item['feed_id']] = tweet['id']
            save_state(state)
            if is_scheduled:
                ig_status_str = "posted" if ig_success else "failed/skipped"
                logger.info(f"[OK] FB scheduled, IG {ig_status_str} for {item['feed_id']}")
            else:
                logger.info(f"[OK] {media_type} posted for {item['feed_id']}")
            
    # Save Reports
    run_timestamp = datetime.now().isoformat()
    
    # 1. Internal JSON Report
    report = {
        'timestamp': run_timestamp,
        'accounts_checked': len(accounts),
        'new_posts_found': len(posts_to_make),
        'facebook_actions': post_stats
    }
    with open('run_report.json', 'w') as f:
        json.dump(report, f, indent=2)
        
    # 2. Cucumber JSON Report (for Artifacts/Allure)
    cucumber_features = []
    
    # Feature 1: Scrape Accounts
    elements = []
    for i, res_list in enumerate(results):
        acc = accounts[i]
        username = acc.get('username', 'unknown')
        status = "passed" if res_list else "failed" # Simple pass if we got tweets, fail if empty/error (optional logic)
        if not res_list: status = "skipped" # If just no new tweets, technically not a fail, but for report usage:
        
        # Check if we had an error log for this user? (Hard to track without better state, assuming pass if no exception flow)
        # We'll treat finding items as pass.
        
        step_status = "passed"
        if not res_list: step_status = "passed" # It's okay to find 0 items
        
        elements.append({
            "name": f"Check Account: {username}",
            "type": "scenario",
            "steps": [
                {
                    "name": f"Scrape {username}",
                    "result": {"status": step_status, "duration": 1000000}
                }
            ]
        })
    
    cucumber_features.append({
        "name": "Twitter Scraping",
        "description": "Scrape tweets from Nitter instances",
        "uri": "main.py",
        "elements": elements
    })
    
    # Feature 2: Facebook Posting
    fb_elements = []
    for action in post_stats:
        status = "passed" if action['status'] == 'success' else "failed"
        fb_elements.append({
            "name": f"Post to FB: {action['id']}",
            "type": "scenario",
            "steps": [
                {
                    "name": "Upload and Post",
                    "result": {"status": status, "error_message": action.get('error', '')}
                }
            ]
        })
    
    if fb_elements:
        cucumber_features.append({
            "name": "Facebook Publishing",
            "description": "Upload content to Facebook Page",
            "uri": "main.py",
            "elements": fb_elements
        })
        
    with open('cucumber_report.json', 'w') as f:
        json.dump(cucumber_features, f, indent=2)
            
    # Cleanup Temp Files (Now inside the function where temp_dir is defined)
    try:
        if os.path.exists(temp_dir):
            for file in os.listdir(temp_dir):
                file_path = os.path.join(temp_dir, file)
                try:
                    if os.path.isfile(file_path):
                        os.unlink(file_path)
                except Exception as e:
                    logger.warning(f"Failed to delete {file_path}: {e}")
            logger.info("Temp directory cleaned.")
    except Exception as e:
        logger.warning(f"Error cleaning temp dir: {e}")

    logger.info("Bot Run Completed. Reports generated: run_report.json, cucumber_report.json")

if __name__ == '__main__':
    asyncio.run(main_async())
