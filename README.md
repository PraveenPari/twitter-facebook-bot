# Twitter to Facebook & Instagram Bot

Automated bot that monitors public X/Twitter accounts (without Nitter or paid X API keys) and cross-posts media tweets to Facebook Pages and Instagram Business Accounts.

## Features

- 🐦 Multi-channel X/Twitter monitoring (no Nitter or browser automation required):
  1. **FxTwitter v2 API** (`api.fxtwitter.com` profile statuses + search fallback, caching numeric user IDs in `state.json`)
  2. **FxTwitter RSS Feed** (`fxtwitter.com/{handle}/feed.xml`)
  3. **Optional X Cookies (`twifork`/`twikit`)** via `TWITTER_COOKIES` env var or `twitter_cookies.json`
  4. **Direct X Guest GraphQL** (`api.x.com` guest token + GraphQL timeline)
  5. **X Syndication Embed API** fallback
- 📘 Posts to Facebook Pages (images and videos, with native scheduling)
- 📸 Posts to Instagram Business Account (images and Reels up to 15 minutes via direct resumable upload)
- ⏰ Scheduled Facebook posting spaced by `schedule_gap_minutes`
- 🔄 State persistence (`state.json`) to avoid duplicate posts and cache numeric X user IDs
- 🎥 YouTube Live re-streaming support (optional)

## Requirements

- Python 3.10+ (Python 3.9 works without optional `twifork` cookie fallback)
- FFmpeg/FFprobe (for video duration checks and `yt-dlp` fallback merging)

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Install FFmpeg (for video duration check):**
   - Windows: `winget install Gyan.FFmpeg`
   - Linux: `apt install ffmpeg`
   - Mac: `brew install ffmpeg`

3. **Configure the bot:**
   - Copy `config.json.template` to `config.json`
   - Add your Facebook Page ID and Access Token (or set `FB_PAGE_ID` / `FB_ACCESS_TOKEN`)
   - Add your Instagram Business Account ID and Access Token (or set `IG_USER_ID` / `IG_ACCESS_TOKEN`)
   - Configure Twitter accounts to monitor

## Configuration

```json
{
  "twitter_accounts": [
    { "id": "account_id", "username": "TwitterHandle" }
  ],
  "facebook": {
    "page_id": "YOUR_FB_PAGE_ID",
    "access_token": "YOUR_PAGE_ACCESS_TOKEN"
  },
  "instagram": {
    "enabled": true,
    "user_id": "YOUR_IG_BUSINESS_ACCOUNT_ID",
    "access_token": "YOUR_USER_ACCESS_TOKEN"
  },
  "settings": {
    "post_window_minutes": 60,
    "schedule_gap_minutes": 10
  }
}
```

### Optional X/Twitter Cookies Fallback
No X API key or login is needed for normal operation (FxTwitter v2 works out of the box). If you ever want a cookie-authenticated backup channel via `twifork`, export cookies (`auth_token`, `ct0`, etc.) from a logged-in browser session and supply them either:
- as `TWITTER_COOKIES` environment variable / GitHub Secret (JSON object, cookie-editor JSON array, or `key=value; ...` string), or
- in a local `twitter_cookies.json` file (already gitignored).

## Token Setup

### Facebook Page Access Token
1. Go to [Graph API Explorer](https://developers.facebook.com/tools/explorer/)
2. Select your app and page
3. Add permissions: `pages_manage_posts`, `publish_video`, `pages_read_engagement`
4. Generate Page Access Token
5. Exchange for 60-day long-lived token

### Instagram Business Account
1. Link your Instagram to a Facebook Page
2. Get the Instagram Business Account ID via: `GET /{page-id}?fields=instagram_business_account`
3. Use a User Access Token with `instagram_content_publish` permission

## Running

```bash
python main.py
```

Set `POST_WINDOW_MINUTES` to override the tweet lookback window in minutes (default: `60`).

## GitHub Actions Deployment

The bot runs on a 30-minute schedule via `.github/workflows/bot.yml` (no Playwright/Chromium or `xvfb-run` needed).

### Secrets:
- `CONFIG_JSON` (full `config.json` contents)
- `FB_PAGE_ID`
- `FB_ACCESS_TOKEN` (Page Access Token)
- `IG_USER_ID`
- `IG_ACCESS_TOKEN` (User Access Token)
- `GIST_TOKEN` & `GIST_ID` (for `state.json` persistence)
- `TWITTER_COOKIES` (optional, backup cookie-authenticated channel)

## Limitations

- Instagram Reels must be between 3 seconds and 15 minutes
- Instagram image posts require temporary public hosting (uploaded via Freeimage.host / Tmpfiles.org / ImgBB)
- **Instagram posts immediately** (API scheduling is not used)
- **Facebook uses native scheduling** for queued multi-posts, spaced by `schedule_gap_minutes`
- Facebook tokens expire after 60 days unless refreshed

## License

MIT
