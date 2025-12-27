# 🚀 DEPLOYMENT CHECKLIST

## ✅ **Step-by-Step Deployment Guide**

### **Step 1: Update GitHub Secret - CONFIG_JSON**

1. **Copy content from CONFIG_JSON.template**
   - Open: `CONFIG_JSON.template`
   - Select ALL content (Ctrl+A)
   - Copy (Ctrl+C)

2. **Go to GitHub Repository**
   - Navigate to: https://github.com/YOUR_USERNAME/twitter-facebook-bot
   - Click: **Settings** (top menu)
   - Click: **Secrets and variables** → **Actions** (left sidebar)

3. **Update CONFIG_JSON Secret**
   - Find secret: `CONFIG_JSON`
   - Click: **Update** (pencil icon)
   - Paste the content
   - Click: **Update secret**

---

### **Step 2: Verify Other Secrets**

Make sure these secrets exist:

| Secret Name | Value | Status |
|-------------|-------|--------|
| `FB_PAGE_ID` | 946593568529880 | ✅ Should exist |
| `FB_ACCESS_TOKEN` | Your token | ✅ Should exist |
| `GEMINI_API_KEY` | Your API key | ✅ Should exist |
| `GIST_TOKEN` | GitHub token | ✅ Should exist |
| `GIST_ID` | Gist ID | ✅ Should exist |
| `CONFIG_JSON` | **UPDATE THIS** | ⚠️ Update now |

---

### **Step 3: Push Code to GitHub**

```bash
# Add all files
git add .

# Commit
git commit -m "Production ready - streaming with error handling"

# Push
git push origin main
```

---

### **Step 4: Verify Workflow File**

Make sure `.github/workflows/bot.yml` exists and is correct.

**Check:**
- ✅ Runs every 30 minutes
- ✅ Installs Python 3.11
- ✅ Installs Playwright
- ✅ Runs main.py

---

### **Step 5: Monitor First Run**

1. Go to GitHub repository
2. Click: **Actions** tab
3. Wait for workflow to trigger (within 30 minutes)
4. Click on the running workflow
5. Watch the logs

---

## 📊 **Expected Output - First Run:**

```
STEP 1: CHECKING YOUTUBE LIVE FOR RE-STREAMING
[YouTube] Attempting to start re-streaming...
[YouTube] No live stream detected

⚠️  FACEBOOK LIVE API ERROR - PAGE NOT YET ELIGIBLE
   Your page needs to cross 60 days to use Live Video API
   
   Continuing to Twitter monitoring...

STEP 2: CHECKING TWITTER ACCOUNTS
Checking: @TVKVijayHQ
  [TVKVijayHQ] OK! Valid tweet (150 chars)
  
Processing 1/3: tvk_vijay_hq
  Downloading image...
  [OK] Image downloaded
  Enhancing caption...
  Posting to Facebook...
  [SUCCESS] POSTED: 123456789_123456789

✅ Done!
```

---

## ⚠️ **Common Issues:**

### **Issue 1: CONFIG_JSON Secret Error**
```
Error: No config found!
```
**Fix:** Update CONFIG_JSON secret with content from template

### **Issue 2: FFmpeg Not Found**
```
Error: ffmpeg: command not found
```
**Fix:** Should auto-install - check workflow file has FFmpeg install step

### **Issue 3: Twitter Login Failed**
```
Warning: Login failed - using guest mode
```
**Fix:** Check Twitter credentials in CONFIG_JSON

---

## ✅ **Success Indicators:**

After deployment, you should see:

1. ✅ GitHub Actions runs every 30 minutes
2. ✅ Twitter accounts checked
3. ✅ Tweets posted to Facebook
4. ✅ State saved to Gist
5. ⚠️ YouTube streaming error (expected until 60 days)

---

## 🎯 **Final Checklist:**

- [ ] CONFIG_JSON secret updated
- [ ] All other secrets verified
- [ ] Code pushed to GitHub
- [ ] Workflow file exists
- [ ] First run monitored
- [ ] Tweets appearing on Facebook

---

## 📝 **After Deployment:**

### **Daily:**
- ✅ Bot runs automatically every 30 minutes
- ✅ No manual intervention needed

### **When YouTube Goes Live:**
- ⚠️ Will try to stream (fails with 60-day error)
- ✅ Continues to Twitter (doesn't stop)

### **After 60 Days:**
- ✅ YouTube streaming auto-enables
- ✅ No code changes needed!

---

## 🚀 **Ready to Deploy?**

**Run these commands:**

```bash
git add .
git commit -m "Production deployment"
git push
```

Then update CONFIG_JSON secret in GitHub!

**Your bot will be live in 30 minutes!** ⏰
