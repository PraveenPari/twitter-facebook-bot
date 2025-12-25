"""
Facebook Permanent Token Generator
===================================
This script converts a short-lived token to a PERMANENT page token.

How to use:
1. Go to https://developers.facebook.com/tools/explorer/
2. Generate a new Access Token (with pages_manage_posts permission)
3. Run this script and paste your details when asked
"""

import requests

print("=" * 60)
print("Facebook Permanent Token Generator")
print("=" * 60)
print()

# Get inputs from user
print("Step 1: Enter your App details")
print("-" * 40)
app_id = input("Enter your App ID: ").strip()
app_secret = input("Enter your App Secret: ").strip()

print()
print("Step 2: Enter your short-lived token")
print("-" * 40)
print("(Get this from Graph API Explorer - it's the one that expires)")
short_token = input("Enter short-lived token: ").strip()

print()
print("Converting to long-lived token...")
print("-" * 40)

# Step 1: Convert short-lived to long-lived user token
url = f"https://graph.facebook.com/v22.0/oauth/access_token"
params = {
    "grant_type": "fb_exchange_token",
    "client_id": app_id,
    "client_secret": app_secret,
    "fb_exchange_token": short_token
}

response = requests.get(url, params=params)
data = response.json()

if "error" in data:
    print(f"ERROR: {data['error'].get('message', data)}")
    print("\nMake sure:")
    print("  1. Your App ID and Secret are correct")
    print("  2. Your short-lived token is fresh (not expired)")
    print("  3. The token was generated from the correct app")
    exit(1)

long_lived_token = data.get("access_token")
expires_in = data.get("expires_in", 0)
print(f"✓ Got long-lived token (expires in {expires_in // 86400} days)")

# Step 2: Get page access tokens
print()
print("Fetching your pages...")
print("-" * 40)

url = f"https://graph.facebook.com/v22.0/me/accounts"
params = {"access_token": long_lived_token}

response = requests.get(url, params=params)
data = response.json()

if "error" in data:
    print(f"ERROR: {data['error'].get('message', data)}")
    exit(1)

pages = data.get("data", [])

if not pages:
    print("No pages found! Make sure you have:")
    print("  - Admin access to a Facebook Page")
    print("  - Added 'pages_manage_posts' permission")
    exit(1)

print(f"Found {len(pages)} page(s):")
print()

for i, page in enumerate(pages):
    print(f"  [{i+1}] {page['name']} (ID: {page['id']})")

print()

# Let user select a page
if len(pages) == 1:
    selected = pages[0]
    print(f"Auto-selected: {selected['name']}")
else:
    choice = input(f"Select page number (1-{len(pages)}): ").strip()
    selected = pages[int(choice) - 1]

print()
print("=" * 60)
print("🎉 YOUR PERMANENT PAGE TOKEN")
print("=" * 60)
print()
print(f"Page Name: {selected['name']}")
print(f"Page ID:   {selected['id']}")
print()
print("Access Token (copy this):")
print("-" * 40)
print(selected['access_token'])
print("-" * 40)
print()
print("This token NEVER expires! ✓")
print()
print("Next steps:")
print(f"  1. Copy the token above")
print(f"  2. Open config.json")
print(f"  3. Replace the access_token value with the new token")
print()

# Verify the token
print("Verifying token...")
verify_url = f"https://graph.facebook.com/debug_token"
params = {
    "input_token": selected['access_token'],
    "access_token": f"{app_id}|{app_secret}"
}
response = requests.get(verify_url, params=params)
verify_data = response.json().get("data", {})

if verify_data.get("is_valid"):
    expires = verify_data.get("expires_at", 0)
    if expires == 0:
        print("✓ Token verified - NEVER EXPIRES!")
    else:
        from datetime import datetime
        exp_date = datetime.fromtimestamp(expires)
        print(f"✓ Token verified - Expires: {exp_date}")
else:
    print("⚠ Could not verify token")
