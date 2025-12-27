"""
Twitter to Facebook Bot - PLAYWRIGHT NITTER VERSION
Uses Playwright to scrape nitter.net directly + YouTube Live Monitor
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

async def scrape_nitter_user_playwright(username, browser):
    """Scrape nitter.net using Playwright"""
    url = f"https://nitter.net/{username}"
    logger.info(f"[{username}] Navigating to {url}")
    
    tweets = []
    page = await browser.new_page()
    try:
        # 1. Navigation with improved waiting
        try:
            logger.info(f"[{username}] Waiting for page load (timeout=90s)...")
            await page.goto(url, timeout=90000, wait_until='networkidle')
            await page.wait_for_selector('.timeline-item', timeout=20000)
            logger.info(f"[{username}] Page loaded successfully")
        except Exception as e:
            logger.error(f"[{username}] Navigation failed: {str(e)[:200]}")
            return []

        # 2. Scrape Items
        items = await page.query_selector_all('.timeline-item')
        logger.info(f"[{username}] Found {len(items)} items on timeline")
        
        for item in items[:5]: # Check top 5
            # Get text
            text_el = await item.query_selector('.tweet-content')
            text = await text_el.inner_text() if text_el else ""
            
            # Get ID/Link
            link_el = await item.query_selector('.tweet-link')
            href = await link_el.get_attribute('href') if link_el else ""
            tweet_id = href.split('/')[-1].split('#')[0] if href else ""
            full_link = f"https://nitter.net{href}" if href else ""
            
            # Get Media
            media_url = None
            has_video = False
            
            img_el = await item.query_selector('.attachments img')
            if img_el:
                src = await img_el.get_attribute('src')
                if src: media_url = f"https://nitter.net{src}"
            
            vid_el = await item.query_selector('.attachments video')
            if vid_el: has_video = True
            
            if tweet_id:
                logger.info(f"[{username}] Found tweet {tweet_id}: TextLen={len(text)}, Media={'Video' if has_video else ('Image' if media_url else 'None')}")
                tweets.append({
                    'id': tweet_id,
                    'text': text,
                    'link': full_link,
                    'media_url': media_url,
                    'has_video': has_video
                })
                
    except Exception as e:
        logger.error(f"[{username}] Error during scraping: {e}")
    finally:
        await page.close()
        
    return tweets

def download_media(url, is_video=False):
    """Download media using requests or yt-dlp"""
    try:
        temp_dir = tempfile.gettempdir()
        if is_video:
            # For video, use yt-dlp on the tweet URL (replace nitter with twitter for better extraction)
            tweet_url = url.replace('nitter.net', 'twitter.com')
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
    logger.info("Bot Started: Playwright (Nitter.net) + YouTube Live")
    logger.info("="*60)
    
    config = load_config()
    state = load_state()
    
    # ... (YouTube check remains similar, adding logging)
    if HAS_YOUTUBE and config.get('youtube_restream', {}).get('enabled'):
        logger.info("Checking YouTube Live...")
        # ...
    
    logger.info("Starting Playwright Browser...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
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
                # Process one by one
                tweets = await scrape_nitter_user_playwright(username, browser)
                results.append(tweets)
                # Small delay between checks
                await asyncio.sleep(2)
            else:
                 logger.warning(f"Skipping account {i+1}, no username found.")
                 results.append([])

        
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
            
        await browser.close()
        
    logger.info(f"Found {len(posts_to_make)} new posts.")
    
    # 3. Post to Facebook
    page_id = os.environ.get('FB_PAGE_ID') or config['facebook']['page_id']
    token = os.environ.get('FB_ACCESS_TOKEN') or config['facebook']['access_token']
    gemini_key = os.environ.get('GEMINI_API_KEY')
    
    base_time = int(time.time())
    
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
        
        if 'id' in res or 'post_id' in res:
            state['last_posted_ids'][item['feed_id']] = tweet['id']
            save_state(state)
            
    logger.info("Bot Run Completed.")

if __name__ == '__main__':
    asyncio.run(main_async())
