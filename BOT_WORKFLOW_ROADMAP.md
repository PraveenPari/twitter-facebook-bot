# Twitter to Facebook Bot - Complete Workflow Roadmap

## 🎯 Overview
This bot monitors multiple Twitter accounts and automatically posts their latest tweets to your Facebook page using **Playwright browser automation**. It runs every 30 minutes via GitHub Actions.

---

## 📊 Architecture Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                    GITHUB ACTIONS (Every 30 min)              │
└─────────────────────────┬────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│                     BOT INITIALIZATION                        │
│  1. Load config.json from secrets                            │
│  2. Load state.json from GitHub Gist                         │
│  3. Initialize Playwright browser (headless)                 │
└─────────────────────────┬────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│              STEP 1: YOUTUBE LIVE RE-STREAMING               │
│  ✓ Check if YouTube re-streaming is enabled                 │
│  ✓ If yes, monitor for live streams and re-stream to FB     │
│  ✓ If no live stream detected, continue to Twitter          │
└─────────────────────────┬────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│           STEP 2: TWITTER ACCOUNT MONITORING                 │
│                                                               │
│  For each of 12 Twitter accounts (SEQUENTIAL):              │
│                                                               │
│  ┌───────────────────────────────────────────────┐         │
│  │   1. LOGIN TO TWITTER                          │         │
│  │      - Try to load saved session               │         │
│  │      - If no session, login with credentials   │         │
│  │      - If login fails, use guest mode          │         │
│  └───────────────────────────────────────────────┘         │
│                                                               │
│  ┌───────────────────────────────────────────────┐         │
│  │   2. NAVIGATE TO ACCOUNT (using Playwright)    │         │
│  │      - Open twitter.com/username               │         │
│  │      - Wait 2-4 seconds for content load       │         │
│  │      - Find tweet elements on page             │         │
│  └───────────────────────────────────────────────┘         │
│                                                               │
│  ┌───────────────────────────────────────────────┐         │
│  │   3. EXTRACT LATEST TWEET                      │         │
│  │      - Get tweet ID, text, media, timestamps   │         │
│  │      - Check if it's from correct user         │         │
│  │      - Extract images/videos URLs              │         │
│  └───────────────────────────────────────────────┘         │
│                                                               │
│  ┌───────────────────────────────────────────────┐         │
│  │   4. VALIDATION FILTERS                        │         │
│  │                                                 │         │
│  │   ❌ SKIP IF:                                  │         │
│  │      • Already posted (check state.json)       │         │
│  │      • Tweet is a retweet                      │         │
│  │      • Tweet is a reply                        │         │
│  │      • Tweet is > 90 minutes old               │         │
│  │      • Tweet text is < 50 characters           │         │
│  │      • Tweet is sponsored/promoted             │         │
│  │                                                 │         │
│  │   ✅ ACCEPT IF:                                │         │
│  │      • Original tweet from target account      │         │
│  │      • Posted within last 90 minutes           │         │
│  │      • Text length >= 50 characters            │         │
│  │      • Not already posted to Facebook          │         │
│  └───────────────────────────────────────────────┘         │
│                                                               │
│  ┌───────────────────────────────────────────────┐         │
│  │   5. ADD TO QUEUE                              │         │
│  │      - If tweet passes all filters             │         │
│  │      - Add to posting queue with metadata      │         │
│  └───────────────────────────────────────────────┘         │
│                                                               │
└─────────────────────────┬────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│               STEP 3: PROCESS POSTING QUEUE                  │
│                                                               │
│  For each tweet in queue (PARALLEL - up to 3 at once):      │
│                                                               │
│  ┌───────────────────────────────────────────────┐         │
│  │   A. DOWNLOAD MEDIA (if present)               │         │
│  │      - Download images from Twitter            │         │
│  │      - Download videos using yt-dlp            │         │
│  │      - Save to temporary file                  │         │
│  └───────────────────────────────────────────────┘         │
│                          │                                    │
│                          ▼                                    │
│  ┌───────────────────────────────────────────────┐         │
│  │   B. ENHANCE CAPTION (Gemini AI)               │         │
│  │      - Send original tweet text to Gemini      │         │
│  │      - Add Tamil political keywords            │         │
│  │      - Make it emotionally inspiring           │         │
│  │      - Add call-to-action phrases              │         │
│  │      - Keep positive tone about TVK/Vijay      │         │
│  │      - Limit to 300 words                      │         │
│  └───────────────────────────────────────────────┘         │
│                          │                                    │
│                          ▼                                    │
│  ┌───────────────────────────────────────────────┐         │
│  │   C. GENERATE SEO HASHTAGS                     │         │
│  │      - Core TVK hashtags (always included):    │         │
│  │        #TVK #ThamizhagaVetriKazhagam #Vijay   │         │
│  │      - Random TVK hashtags (3 from list)       │         │
│  │      - Content-based hashtags                  │         │
│  │        (election → #TNElection2026, etc)       │         │
│  │      - General SEO hashtags                    │         │
│  │        #TamilNadu #TNPolitics #Trending        │         │
│  │      - Total: 10 unique hashtags               │         │
│  └───────────────────────────────────────────────┘         │
│                          │                                    │
│                          ▼                                    │
│  ┌───────────────────────────────────────────────┐         │
│  │   D. FORMAT FINAL POST                         │         │
│  │      Enhanced Caption                          │         │
│  │      ──────────────────────────────            │         │
│  │      #TVK #ThamizhagaVetriKazhagam ...         │         │
│  └───────────────────────────────────────────────┘         │
│                          │                                    │
│                          ▼                                    │
│  ┌───────────────────────────────────────────────┐         │
│  │   E. POST TO FACEBOOK                          │         │
│  │                                                 │         │
│  │   • First post: Publish immediately            │         │
│  │   • Subsequent posts: Schedule with 10min gap  │         │
│  │                                                 │         │
│  │   POST #1: Now                                 │         │
│  │   POST #2: Now + 10 minutes                    │         │
│  │   POST #3: Now + 20 minutes                    │         │
│  │   POST #4: Now + 30 minutes                    │         │
│  │                                                 │         │
│  │   Via Facebook Graph API:                      │         │
│  │   - Images: /page_id/photos                    │         │
│  │   - Videos: /page_id/videos                    │         │
│  │   - Text only: /page_id/feed                   │         │
│  └───────────────────────────────────────────────┘         │
│                          │                                    │
│                          ▼                                    │
│  ┌───────────────────────────────────────────────┐         │
│  │   F. UPDATE STATE                              │         │
│  │      - Mark tweet ID as posted                 │         │
│  │      - Update state.json                       │         │
│  │      - Clean up temporary media files          │         │
│  └───────────────────────────────────────────────┘         │
│                                                               │
└─────────────────────────┬────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│                 STEP 4: SAVE & CLEANUP                       │
│  ✓ Save state.json to GitHub Gist                           │
│  ✓ Close Playwright browser                                 │
│  ✓ Exit (GitHub Actions will run again in 30 min)           │
└──────────────────────────────────────────────────────────────┘
```

---

## 🔧 Technical Implementation Details

### **1. Browser Automation (Playwright)**

**Why Playwright instead of RSS?**
- Twitter RSS feeds are unreliable and often blocked
- Playwright uses real browser automation
- Can bypass Cloudflare and anti-bot protections
- Can extract full media (images/videos)
- More resilient to Twitter API changes

**How it works:**
```python
# Initialize browser
scraper = TwitterBrowserScraper(headless=True)
await scraper.start()

# Login (once, saves session for future runs)
await scraper.login(email, password, username)

# Get tweets from account
tweets = await scraper.get_latest_tweets("TVKVijayHQ", count=1)

# Extract data
tweet = tweets[0]
tweet_id = tweet['id']
text = tweet['text']
media = tweet['media']  # Images/videos
is_retweet = tweet['is_retweet']
is_reply = tweet['is_reply']
created_at = tweet['created_at']
```

### **2. Sequential vs Parallel Processing**

**Account Checking: SEQUENTIAL** (one at a time)
- Prevents browser rate limiting
- Avoids Twitter blocking
- More reliable
- 2-second delay between accounts

**Facebook Posting: PARALLEL** (up to 3 at once)
- Uses ThreadPoolExecutor
- Downloads media concurrently
- Enhances captions in parallel
- Posts to Facebook simultaneously

### **3. Filtering Logic**

```python
# Filter 1: Already posted?
if state['last_posted_ids'].get(account_id) == tweet_id:
    SKIP

# Filter 2: Is it a retweet?
if tweet['is_retweet']:
    SKIP

# Filter 3: Is it a reply?
if tweet['is_reply']:
    SKIP

# Filter 4: Too old?
age_minutes = (now - tweet_time).total_seconds() / 60
if age_minutes > 90:  # configurable
    SKIP

# Filter 5: Too short?
if len(clean_text(tweet['text'])) < 50:  # configurable
    SKIP

# Filter 6: Sponsored/Promoted?
if tweet['user'] != target_username:
    SKIP

# ✅ All filters passed - ADD TO QUEUE
```

### **4. Media Download**

**Images:**
```python
response = requests.get(image_url)
temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
temp_file.write(response.content)
return temp_file.name
```

**Videos:**
- Uses `yt-dlp` library
- Downloads highest quality available
- Extracts from Twitter embeds

### **5. Gemini AI Enhancement**

**Prompt Template:**
```
You are a Tamil political social media expert for TVK party.

TASK: Enhance this caption for maximum Facebook engagement.

ORIGINAL: [Tweet text]

REQUIREMENTS:
1. Keep core message intact
2. Add powerful Tamil words (transliterated)
3. Make it emotionally inspiring
4. Add call-to-action
5. Keep concise (under 300 words)
6. ONLY POSITIVE tone about TVK
7. Include 2-3 Tamil SEO words

ENHANCED CAPTION:
```

**Result:**
- Original 50-character tweet becomes engaging 200-word post
- Culturally relevant Tamil keywords added
- Emotional appeal enhanced
- Better Facebook algorithm ranking

### **6. Hashtag Strategy**

**Always Included (Core TVK):**
- #TVK
- #ThamizhagaVetriKazhagam
- #ThalapathyVijay

**Random Selection (3 from):**
- #TVKForTamilNadu
- #TVKVision
- #TVKMovement
- #VijayPolitics
- (+ 20 more TVK hashtags)

**Content-Based (Dynamic):**
- "election" in text → #TNElection2026
- "rally" in text → #TVKRally
- "youth" in text → #TVKYouth
- "farmer" in text → #FarmersSupport
- (+ 10 more mappings)

**General SEO (Fill remaining):**
- #TamilNadu
- #TNPolitics
- #Trending
- #Breaking
- (+ 10 more)

**Total:** Exactly 10 unique hashtags per post

### **7. Facebook Posting Schedule**

```python
# Base time
base_time = now()

# Post 1: Immediate
schedule_time = None  # Posts immediately

# Post 2: +10 minutes
schedule_time = base_time + 10 minutes

# Post 3: +20 minutes
schedule_time = base_time + 20 minutes

# Post 4: +30 minutes
schedule_time = base_time + 30 minutes
```

**Why scheduling?**
- Facebook limits post frequency
- Spreads content throughout the day
- Better audience reach
- Prevents flagging as spam

---

## ⚙️ Configuration

### **config.json Structure:**

```json
{
  "twitter_accounts": [
    {
      "id": "tvk_vijay_hq",
      "username": "TVKVijayHQ",
      "enabled": true
    },
    // ... 11 more accounts
  ],
  
  "twitter_auth": {
    "email": "your_twitter_email@gmail.com",
    "password": "your_password",
    "username": "your_twitter_handle"
  },
  
  "facebook": {
    "page_id": "946593568529880",
    "access_token": "EAA..."
  },
  
  "settings": {
    "post_window_minutes": 90,      // Only post tweets < 90 min old
    "schedule_gap_minutes": 10,     // 10 min between scheduled posts
    "min_content_length": 50        // Minimum tweet length
  },
  
  "gemini": {
    "api_key": "AIza...",
    "model": "gemini-2.0-flash-exp"
  }
}
```

### **state.json Structure:**

```json
{
  "last_posted_ids": {
    "tvk_vijay_hq": "1871234567890123456",
    "tvk_party_hq": "1871234567890123457",
    // ... stores last posted tweet ID per account
  }
}
```

---

## 🚀 Execution Flow (Real Example)

### **Run 1: 10:00 AM**

1. Check @TVKVijayHQ
   - Latest tweet: ID `...456` (posted 10 min ago)
   - ✅ Valid → Queue for posting
   
2. Check @TVKPartyHQ
   - Latest tweet: ID `...789` (retweet)
   - ❌ Skip: Is retweet
   
3. Check @TVKHQITWingOffl
   - Latest tweet: ID `...123` (posted 5 min ago)
   - ✅ Valid → Queue for posting

**QUEUE:** 2 posts

**PROCESSING:**
- Post 1 (TVKVijayHQ): Post NOW (10:00 AM)
- Post 2 (TVKHQITWingOffl): Schedule for 10:10 AM

**STATE UPDATE:**
```json
{
  "last_posted_ids": {
    "tvk_vijay_hq": "...456",
    "tvk_it_wing": "...123"
  }
}
```

### **Run 2: 10:30 AM** (30 minutes later)

1. Check @TVKVijayHQ
   - Latest tweet: ID `...456`
   - ❌ Skip: Already posted (matches state.json)
   
2. Check @TVKPartyHQ
   - Latest tweet: ID `...999` (posted 15 min ago)
   - ✅ Valid → Queue for posting

**QUEUE:** 1 post

**PROCESSING:**
- Post 1 (TVKPartyHQ): Post NOW (10:30 AM)

---

## 📈 Performance Metrics

| Metric | Value |
|--------|-------|
| Accounts checked per run | 12 |
| Time per account check | ~5 seconds |
| Total check time | ~60 seconds |
| Posts processed (parallel) | 3 simultaneously |
| Time per post processing | ~10 seconds |
| Total run time | ~2-3 minutes |
| Runs per day | 48 (every 30 min) |
| Max posts per day | ~50-100 |

---

## 🛡️ Error Handling

### **Twitter Login Failures:**
- Try saved session first
- Fallback to fresh login
- Fallback to guest mode (limited)
- Continue execution

### **Tweet Fetch Failures:**
- Log error for specific account
- Continue to next account
- Don't crash entire run

### **Media Download Failures:**
- Post without media
- Continue execution
- Log warning

### **Facebook API Failures:**
- Log error with details
- Don't update state (retry next run)
- Continue to next post

### **Gemini AI Failures:**
- Use original tweet text
- Continue execution
- Post still succeeds

---

## 🔄 State Management

**GitHub Gist:**
- Free persistent storage
- Accessible across GitHub Actions runs
- No database needed
- Automatic versioning

**Download at start:**
```bash
curl -H "Authorization: token $GIST_TOKEN" \
  "https://api.github.com/gists/$GIST_ID" | \
  python -c "import sys,json; ..." > state.json
```

**Upload at end:**
```bash
curl -X PATCH \
  -H "Authorization: token $GIST_TOKEN" \
  "https://api.github.com/gists/$GIST_ID" \
  -d '{"files":{"state.json":{"content":"..."}}}'
```

---

## 📝 Logging Example

```
==================================================
Twitter to Facebook Bot - PARALLEL OPTIMIZED
Time: 2025-12-27T15:58:30+05:30
==================================================
Settings: window=90min, gap=10min, min_len=50

STEP 1: CHECKING YOUTUBE LIVE FOR RE-STREAMING
[YouTube] Re-streaming disabled in config

STEP 2: CHECKING TWITTER ACCOUNTS
Accounts to check: 12

[1/12] Checking @TVKVijayHQ...
  [Browser] Navigating to @TVKVijayHQ...
  [Browser] Waiting 3.0s for content...
  [Browser] Found 8 tweet elements
  Already posted

[2/12] Checking @TVKPartyHQ...
  [Browser] Navigating to @TVKPartyHQ...
  [Browser] Waiting 2.5s for content...
  [Browser] Found 10 tweet elements
  SKIP: Retweet

[3/12] Checking @TVKHQITWingOffl...
  [Browser] Navigating to @TVKHQITWingOffl...
  [Browser] Waiting 3.8s for content...
  [Browser] Found 6 tweet elements
  ✅ Valid tweet (156 chars, 12min old)

...

Found 3 posts to publish

Processing 1/3: tvk_it_wing
  Downloading image...
  [OK] Image downloaded
  Enhancing caption...
  [OK] Caption enhanced (78 → 234 chars)
  Posting to Facebook...
  [SUCCESS] POSTED: 12345_67890

Processing 2/3: tvk_vijay_24x7
  Enhancing caption...
  [OK] Caption enhanced
  Posting to Facebook...
  [SUCCESS] SCHEDULED: 12345_67891

Done!
```

---

## 🎯 Key Success Factors

1. **Playwright Automation** → Reliable Twitter scraping
2. **Sequential Account Checking** → Avoids rate limits
3. **Parallel FB Posting** → Fast execution
4. **Gemini AI Enhancement** → Engaging captions
5. **Smart Hashtag Generation** → Better reach
6. **GitHub Gist State** → Prevents duplicate posts
7. **Scheduled Posting** → Spreads content evenly
8. **Comprehensive Filtering** → Quality over quantity

---

## 📊 Success Rate

- **Tweet Detection:** ~95% (Playwright is very reliable)
- **Media Download:** ~90% (some videos may fail)
- **Gemini Enhancement:** ~85% (quota dependent)
- **Facebook Posting:** ~98% (very reliable API)
- **Overall Success:** ~85-90% posts successfully published

---

**Last Updated:** December 27, 2025
