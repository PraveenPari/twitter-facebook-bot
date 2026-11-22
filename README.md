# Twitter to Facebook & Instagram Bot

Automated bot that monitors public X/Twitter accounts (without Nitter or paid X API keys) and cross-posts media tweets to Facebook Pages and Instagram Business Accounts.

## Features

- 🐦 Multi-channel X/Twitter monitoring (no Nitter or browser automation required):
  1. **FxTwitter v2 API** (`api.fxtwitter.com` profile statuses + search fallback, caching numeric user IDs in `state.json`)
  2. **FxTwitter RSS Feed** (`fxtwitter.com/{handle}/feed.xml`)
  3. **Optional X Cookies (`twifork`/`twikit`)** via `TWITTER_COOKIES` env var or `twitter_cookies.json`
  4. **Direct X Guest GraphQL** (`api.x.com` guest token + GraphQL timeline)
  5. **X Syndication Embed API** fallback
- 🔎 Hashtag / keyword discovery (enabled by default for `#TVK`; add more queries such as `#TVKParty` and `#ThalapathyVijay`) using FxTwitter search and cookie-authenticated fallback
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
    "max_lookback_minutes": 1440,
    "max_posts_per_account": 3,
    "max_posts_per_run": 10,
    "schedule_gap_minutes": 10,
    "hashtag_search": {
      "enabled": true,
      "queries": [
        { "id": "hashtag_tvk", "query": "#TVK" },
        { "id": "hashtag_tvkparty", "query": "#TVKParty" },
        { "id": "hashtag_thalapathy_vijay", "query": "#ThalapathyVijay" }
      ],
      "limit": 40,
      "media_only": false
    }
  }
}
```

### Hashtag search and optional X/Twitter cookies
`#TVK` search is enabled by default, including for existing `CONFIG_JSON` secrets that predate this setting. Add the block shown above under `settings.hashtag_search` to search more tags or keywords. FxTwitter's public search is tried first. If it is unavailable, X's logged-out search is blocked, so the bot can fall back to `twifork` only when valid cookies are provided. For GitHub Actions, update the JSON stored in the `CONFIG_JSON` secret with the `hashtag_search` block from the template.

No X API key or login is normally needed. To enable the authenticated fallback, export cookies (`auth_token`, `ct0`, etc.) from a logged-in browser session and supply them as the `TWITTER_COOKIES` environment variable / GitHub Secret (JSON object, cookie-editor JSON array, or `key=value; ...` string), or in a local `twitter_cookies.json` file (already gitignored). Never commit or share X cookies; they grant account access.

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

Set `POST_WINDOW_MINUTES` to override the base tweet lookback window in minutes (default: `60`). When a run is late, the bot widens the window to the time since the last fully processed run, up to `settings.max_lookback_minutes` (default: 24 hours). The watermark is held when there are unprocessed posts or failed sources, so the next invocation can drain the backlog without reposting IDs already delivered.

## GitHub Actions Deployment

The bot is requested on a 30-minute schedule via `.github/workflows/bot.yml` (no Playwright/Chromium or `xvfb-run` needed). GitHub Actions schedule events are best-effort and can be delayed or skipped, so this cannot guarantee an exact 30-minute cadence; catch-up logic preserves missed posts for later runs. Each run handles up to 3 media posts per source and 10 total by default, spaced using `schedule_gap_minutes`.

### Secrets:
- `CONFIG_JSON` (full `config.json` contents)
- `FB_PAGE_ID`
- `FB_ACCESS_TOKEN` (Page Access Token)
- `IG_USER_ID`
- `IG_ACCESS_TOKEN` (User Access Token)
- `GIST_TOKEN` & `GIST_ID` (for `state.json` persistence)
- `TWITTER_COOKIES` (optional, cookie-authenticated fallback for timelines and hashtag search)

## Limitations

- Instagram Reels must be between 3 seconds and 15 minutes
- Instagram image posts require temporary public hosting (uploaded via Freeimage.host / Tmpfiles.org / ImgBB)
- **Instagram posts immediately** (API scheduling is not used)
- **Facebook uses native scheduling** for queued multi-posts, spaced by `schedule_gap_minutes`
- Facebook tokens expire after 60 days unless refreshed

## License

MIT
