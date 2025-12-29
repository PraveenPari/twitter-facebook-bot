"""
Test script for instagrapi trending hashtags
Using hashtag_medias_top instead of recent (more stable API)
"""
import json
import os
import re
import time
from collections import Counter

# Check if instagrapi is installed
try:
    from instagrapi import Client
    print("✅ instagrapi is installed")
except ImportError:
    print("❌ instagrapi not installed. Run: pip install instagrapi")
    exit(1)

SESSION_FILE = "ig_session.json"

def load_config():
    if os.path.exists('config.json'):
        with open('config.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    raise Exception("config.json not found!")

def test_trending_hashtags():
    # Load config
    print("\n📁 Loading config.json...")
    config = load_config()
    print("✅ Config loaded")
    
    # Get credentials
    instagrapi_config = config.get('instagrapi', {})
    username = instagrapi_config.get('username')
    password = instagrapi_config.get('password')
    
    if not username or not password:
        print("❌ Instagram credentials not found!")
        return
    
    print(f"\n🔄 Logging into Instagram as: {username}")
    
    cl = Client()
    cl.delay_range = [1, 3]
    
    # Try to reuse session
    if os.path.exists(SESSION_FILE):
        try:
            cl.load_settings(SESSION_FILE)
            cl.login(username, password)
            print("✅ Logged in (session reused)")
        except:
            cl = Client()
            cl.login(username, password)
            cl.dump_settings(SESSION_FILE)
            print("✅ Fresh login")
    else:
        try:
            cl.login(username, password)
            cl.dump_settings(SESSION_FILE)
            print(f"✅ Login successful! User ID: {cl.user_id}")
        except Exception as e:
            print(f"❌ Login failed: {e}")
            return
    
    print("\n" + "="*60)
    print("FETCHING TRENDING HASHTAGS")
    print("="*60)
    
    search_hashtags = ['TVK', 'TVKVijay', 'actorvijay', 'ThalapathyVijay', 'Vijay']
    all_extracted_hashtags = []
    
    for hashtag_name in search_hashtags:
        print(f"\n🔍 Fetching #{hashtag_name}...")
        
        try:
            # Method 1: Try hashtag_medias_top (more stable)
            try:
                medias = cl.hashtag_medias_top(hashtag_name, amount=20)
                print(f"   📸 Got {len(medias)} top posts")
                
                for media in medias:
                    caption = media.caption_text if media.caption_text else ""
                    found_tags = re.findall(r'#(\w+)', caption)
                    all_extracted_hashtags.extend(['#' + tag for tag in found_tags])
                    
            except Exception as e1:
                print(f"   ⚠️  Top medias failed: {e1}")
                
                # Method 2: Try getting hashtag info
                try:
                    hashtag_info = cl.hashtag_info(hashtag_name)
                    print(f"   📊 Hashtag #{hashtag_name} has {hashtag_info.media_count} posts")
                except:
                    pass
                    
                # Method 3: Try searching for posts
                try:
                    search_results = cl.search_hashtags(hashtag_name)
                    print(f"   🔎 Found {len(search_results)} related hashtags")
                    
                    for ht in search_results[:5]:
                        all_extracted_hashtags.append('#' + ht.name)
                except Exception as e2:
                    print(f"   ❌ Search also failed: {e2}")
            
            time.sleep(2)
            
        except Exception as e:
            print(f"   ❌ Error: {e}")
            continue
    
    # Show results
    print("\n" + "="*60)
    print("RESULTS")
    print("="*60)
    
    if all_extracted_hashtags:
        hashtag_counts = Counter(all_extracted_hashtags)
        
        exclude = ['#TVK', '#TVKVijay', '#actorvijay', '#ThalapathyVijay', '#Vijay']
        
        print(f"\n📊 Total hashtags: {len(all_extracted_hashtags)}")
        print(f"📊 Unique: {len(hashtag_counts)}")
        
        print(f"\n🔥 TOP TRENDING HASHTAGS:")
        print("-" * 50)
        
        trending = []
        rank = 1
        for tag, count in hashtag_counts.most_common(50):
            if tag not in exclude and len(tag) > 2:
                print(f"   {rank:2d}. {tag:<35} ({count}x)")
                trending.append(tag)
                rank += 1
                if rank > 25:
                    break
        
        core_tags = ['#TVK', '#ThamizhagaVetriKazhagam', '#ThalapathyVijay', '#TamilNadu']
        final = core_tags + [t for t in trending if t not in core_tags][:16]
        
        print("\n" + "="*60)
        print("📋 FINAL HASHTAGS FOR YOUR POSTS:")
        print("="*60)
        print("\n" + " ".join(final[:20]))
        
        print("\n✅ SUCCESS!")
        return final
    else:
        print("\n⚠️  No hashtags fetched")
        print("   Instagram may be rate limiting or API changed")
        print("   Using static hashtags as fallback")
        
        fallback = ['#TVK', '#ThamizhagaVetriKazhagam', '#ThalapathyVijay', '#TamilNadu',
                   '#Vijay', '#VijayPolitics', '#TNPolitics', '#TamilNadu2026']
        print("\n📋 FALLBACK HASHTAGS:")
        print(" ".join(fallback))

if __name__ == "__main__":
    print("="*60)
    print("  INSTAGRAPI TRENDING HASHTAGS TEST")
    print("="*60)
    
    test_trending_hashtags()
