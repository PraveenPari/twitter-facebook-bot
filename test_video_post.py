"""
Test Video Download and Facebook Posting
This script tests the complete video workflow:
1. Download video from a specific tweet
2. Enhance caption with Gemini AI
3. Post video to Facebook
"""
import json
import os
import sys
import tempfile
from datetime import datetime

# Fix encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    HAS_YTDLP = False
    print("ERROR: yt-dlp not installed!")
    sys.exit(1)

try:
    from google import genai
    from google.genai import types
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

import requests


def load_config():
    """Load config from file"""
    with open('config.json', 'r', encoding='utf-8') as f:
        return json.load(f)


def download_video(tweet_url):
    """Download video from tweet using yt-dlp"""
    print(f"\n{'='*60}")
    print(f"DOWNLOADING VIDEO FROM TWEET")
    print(f"{'='*60}")
    print(f"URL: {tweet_url}\n")
    
    if not HAS_YTDLP:
        print("ERROR: yt-dlp not installed!")
        return None
    
    try:
        temp_dir = tempfile.gettempdir()
        output_template = os.path.join(temp_dir, '%(id)s.%(ext)s')
        
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': output_template,
            'quiet': False,  # Show output for testing
            'no_warnings': False,
            'extract_flat': False,
        }
        
        print("Starting download...")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(tweet_url, download=True)
            if info:
                video_id = info.get('id', 'video')
                print(f"\nVideo ID: {video_id}")
                
                # Try to find the downloaded file
                for ext in ['mp4', 'webm', 'mkv']:
                    video_path = os.path.join(temp_dir, f"{video_id}.{ext}")
                    if os.path.exists(video_path):
                        file_size = os.path.getsize(video_path) / (1024 * 1024)  # MB
                        print(f"✅ Video downloaded: {video_path}")
                        print(f"   Size: {file_size:.2f} MB")
                        return video_path
        
        print("❌ Video file not found after download")
        return None
    except Exception as e:
        print(f"❌ Video Download Error: {e}")
        import traceback
        traceback.print_exc()
        return None


def enhance_caption_with_gemini(original_caption, api_key):
    """Use Gemini AI to enhance caption"""
    print(f"\n{'='*60}")
    print(f"ENHANCING CAPTION WITH GEMINI AI")
    print(f"{'='*60}")
    print(f"Original: {original_caption[:100]}...\n")
    
    if not HAS_GEMINI or not api_key:
        print("⚠️  Gemini not available, using original caption")
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
                print(f"✅ Caption enhanced!")
                print(f"   Original length: {len(original_caption)} chars")
                print(f"   Enhanced length: {len(enhanced)} chars")
                return enhanced
        
        return original_caption
            
    except Exception as e:
        print(f"⚠️  Gemini error: {e}")
        return original_caption


def post_video_to_facebook(page_id, token, message, video_path):
    """Post video to Facebook page"""
    print(f"\n{'='*60}")
    print(f"POSTING VIDEO TO FACEBOOK")
    print(f"{'='*60}")
    print(f"Page ID: {page_id}")
    print(f"Video: {video_path}")
    print(f"Caption length: {len(message)} chars\n")
    
    try:
        url = f"https://graph.facebook.com/v22.0/{page_id}/videos"
        
        data = {
            'description': message,
            'access_token': token
        }
        
        print("Uploading video to Facebook...")
        with open(video_path, 'rb') as f:
            response = requests.post(url, data=data, files={'source': f}, timeout=300)
        
        result = response.json()
        
        if 'id' in result or 'post_id' in result:
            post_id = result.get('id') or result.get('post_id')
            print(f"✅ SUCCESS! Video posted")
            print(f"   Post ID: {post_id}")
            print(f"   View at: https://facebook.com/{post_id}")
            return True, post_id
        else:
            error_msg = result.get('error', {}).get('message', str(result))
            print(f"❌ FAILED: {error_msg}")
            return False, error_msg
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False, str(e)


def main():
    print("="*60)
    print("VIDEO POSTING TEST")
    print(f"Time: {datetime.now().isoformat()}")
    print("="*60)
    
    # Load config
    config = load_config()
    
    # Get credentials
    page_id = os.environ.get('FB_PAGE_ID') or config['facebook']['page_id']
    token = os.environ.get('FB_ACCESS_TOKEN') or config['facebook']['access_token']
    gemini_key = os.environ.get('GEMINI_API_KEY') or config.get('gemini', {}).get('api_key', '')
    
    # Test tweet URL - You can change this to any tweet with video
    # Example: A popular tweet with video
    test_tweet_url = input("\nEnter tweet URL with video (or press Enter for default): ").strip()
    
    if not test_tweet_url:
        # Default test - use a recent TVK tweet with video if you have one
        print("\n⚠️  No URL provided. Please provide a tweet URL with video.")
        print("Example: https://twitter.com/TVKVijayHQ/status/1234567890")
        return
    
    test_caption = "Test video post from TVK - Testing automated video posting system"
    
    # STEP 1: Download video
    video_path = download_video(test_tweet_url)
    
    if not video_path:
        print("\n❌ Video download failed. Cannot continue.")
        return
    
    # STEP 2: Enhance caption
    enhanced_caption = enhance_caption_with_gemini(test_caption, gemini_key)
    
    # Add hashtags
    hashtags = [
        "#TVK", "#ThamizhagaVetriKazhagam", "#ThalapathyVijay",
        "#TVKForTamilNadu", "#TVKVision", "#TamilNadu",
        "#TNPolitics", "#Trending", "#LatestNews", "#TVKMovement"
    ]
    
    final_message = f"{enhanced_caption}\n\n{'─' * 30}\n{' '.join(hashtags)}"
    
    # STEP 3: Post to Facebook
    success, result = post_video_to_facebook(page_id, token, final_message, video_path)
    
    # Cleanup
    if os.path.exists(video_path):
        os.remove(video_path)
        print(f"\n🗑️  Cleaned up: {video_path}")
    
    # Final summary
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}")
    print(f"Video Download: {'✅ Success' if video_path else '❌ Failed'}")
    print(f"Caption Enhancement: {'✅ Success' if len(enhanced_caption) > len(test_caption) else '⚠️  Skipped'}")
    print(f"Facebook Posting: {'✅ Success' if success else '❌ Failed'}")
    
    if success:
        print(f"\n🎉 VIDEO POSTED SUCCESSFULLY!")
        print(f"Post ID: {result}")
    else:
        print(f"\n❌ TEST FAILED: {result}")


if __name__ == '__main__':
    main()
