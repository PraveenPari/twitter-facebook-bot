# GitHub Actions Setup Guide
## Twitter to Facebook Bot - Automated Posting

This guide will help you set up GitHub Actions to run your bot automatically every 30 minutes.

---

## Step 1: Create a GitHub Repository

1. Go to [GitHub](https://github.com) and create a new repository
2. Name it: `twitter-to-facebook-bot` (or any name you prefer)
3. Make it **Private** (recommended for security)
4. Don't initialize with README (we'll push our code)

---

## Step 2: Push Your Code to GitHub

Open PowerShell in your project directory and run:

```powershell
# Initialize git (if not already done)
git init

# Add all files
git add .

# Commit
git commit -m "Initial commit: Twitter to Facebook bot"

# Add remote (replace YOUR_USERNAME with your GitHub username)
git remote add origin https://github.com/YOUR_USERNAME/twitter-to-facebook-bot.git

# Push to GitHub
git push -u origin main
```

---

## Step 3: Create a GitHub Gist for State Persistence

The bot needs to remember which posts it already published. We'll use a GitHub Gist (free):

1. Go to https://gist.github.com/
2. Click **"New gist"**
3. Name it: `state.json`
4. Content: `{"last_posted_ids": {}}`
5. Click **"Create secret gist"**
6. **Copy the Gist ID** from the URL (e.g., `https://gist.github.com/YOUR_USERNAME/abc123def456` - copy `abc123def456`)

---

## Step 4: Create a Personal Access Token for Gist

1. Go to https://github.com/settings/tokens
2. Click **"Generate new token"** → **"Generate new token (classic)"**
3. Name: `Bot Gist Access`
4. Expiration: **No expiration** (or 1 year)
5. Scopes: Check **only** `gist`
6. Click **"Generate token"**
7. **COPY THE TOKEN** - you won't see it again!

---

## Step 5: Add GitHub Secrets

Go to your repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Add these secrets one by one:

### Secret 1: `GIST_TOKEN`
**Value:** The Personal Access Token you just created
```
ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### Secret 2: `GIST_ID`
**Value:** The Gist ID from Step 3
```
abc123def456
```

### Secret 3: `FB_PAGE_ID`
**Value:** Your Facebook Page ID
```
946593568529880
```

### Secret 4: `FB_ACCESS_TOKEN`
**Value:** Your 59-day Facebook token
```
EAAT9tZCqOCP0BQTR8iw1MEjuZAf9hHc6Ui6hRtRiYZAtTQ0ZCCOTaWnNQEeZCe0Rmo66R4yngVpvVLHfY57nfZAgQlKK3zCCr5CNv2BiNvcnl9VVoZCktxvVyOBDMSXg7DgkBB94srFtYSHfpQPlvIojVaDMe6A7qXfNONVAat44v2Li27eSr0EqPbTG5Fj673OaR4ewTAU
```

### Secret 5: `GEMINI_API_KEY`
**Value:** Your Gemini API key
```
AIzaSyB0R8ffJux2P6YhWDc8a_UugRrXGjsub8s
```

### Secret 6: `CONFIG_JSON`
**Value:** Copy the ENTIRE content of your `config.json` file

**IMPORTANT:** Remove sensitive data and use placeholders:

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
        "page_id": "PLACEHOLDER_USE_SECRET",
        "access_token": "PLACEHOLDER_USE_SECRET"
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
        "api_key": "PLACEHOLDER_USE_SECRET",
        "model": "gemini-2.0-flash-exp"
    }
}
```

**Note:** The workflow will automatically replace placeholders with the actual secrets.

---

## Step 6: Update main.py to Use Environment Variables

The bot already checks for environment variables first, so no code changes needed!

---

## Step 7: Enable GitHub Actions

1. Go to your repository → **Actions** tab
2. If prompted, click **"I understand my workflows, go ahead and enable them"**
3. You should see **"Twitter to Facebook Bot"** workflow
4. Click **"Run workflow"** → **"Run workflow"** to test it manually

---

## Step 8: Verify It's Working

1. Go to **Actions** tab
2. Click on the latest workflow run
3. Check the logs to see if the bot ran successfully
4. Check your Facebook page to see if posts were created

---

## Schedule Details

The bot will now run **automatically every 30 minutes**:

| Time | Action |
|------|--------|
| Every 30 min | Check RSS feeds for new posts |
| If new post found | Download media → Enhance with AI → Add hashtags → Post to Facebook |
| Always | Save state to Gist (remember posted IDs) |

---

## Important Notes

### Token Expiration Reminders:

1. **Facebook Token**: Expires **February 22, 2026**
   - Set a calendar reminder for Feb 15, 2026
   - Get a new token and update the `FB_ACCESS_TOKEN` secret

2. **Gemini API**: Free tier limits
   - 50 requests/day
   - If exceeded, bot still works (uses original captions)
   - Resets every 24 hours

### Cost:
- **GitHub Actions**: **FREE** (2,000 minutes/month for private repos)
- **This bot uses**: ~5 minutes/day = ~150 minutes/month
- **100% FREE!** ✅

---

## Troubleshooting

### Bot not running?
- Check **Actions** tab for errors
- Verify all secrets are set correctly

### Posts not appearing on Facebook?
- Check if Facebook token expired
- Verify page permissions

### Gemini AI errors?
- Check if you hit daily quota (50 requests)
- Either wait 24 hours or disable AI enhancement

---

## Manual Testing

To test the bot manually:

```powershell
# Run locally
.venv\Scripts\python.exe main.py

# Or trigger on GitHub
# Go to Actions → Twitter to Facebook Bot → Run workflow
```

---

## Security Best Practices

✅ **Never commit tokens to git**
✅ **Use GitHub Secrets for all sensitive data**
✅ **Keep repository private**
✅ **Rotate tokens periodically**

---

## Summary

Your bot is now:
- ✅ Running every 30 minutes automatically
- ✅ All tokens are secure in GitHub Secrets
- ✅ State persists using GitHub Gist (free)
- ✅ 100% free (GitHub Actions free tier)
- ✅ No server needed!

🎉 **Your Twitter to Facebook bot is fully automated!**
