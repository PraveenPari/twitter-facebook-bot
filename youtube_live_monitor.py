"""
YouTube Live Stream Monitor & Re-streamer
checks for live streams and re-streams to Facebook using FFmpeg
"""
import os
import subprocess
import time
import requests
import json
import yt_dlp

def get_live_stream_url(channel_url):
    """Get m3u8 stream URL from YouTube channel"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Check the channel live tab
            if '/live' not in channel_url:
                channel_url = f"{channel_url.rstrip('/')}/live"
                
            info = ydl.extract_info(channel_url, download=False)
            
            if not info:
                return None, None
                
            # Check if actually live - look for entries with 'is_live'
            if 'entries' in info:
                for entry in info['entries']:
                    if entry.get('is_live') or entry.get('live_status') == 'is_live':
                        video_id = entry['id']
                        title = entry.get('title', 'Live Stream')
                        
                        # Get the actual stream URL for this video
                        stream_url = get_video_stream_url(video_id)
                        return stream_url, title
    except Exception as e:
        print(f"Error checking channel {channel_url}: {e}")
        
    return None, None

def get_video_stream_url(video_id):
    """Get direct stream URL for a video"""
    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = {
        'format': 'best',
        'quiet': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('url')
    except:
        return None

def start_restream(stream_url, fb_stream_key):
    """Start re-streaming using FFmpeg"""
    if not stream_url or not fb_stream_key:
        return False
        
    # FFmpeg command to copy stream (pass-through) to Facebook
    # This is lightweight as it doesn't re-encode
    cmd = [
        'ffmpeg',
        '-i', stream_url,
        '-c', 'copy',           # Copy without re-encoding
        '-f', 'flv',            # Facebook Live format
        f'rtmps://live-api-s.facebook.com:443/rtmp/{fb_stream_key}'
    ]
    
    print("Starting re-stream...")
    try:
        # Run ffmpeg
        process = subprocess.Popen(cmd)
        
        # Determine how long to run (or until process dies)
        # For a bot run, checking for 5 minutes might be enough, 
        # but re-streaming usually needs a dedicated long-running process.
        # Since this is a cron job bot, re-streaming is tricky.
        # We'll run for 25 minutes (to fit in 30 min cron) or until live ends.
        
        end_time = time.time() + (25 * 60)
        while time.time() < end_time:
            if process.poll() is not None:
                print("FFmpeg process ended unexpectedly")
                return False
            time.sleep(30)
            
        process.terminate()
        return True
        
    except Exception as e:
        print(f"FFmpeg error: {e}")
        return False

def check_and_restream(config):
    """Main function to check channels and restream"""
    # This feature requires a persistent process or long-running job
    # For GitHub Actions cron, it will run for the duration of the job
    
    restream_config = config.get('youtube_restream', {})
    if not restream_config.get('enabled'):
        return
        
    channels = restream_config.get('channels', [])
    fb_key = os.environ.get('FB_STREAM_KEY') # Needs to be added to secrets if used
    
    if not fb_key:
        print("No FB_STREAM_KEY found")
        return

    for channel in channels:
        print(f"Checking YouTube channel: {channel}")
        stream_url, title = get_live_stream_url(channel)
        
        if stream_url:
            print(f"LIVE FOUND: {title}")
            print(f"Re-streaming to Facebook...")
            start_restream(stream_url, fb_key)
            return True # Streaming started (and finished after timeout), stop other checks
            
    return False
