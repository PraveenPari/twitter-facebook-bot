"""
Twitter to Facebook Bot - Standalone Version
For running on GitHub Actions, Replit, or any Python environment.
"""
import json
import os
import random
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import requests
import xml.etree.ElementTree as ET

try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    HAS_YTDLP = False
    print("Warning: yt-dlp not installed, video support disabled")

# Gemini AI for caption enhancement
try:
    from google import genai
    from google.genai import types
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False
    print("Warning: google-genai not installed, AI caption enhancement disabled")

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
    # Try file first
    if os.path.exists('config.json'):
        with open('config.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    
    # Try environment variable
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
    """Clean HTML and extract plain text from RSS content"""
    if not raw_content:
        return ''
    
    text = raw_content
    
    # Convert HTML line breaks
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)
    
    # Remove all HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Decode HTML entities
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&quot;', '"')
    text = text.replace('&#39;', "'")
    text = text.replace('&nbsp;', ' ')
    
    # Remove URLs
    text = re.sub(r'https?://\S+', '', text)
    
    # Remove Twitter attribution
    text = re.sub(r'—\s*[^(]+\(@\w+\)\s*\w+\s+\d+,\s+\d+', '', text)
    
    # Clean up whitespace
    text = re.sub(r' +', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()


# TVK Positive Hashtags - curated list of positive hashtags
TVK_POSITIVE_HASHTAGS = [
    "#TVK", "#ThamizhagaVetriKazhagam", "#Vijay", "#ThalapathyVijay",
    "#TVKForTamilNadu", "#TVKForPeople", "#TVKVision", "#TVKMovement",
    "#TamilNaduPolitics", "#TVKLeader", "#VijayPolitics", "#TVKSupport",
    "#TVKForChange", "#TVKForProgress", "#TVKForDevelopment",
    "#TVKArmy", "#TVKFamily", "#ThalapathyPolitics", "#TVKWave",
    "#TVKRevolution", "#TVKForYouth", "#TVKForFuture", "#TVKRising",
    "#TamilNaduFuture", "#TVKVictory", "#TVKPower", "#TVKStrong"
]

# General trending/SEO hashtags for politics and news
GENERAL_SEO_HASHTAGS = [
    "#TamilNadu", "#TNPolitics", "#TamilNews", "#Chennai",
    "#TamilNaduNews", "#PoliticalNews", "#IndianPolitics",
    "#SouthIndia", "#TamilPolitics", "#Breaking", "#Trending",
    "#ViralNews", "#LatestNews", "#TamilNaduUpdates"
]


def get_trending_hashtags():
    """Try to fetch trending hashtags from free APIs"""
    trending = []
    
    # Try RapidAPI Hashtag Generator (free tier)
    try:
        # This is a backup - will use curated list if API fails
        url = "https://hashtagy-generate-hashtags.p.rapidapi.com/v1/custom_1/tags"
        headers = {
            "X-RapidAPI-Key": os.environ.get("RAPIDAPI_KEY", ""),
            "X-RapidAPI-Host": "hashtagy-generate-hashtags.p.rapidapi.com"
        }
        if headers["X-RapidAPI-Key"]:
            params = {"keyword": "TVK Tamil Nadu politics"}
            response = requests.get(url, headers=headers, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if "data" in data:
                    trending = ["#" + tag for tag in data["data"][:5]]
    except Exception as e:
        print(f"  Trending API unavailable: {e}")
    
    return trending


def generate_seo_hashtags(content="", max_hashtags=10):
    """Generate SEO-optimized hashtags for Facebook post
    
    Includes:
    - TVK positive hashtags (always included)
    - Trending hashtags from API (if available)
    - Content-based relevant hashtags
    - General SEO hashtags
    """
    hashtags = []
    
    # Always include core TVK hashtags (pick 4-5 random ones)
    core_tvk = ["#TVK", "#ThamizhagaVetriKazhagam", "#ThalapathyVijay"]
    hashtags.extend(core_tvk)
    
    # Add more random TVK positive hashtags
    remaining_tvk = [h for h in TVK_POSITIVE_HASHTAGS if h not in core_tvk]
    hashtags.extend(random.sample(remaining_tvk, min(3, len(remaining_tvk))))
    
    # Try to get trending hashtags
    trending = get_trending_hashtags()
    if trending:
        hashtags.extend(trending[:3])
    
    # Extract keywords from content and create hashtags
    if content:
        # Common Tamil Nadu political keywords
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
    
    # Add general SEO hashtags to fill up
    while len(hashtags) < max_hashtags:
        remaining = [h for h in GENERAL_SEO_HASHTAGS if h not in hashtags]
        if not remaining:
            break
        hashtags.append(random.choice(remaining))
    
    # Remove duplicates while preserving order
    seen = set()
    unique_hashtags = []
    for h in hashtags:
        h_lower = h.lower()
        if h_lower not in seen:
            seen.add(h_lower)
            unique_hashtags.append(h)
    
    return unique_hashtags[:max_hashtags]


def format_post_with_hashtags(message, hashtags):
    """Format the final post with message and hashtags"""
    hashtag_text = " ".join(hashtags)
    
    # Add separator and hashtags at the end
    formatted = f"{message}\n\n{'─' * 30}\n{hashtag_text}"
    
    return formatted


def enhance_caption_with_gemini(original_caption, media_path=None, media_type='text'):
    """
    Use Gemini AI to enhance the caption with Tamil SEO words and emotional appeal.
    Can analyze video/image content for better context.
    """
    if not HAS_GEMINI:
        print("  Gemini AI not available, using original caption")
        return original_caption
    
    # Get API key from environment or config
    api_key = os.environ.get('GEMINI_API_KEY', '')
    if not api_key:
        # Try to load from config
        try:
            if os.path.exists('config.json'):
                with open('config.json', 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    api_key = config.get('gemini', {}).get('api_key', '')
        except:
            pass
    
    if not api_key:
        print("  No Gemini API key found, using original caption")
        return original_caption
    
    try:
        # Configure Gemini with new API
        client = genai.Client(api_key=api_key)
        
        # Prepare the prompt for Tamil political content enhancement
        prompt = f"""You are a Tamil political social media expert for TVK (Thamizhaga Vetri Kazhagam) party led by Vijay.

TASK: Enhance this caption for maximum Facebook engagement while keeping it POSITIVE about TVK.

ORIGINAL CAPTION:
{original_caption}

REQUIREMENTS:
1. Keep the core message intact
2. Add powerful Tamil words and phrases (transliterated) like:
   - "மக்கள் சேவை" (Makkal Sevai - People's Service)
   - "வெற்றி" (Vetri - Victory)  
   - "மாற்றம்" (Maatram - Change)
   - "நம்பிக்கை" (Nambikkai - Hope)
   - "ஒற்றுமை" (Otrumai - Unity)
3. Make it emotionally inspiring and hopeful
4. Add call-to-action phrases
5. Keep it concise (under 300 words)
6. Ensure ONLY POSITIVE tone about TVK and Vijay
7. Include 2-3 Tamil SEO words naturally

ENHANCED CAPTION (respond with ONLY the enhanced caption, no explanations):"""

        # Prepare content parts
        parts = []
        
        # Add media if available
        if media_path and os.path.exists(media_path):
            try:
                file_size = os.path.getsize(media_path) / (1024 * 1024)  # MB
                
                if media_type == 'image':
                    print(f"  Including image in Gemini analysis...")
                    # Read and upload image
                    with open(media_path, 'rb') as f:
                        image_bytes = f.read()
                    
                    # Add image to parts
                    parts.append(types.Part.from_bytes(
                        data=image_bytes,
                        mime_type=mimetypes.guess_type(media_path)[0] or 'image/jpeg'
                    ))
                elif media_type == 'video' and file_size < 20:
                    print(f"  Including video in Gemini analysis...")
                    # Upload video file
                    with open(media_path, 'rb') as f:
                        video_bytes = f.read()
                    
                    parts.append(types.Part.from_bytes(
                        data=video_bytes,
                        mime_type='video/mp4'
                    ))
            except Exception as e:
                print(f"  Could not include media in AI analysis: {e}")
        
        # Add text prompt
        parts.append(types.Part.from_text(text=prompt))
        
        # Generate enhanced caption
        print(f"  Generating enhanced caption with Gemini AI...")
        response = client.models.generate_content(
            model='gemini-2.0-flash-exp',
            contents=parts
        )
        
        if response and response.text:
            enhanced = response.text.strip()
            # Validate the response
            if len(enhanced) > 50 and len(enhanced) < 2000:
                print(f"  Caption enhanced successfully!")
                return enhanced
            else:
                print(f"  AI response too short/long, using original")
                return original_caption
        else:
            print(f"  No response from Gemini, using original")
            return original_caption
            
    except Exception as e:
        print(f"  Gemini AI error: {e}")
        return original_caption


def is_repost_or_reply(content, raw_description='', tweet_link=''):
    """Check if a tweet is a repost, quote tweet, or reply"""
    if not content:
        return False
    
    # Check for retweet indicators
    retweet_patterns = [r'^RT\s+@', r'^RT:', r'\bRetweet\b']
    for pattern in retweet_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return True
    
    # Check for reply
    if re.match(r'^@\w+', content.strip()):
        return True
    
    # Check for quote tweets (links to OTHER tweets)
    if raw_description:
        embedded = re.findall(r'https?://(?:x\.com|twitter\.com)/(\w+)/status/(\d+)', raw_description)
        
        own_id = None
        if tweet_link:
            own_match = re.search(r'/status/(\d+)', tweet_link)
            if own_match:
                own_id = own_match.group(1)
        
        for username, tweet_id in embedded:
            if own_id and tweet_id != own_id:
                return True
    
    return False


def parse_date(date_str):
    """Parse RSS date string"""
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except:
        return None


def is_within_time_window(pub_date_str, window_minutes):
    """Check if date is within window"""
    pub_date = parse_date(pub_date_str)
    if not pub_date:
        return False
    
    now = datetime.now(timezone.utc)
    if pub_date.tzinfo is None:
        pub_date = pub_date.replace(tzinfo=timezone.utc)
    
    return (now - pub_date) <= timedelta(minutes=window_minutes)


def extract_image_url(description, media_url=None):
    """Extract image URL from description or media tag"""
    if description:
        matches = re.findall(r'https://pbs\.twimg\.com/media/[A-Za-z0-9_-]+(?:\.[a-zA-Z]+)?(?:\?[^"\s<>]*)?', description)
        if matches:
            return matches[0].replace('&amp;', '&')
    
    if media_url:
        return media_url.replace('&amp;', '&')
    
    return None


def download_image(url):
    """Download image and return file path"""
    try:
        if 'pbs.twimg.com/media/' in url and '?' not in url:
            url = url + '?format=jpg&name=large'
        
        response = requests.get(url, timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
        response.raise_for_status()
        
        ext = '.jpg'
        ct = response.headers.get('content-type', '')
        if 'png' in ct: ext = '.png'
        elif 'gif' in ct: ext = '.gif'
        elif 'webp' in ct: ext = '.webp'
        
        f = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        f.write(response.content)
        f.close()
        
        print(f"Image downloaded: {len(response.content)/1024:.1f} KB")
        return f.name
    except Exception as e:
        print(f"Failed to download image: {e}")
        return None


def download_video(tweet_url):
    """Download video using yt-dlp with improved error handling"""
    if not HAS_YTDLP:
        return None, "yt-dlp not installed"
    
    try:
        output = tempfile.mktemp(suffix='')
        
        # Improved options for Twitter/X video download
        opts = {
            'outtmpl': output + '.%(ext)s',
            'quiet': False,
            'no_warnings': False,
            'format': 'best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best',
            'socket_timeout': 60,
            'retries': 3,
            'fragment_retries': 3,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            },
            # Try to use browser cookies for authentication
            'cookiesfrombrowser': ('chrome',),
            'nocheckcertificate': True,
            'ignoreerrors': False,
            'no_color': True,
            'merge_output_format': 'mp4',
        }
        
        print(f"  Attempting video download from: {tweet_url}")
        
        # First attempt with cookies
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(tweet_url, download=True)
                if info:
                    filename = ydl.prepare_filename(info)
                    # Handle merged files
                    if not os.path.exists(filename):
                        # Try with .mp4 extension
                        mp4_file = output + '.mp4'
                        if os.path.exists(mp4_file):
                            filename = mp4_file
                    
                    if os.path.exists(filename):
                        size = os.path.getsize(filename) / (1024*1024)
                        print(f"  Video downloaded: {size:.1f} MB")
                        return filename, None
        except Exception as e1:
            print(f"  First attempt failed: {e1}")
            # Try without cookies
            opts.pop('cookiesfrombrowser', None)
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(tweet_url, download=True)
                    if info:
                        filename = ydl.prepare_filename(info)
                        if not os.path.exists(filename):
                            mp4_file = output + '.mp4'
                            if os.path.exists(mp4_file):
                                filename = mp4_file
                        
                        if os.path.exists(filename):
                            size = os.path.getsize(filename) / (1024*1024)
                            print(f"  Video downloaded: {size:.1f} MB")
                            return filename, None
            except Exception as e2:
                return None, f"Both attempts failed: {e1}, then {e2}"
        
        return None, "File not created after download"
    except Exception as e:
        return None, str(e)


def check_for_video(tweet_url):
    """Check if tweet has video"""
    if not HAS_YTDLP:
        return False
    
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True}) as ydl:
            info = ydl.extract_info(tweet_url, download=False)
            if info and (info.get('duration') or info.get('ext') in ['mp4', 'mov', 'webm']):
                return True
        return False
    except:
        return False


def fetch_feed(url):
    """Fetch and parse RSS feed"""
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        
        ns = {'media': 'http://search.yahoo.com/mrss/'}
        items = []
        
        for item in root.findall('.//item'):
            link = item.find('link')
            desc = item.find('description')
            pub = item.find('pubDate')
            
            media_url = None
            media = item.find('media:content', ns)
            if media is not None:
                media_url = media.get('url', '').replace('&amp;', '&')
            
            if link is not None:
                items.append({
                    'link': link.text,
                    'id': link.text.split('/')[-1] if link.text else '',
                    'description': desc.text if desc is not None else '',
                    'pub_date': pub.text if pub is not None else None,
                    'media_url': media_url
                })
        
        return items
    except Exception as e:
        print(f"Failed to fetch feed: {e}")
        return []


def post_to_facebook(page_id, token, message, media_path=None, scheduled_time=None, media_type='text'):
    """Post to Facebook page"""
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


def main():
    print("=" * 50)
    print("Twitter to Facebook Bot")
    print(f"Time: {datetime.now().isoformat()}")
    print("=" * 50)
    
    # Load config and state
    config = load_config()
    state = load_state()
    
    # Get settings
    settings = config.get('settings', {})
    post_window = settings.get('post_window_minutes', DEFAULT_POST_WINDOW_MINUTES)
    schedule_gap = settings.get('schedule_gap_minutes', DEFAULT_SCHEDULE_GAP_MINUTES)
    min_length = settings.get('min_content_length', DEFAULT_MIN_CONTENT_LENGTH)
    
    page_id = config['facebook']['page_id']
    token = config['facebook']['access_token']
    feeds = config.get('feeds', [])
    
    print(f"Settings: window={post_window}min, gap={schedule_gap}min, min_len={min_length}")
    
    if not feeds:
        print("No feeds configured!")
        return
    
    # Sort by priority
    feeds = sorted(feeds, key=lambda f: f.get('priority', 99))
    
    # Collect posts
    posts = []
    
    for feed in feeds:
        if not feed.get('enabled', True):
            continue
        
        feed_id = feed.get('id', 'unknown')
        feed_url = feed.get('url')
        
        print(f"\nChecking: {feed_id}")
        
        items = fetch_feed(feed_url)
        if not items:
            continue
        
        latest = items[0]
        latest_id = latest['id']
        
        # Skip if already posted
        last_id = state.get('last_posted_ids', {}).get(feed_id)
        if last_id == latest_id:
            print(f"  Already posted: {latest_id}")
            continue
        
        # Check time window
        if not is_within_time_window(latest['pub_date'], post_window):
            print(f"  Too old (>{post_window}min)")
            continue
        
        # Clean and check
        message = clean_text(latest['description'])
        print(f"  Length: {len(message)} chars")
        
        if len(message) < min_length:
            print(f"  SKIP: Too short")
            continue
        
        if is_repost_or_reply(message, latest['description'], latest['link']):
            print(f"  SKIP: Repost/reply")
            continue
        
        # Get media
        image_url = extract_image_url(latest['description'], latest.get('media_url'))
        has_video = False
        
        if image_url:
            print(f"  Has image")
        else:
            print(f"  Checking for video...")
            has_video = check_for_video(latest['link'])
            print(f"  Has video: {has_video}")
        
        posts.append({
            'feed_id': feed_id,
            'item_id': latest_id,
            'message': message,
            'image_url': image_url,
            'tweet_url': latest['link'],
            'has_video': has_video
        })
    
    print(f"\n{'='*50}")
    print(f"Posts to make: {len(posts)}")
    print("=" * 50)
    
    if not posts:
        save_state(state)
        return
    
    # Post them
    base_time = datetime.now(timezone.utc)
    
    for i, post in enumerate(posts):
        feed_id = post['feed_id']
        message = post['message']
        
        print(f"\n{'─'*40}")
        print(f"Processing: {feed_id}")
        print(f"{'─'*40}")
        
        # STEP 1: Download media FIRST (needed for AI analysis)
        media_path = None
        media_type = 'text'
        
        if post.get('image_url'):
            print(f"Step 1: Downloading image...")
            media_path = download_image(post['image_url'])
            if media_path:
                media_type = 'image'
                print(f"  ✓ Image downloaded")
        elif post.get('has_video'):
            print(f"Step 1: Downloading video...")
            media_path, err = download_video(post['tweet_url'])
            if media_path:
                media_type = 'video'
                print(f"  ✓ Video downloaded")
            else:
                print(f"  ✗ Video failed: {err}")
        else:
            print(f"Step 1: No media to download")
        
        # STEP 2: Enhance caption with Gemini AI (using media for context)
        print(f"Step 2: Enhancing caption with Gemini AI...")
        enhanced_message = enhance_caption_with_gemini(
            original_caption=message,
            media_path=media_path,
            media_type=media_type
        )
        
        # STEP 3: Generate SEO hashtags
        print(f"Step 3: Generating SEO hashtags...")
        hashtags = generate_seo_hashtags(content=enhanced_message, max_hashtags=10)
        print(f"  Hashtags: {' '.join(hashtags[:5])}...")
        
        # STEP 4: Format final message with hashtags
        final_message = format_post_with_hashtags(enhanced_message, hashtags)
        
        # STEP 5: Post to Facebook
        sched = None
        if i == 0:
            print(f"Step 4: Posting immediately ({media_type})...")
        else:
            sched_dt = base_time + timedelta(minutes=schedule_gap * i)
            sched = int(sched_dt.timestamp())
            print(f"Step 4: Scheduling for {sched_dt.strftime('%H:%M')} ({media_type})...")
        
        success, result = post_to_facebook(page_id, token, final_message, media_path, sched, media_type)
        
        # Cleanup
        if media_path and os.path.exists(media_path):
            os.remove(media_path)
        
        if success:
            status = 'SCHEDULED' if i > 0 else 'POSTED'
            print(f"SUCCESS! {status}: {result}")
            state.setdefault('last_posted_ids', {})[feed_id] = post['item_id']
        else:
            print(f"FAILED: {result}")
    
    # Save state
    save_state(state)
    print("\nDone!")


if __name__ == '__main__':
    main()
