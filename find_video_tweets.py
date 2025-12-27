"""
Find tweets with videos from configured accounts
"""
import asyncio
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from twitter_browser_scraper import TwitterBrowserScraper
import json


async def find_video_tweets():
    """Find tweets with videos from TVK accounts"""
    
    # Load config to get accounts
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    accounts = config.get('twitter_accounts', [])[:5]  # Check first 5 accounts
    
    print("="*60)
    print("SEARCHING FOR VIDEO TWEETS")
    print("="*60)
    
    scraper = TwitterBrowserScraper(headless=True)
    await scraper.start()
    
    # Try to login
    session_loaded = await scraper.load_session()
    if session_loaded:
        print("[OK] Session loaded\n")
    
    video_tweets = []
    
    for account in accounts:
        username = account.get('username', '').replace('@', '')
        if not username:
            continue
        
        print(f"\nChecking @{username}...")
        
        try:
            tweets = await scraper.get_latest_tweets(username, count=10)
            
            for tweet in tweets:
                if tweet.get('has_video'):
                    print(f"  ✅ FOUND VIDEO!")
                    print(f"     URL: {tweet['url']}")
                    print(f"     Text: {tweet['text'][:80]}...")
                    print(f"     Age: {tweet['created_at']}")
                    
                    video_tweets.append({
                        'username': username,
                        'url': tweet['url'],
                        'text': tweet['text'][:100],
                        'created_at': str(tweet['created_at'])
                    })
                    
                    if len(video_tweets) >= 3:  # Find 3 video tweets
                        break
            
            if len(video_tweets) >= 3:
                break
                
        except Exception as e:
            print(f"  Error: {e}")
    
    await scraper.close()
    
    print(f"\n{'='*60}")
    print(f"FOUND {len(video_tweets)} VIDEO TWEETS")
    print(f"{'='*60}")
    
    if video_tweets:
        print("\nVideo tweets found:")
        for i, vt in enumerate(video_tweets, 1):
            print(f"\n{i}. @{vt['username']}")
            print(f"   URL: {vt['url']}")
            print(f"   Text: {vt['text']}...")
        
        # Save to file for reference
        with open('found_video_tweets.json', 'w', encoding='utf-8') as f:
            json.dump(video_tweets, f, indent=2, ensure_ascii=False)
        print("\n💾 Saved to: found_video_tweets.json")
        
        return video_tweets[0]['url']  # Return first video tweet URL
    else:
        print("\n⚠️  No video tweets found in recent posts")
        return None


if __name__ == '__main__':
    result = asyncio.run(find_video_tweets())
    if result:
        print(f"\n🎯 Use this URL for testing:")
        print(f"   {result}")
