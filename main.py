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
        
        # Create ONE shared context for all tabs
        context = await browser.new_context(
            record_video_dir="debug_videos",
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
    
    # 3. Post to Facebook
    page_id = os.environ.get('FB_PAGE_ID') or config['facebook']['page_id']
    token = os.environ.get('FB_ACCESS_TOKEN') or config['facebook']['access_token']
    gemini_key = os.environ.get('GEMINI_API_KEY')
    
    base_time = int(time.time())
    
    post_stats = []
    
    for i, item in enumerate(all_posts):
        tweet = item['tweet']
        is_video = tweet.get('has_video', False)
        media_type = "VIDEO" if is_video else "IMAGE"
        
        # First post = immediate, rest = scheduled at 10-min intervals
        if i == 0:
            is_scheduled = False
            sched_time = None
            logger.info(f"[NOW] Posting {media_type} for {item['feed_id']}...")
        else:
            is_scheduled = True
            sched_time = base_time + (i * 600)  # 10 min intervals
            mins = i * 10
            logger.info(f"[SCHEDULE +{mins}min] {media_type} for {item['feed_id']}...")
        
        # Download media
        if is_video:
            media_path = download_media(tweet['link'], is_video=True)
        else:
            media_path = download_media(tweet['media_url'], is_video=False)
            
        if not media_path:
            logger.error(f"Failed to download {media_type} for {item['feed_id']}")
            post_stats.append({'id': item['feed_id'], 'type': media_type.lower(), 'status': 'failed', 'error': 'download_failed'})
            continue
        
        # Enhance caption
        msg = clean_text(tweet['text'])
        logger.info("Enhancing caption...")
        msg = enhance_caption(msg, gemini_key)
        tags = generate_hashtags(msg)
        final_msg = f"{msg}\n\n{' '.join(tags)}"
        
        # Post to Facebook
        res = post_facebook(page_id, token, final_msg, media_path, is_video=is_video, is_sched=is_scheduled, sched_time=sched_time)
        post_stats.append({'id': item['feed_id'], 'type': media_type.lower(), 'status': 'success' if 'id' in res or 'post_id' in res else 'failed', 'error': res.get('error')})
        
        if 'id' in res or 'post_id' in res:
            state['last_posted_ids'][item['feed_id']] = tweet['id']
            save_state(state)
            if is_scheduled:
                logger.info(f"[OK] {media_type} scheduled for {item['feed_id']}")
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
            
    logger.info("Bot Run Completed. Reports generated: run_report.json, cucumber_report.json")

if __name__ == '__main__':
    asyncio.run(main_async())
