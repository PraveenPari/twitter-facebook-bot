import requests
import xml.etree.ElementTree as ET

url = 'https://rss.app/feeds/rk1HyvzYX7LCyePL.xml'
r = requests.get(url, timeout=30)
root = ET.fromstring(r.text)

item = root.find('.//item')
link = item.find('link').text if item.find('link') is not None else ''
desc = item.find('description').text if item.find('description') is not None else ''

print('Link:', link)
print()
print('='*60)
print('Raw description:')
print('='*60)
print(desc)

# Save to file for inspection
with open('feed4_raw.txt', 'w', encoding='utf-8') as f:
    f.write(desc)
print('\nSaved to feed4_raw.txt')
