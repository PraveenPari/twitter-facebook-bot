import requests
import xml.etree.ElementTree as ET
import re

url = 'https://rss.app/feeds/mhXvYBo3pbDAI8VN.xml'
r = requests.get(url, timeout=30)
root = ET.fromstring(r.text)

item = root.find('.//item')
if item:
    link = item.find('link').text if item.find('link') is not None else ''
    desc = item.find('description').text if item.find('description') is not None else ''
    
    print(f'Link: {link}')
    
    # Save to file
    with open('feed3_debug.txt', 'w', encoding='utf-8') as f:
        f.write(f'Tweet Link: {link}\n\n')
        f.write(f'Description:\n{desc}')
    
    print('Saved to feed3_debug.txt')
    
    # Find embedded tweets
    embedded = re.findall(r'https?://(?:x\.com|twitter\.com)/(\w+)/status/(\d+)', desc or '')
    print(f'\nEmbedded tweets: {embedded}')
    
    # Own ID
    own_match = re.search(r'/status/(\d+)', link)
    own_id = own_match.group(1) if own_match else None
    print(f'Own ID: {own_id}')
    
    for username, tweet_id in embedded:
        if tweet_id != own_id:
            print(f'DIFFERENT: {username}/{tweet_id}')
        else:
            print(f'SAME: {username}/{tweet_id}')
