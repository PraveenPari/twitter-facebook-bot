"""
Test script for Twitter to Facebook posting.
Loads configuration from config.json or environment variables.
"""
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import requests
import xml.etree.ElementTree as ET
import yt_dlp

# Fix encoding for Windows console
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Default settings (will be overridden by config)
DEFAULT_POST_WINDOW_MINUTES = 10
DEFAULT_SCHEDULE_GAP_MINUTES = 10


def load_config():
    """Load configuration from config.json or environment"""
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # Also load Facebook token from environment if not in config
        fb_token = os.environ.get('FB_ACCESS_TOKEN')
        if fb_token:
            config['facebook']['access_token'] = fb_token
        
        return config
    else:
        # Fall back to environment variables
        return {
            'feeds': [{
                'id': 'primary',
                'url': os.environ.get('PRIMARY_RSS_URL', ''),
                'priority': 1,
                'enabled': True
            }],
            'facebook': {
                'page_id': os.environ.get('FB_PAGE_ID', ''),
                'access_token': os.environ.get('FB_ACCESS_TOKEN', '')
            },
            'settings': {
                'post_window_minutes': DEFAULT_POST_WINDOW_MINUTES,
                'schedule_gap_minutes': DEFAULT_SCHEDULE_GAP_MINUTES
            }
        }


def clean_text(text):
    """Clean HTML and format text with proper spacing preserved"""
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
    """
    if not content:
        return False
    
    # Check for retweet indicators
    retweet_patterns = [
        r'^RT\s+@',
        r'^RT:',
        r'\bRetweet\b',
    ]
    
    for pattern in retweet_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return True
    
    if re.match(r'^@\w+', content.strip()):
        return True
    
    # Check for quote tweets (embedded tweet links to OTHER tweets)
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
        return parsedate_to_datetime(date_str)
    except Exception:
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except Exception:
            return None


def is_within_time_window(pub_date_str, window_minutes=DEFAULT_POST_WINDOW_MINUTES):
    """Check if the post was published within the last N minutes"""
    if not pub_date_str:
        return True
    
    pub_date = parse_rss_date(pub_date_str)
    if not pub_date:
        return True
    
    now = datetime.now(timezone.utc)
    if pub_date.tzinfo is None:
        pub_date = pub_date.replace(tzinfo=timezone.utc)
    
    time_diff = now - pub_date
    return time_diff <= timedelta(minutes=window_minutes)


def extract_image_from_content(content):
    """Extract image URL only from this specific content"""
    if not content:
        return None
    
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
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        temp_file.write(response.content)
        temp_file.close()
        
        file_size_kb = len(response.content) / 1024
        print(f"Image downloaded: {file_size_kb:.1f} KB")
        return temp_file.name
    except Exception as e:
        print(f"Failed to download image: {e}")
        return None


def download_video_from_tweet(tweet_url):
    """Download video from a tweet using yt-dlp."""
    try:
        output_path = tempfile.mktemp(suffix='')
        
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
            
            if os.path.exists(filename):
                file_size = os.path.getsize(filename) / (1024 * 1024)
                print(f"Video downloaded: {filename} ({file_size:.1f} MB)")
                return filename, None
            else:
                return None, "Video file not created"
                
    except Exception as e:
        error_msg = str(e)
        print(f"Failed to download video: {error_msg}")
        return None, error_msg


def check_for_video_in_tweet(tweet_url):
    """Check if a tweet contains a video without downloading."""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'socket_timeout': 10,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(tweet_url, download=False)
            if info:
                if info.get('duration') or info.get('ext') in ['mp4', 'mov', 'webm']:
                    return True
        return False
    except Exception:
        return False


def fetch_feed_items(feed_url):
    """Fetch all items from an RSS feed"""
    response = requests.get(feed_url, timeout=30)
    response.raise_for_status()
    root = ET.fromstring(response.text)
    
    # Namespace for media:content
    namespaces = {'media': 'http://search.yahoo.com/mrss/'}
    
    items = []
    for item in root.findall('.//item'):
        link = item.find('link')
        desc = item.find('description')
        pub_date = item.find('pubDate')
        
        # Try to get media:content URL
        media_url = None
        media_elem = item.find('media:content', namespaces)
        if media_elem is not None:
            media_url = media_elem.get('url', '')
            media_url = media_url.replace('&amp;', '&')
        
        if link is not None:
            items.append({
                'link': link.text,
                'id': link.text.split('/')[-1] if link.text else '',
                'description': desc.text if desc is not None else '',
                'pub_date': pub_date.text if pub_date is not None else None,
                'media_url': media_url
            })
    
    return items


def post_to_facebook(config, message, media_path=None, scheduled_time=None, media_type='text'):
    """Post to Facebook with optional media and scheduling"""
    page_id = config['facebook']['page_id']
    access_token = config['facebook']['access_token']
    
    if media_path and media_type == 'video':
        # Post with video
        url = f"https://graph.facebook.com/v22.0/{page_id}/videos"
        data = {'description': message, 'access_token': access_token}
        
        if scheduled_time:
            data['published'] = 'false'
            data['scheduled_publish_time'] = int(scheduled_time)
        
        with open(media_path, 'rb') as video_file:
            response = requests.post(url, data=data, files={'source': video_file})
    elif media_path and media_type == 'image':
        # Post with image
        url = f"https://graph.facebook.com/v22.0/{page_id}/photos"
        data = {'caption': message, 'access_token': access_token}
        
        if scheduled_time:
            data['published'] = 'false'
            data['scheduled_publish_time'] = int(scheduled_time)
        
        with open(media_path, 'rb') as img_file:
            response = requests.post(url, data=data, files={'source': img_file})
    else:
        # Text only post
        url = f"https://graph.facebook.com/v22.0/{page_id}/feed"
        data = {'message': message, 'access_token': access_token}
        
        if scheduled_time:
            data['published'] = 'false'
            data['scheduled_publish_time'] = int(scheduled_time)
        
        response = requests.post(url, data=data)
    
    return response.json()


def get_page_groups(config):
    """Get list of groups the page is a member of."""
    try:
        page_id = config['facebook']['page_id']
        access_token = config['facebook']['access_token']
        
        url = f"https://graph.facebook.com/v22.0/{page_id}/groups"
        params = {
            'access_token': access_token,
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


def share_post_to_groups(config, post_id, message):
    """Share a page post to all groups the page participates in."""
    access_token = config['facebook']['access_token']
    groups = get_page_groups(config)
    
    if not groups:
        print("No groups found to share to")
        return []
    
    results = []
    for group in groups:
        group_id = group['id']
        group_name = group.get('name', 'Unknown')
        
        try:
            post_link = f"https://www.facebook.com/{post_id}"
            url = f"https://graph.facebook.com/v22.0/{group_id}/feed"
            data = {
                'message': message,
                'link': post_link,
                'access_token': access_token
            }
            
            response = requests.post(url, data=data)
            result = response.json()
            
            if 'id' in result:
                print(f"  Shared to group '{group_name}': {result['id']}")
                results.append({'group_id': group_id, 'group_name': group_name, 'success': True})
            else:
                error = result.get('error', {}).get('message', 'Unknown error')
                print(f"  Failed to share to '{group_name}': {error}")
                results.append({'group_id': group_id, 'group_name': group_name, 'success': False, 'error': error})
        except Exception as e:
            print(f"  Error sharing to '{group_name}': {e}")
            results.append({'group_id': group_id, 'group_name': group_name, 'success': False, 'error': str(e)})
    
    return results


def main():
    """Main execution - check all feeds and post/schedule"""
    print("=" * 50)
    print("Twitter to Facebook Bot - Test Run")
    print(f"Time: {datetime.now().isoformat()}")
    print("=" * 50)
    
    # Load config
    config = load_config()
    
    # Get settings from config
    settings = config.get('settings', {})
    post_window_minutes = settings.get('post_window_minutes', DEFAULT_POST_WINDOW_MINUTES)
    schedule_gap_minutes = settings.get('schedule_gap_minutes', DEFAULT_SCHEDULE_GAP_MINUTES)
    min_content_length = settings.get('min_content_length', 50)
    
    print(f"Settings: post_window={post_window_minutes}min, schedule_gap={schedule_gap_minutes}min, min_length={min_content_length}")
    
    if not config['feeds']:
        print("ERROR: No feeds configured!")
        return
    
    # Sort feeds by priority
    feeds = sorted(config['feeds'], key=lambda f: f.get('priority', 99))
    
    # Collect posts from all feeds
    posts_to_make = []
    
    for feed in feeds:
        if not feed.get('enabled', True):
            continue
        
        feed_id = feed.get('id', 'unknown')
        feed_url = feed.get('url')
        priority = feed.get('priority', 99)
        
        print(f"\nChecking feed: {feed_id} (priority: {priority})")
        print(f"URL: {feed_url[:50]}...")
        
        try:
            items = fetch_feed_items(feed_url)
            if not items:
                print(f"  No items found")
                continue
            
            latest = items[0]
            print(f"  Latest ID: {latest['id']}")
            
            # Check time window
            if not is_within_time_window(latest.get('pub_date'), post_window_minutes):
                print(f"  SKIP: Post older than {post_window_minutes} minutes")
                continue
            
            # Clean text
            message = clean_text(latest['description'])
            print(f"  Message length: {len(message)} chars")
            
            # Check minimum content length (short tweets are often reposts)
            if len(message) < min_content_length:
                print(f"  SKIP: Too short (min {min_content_length} chars)")
                continue
            
            # Check for repost/quote tweet
            tweet_url = latest.get('link', '')
            if is_repost_or_reply(message, latest['description'], tweet_url):
                print(f"  SKIP: Repost/retweet/quote tweet/reply")
                continue
            
            # Get image - first try description, then media:content tag
            image_url = extract_image_from_content(latest['description'])
            if not image_url:
                image_url = latest.get('media_url')
                if image_url:
                    print(f"  Found image in media:content tag")
            
            has_video = False
            
            if image_url:
                print(f"  Has image: Yes")
            else:
                print(f"  Has image: No, checking for video...")
                if tweet_url:
                    has_video = check_for_video_in_tweet(tweet_url)
                    print(f"  Has video: {'Yes' if has_video else 'No'}")
            
            posts_to_make.append({
                'feed_id': feed_id,
                'priority': priority,
                'item_id': latest['id'],
                'message': message,
                'image_url': image_url,
                'tweet_url': tweet_url,
                'has_video': has_video
            })
            print(f"  ✓ Valid post to make")
            
        except Exception as e:
            print(f"  ERROR: {e}")
    
    print(f"\n{'=' * 50}")
    print(f"Total posts to make: {len(posts_to_make)}")
    print("=" * 50)
    
    if not posts_to_make:
        print("No new posts to make.")
        return
    
    # Sort by priority
    posts_to_make.sort(key=lambda p: p['priority'])
    
    # Post/schedule
    base_time = datetime.now(timezone.utc)
    
    for i, post in enumerate(posts_to_make):
        feed_id = post['feed_id']
        message = post['message']
        image_url = post.get('image_url')
        tweet_url = post.get('tweet_url', '')
        has_video = post.get('has_video', False)
        
        # Download media
        media_path = None
        media_type = 'text'
        
        if image_url:
            # Has image - download it
            print(f"\nDownloading image for {feed_id}...")
            media_path = download_image(image_url)
            if media_path:
                media_type = 'image'
        elif has_video and tweet_url:
            # Has video - download it
            print(f"\nDownloading video for {feed_id}...")
            media_path, error = download_video_from_tweet(tweet_url)
            if media_path:
                media_type = 'video'
            else:
                print(f"Video download failed: {error}")
        
        # Determine scheduling
        if i == 0:
            scheduled_time = None
            action = "Posting immediately"
        else:
            scheduled_dt = base_time + timedelta(minutes=schedule_gap_minutes * i)
            scheduled_time = int(scheduled_dt.timestamp())
            action = f"Scheduling for {scheduled_dt.strftime('%H:%M:%S')}"
        
        print(f"\n{action} from {feed_id} (type: {media_type})...")
        result = post_to_facebook(config, message, media_path, scheduled_time, media_type)
        
        # Cleanup
        if media_path and os.path.exists(media_path):
            os.remove(media_path)
        
        if 'id' in result or 'post_id' in result:
            post_id = result.get('id') or result.get('post_id')
            status = 'SCHEDULED' if i > 0 else 'POSTED'
            print(f"SUCCESS! {status}: {post_id}")
            
            # Share to groups ONLY for immediate posts (not scheduled)
            if i == 0:
                print(f"\nSharing to groups...")
                group_results = share_post_to_groups(config, post_id, message)
                shared_count = sum(1 for r in group_results if r.get('success'))
                print(f"Shared to {shared_count}/{len(group_results)} groups")
        else:
            print(f"ERROR: {result}")


if __name__ == '__main__':
    main()
