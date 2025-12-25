# Twitter to Facebook Bot 🤖

Automatically posts tweets from Twitter/X RSS feeds to Facebook page every 30 minutes.

## Features

✅ **Auto-posting** - Runs every 30 minutes via GitHub Actions  
✅ **AI Enhancement** - Uses Gemini AI to enhance captions with Tamil keywords  
✅ **SEO Hashtags** - Adds TVK positive hashtags automatically  
✅ **Media Support** - Downloads and posts images/videos  
✅ **Smart Filtering** - Skips retweets, replies, and duplicate posts  
✅ **Scheduled Posts** - Spaces multiple posts 10 minutes apart  
✅ **100% Free** - Uses GitHub Actions free tier

## Setup

### Prerequisites

1. GitHub account
2. Facebook Page with admin access
3. Facebook access token (get from Graph API Explorer)
4. Gemini API key (get from https://aistudio.google.com/apikey)

### Quick Start

1. **Fork/Clone this repository**

2. **Add GitHub Secrets** (Settings → Secrets → Actions)
   - `GIST_TOKEN` - Personal access token with gist scope
   - `GIST_ID` - Gist ID for state persistence
   - `FB_PAGE_ID` - Your Facebook page ID
   - `FB_ACCESS_TOKEN` - Facebook page access token
   - `GEMINI_API_KEY` - Google Gemini API key
   - `CONFIG_JSON` - Bot configuration (see SECRETS_REFERENCE.md)

3. **Enable GitHub Actions**
   - Go to Actions tab
   - Enable workflows

4. **Done!** Bot runs automatically every 30 minutes

## Documentation

- **[GITHUB_SETUP.md](GITHUB_SETUP.md)** - Detailed setup guide
- **[SECRETS_REFERENCE.md](SECRETS_REFERENCE.md)** - All secrets and values

## How It Works

```
Every 30 minutes:
  ↓
Check RSS feeds → Find new tweets
  ↓
Download media (images/videos)
  ↓
Enhance caption with AI (Tamil keywords)
  ↓
Add TVK positive hashtags
  ↓
Post to Facebook → Schedule if multiple posts
  ↓
Save state → Remember posted IDs
```

## Configuration

Edit `config.json` to customize:

- RSS feed URLs to monitor
- Post time window (default: 90 minutes)
- Minimum content length (default: 50 chars)
- Hashtag settings
- AI enhancement toggle

## Local Testing

```powershell
# Install dependencies
pip install -r requirements.txt

# Run bot
python main.py
```

## Schedule

- **Frequency**: Every 30 minutes
- **Cost**: FREE (GitHub Actions free tier: 2,000 minutes/month)
- **Usage**: ~5 minutes/day = 150 minutes/month

## Security

✅ All sensitive tokens stored in GitHub Secrets  
✅ Config uses environment variables  
✅ `.gitignore` prevents token commits  
✅ Private repository recommended

## Support

For issues or questions, check the documentation files or create an issue.

## License

MIT License - Feel free to use and modify!

---

**Made with ❤️ for TVK supporters**
