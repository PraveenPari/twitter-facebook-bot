# GitHub Secrets Quick Reference

## Required Secrets (6 total)

Copy these values to GitHub → Settings → Secrets and variables → Actions → New repository secret

---

### 1. GIST_TOKEN
**Purpose:** Access GitHub Gist for state persistence  
**Value:** Personal Access Token with `gist` scope  
**Get from:** https://github.com/settings/tokens

```
ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

### 2. GIST_ID  
**Purpose:** ID of the Gist storing bot state  
**Value:** Gist ID from the URL  
**Get from:** https://gist.github.com/ (create new gist with `state.json`)

```
abc123def456
```

---

### 3. FB_PAGE_ID
**Purpose:** Facebook Page ID to post to  
**Current Value:**

```
946593568529880
```

---

### 4. FB_ACCESS_TOKEN
**Purpose:** Facebook access token for posting  
**Expires:** February 22, 2026 (59 days)  
**Current Value:**

```
EAAT9tZCqOCP0BQTR8iw1MEjuZAf9hHc6Ui6hRtRiYZAtTQ0ZCCOTaWnNQEeZCe0Rmo66R4yngVpvVLHfY57nfZAgQlKK3zCCr5CNv2BiNvcnl9VVoZCktxvVyOBDMSXg7DgkBB94srFtYSHfpQPlvIojVaDMe6A7qXfNONVAat44v2Li27eSr0EqPbTG5Fj673OaR4ewTAU
```

**⚠️ Important:** Update this secret before Feb 22, 2026!

---

### 5. GEMINI_API_KEY
**Purpose:** Google Gemini AI for caption enhancement  
**Current Value:**

```
AIzaSyB0R8ffJux2P6YhWDc8a_UugRrXGjsub8s
```

---

### 6. CONFIG_JSON
**Purpose:** Complete bot configuration  
**Value:** Copy entire config.json content, but replace sensitive values with placeholders

```json
{
    "feeds": [
        {
            "id": "tvk_vijay_main",
            "url": "https://rss.app/feeds/6Vpit9O1ZlzMzKqX.xml",
            "priority": 1,
            "name": "TVK Vijay Official",
            "enabled": true
        },
        {
            "id": "feed_2",
            "url": "https://rss.app/feeds/JRzDV3yzKfSUj01s.xml",
            "priority": 2,
            "name": "Feed 2",
            "enabled": true
        },
        {
            "id": "feed_3",
            "url": "https://rss.app/feeds/mhXvYBo3pbDAI8VN.xml",
            "priority": 3,
            "name": "Feed 3",
            "enabled": true
        },
        {
            "id": "feed_4",
            "url": "https://rss.app/feeds/rk1HyvzYX7LCyePL.xml",
            "priority": 4,
            "name": "Feed 4",
            "enabled": true
        },
        {
            "id": "feed_5",
            "url": "https://rss.app/feeds/dKx755ccU5FJFo1O.xml",
            "priority": 5,
            "name": "Feed 5",
            "enabled": true
        }
    ],
    "facebook": {
        "page_id": "PLACEHOLDER",
        "access_token": "PLACEHOLDER"
    },
    "settings": {
        "post_window_minutes": 90,
        "schedule_gap_minutes": 10,
        "min_content_length": 50,
        "skip_retweets": true,
        "skip_replies": true,
        "hashtags_enabled": true,
        "max_hashtags": 10,
        "enable_ai_enhancement": true
    },
    "gemini": {
        "api_key": "PLACEHOLDER",
        "model": "gemini-2.0-flash-exp"
    }
}
```

---

## Token Expiration Tracker

| Secret | Expires | Action Required |
|--------|---------|-----------------|
| GIST_TOKEN | Check your settings | Renew as needed |
| FB_ACCESS_TOKEN | **Feb 22, 2026** | ⚠️ Set reminder! |
| GEMINI_API_KEY | Never | - |
| CONFIG_JSON | Never | - |

---

## Quick Setup Checklist

- [ ] Create GitHub repository
- [ ] Create GitHub Gist for state.json
- [ ] Generate Personal Access Token (gist scope)
- [ ] Add all 6 secrets to GitHub
- [ ] Push code to GitHub
- [ ] Enable GitHub Actions
- [ ] Test with manual workflow run
- [ ] Set calendar reminder for Feb 15, 2026 (token renewal)

---

## Support

If you need to update any secret:
1. Go to GitHub repository → Settings
2. Secrets and variables → Actions
3. Click on the secret name
4. Click "Update secret"
5. Paste new value → "Update secret"

✅ **The bot will automatically use the new value on the next run!**
