"""
Twitter Browser Scraper using Playwright
Bypasses Cloudflare and gets tweets directly from browser
"""
import asyncio
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
import requests


class TwitterBrowserScraper:
    """Scrapes Twitter using Playwright (real browser)"""
    
    def __init__(self, headless=True):
        """
        Initialize browser scraper
        
        Args:
            headless: Run browser in headless mode (True for production)
        """
        self.headless = headless
        self.browser = None
        self.context = None
        self.page = None
        
    async def start(self):
        """Start the browser"""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=['--disable-blink-features=AutomationControlled']
        )
        self.context = await self.browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        self.page = await self.context.new_page()
        print("  [Browser] Started")
    
    async def close(self):
        """Close the browser"""
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if hasattr(self, 'playwright'):
            await self.playwright.stop()
        print("  [Browser] Closed")
    
    async def login(self, email, password, username=None):
        """
        Login to Twitter for authenticated access
        
        Args:
            email: Twitter email
            password: Twitter password
            username: Twitter username (optional, may be needed for 2FA)
        """
        if not self.page:
            await self.start()
        
        try:
            print("  [Browser] Logging in to Twitter...")
            
            # Go to Twitter login page
            await self.page.goto('https://twitter.com/i/flow/login', timeout=30000)
            await asyncio.sleep(3)
            
            # Enter email/username
            print("  [Browser] Entering email...")
            email_input = await self.page.wait_for_selector('input[autocomplete="username"]', timeout=10000)
            await email_input.fill(email)
            await asyncio.sleep(1)
            
            # Click Next
            await self.page.keyboard.press('Enter')
            await asyncio.sleep(3)
            
            # Check if username verification is needed (sometimes Twitter asks)
            try:
                username_input = await self.page.wait_for_selector('input[data-testid="ocfEnterTextTextInput"]', timeout=5000)
                if username_input and username:
                    print("  [Browser] Username verification required...")
                    await username_input.fill(username)
                    await self.page.keyboard.press('Enter')
                    await asyncio.sleep(3)
            except:
                pass  # Username verification not needed
            
            # Enter password
            print("  [Browser] Entering password...")
            password_input = await self.page.wait_for_selector('input[name="password"]', timeout=10000)
            await password_input.fill(password)
            await asyncio.sleep(1)
            
            # Click Login
            await self.page.keyboard.press('Enter')
            await asyncio.sleep(5)
            
            # Check if login was successful
            try:
                await self.page.wait_for_selector('[data-testid="AppTabBar_Home_Link"]', timeout=10000)
                print("  [Browser] Login successful!")
                
                # Save cookies for future use
                cookies = await self.context.cookies()
                with open('twitter_session.json', 'w') as f:
                    json.dump(cookies, f)
                print("  [Browser] Session saved to twitter_session.json")
                
                return True
            except:
                print("  [Browser] Login failed or took too long")
                return False
                
        except Exception as e:
            print(f"  [Browser] Login error: {e}")
            return False
    
    async def load_session(self):
        """Load saved Twitter session from cookies"""
        try:
            if os.path.exists('twitter_session.json'):
                print("  [Browser] Loading saved session...")
                with open('twitter_session.json', 'r') as f:
                    cookies = json.load(f)
                await self.context.add_cookies(cookies)
                print("  [Browser] Session loaded")
                return True
        except Exception as e:
            print(f"  [Browser] Could not load session: {e}")
        return False
    
    async def get_latest_tweets(self, username, count=5):
        """
        Get latest tweets from a user
        
        Args:
            username: Twitter username (without @)
            count: Number of tweets to fetch
            
        Returns:
            List of tweet dictionaries
        """
        if not self.page:
            await self.start()
        
        try:
            # Navigate to user's profile
            url = f"https://twitter.com/{username}"
            print(f"  [Browser] Navigating to @{username}...")
            
            # Navigate and WAIT for full page load (DOM + network)
            await self.page.goto(url, wait_until='networkidle', timeout=30000)
            
            # Wait for content (increased to ensure full load)
            print(f"  [Browser] Waiting for content...")
            await asyncio.sleep(3)
            
            # Scroll to trigger lazy loading
            for i in range(2):  # Reduced from 5 to 2
                await self.page.evaluate('window.scrollBy(0, 800)')
                await asyncio.sleep(0.5)  # Reduced from 1s to 0.5s
            
            # Try multiple selectors (Twitter changes them frequently)
            tweet_elements = []
            
            # Try primary selector
            tweet_elements = await self.page.query_selector_all('article[data-testid="tweet"]')
            
            # If no tweets found, try alternative selector
            if not tweet_elements:
                print(f"  [Browser] Trying alternative selectors...")
                tweet_elements = await self.page.query_selector_all('article')
            
            print(f"  [Browser] Found {len(tweet_elements)} tweet elements")
            
            if not tweet_elements:
                # Take screenshot for debugging
                try:
                    await self.page.screenshot(path='debug_screenshot.png')
                    print(f"  [Browser] Saved debug screenshot to debug_screenshot.png")
                except:
                    pass
            
            # Parse tweet elements
            tweets = []
            for i, tweet_elem in enumerate(tweet_elements[:count]):
                try:
                    tweet_data = await self._parse_tweet_element(tweet_elem, username)
                    if tweet_data:
                        tweets.append(tweet_data)
                except Exception as e:
                    print(f"  [Browser] Error parsing tweet {i}: {e}")
                    continue
            
            return tweets
            
        except PlaywrightTimeout:
            print(f"  [Browser] Timeout loading @{username}")
            return []
        except Exception as e:
            print(f"  [Browser] Error: {e}")
            return []
    
    async def _parse_tweet_element(self, element, username):
        """Parse a tweet element into structured data"""
        try:
            # Get tweet text
            text_elem = await element.query_selector('[data-testid="tweetText"]')
            text = await text_elem.inner_text() if text_elem else ""
            
            # Get tweet link/ID
            link_elem = await element.query_selector('a[href*="/status/"]')
            tweet_url = ""
            tweet_id = ""
            if link_elem:
                href = await link_elem.get_attribute('href')
                if href:
                    tweet_url = f"https://twitter.com{href}"
                    match = re.search(r'/status/(\d+)', href)
                    if match:
                        tweet_id = match.group(1)
            
            # Get timestamp
            time_elem = await element.query_selector('time')
            created_at = None
            if time_elem:
                datetime_str = await time_elem.get_attribute('datetime')
                if datetime_str:
                    created_at = datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
            
            # Check if it's a retweet
            is_retweet = await element.query_selector('[data-testid="socialContext"]') is not None
            
            # Check if it's a reply (starts with @mentions)
            is_reply = text.strip().startswith('@')
            
            # Get media (images/videos)
            media = []
            
            # Images
            image_elems = await element.query_selector_all('[data-testid="tweetPhoto"] img')
            for img in image_elems:
                src = await img.get_attribute('src')
                if src and 'twimg.com/media' in src:
                    # Get original quality
                    src = re.sub(r'&name=\w+', '&name=large', src)
                    media.append({
                        'type': 'image',
                        'url': src
                    })
            
            # Videos
            video_elem = await element.query_selector('video')
            has_video = video_elem is not None
            
            return {
                'id': tweet_id,
                'text': text,
                'url': tweet_url,
                'created_at': created_at or datetime.now(timezone.utc),
                'user': username,
                'is_retweet': is_retweet,
                'is_reply': is_reply,
                'media': media,
                'has_video': has_video,
                'has_images': len(media) > 0
            }
            
        except Exception as e:
            print(f"  [Browser] Parse error: {e}")
            return None
    
    async def download_media(self, url, media_type='image'):
        """
        Download media from URL
        
        Args:
            url: Media URL
            media_type: 'image' or 'video'
            
        Returns:
            Path to downloaded file
        """
        try:
            response = requests.get(url, timeout=30, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            response.raise_for_status()
            
            # Determine extension
            ext = '.jpg' if media_type == 'image' else '.mp4'
            if media_type == 'image':
                ct = response.headers.get('content-type', '')
                if 'png' in ct:
                    ext = '.png'
                elif 'gif' in ct:
                    ext = '.gif'
                elif 'webp' in ct:
                    ext = '.webp'
            
            # Save to temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
            temp_file.write(response.content)
            temp_file.close()
            
            size_mb = len(response.content) / (1024 * 1024)
            print(f"  [Download] {media_type}: {size_mb:.1f} MB")
            
            return temp_file.name
            
        except Exception as e:
            print(f"  [Download] Error: {e}")
            return None


# Synchronous helper functions
def get_tweets(username, count=5, headless=True):
    """
    Synchronous wrapper to get tweets
    
    Args:
        username: Twitter username (without @)
        count: Number of tweets to fetch
        headless: Run browser in headless mode
        
    Returns:
        List of tweet dictionaries
    """
    async def _async_get():
        scraper = TwitterBrowserScraper(headless=headless)
        try:
            await scraper.start()
            tweets = await scraper.get_latest_tweets(username, count)
            return tweets
        finally:
            await scraper.close()
    
    return asyncio.run(_async_get())


def get_latest_tweet(username, headless=True):
    """Get just the latest tweet from a user"""
    tweets = get_tweets(username, count=1, headless=headless)
    return tweets[0] if tweets else None


if __name__ == '__main__':
    # Test the scraper
    print("="*60)
    print("TESTING PLAYWRIGHT TWITTER SCRAPER")
    print("="*60)
    
    test_user = "elonmusk"  # Change to your target
    
    print(f"\nFetching from @{test_user}...")
    tweets = get_tweets(test_user, count=2, headless=False)  # headless=False to see browser
    
    if tweets:
        print(f"\n[SUCCESS] Fetched {len(tweets)} tweets!\n")
        for i, tweet in enumerate(tweets, 1):
            print(f"Tweet #{i}")
            print(f"  ID: {tweet['id']}")
            print(f"  Text: {tweet['text'][:80]}...")
            print(f"  Media: {len(tweet['media'])} images, Video: {tweet['has_video']}")
            print(f"  Retweet: {tweet['is_retweet']}, Reply: {tweet['is_reply']}")
            print()
    else:
        print("\n[FAILED] No tweets fetched")
