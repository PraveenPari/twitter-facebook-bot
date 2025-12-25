import requests
import xml.etree.ElementTree as ET
import re

url = 'https://rss.app/feeds/dKx755ccU5FJFo1O.xml'
r = requests.get(url, timeout=30)
root = ET.fromstring(r.text)

print('All items in feed:')
for i, item in enumerate(root.findall('.//item')):
    link = item.find('link').text if item.find('link') is not None else ''
    pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ''
    desc = item.find('description').text if item.find('description') is not None else ''
    
    print(f'\n--- Item {i+1} ---')
    print(f'Link: {link}')
    print(f'PubDate: {pub_date}')
    
    desc_preview = desc[:300] if desc else 'N/A'
    print(f'Description preview: {desc_preview}')
    
    # Check for embedded tweet
    embedded = re.search(r'https?://(?:x\.com|twitter\.com)/\w+/status/\d+', desc or '')
    print(f'Has embedded tweet link: {bool(embedded)}')
    if embedded:
        print(f'  Embedded URL: {embedded.group()}')

# Save latest to file
item = root.find('.//item')
if item:
    desc = item.find('description').text if item.find('description') is not None else ''
    with open('feed5_latest.txt', 'w', encoding='utf-8') as f:
        f.write(desc)
    print('\nSaved latest description to feed5_latest.txt')
