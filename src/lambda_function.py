"""
Twitter to Facebook Cross-Poster Lambda Function
Supports multiple RSS feeds with priority-based posting and Facebook scheduled publishing.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone
import boto3
import requests
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import yt_dlp


# --- Configuration from Environment Variables ---
FB_ACCESS_TOKEN = os.environ.get('FB_ACCESS_TOKEN')
FB_PAGE_ID = os.environ.get('FB_PAGE_ID')
S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME')
CONFIG_FILE = 'feed_config.json'
STATE_FILE = 'posting_state.json'

# Default config if not provided via S3
DEFAULT_FEEDS = os.environ.get('RSS_FEEDS', '').split(',')
PRIMARY_FEED = os.environ.get('PRIMARY_RSS_URL', '')

# Default settings (can be overridden by config)
DEFAULT_POST_WINDOW_MINUTES = 10  # Only post tweets from the last 10 minutes
DEFAULT_SCHEDULE_GAP_MINUTES = 10  # Gap between scheduled posts

# --- AWS S3 Client ---
s3 = boto3.client('s3')


def load_state():
    """Load posting state from S3"""
    try:
        response = s3.get_object(Bucket=S3_BUCKET_NAME, Key=STATE_FILE)
        return json.loads(response['Body'].read().decode('utf-8'))
    except Exception:
        return {
            'last_posted_ids': {},
            'last_post_time': None,
            'scheduled_posts': []
        }


def save_state(state):
    """Save posting state to S3"""
    s3.put_object(
        Bucket=S3_BUCKET_NAME,
        Key=STATE_FILE,
        Body=json.dumps(state, indent=2, default=str),
        ContentType='application/json'
    )


def load_feed_config():
    """Load feed configuration from S3 or environment"""
    try:
        response = s3.get_object(Bucket=S3_BUCKET_NAME, Key=CONFIG_FILE)
        return json.loads(response['Body'].read().decode('utf-8'))
    except Exception:
        # Build config from environment variables
        feeds = []
        
        # Primary feed (highest priority)
        if PRIMARY_FEED:
            feeds.append({
                'id': 'primary',
                'url': PRIMARY_FEED,
                'priority': 1,
                'enabled': True
            })
        
        # Additional feeds from comma-separated list
        for i, url in enumerate(DEFAULT_FEEDS):
            if url.strip():
                feeds.append({
                    'id': f'feed_{i+2}',
                    'url': url.strip(),
                    'priority': i + 2,
                    'enabled': True
                })
        
        return {'feeds': feeds}


def clean_text(text):
    """Clean HTML and format text naturally with proper spacing preserved"""
    if not text:
        return ""
    
    # Convert <br> tags to newlines
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)
    
    # Remove all other HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Decode HTML entities
    html_entities = {
        '&amp;': '&', '&lt;': '<', '&gt;': '>',
        '&quot;': '"', '&#39;': "'", '&nbsp;': ' '
    }
    for entity, char in html_entities.items():
        text = text.replace(entity, char)
    
    # Remove URLs
    text = re.sub(r'https?://\S+', '', text)
    
    # Remove Twitter attribution
    text = re.sub(r'—\s*[^—\n]+\(@\w+\)\s*\w+\s*\d+,?\s*\d*', '', text)
    text = re.sub(r'pic\.twitter\.com/\S+', '', text)
    
    # Clean spacing but preserve paragraph breaks
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(lines)
    
    return text.strip()


def is_repost_or_reply(content, raw_description='', tweet_link=''):
    """
    Check if a tweet is a repost (retweet), quote tweet, or reply.
    Returns True if it should be skipped.
    
    Args:
        content: Cleaned text content
        raw_description: Raw HTML/RSS description before cleaning
        tweet_link: The link to this specific tweet (to exclude self-references)
    """
    if not content:
        return False
    
    # Check for retweet indicators in cleaned content
    retweet_patterns = [
        r'^RT\s+@',           # Starts with "RT @username"
        r'^RT:',              # Starts with "RT:"
        r'\bRetweet\b',       # Contains "Retweet" as a word
    ]
    
    for pattern in retweet_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return True
    
    # Check for reply indicators (tweets that start with @mention)
    if re.match(r'^@\w+', content.strip()):
        return True
    
    # Check raw description for quote tweets (embedded tweet links to OTHER tweets)
    if raw_description:
        # Find all tweet links in the description
        embedded_tweets = re.findall(
            r'https?://(?:x\.com|twitter\.com)/(\w+)/status/(\d+)',
            raw_description
        )
        
        # Extract this tweet's ID from its link
        own_tweet_id = None
        if tweet_link:
            own_match = re.search(r'/status/(\d+)', tweet_link)
            if own_match:
                own_tweet_id = own_match.group(1)
        
        # Check if any embedded tweet is DIFFERENT from this tweet
        for username, tweet_id in embedded_tweets:
            if own_tweet_id and tweet_id != own_tweet_id:
                # This embeds a DIFFERENT tweet - it's a quote tweet
                return True
    
    return False


def parse_rss_date(date_str):
    """Parse RSS date string to datetime object"""
    try:
        # Try standard RSS date format
        return parsedate_to_datetime(date_str)
    except Exception:
        try:
            # Try ISO format
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except Exception:
            return None


def is_within_time_window(pub_date_str, window_minutes=DEFAULT_POST_WINDOW_MINUTES):
    """Check if the post was published within the last N minutes"""
    if not pub_date_str:
        # If no date, assume it's recent (for feeds that don't include dates)
        return True
    
    pub_date = parse_rss_date(pub_date_str)
    if not pub_date:
        return True  # Can't parse, assume recent
    
    # Make sure we're comparing timezone-aware datetimes
    now = datetime.now(timezone.utc)
    if pub_date.tzinfo is None:
        pub_date = pub_date.replace(tzinfo=timezone.utc)
    
    time_diff = now - pub_date
    return time_diff <= timedelta(minutes=window_minutes)


def extract_image_from_content(content):
    """Extract image URL only from the specific content provided"""
    if not content:
        return None
    
    # Only match Twitter media CDN URLs
    matches = re.findall(
        r'https://pbs\.twimg\.com/media/[A-Za-z0-9_-]+(?:\.[a-zA-Z]+)?(?:\?[^"\s<>]*)?',
        content
    )
    
    if matches:
        url = matches[0].replace('&amp;', '&')
        url = re.sub(r'["\'>]$', '', url)
        return url
    
    return None


def download_image(url):
    """Download image and return local file path"""
    try:
        if 'pbs.twimg.com/media/' in url and '?' not in url:
            url = url + '?format=jpg&name=large'
        
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, timeout=30, headers=headers)
        response.raise_for_status()
        
        content_type = response.headers.get('content-type', '')
        if 'image' not in content_type:
            return None
        
        ext = '.png' if 'png' in content_type else '.gif' if 'gif' in content_type else '.jpg'
        
        # Use /tmp for Lambda
        temp_path = f'/tmp/image_{datetime.now().timestamp()}{ext}'
        with open(temp_path, 'wb') as f:
            f.write(response.content)
        
        return temp_path
    except Exception as e:
        print(f"Failed to download image: {e}")
        return None


def download_video_from_tweet(tweet_url):
    """
    Download video from a tweet using yt-dlp.
    Returns tuple: (video_path, None) on success, (None, error_msg) on failure
    """
    try:
        output_path = f'/tmp/video_{datetime.now().timestamp()}'
        
        ydl_opts = {
            'outtmpl': output_path + '.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'format': 'best[ext=mp4]/best',
            'socket_timeout': 30,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(tweet_url, download=True)
            filename = ydl.prepare_filename(info)
            
            # Check if file exists
            if os.path.exists(filename):
                file_size = os.path.getsize(filename) / (1024 * 1024)  # MB
                print(f"Video downloaded: {filename} ({file_size:.1f} MB)")
                return filename, None
            else:
                return None, "Video file not created"
                
    except Exception as e:
        error_msg = str(e)
        print(f"Failed to download video: {error_msg}")
        return None, error_msg


def check_for_video_in_tweet(tweet_url):
    """
    Check if a tweet contains a video using yt-dlp without downloading.
    Returns True if video is present.
    """
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'socket_timeout': 10,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(tweet_url, download=False)
            # If we get info without error, there's media
            if info:
                # Check if it's a video (not just an image)
                if info.get('duration') or info.get('ext') in ['mp4', 'mov', 'webm']:
                    return True
        return False
    except Exception:
        return False


def fetch_rss_feed(feed_url):
    """Fetch and parse RSS feed"""
    try:
        response = requests.get(feed_url, timeout=30)
        response.raise_for_status()
        root = ET.fromstring(response.text)
        
        # Namespace for media:content
        namespaces = {'media': 'http://search.yahoo.com/mrss/'}
        
        items = []
        for item in root.findall('.//item'):
            link_elem = item.find('link')
            desc_elem = item.find('description')
            pub_date_elem = item.find('pubDate')
            
            # Try to get media:content URL
            media_url = None
            media_elem = item.find('media:content', namespaces)
            if media_elem is not None:
                media_url = media_elem.get('url', '')
                # Clean up URL
                media_url = media_url.replace('&amp;', '&')
            
            if link_elem is not None:
                items.append({
                    'link': link_elem.text,
                    'id': link_elem.text.split('/')[-1] if link_elem.text else None,
                    'description': desc_elem.text if desc_elem is not None else '',
                    'pub_date': pub_date_elem.text if pub_date_elem is not None else None,
                    'media_url': media_url  # Image URL from media:content tag
                })
        
        return items
    except Exception as e:
        print(f"Failed to fetch RSS: {e}")
        return []


def post_to_facebook(message, media_path=None, scheduled_time=None, media_type='image'):
    """
    Post to Facebook with optional media and optional scheduling.
    
    Args:
        message: The text content
        media_path: Path to image or video file (or None for text-only)
        scheduled_time: Unix timestamp for when to publish (None = publish immediately)
        media_type: 'image', 'video', or 'text'
    """
    try:
        if media_path and media_type == 'video':
            # Post with video
            url = f"https://graph.facebook.com/v22.0/{FB_PAGE_ID}/videos"
            data = {
                'description': message,
                'access_token': FB_ACCESS_TOKEN
            }
            
            if scheduled_time:
                data['published'] = 'false'
                data['scheduled_publish_time'] = int(scheduled_time)
            
            with open(media_path, 'rb') as video_file:
                response = requests.post(url, data=data, files={'source': video_file})
                
        elif media_path and media_type == 'image':
            # Post with image
            url = f"https://graph.facebook.com/v22.0/{FB_PAGE_ID}/photos"
            data = {
                'caption': message,
                'access_token': FB_ACCESS_TOKEN
            }
            
            if scheduled_time:
                data['published'] = 'false'
                data['scheduled_publish_time'] = int(scheduled_time)
            
            with open(media_path, 'rb') as img_file:
                response = requests.post(url, data=data, files={'source': img_file})
        else:
            # Text only post
            url = f"https://graph.facebook.com/v22.0/{FB_PAGE_ID}/feed"
            data = {
                'message': message,
                'access_token': FB_ACCESS_TOKEN
            }
            
            if scheduled_time:
                data['published'] = 'false'
                data['scheduled_publish_time'] = int(scheduled_time)
            
            response = requests.post(url, data=data)
        
        result = response.json()
        if 'id' in result or 'post_id' in result:
            return True, result.get('id') or result.get('post_id')
        else:
            return False, result.get('error', {}).get('message', 'Unknown error')
    except Exception as e:
        return False, str(e)


def get_page_groups():
    """
    Get list of groups the page is a member of.
    Returns list of {id, name} dicts.
    """
    try:
        url = f"https://graph.facebook.com/v22.0/{FB_PAGE_ID}/groups"
        params = {
            'access_token': FB_ACCESS_TOKEN,
            'fields': 'id,name'
        }
        response = requests.get(url, params=params)
        result = response.json()
        
        if 'data' in result:
            groups = result['data']
            print(f"Found {len(groups)} groups for page")
            return groups
        else:
            print(f"Failed to get groups: {result}")
            return []
    except Exception as e:
        print(f"Error getting groups: {e}")
        return []


def share_post_to_groups(post_id, message):
    """
    Share a page post to all groups the page participates in.
    
    Args:
        post_id: The ID of the post on the page
        message: The caption to use when sharing
    
    Returns:
        List of results for each group share attempt
    """
    groups = get_page_groups()
    if not groups:
        print("No groups found to share to")
        return []
    
    results = []
    for group in groups:
        group_id = group['id']
        group_name = group.get('name', 'Unknown')
        
        try:
            # Share the post to the group using the link
            post_link = f"https://www.facebook.com/{post_id}"
            url = f"https://graph.facebook.com/v22.0/{group_id}/feed"
            data = {
                'message': message,
                'link': post_link,
                'access_token': FB_ACCESS_TOKEN
            }
            
            response = requests.post(url, data=data)
            result = response.json()
            
            if 'id' in result:
                print(f"  Shared to group '{group_name}': {result['id']}")
                results.append({'group_id': group_id, 'group_name': group_name, 'success': True, 'post_id': result['id']})
            else:
                error = result.get('error', {}).get('message', 'Unknown error')
                print(f"  Failed to share to group '{group_name}': {error}")
                results.append({'group_id': group_id, 'group_name': group_name, 'success': False, 'error': error})
        except Exception as e:
            print(f"  Error sharing to group '{group_name}': {e}")
            results.append({'group_id': group_id, 'group_name': group_name, 'success': False, 'error': str(e)})
    
    return results


def get_new_post_from_feed(feed_config, state, post_window_minutes=DEFAULT_POST_WINDOW_MINUTES, min_content_length=50):
    """
    Get a new post from a feed if available.
    Returns the post data or None if no valid new post.
    """
    feed_id = feed_config.get('id', 'unknown')
    feed_url = feed_config.get('url')
    
    if not feed_url:
        return None
    
    # Fetch RSS
    items = fetch_rss_feed(feed_url)
    if not items:
        return None
    
    # Get latest item
    latest = items[0]
    latest_id = latest.get('id')
    
    # Check if already posted (prevent duplicates)
    last_posted = state.get('last_posted_ids', {}).get(feed_id)
    if latest_id == last_posted:
        print(f"[{feed_id}] No new posts (already posted: {latest_id})")
        return None
    
    # Check if post is within time window
    if not is_within_time_window(latest.get('pub_date'), post_window_minutes):
        print(f"[{feed_id}] Post too old (>{post_window_minutes}min), skipping: {latest_id}")
        return None
    
    # Check if repost/reply
    raw_description = latest.get('description', '')
    tweet_link = latest.get('link', '')
    cleaned_text = clean_text(raw_description)
    
    if is_repost_or_reply(cleaned_text, raw_description, tweet_link):
        print(f"[{feed_id}] Skipping repost/reply: {latest_id}")
        # Mark as seen so we don't check again
        return {'action': 'skip', 'feed_id': feed_id, 'item_id': latest_id, 'reason': 'repost'}
    
    # Check minimum content length (short tweets are often reposts)
    if len(cleaned_text) < min_content_length:
        print(f"[{feed_id}] Too short ({len(cleaned_text)} < {min_content_length}), skipping: {latest_id}")
        return {'action': 'skip', 'feed_id': feed_id, 'item_id': latest_id, 'reason': 'too_short'}
    
    if not cleaned_text:
        print(f"[{feed_id}] Empty content after cleaning: {latest_id}")
        return None
    
    # Extract image - first try description, then media:content tag
    image_url = extract_image_from_content(raw_description)
    if not image_url:
        # Try media_url from RSS media:content tag
        image_url = latest.get('media_url')
        if image_url:
            print(f"[{feed_id}] Found image in media:content tag")
    
    # Check if tweet has video (need tweet URL for yt-dlp)
    tweet_url = latest.get('link', '')
    has_video = False
    
    # If no image found in RSS, check if tweet has video
    if not image_url and tweet_url:
        print(f"[{feed_id}] No image in RSS, checking for video...")
        has_video = check_for_video_in_tweet(tweet_url)
        if has_video:
            print(f"[{feed_id}] Video detected in tweet")
    
    return {
        'action': 'post',
        'feed_id': feed_id,
        'feed_priority': feed_config.get('priority', 99),
        'item_id': latest_id,
        'message': cleaned_text,
        'image_url': image_url,
        'tweet_url': tweet_url,
        'has_video': has_video,
        'pub_date': latest.get('pub_date')
    }


def lambda_handler(event, context):
    """Main Lambda handler - processes all feeds with priority and scheduling"""
    print("=" * 50)
    print("Twitter to Facebook Bot - Starting")
    print(f"Time: {datetime.now().isoformat()}")
    print("=" * 50)
    
    # Load state and config
    state = load_state()
    config = load_feed_config()
    
    # Get settings from config
    settings = config.get('settings', {})
    post_window_minutes = settings.get('post_window_minutes', DEFAULT_POST_WINDOW_MINUTES)
    schedule_gap_minutes = settings.get('schedule_gap_minutes', DEFAULT_SCHEDULE_GAP_MINUTES)
    min_content_length = settings.get('min_content_length', 50)
    
    print(f"Settings: post_window={post_window_minutes}min, schedule_gap={schedule_gap_minutes}min, min_length={min_content_length}")
    
    feeds = config.get('feeds', [])
    if not feeds:
        return {"statusCode": 200, "body": "No feeds configured"}
    
    # Sort feeds by priority (1 = highest)
    feeds = sorted(feeds, key=lambda f: f.get('priority', 99))
    
    # Collect all new posts from all feeds
    posts_to_make = []
    
    for feed in feeds:
        if not feed.get('enabled', True):
            continue
        
        print(f"\nChecking feed: {feed.get('id')} (priority: {feed.get('priority', 99)})")
        result = get_new_post_from_feed(feed, state, post_window_minutes, min_content_length)
        
        if result:
            if result.get('action') == 'skip':
                # Mark as processed
                if 'last_posted_ids' not in state:
                    state['last_posted_ids'] = {}
                state['last_posted_ids'][result['feed_id']] = result['item_id']
            elif result.get('action') == 'post':
                posts_to_make.append(result)
    
    # Sort posts by priority
    posts_to_make.sort(key=lambda p: p.get('feed_priority', 99))
    
    print(f"\n{'=' * 50}")
    print(f"Found {len(posts_to_make)} posts to make")
    print("=" * 50)
    
    results = []
    posts_made = 0
    
    # Calculate scheduling times
    # First post = now, subsequent posts = +10 mins each
    base_time = datetime.now(timezone.utc)
    
    for i, post in enumerate(posts_to_make):
        feed_id = post['feed_id']
        item_id = post['item_id']
        message = post['message']
        image_url = post.get('image_url')
        tweet_url = post.get('tweet_url', '')
        has_video = post.get('has_video', False)
        
        # Download media
        media_path = None
        media_type = 'text'
        
        if image_url:
            # Has image - download it
            print(f"Downloading image for {feed_id}...")
            media_path = download_image(image_url)
            if media_path:
                media_type = 'image'
        elif has_video and tweet_url:
            # Has video - download it using yt-dlp
            print(f"Downloading video for {feed_id}...")
            media_path, error = download_video_from_tweet(tweet_url)
            if media_path:
                media_type = 'video'
            else:
                print(f"Video download failed: {error}")
        
        # Determine if this should be scheduled
        if i == 0:
            # First post - publish immediately
            scheduled_time = None
            print(f"\nPosting immediately from {feed_id} (type: {media_type})...")
        else:
            # Subsequent posts - schedule N mins apart
            scheduled_time = base_time + timedelta(minutes=schedule_gap_minutes * i)
            scheduled_unix = int(scheduled_time.timestamp())
            print(f"\nScheduling post from {feed_id} for {scheduled_time.isoformat()} (type: {media_type})...")
            scheduled_time = scheduled_unix
        
        # Post to Facebook
        success, result = post_to_facebook(message, media_path, scheduled_time, media_type)
        
        # Cleanup media
        if media_path and os.path.exists(media_path):
            os.remove(media_path)
        
        if success:
            status = "scheduled" if i > 0 else "posted"
            print(f"SUCCESS! {status.upper()}: {result}")
            results.append({
                'action': status,
                'feed_id': feed_id,
                'post_id': result,
                'item_id': item_id
            })
            
            # Share to groups ONLY for immediate posts (not scheduled)
            if i == 0:
                print(f"\nSharing to groups...")
                group_results = share_post_to_groups(result, message)
                shared_count = sum(1 for r in group_results if r.get('success'))
                print(f"Shared to {shared_count}/{len(group_results)} groups")
            
            # Update state
            if 'last_posted_ids' not in state:
                state['last_posted_ids'] = {}
            state['last_posted_ids'][feed_id] = item_id
            
            if i == 0:
                state['last_post_time'] = datetime.now().isoformat()
            
            posts_made += 1
        else:
            print(f"FAILED: {result}")
            results.append({
                'action': 'error',
                'feed_id': feed_id,
                'error': result
            })
    
    # Save updated state
    save_state(state)
    
    print("\n" + "=" * 50)
    print(f"Completed. Posts made/scheduled: {posts_made}")
    print("=" * 50)
    
    return {
        "statusCode": 200,
        "body": json.dumps({
            "posts_made": posts_made,
            "results": results
        })
    }
