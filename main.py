"""
Twitter to Facebook Bot - RSS FEED VERSION (SIMPLE & RELIABLE)
No browser automation - uses RSS feeds from RSS.app or Nitter
"""
import json
import os
import random
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
import xml.etree.ElementTree as ET
import requests

try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    HAS_YTDLP = False

try:
    from google import genai
    from google.genai import types
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

# Fix encoding
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
    
    raise Exception("No config found!")


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
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', raw_content)
    # Remove URLs
    text = re.sub(r'https?://\S+', '', text)
    # Remove leading @mentions
    text = re.sub(r'^(@\w+\s*)+', '', text)
    # Normalize whitespace
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
    
    # Core TVK hashtags (always)
    core_tvk = ["#TVK", "#ThamizhagaVetriKazhagam", "#ThalapathyVijay"]
    hashtags.extend(core_tvk)
    
    # Random TVK hashtags
    remaining_tvk = [h for h in TVK_POSITIVE_HASHTAGS if h not in core_tvk]
    hashtags.extend(random.sample(remaining_tvk, min(3, len(remaining_tvk))))
    
    # Content-based hashtags
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
    
    # Fill with general SEO
    while len(hashtags) < max_hashtags:
        remaining = [h for h in GENERAL_SEO_HASHTAGS if h not in hashtags]
        if not remaining:
            break
        hashtags.append(random.choice(remaining))
    
    # Remove duplicates
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
    """Use Gemini AI to enhance caption"""
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


def is_repost_or_reply(content, raw_description='', tweet_link=''):
    """Check if a tweet is a repost, quote tweet, or reply"""
    # Check for RT indicators
    if content.strip().startswith('RT @') or 'RT @' in content[:20]:
        return True
    
    # Check for reply indicators
    if content.strip().startswith('@'):
        return True
    
    # Check raw description for retweet indicators
    if 'retweeted' in raw_description.lower():
        return True
    
    return False


def parse_date(date_str):
    """Parse RSS date string"""
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(date_str)
    except:
        return datetime.now(timezone.utc)


def is_within_time_window(pub_date_str, window_minutes):
    """Check if date is within window"""
    if not pub_date_str:
        return False
    
    pub_date = parse_date(pub_date_str)
    now = datetime.now(timezone.utc)
    
    if pub_date.tzinfo is None:
        pub_date = pub_date.replace(tzinfo=timezone.utc)
    
    age_minutes = (now - pub_date).total_seconds() / 60
    return age_minutes <= window_minutes


def extract_image_url(description, media_url=None):
    """Extract image URL from description or media tag"""
    if media_url and ('twimg.com' in media_url or 'pbs.twimg.com' in media_url):
        # Get original quality
        media_url = re.sub(r'&name=\w+', '&name=large', media_url)
        return media_url
    
    # Try to find image in description
    img_match = re.search(r'https://pbs\.twimg\.com/media/[^"\s<]+', description or '')
    if img_match:
        url = img_match.group(0)
        url = re.sub(r'&name=\w+', '&name=large', url)
        return url
    
    return None


def download_image(url):
    """Download image and return file path"""
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        # Determine extension
        ext = '.jpg'
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
        print(f"  Image download error: {e}")
        return None


def download_video(tweet_url):
    """Download video using yt-dlp"""
    if not HAS_YTDLP:
        return None
    
    try:
        temp_dir = tempfile.gettempdir()
        output_template = os.path.join(temp_dir, '%(id)s.%(ext)s')
        
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(tweet_url, download=True)
            if info:
                video_id = info.get('id', 'video')
                for ext in ['mp4', 'webm', 'mkv']:
                    video_path = os.path.join(temp_dir, f"{video_id}.{ext}")
                    if os.path.exists(video_path):
                        return video_path
        
        return None
    except Exception as e:
        print(f"  Video download error: {e}")
        return None


def check_for_video(tweet_url):
    """Check if tweet has video"""
    # Simple heuristic - try to download
    video_path = download_video(tweet_url)
    if video_path and os.path.exists(video_path):
        return True
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
    print("="*50)
    print("Twitter to Facebook Bot - RSS FEED VERSION")
    print(f"Time: {datetime.now().isoformat()}")
    print("="*50)
    
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
        
        # STEP 1: Download media
        media_path = None
        media_type = 'text'
        
        if post.get('image_url'):
            print(f"Downloading image...")
            media_path = download_image(post['image_url'])
            if media_path:
                media_type = 'image'
                print(f"  ✓ Image downloaded")
        elif post.get('has_video'):
            print(f"Downloading video...")
            media_path = download_video(post['tweet_url'])
            if media_path:
                media_type = 'video'
                print(f"  ✓ Video downloaded")
        
        # STEP 2: Enhance caption
        print(f"Enhancing caption...")
        enhanced_message = enhance_caption_with_gemini(message, media_path, media_type)
        
        # STEP 3: Generate hashtags
        print(f"Generating hashtags...")
        hashtags = generate_seo_hashtags(content=enhanced_message, max_hashtags=10)
        
        # STEP 4: Format final message
        final_message = format_post_with_hashtags(enhanced_message, hashtags)
        
        # STEP 5: Post to Facebook
        sched = None
        if i > 0:
            sched_dt = base_time + timedelta(minutes=schedule_gap * i)
            sched = int(sched_dt.timestamp())
        
        print(f"Posting to Facebook...")
        success, result = post_to_facebook(page_id, token, final_message, media_path, sched, media_type)
        
        # Cleanup
        if media_path and os.path.exists(media_path):
            os.remove(media_path)
        
        if success:
            status = 'SCHEDULED' if i > 0 else 'POSTED'
            print(f"  [SUCCESS] {status}: {result}")
            state.setdefault('last_posted_ids', {})[feed_id] = post['item_id']
        else:
            print(f"  [FAILED] {result}")
    
    # Save state
    save_state(state)
    print("\nDone!")


if __name__ == '__main__':
    main()
