"""
YouTube Live Stream Monitor
Checks if a YouTube channel is live and posts to Facebook
Posts FIRST before checking Twitter
"""
import requests
import json
import os
from datetime import datetime


class YouTubeLiveMonitor:
    """Monitor YouTube channel for live streams"""
    
    def __init__(self, api_key, channel_id):
        """
        Initialize YouTube monitor
        
        Args:
            api_key: YouTube Data API v3 key
            channel_id: YouTube channel ID to monitor
        """
        self.api_key = api_key
        self.channel_id = channel_id
        self.base_url = "https://www.googleapis.com/youtube/v3"
    
    def check_if_live(self):
        """
        Check if the channel is currently live
        
        Returns:
            (is_live, live_data) where live_data contains:
            - title: Stream title
            - description: Stream description
            - thumbnail: Thumbnail URL
            - video_id: Video ID
            - video_url: Full YouTube URL
        """
        try:
            # Search for live broadcasts
            url = f"{self.base_url}/search"
            params = {
                'part': 'snippet',
                'channelId': self.channel_id,
                'eventType': 'live',
                'type': 'video',
                'key': self.api_key,
                'maxResults': 1
            }
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            # Check if there's a live stream
            if 'items' in data and len(data['items']) > 0:
                live_stream = data['items'][0]
                snippet = live_stream['snippet']
                video_id = live_stream['id']['videoId']
                
                return True, {
                    'title': snippet['title'],
                    'description': snippet.get('description', ''),
                    'thumbnail': snippet['thumbnails']['high']['url'],
                    'video_id': video_id,
                    'video_url': f"https://www.youtube.com/watch?v={video_id}",
                    'channel_title': snippet['channelTitle']
                }
            
            return False, None
            
        except Exception as e:
            print(f"[YouTube] Error checking live status: {e}")
            return False, None
    
    def create_facebook_post_message(self, live_data, hide_youtube=True):
        """
        Create Facebook post message from live stream data
        
        Args:
            live_data: Live stream data from check_if_live()
            hide_youtube: If True, don't mention YouTube in the post
        
        Returns:
            (message, video_url) tuple
        """
        title = live_data['title']
        
        if hide_youtube:
            # Create message without mentioning YouTube
            message = f"""🔴 LIVE NOW! 🔴

{title}

Watch now 👇"""
        else:
            # Include YouTube mention
            message = f"""🔴 LIVE NOW on YouTube! 🔴

{title}

Watch live 👇"""
        
        return message, live_data['video_url']


def post_youtube_live_to_facebook(page_id, token, message, video_url):
    """
    Post YouTube live stream to Facebook
    
    Args:
        page_id: Facebook page ID
        token: Facebook page access token
        message: Post message
        video_url: YouTube live stream URL
    
    Returns:
        (success, result)
    """
    try:
        # Post as link (Facebook will create video preview)
        url = f"https://graph.facebook.com/v22.0/{page_id}/feed"
        data = {
            'message': message,
            'link': video_url,
            'access_token': token
        }
        
        response = requests.post(url, data=data)
        result = response.json()
        
        if 'id' in result:
            return True, result['id']
        else:
            return False, result.get('error', {}).get('message', str(result))
            
    except Exception as e:
        return False, str(e)


def check_and_post_youtube_live(config, state):
    """
    Check YouTube for live stream and post to Facebook if live
    
    Args:
        config: Bot configuration
        state: Bot state
    
    Returns:
        True if live stream was posted, False otherwise
    """
    # Get YouTube settings
    youtube_config = config.get('youtube_live', {})
    
    if not youtube_config.get('enabled', False):
        return False
    
    api_key = os.environ.get('YOUTUBE_API_KEY') or youtube_config.get('api_key')
    channel_id = youtube_config.get('channel_id')
    
    if not api_key or not channel_id:
        return False
    
    # Get Facebook credentials
    page_id = os.environ.get('FB_PAGE_ID') or config['facebook']['page_id']
    token = os.environ.get('FB_ACCESS_TOKEN') or config['facebook']['access_token']
    
    # Check if already posted this stream
    last_posted_video_id = state.get('last_youtube_live_id')
    
    # Initialize monitor
    monitor = YouTubeLiveMonitor(api_key, channel_id)
    
    # Check if live
    print("\n[YouTube] Checking for live stream...")
    is_live, live_data = monitor.check_if_live()
    
    if not is_live:
        print("[YouTube] No live stream detected")
        return False
    
    print(f"[YouTube] 🔴 LIVE DETECTED: {live_data['title']}")
    
    # Check if we already posted this stream
    if last_posted_video_id == live_data['video_id']:
        print("[YouTube] Already posted this live stream")
        return False
    
    # Create Facebook post message (hide YouTube mention)
    hide_youtube = youtube_config.get('hide_youtube_source', True)
    message, video_url = monitor.create_facebook_post_message(live_data, hide_youtube)
    
    # Post to Facebook
    print("[YouTube] Posting live stream to Facebook...")
    success, result = post_youtube_live_to_facebook(page_id, token, message, video_url)
    
    if success:
        print(f"[YouTube] ✅ Posted! FB ID: {result}")
        # Update state
        state['last_youtube_live_id'] = live_data['video_id']
        return True
    else:
        print(f"[YouTube] ❌ Failed: {result}")
        return False


# For testing
if __name__ == '__main__':
    # Test YouTube live detection
    print("YouTube Live Monitor - Test")
    
    API_KEY = input("Enter YouTube API key: ")
    CHANNEL_ID = input("Enter YouTube channel ID: ")
    
    monitor = YouTubeLiveMonitor(API_KEY, CHANNEL_ID)
    is_live, live_data = monitor.check_if_live()
    
    if is_live:
        print(f"\n🔴 LIVE NOW!")
        print(f"Title: {live_data['title']}")
        print(f"URL: {live_data['video_url']}")
        
        message, url = monitor.create_facebook_post_message(live_data, hide_youtube=True)
        print(f"\nFacebook Post (YouTube hidden):")
        print(message)
        print(url)
    else:
        print("\nNo live stream detected")
