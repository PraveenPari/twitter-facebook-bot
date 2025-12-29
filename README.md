# Twitter to Facebook & Instagram Bot

Automated bot that monitors Twitter (via Nitter) and cross-posts content to Facebook Pages and Instagram Business Accounts.

## Features

- 🐦 Monitors multiple Twitter accounts via Nitter
- 📘 Posts to Facebook Pages (text, images, videos)
- 📸 Posts to Instagram Business Account (images, reels)
- 🎬 Video duration check (skips Instagram for videos > 5 minutes)
- ⏰ Scheduled posting with 10-minute intervals
- 🔄 State persistence (avoids duplicate posts)
- 🎥 YouTube Live re-streaming support (optional)
- ✨ AI-powered caption enhancement via Gemini (optional)

## Requirements

- Python 3.9+
- FFmpeg/FFprobe (for video duration check)
- Playwright browsers

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

2. **Install FFmpeg (for video duration check):**
   - Windows: `winget install Gyan.FFmpeg`
   - Linux: `apt install ffmpeg`
   - Mac: `brew install ffmpeg`

3. **Configure the bot:**
   - Copy `config.json.template` to `config.json`
   - Add your Facebook Page Access Token
   - Add your Instagram Business Account ID
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
    "post_window_minutes": 30,
    "schedule_gap_minutes": 10
  }
}
```

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

## GitHub Actions Deployment

The bot can run on a schedule via GitHub Actions. See `.github/workflows/` for the workflow configuration.

### Required Secrets:
- `FB_PAGE_ID`
- `FB_ACCESS_TOKEN` (Page Access Token)
- `IG_USER_ID`
- `IG_ACCESS_TOKEN` (User Access Token)
- `GEMINI_API_KEY` (optional)
- `GIST_TOKEN` (for state persistence)

## Limitations

- Instagram videos must be under 5 minutes (for Reels)
- Instagram requires public URL for media (uses catbox.moe for video hosting)
- **Instagram posts immediately** (no API scheduling support) - all IG posts go out at once
- **Facebook uses native scheduling** - posts are spaced 10 minutes apart
- Facebook token expires after 60 days (needs renewal)


## License

MIT
