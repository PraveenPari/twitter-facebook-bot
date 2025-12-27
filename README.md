# Twitter to Facebook Bot

Automated bot that monitors 12 TVK Twitter accounts and posts to Facebook Page.

## Features

- ✅ Monitors 12 Twitter accounts simultaneously
- ✅ Downloads images & videos
- ✅ Filters sponsored tweets, retweets, replies
- ✅ AI caption enhancement (Gemini)
- ✅ SEO hashtag generation
- ✅ Runs every 30 minutes (GitHub Actions)
- ✅ Parallel execution (4x faster)

## Monitored Accounts

1. @TVKVijayHQ
2. @TVKPartyHQ
3. @TVKHQITWingOffl
4. @arunraajkg
5. @ashwin_tvk_
6. @TVKVijay24x7
7. @BossTVK
8. @TVK_WORLD
9. @JegadeshTVK
10. @PriyankaSmile01
11. @VijayFansTrends
12. @sangeet29332013

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Run bot
python main.py
```

## GitHub Actions (Automated)

Runs every 30 minutes automatically.

### Required Secrets

Go to: **Settings → Secrets → Actions**

| Secret | Description |
|--------|-------------|
| `FB_PAGE_ID` | Facebook page ID |
| `FB_ACCESS_TOKEN` | Facebook page access token |
| `GEMINI_API_KEY` | Gemini AI API key |
| `CONFIG_JSON` | Twitter accounts + auth (see below) |
| `GIST_TOKEN` | GitHub token for state storage |
| `GIST_ID` | Gist ID for state storage |

### CONFIG_JSON Format

```json
{
  "twitter_accounts": [
    {"id": "tvk_vijay_hq", "username": "TVKVijayHQ", "enabled": true, "priority": 1},
    {"id": "tvk_party_hq", "username": "TVKPartyHQ", "enabled": true, "priority": 2},
    ...all 12 accounts
  ],
  "twitter_auth": {
    "email": "praveensivapariyt@gmail.com",
    "password": "Praveen@2026",
    "username": "tvkmember22"
  },
  "settings": {
    "post_window_minutes": 60,
    "schedule_gap_minutes": 10,
    "min_content_length": 50
  }
}
```

Use `CONFIG_JSON.template` as reference.

## How It Works

1. Logs into Twitter with credentials
2. Checks all 12 accounts in parallel
3. Filters out ads, retweets, replies
4. Downloads media (images/videos)
5. Enhances caption with AI
6. Posts to Facebook Page

## Performance

- **Parallel execution:** All 12 accounts checked simultaneously
- **Speed:** 2-3 minutes (vs 8 minutes sequential)
- **Optimized Playwright:** Reduced wait times

## Files

- `main.py` - Main bot (parallel optimized)
- `twitter_browser_scraper.py` - Twitter automation
- `CONFIG_JSON.template` - Config template
- `.github/workflows/bot.yml` - GitHub Actions workflow

#TVK #ThalapathyVijay
