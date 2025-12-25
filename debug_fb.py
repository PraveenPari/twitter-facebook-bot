"""
Debug script to test video posting to Facebook
"""
import json
import requests

# Load config
with open('config.json', 'r') as f:
    config = json.load(f)

page_id = config['facebook']['page_id']
access_token = config['facebook']['access_token']

# Test video upload with a small test
print("Testing Facebook Video API...")
print(f"Page ID: {page_id}")
print(f"Token (first 20 chars): {access_token[:20]}...")

# Check token permissions
print("\n1. Checking token permissions...")
perm_url = f"https://graph.facebook.com/v22.0/me/permissions"
perm_response = requests.get(perm_url, params={'access_token': access_token})
print(f"Permissions response: {perm_response.json()}")

# Check if we can access the page
print("\n2. Checking page access...")
page_url = f"https://graph.facebook.com/v22.0/{page_id}"
page_response = requests.get(page_url, params={'access_token': access_token})
print(f"Page response: {page_response.json()}")

# Try a simple text post first
print("\n3. Testing text post...")
test_url = f"https://graph.facebook.com/v22.0/{page_id}/feed"
test_response = requests.post(test_url, data={
    'message': 'Test from bot - please ignore',
    'access_token': access_token
})
result = test_response.json()
print(f"Text post response: {result}")

if 'id' in result:
    print("✓ Text posting works!")
    # Delete the test post
    post_id = result['id']
    delete_url = f"https://graph.facebook.com/v22.0/{post_id}"
    requests.delete(delete_url, params={'access_token': access_token})
    print("  (Test post deleted)")
else:
    print("✗ Text posting failed!")
