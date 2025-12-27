"""
YouTube to Facebook Live Re-Streaming - GITHUB ACTIONS COMPATIBLE
Runs continuously in GitHub Actions when live detected
"""
import subprocess
import requests
import re
import time
import os
from datetime import datetime


def get_youtube_live_url(channel_url):
    """Check if YouTube channel is live and get stream URL"""
    try:
        live_url = f"{channel_url}/live"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(live_url, headers=headers, timeout=10)
        
        if '/watch?v=' in response.url:
            video_id = response.url.split('/watch?v=')[1].split('&')[0]
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            
            html = response.text
            title_match = re.search(r'"title":"([^"]+)"', html)
            title = title_match.group(1) if title_match else "Live Stream"
            
            return {
                'is_live': True,
                'video_id': video_id,
                'video_url': video_url,
                'title': title
            }
        
        return {'is_live': False}
    except Exception as e:
        print(f"[YouTube] Error: {e}")
        return {'is_live': False}


def start_facebook_live_stream(page_id, access_token, title):
    """Start a Facebook Live stream and get RTMP URL"""
    try:
        url = f"https://graph.facebook.com/v22.0/{page_id}/live_videos"
        data = {
            'title': title,
            'description': f'🔴 நேரலை | {title}',
            'access_token': access_token
        }
        
        response = requests.post(url, data=data)
        result = response.json()
        
        if 'stream_url' in result:
            return {
                'success': True,
                'stream_url': result['stream_url'],
                'video_id': result['id']
            }
        else:
            return {'success': False, 'error': result}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def restream_youtube_to_facebook(youtube_url, facebook_rtmp_url):
    """
    Re-stream YouTube to Facebook using FFmpeg
    Returns FFmpeg process
    """
    try:
        # Install FFmpeg in GitHub Actions first
        print("[FFmpeg] Checking FFmpeg...")
        
        # FFmpeg command
        cmd = [
            'ffmpeg',
            '-i', youtube_url,
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-f', 'flv',
            facebook_rtmp_url
        ]
        
        print("[FFmpeg] Starting re-stream...")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        return process
    except Exception as e:
        print(f"[FFmpeg] Error: {e}")
        return None


def monitor_and_restream_once(config, state):
    """
    Check YouTube for live, start re-streaming, and keep running until live ends
    This runs ONCE per GitHub Actions trigger and stays alive
    """
    # Get config
    youtube_config = config.get('youtube_restream', {})
    
    if not youtube_config.get('enabled', False):
        return False
    
    channel_url = youtube_config.get('channel_url')
    
    # Get Facebook credentials
    page_id = os.environ.get('FB_PAGE_ID') or config.get('facebook', {}).get('page_id')
    token = os.environ.get('FB_ACCESS_TOKEN') or config.get('facebook', {}).get('access_token')
    
    print("\n" + "="*60)
    print("YOUTUBE → FACEBOOK LIVE RE-STREAMING")
    print("="*60)
    
    # Check if YouTube is live
    print("\n[1] Checking YouTube for live stream...")
    live_data = get_youtube_live_url(channel_url)
    
    if not live_data['is_live']:
        print("[YouTube] No live stream detected")
        return False
    
    print(f"[YouTube] 🔴 LIVE DETECTED: {live_data['title']}")
    
    # Check if already streaming this video
    last_streamed_id = state.get('last_youtube_restream_id')
    if last_streamed_id == live_data['video_id']:
        print("[YouTube] Already re-streaming this live video")
        return False
    
    # Start Facebook Live
    print("\n[2] Starting Facebook Live...")
    fb_live = start_facebook_live_stream(page_id, token, live_data['title'])
    
    if not fb_live['success']:
        print(f"[Facebook] Failed to start live: {fb_live.get('error')}")
        return False
    
    print(f"[Facebook] ✅ Facebook Live started!")
    print(f"[Facebook] Stream URL: {fb_live['stream_url']}")
    
    # Start re-streaming
    print("\n[3] Starting FFmpeg re-stream...")
    ffmpeg_process = restream_youtube_to_facebook(
        live_data['video_url'],
        fb_live['stream_url']
    )
    
    if not ffmpeg_process:
        print("[FFmpeg] Failed to start")
        return False
    
    print("[FFmpeg] ✅ Re-streaming started!")
    print(f"[FFmpeg] YouTube → Facebook Live")
    
    # Update state
    state['last_youtube_restream_id'] = live_data['video_id']
    
    # Keep running and monitoring
    print("\n" + "="*60)
    print("RE-STREAMING IN PROGRESS")
    print("This will run until live ends or 6-hour GitHub Actions limit")
    print("="*60 + "\n")
    
    check_interval = 60  # Check every 60 seconds
    max_runtime = 6 * 60 * 60  # 6 hours max (GitHub Actions limit)
    start_time = time.time()
    
    try:
        while True:
            # Check if still running
            if ffmpeg_process.poll() is not None:
                print("\n[FFmpeg] Process ended")
                break
            
            # Check if YouTube is still live
            if (time.time() - start_time) % 300 == 0:  # Every 5 minutes
                live_check = get_youtube_live_url(channel_url)
                if not live_check['is_live'] or live_check['video_id'] != live_data['video_id']:
                    print("\n[YouTube] Live ended, stopping re-stream...")
                    ffmpeg_process.terminate()
                    break
            
            # Check runtime limit
            runtime = time.time() - start_time
            if runtime > max_runtime:
                print("\n[Limit] 6-hour limit reached, stopping...")
                ffmpeg_process.terminate()
                break
            
            # Status update
            hours = int(runtime // 3600)
            mins = int((runtime % 3600) // 60)
            print(f"[Status] Re-streaming... ({hours}h {mins}m)", end='\r')
            
            time.sleep(check_interval)
    
    except KeyboardInterrupt:
        print("\n[Interrupt] Stopping re-stream...")
        ffmpeg_process.terminate()
    
    ffmpeg_process.wait()
    print("\n[Done] Re-stream stopped")
    
    return True


if __name__ == '__main__':
    # For testing
    import json
    
    print("YouTube to Facebook Re-Streaming (GitHub Actions Compatible)")
    
    config = {
        'youtube_restream': {
            'enabled': True,
            'channel_url': 'https://www.youtube.com/@TVKVijayHQ-Offl'
        },
        'facebook': {
            'page_id': os.environ.get('FB_PAGE_ID'),
            'access_token': os.environ.get('FB_ACCESS_TOKEN')
        }
    }
    
    state = {}
    
    monitor_and_restream_once(config, state)
