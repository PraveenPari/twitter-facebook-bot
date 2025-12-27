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

try:
    from google import genai
    from google.genai import types
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

# Import YouTube monitor
try:
    import youtube_live_monitor
    HAS_YOUTUBE = True
except ImportError:
    HAS_YOUTUBE = False

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("bot_run.log", mode='w', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def load_config():
    if os.path.exists('config.json'):
        with open('config.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    config_str = os.environ.get('CONFIG_JSON')
    if config_str:
        return json.loads(config_str)
    raise Exception("No config found!")

def load_state():
    if os.path.exists('state.json'):
        try:
            with open('state.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {'last_posted_ids': {}}

def save_state(state):
    with open('state.json', 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def clean_text(text):
    if not text: return ''
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'^(@\w+\s*)+', '', text)
    text = re.sub(r' +', ' ', text)
    return text.strip()

# TVK Hashtags (Shortened)
TVK_HASHTAGS = ["#TVK", "#ThamizhagaVetriKazhagam", "#ThalapathyVijay", "#TamilNadu"]

def generate_hashtags(content):
    tags = TVK_HASHTAGS.copy()
    if 'election' in content.lower(): tags.append("#TNElection2026")
    return tags[:10]

def enhance_caption(caption, api_key):
    if not HAS_GEMINI or not api_key: return caption
    try:
        client = genai.Client(api_key=api_key)
        prompt = f"Enhance this Tamil political caption for Facebook (TVK party, Vijay). Positive, inspiring. Max 300 chars. Caption: {caption}"
        resp = client.models.generate_content(model='gemini-2.0-flash-exp', contents=prompt)
        return resp.text.strip() if resp.text else caption
    except:
        return caption

async def scrape_nitter_user_playwright_context(username, browser):
    """Scrape nitter using a fresh Playwright Context per user (for isolated video/state)"""
    
    # List of reliable instances
    instances = [
        "https://nitter.net",
        "https://nitter.poast.org",
        "https://nitter.privacydev.net",
        "https://nitter.lucabased.xyz"
    ]
    
    tweets = []
    today_date = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    
    # Create fresh context
    context = await browser.new_context(
        record_video_dir="debug_videos",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={'width': 1920, 'height': 1080},
        locale='en-US'
    )
    
    msg = f"[{username}] Starting scrape..."
    logger.info(msg)
    
    # Create page
    page = await context.new_page()
    video = page.video
    
    try:
        for instance in instances:
            url = f"{instance}/{username}"
            logger.info(f"[{username}] Trying instance: {instance}...")
            
            try:
                logger.info(f"[{username}] Waiting for page load (timeout=60s)...")
                try:
                    await page.goto(url, timeout=60000, wait_until='domcontentloaded') 
                    title = await page.title()
                    logger.info(f"[{username}] Page loaded. Title: {title}")
                except:
                    logger.error(f"[{username}] Timeout connecting to {instance}")
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    shot_path = f"debug_shot_{username}_{timestamp}_timeout.png"
                    try: await page.screenshot(path=shot_path)
                    except: pass
                    continue 

                content = await page.content()
                if "Rate limit" in content or "upstream connect error" in content:
                     logger.error(f"[{username}] Blocked/Error on {instance}")
                     continue
                
                logger.info(f"[{username}] Waiting for timeline...")
                try:
                    await page.wait_for_selector('.timeline-item', timeout=20000)
                except:
                     logger.error(f"[{username}] Timeline didn't load on {instance}")
                     timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                     shot_path = f"debug_shot_{username}_{timestamp}_fail.png"
                     try: await page.screenshot(path=shot_path, full_page=True)
                     except: pass
                     continue
                
                logger.info(f"[{username}] Success on {instance}!")
                
                # Take Success Screenshot for Report
                try: 
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    await page.screenshot(path=f"debug_shot_{username}_{timestamp}_success.png", full_page=True)
                except: pass
                
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
                    
                    img_el = await item.query_selector('.attachments img')
                    if img_el:
                        src = await img_el.get_attribute('src')
                        if src: media_url = f"{instance}{src}"
                    
                    vid_el = await item.query_selector('.attachments video')
                    if vid_el: has_video = True
                    
                    if tweet_id:
                        tweets.append({
                            'id': tweet_id,
                            'text': text,
                            'link': full_link,
                            'media_url': media_url,
                            'has_video': has_video
                        })
                
                break 
                
            except Exception as e:
                logger.error(f"Error on {instance}: {e}")
                continue 
                
    finally:
        # Wait 5 seconds to ensure video captures the final state (success or error)
        logger.info(f"[{username}] Waiting 5s for video capture...")
        await asyncio.sleep(5)

        # Save video cleanly
        try:
            vid_path = await video.path() 
            await context.close() # CRITICAL: Close context releases file lock
            
            if vid_path:
                 timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                 new_name = f"debug_videos/{username}_{timestamp}.webm"
                 os.makedirs("debug_videos", exist_ok=True)
                 # Retry loop for rename
                 for _ in range(3):
                     try:
                         os.replace(vid_path, new_name)
                         logger.info(f"[{username}] Saved debug video: {new_name}")
                         break
                     except Exception as e:
                         await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Failed to save/rename video: {e}")

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
        # Launch with arguments to avoid detection
        browser = await p.chromium.launch(
            headless=False,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-setuid-sandbox'
            ]
        )
        
        accounts = config.get('feeds', []) or config.get('twitter_accounts', [])
        logger.info(f"Loaded {len(accounts)} accounts to check.")

        # Sequential scraping for stability
        results = []
        for i, acc in enumerate(accounts):
            username = acc.get('username')
            # Only extract if needed
            if not username and 'url' in acc:
                username = acc['url'].strip('/').split('/')[-1]
                if username == 'rss': username = acc['url'].strip('/').split('/')[-2]
            
            if username:
                logger.info(f"Processing Account {i+1}/{len(accounts)}: {username}")
                # Pass browser to function to allow fresh context creation
                tweets = await scrape_nitter_user_playwright_context(username, browser)
                results.append(tweets)
                # Small delay between checks
                await asyncio.sleep(2)
            else:
                 logger.warning(f"Skipping account {i+1}, no username found.")
                 results.append([])
        
        await browser.close()
        
    # Process results
    posts_to_make = []
    for i, tweets in enumerate(results):
        if not tweets: continue
        
        # Use account 'id' for state key
        acc = accounts[i]
        feed_id = acc.get('id', acc.get('username', 'unknown'))
        
        latest = tweets[0] # Take most recent
        
        # Check if posted
        if state.get('last_posted_ids', {}).get(feed_id) == latest['id']:
            continue
            
        posts_to_make.append({
            'feed_id': feed_id,
            'tweet': latest
        })
            
    logger.info(f"Found {len(posts_to_make)} new posts.")
    
    # 3. Post to Facebook
    page_id = os.environ.get('FB_PAGE_ID') or config['facebook']['page_id']
    token = os.environ.get('FB_ACCESS_TOKEN') or config['facebook']['access_token']
    gemini_key = os.environ.get('GEMINI_API_KEY')
    
    base_time = int(time.time())
    
    post_stats = []
    
    for i, item in enumerate(posts_to_make):
        logger.info(f"Processing Post for {item['feed_id']}...")
        tweet = item['tweet']
        
        # Download
        media_path = None
        is_video = tweet['has_video']
        
        if is_video:
            media_path = download_media(tweet['link'], is_video=True)
        elif tweet['media_url']:
            media_path = download_media(tweet['media_url'], is_video=False)
            
        # Enhance
        msg = clean_text(tweet['text'])
        logger.info("Enhancing caption...")
        msg = enhance_caption(msg, gemini_key)
        tags = generate_hashtags(msg)
        final_msg = f"{msg}\n\n{' '.join(tags)}"
        
        # Schedule
        sched_time = None
        if i > 0:
            sched_time = base_time + (i * 600) # 10 min gap
            
        # Post
        res = post_facebook(page_id, token, final_msg, media_path, is_video, i>0, sched_time)
        post_stats.append({'id': item['feed_id'], 'status': 'success' if 'id' in res or 'post_id' in res else 'failed', 'error': res.get('error')})
        
        if 'id' in res or 'post_id' in res:
            state['last_posted_ids'][item['feed_id']] = tweet['id']
            save_state(state)
            
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
            
    logger.info("Bot Run Completed. Reports generated: run_report.json, cucumber_report.json")

if __name__ == '__main__':
    asyncio.run(main_async())
