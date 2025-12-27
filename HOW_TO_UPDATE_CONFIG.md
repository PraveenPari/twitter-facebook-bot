# How to Update CONFIG_JSON Secret

## 📋 **What You Need to Do:**

Copy the content from `CONFIG_JSON.template` and paste it as a GitHub secret.

---

## 🔢 **STEP-BY-STEP GUIDE:**

### **Step 1: Open CONFIG_JSON.template**

Open this file: `CONFIG_JSON.template`

It contains:
```json
{
  "twitter_accounts": [
    {"id": "tvk_vijay_hq", "username": "TVKVijayHQ", "enabled": true, "priority": 1},
    {"id": "tvk_party_hq", "username": "TVKPartyHQ", "enabled": true, "priority": 2},
    ...and 10 more accounts
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

### **Step 2: Copy ALL the content**

**Select everything** from the opening `{` to the closing `}`

### **Step 3: Go to GitHub**

1. Go to your repo: https://github.com/YOUR_USERNAME/twitter-facebook-bot
2. Click **Settings** (top menu)
3. Click **Secrets and variables** → **Actions** (left sidebar)
4. Find the secret named **`CONFIG_JSON`**

### **Step 4: Update the Secret**

1. Click **`CONFIG_JSON`** secret
2. Click **"Update secret"** or **pencil icon** to edit
3. **PASTE** the entire JSON content you copied
4. Click **"Update secret"** button to save

---

## ✅ **What This Does:**

When GitHub Actions runs, it reads this `CONFIG_JSON` and:
- Creates `config.json` with all 12 Twitter accounts
- Uses the Twitter login credentials
- Bot runs with these settings

---

## 📝 **Visual Example:**

### **CONFIG_JSON.template (What to Copy):**
```json
{
  "twitter_accounts": [
    {"id": "tvk_vijay_hq", "username": "TVKVijayHQ", "enabled": true, "priority": 1},
    {"id": "tvk_party_hq", "username": "TVKPartyHQ", "enabled": true, "priority": 2},
    {"id": "tvk_it_wing", "username": "TVKHQITWingOffl", "enabled": true, "priority": 3},
    {"id": "arunraaj_kg", "username": "arunraajkg", "enabled": true, "priority": 4},
    {"id": "ashwin_tvk", "username": "ashwin_tvk_", "enabled": true, "priority": 5},
    {"id": "tvk_vijay_24x7", "username": "TVKVijay24x7", "enabled": true, "priority": 6},
    {"id": "boss_tvk", "username": "BossTVK", "enabled": true, "priority": 7},
    {"id": "tvk_world", "username": "TVK_WORLD", "enabled": true, "priority": 8},
    {"id": "jegadesh_tvk", "username": "JegadeshTVK", "enabled": true, "priority": 9},
    {"id": "priyanka_smile", "username": "PriyankaSmile01", "enabled": true, "priority": 10},
    {"id": "vijay_fans_trends", "username": "VijayFansTrends", "enabled": true, "priority": 11},
    {"id": "sangeet", "username": "sangeet29332013", "enabled": true, "priority": 12}
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

### **GitHub Secret (Where to Paste):**

```
GitHub → Settings → Secrets → Actions
↓
CONFIG_JSON = [PASTE THE JSON HERE]
```

---

## ⚠️ **Important Notes:**

1. **Copy as ONE LINE or formatted** - Both work fine
2. **Include the curly braces** `{ }` - Entire JSON
3. **Don't add quotes** - Just paste the raw JSON
4. **All 12 accounts** should be in the list

---

## 🎯 **Why This is Needed:**

Your **local `config.json`** is gitignored (not pushed to GitHub).

GitHub Actions needs the config, so:
- You store it as a **secret** (`CONFIG_JSON`)
- GitHub Actions reads it
- Creates `config.json` during the run
- Bot uses it to know which accounts to monitor

---

## ✅ **Quick Summary:**

```
1. Open: CONFIG_JSON.template
2. Copy: All content (the entire JSON)
3. Go to: GitHub → Settings → Secrets → Actions
4. Edit: CONFIG_JSON secret
5. Paste: The JSON content
6. Save: Click "Update secret"
```

**Done!** Your bot will now use the 12 Twitter accounts! 🚀
