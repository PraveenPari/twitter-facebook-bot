import unittest
from unittest.mock import MagicMock, patch, mock_open
import sys
import os

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '../src'))

from lambda_function import lambda_handler

class TestRSSBot(unittest.TestCase):

    @patch('lambda_function.feedparser.parse')
    @patch('lambda_function.boto3.client')
    @patch('lambda_function.facebook.GraphAPI')
    @patch('lambda_function.yt_dlp.YoutubeDL')
    @patch.dict(os.environ, {
        'TWITTER_RSS_URL': 'http://rss.fake/feed',
        'S3_BUCKET_NAME': 'test-bucket',
        'FB_ACCESS_TOKEN': 'fake-token',
        'FB_PAGE_ID': '123'
    })
    def test_new_tweet_flow(self, MockYDL, MockFB, MockBoto, MockFeed):
        # 1. Setup RSS Mock
        mock_entry = MagicMock()
        mock_entry.link = "https://twitter.com/user/status/12345"
        MockFeed.return_value.entries = [mock_entry]

        # 2. Setup S3 Mock (Return different ID)
        s3 = MockBoto.return_value
        s3.get_object.return_value = {
            'Body': MagicMock(read=lambda: b'11111') # Old ID
        }

        # 3. Setup YTDL (Download Mock)
        ydl_instance = MockYDL.return_value.__enter__.return_value
        ydl_instance.extract_info.return_value = {'description': 'Cool video'}
        ydl_instance.prepare_filename.return_value = '/tmp/media_file.mp4'

        # 4. Setup File Exists Mock
        with patch('os.path.exists', return_value=True), \
             patch('os.remove') as mock_rm, \
             patch('builtins.open', mock_open(read_data=b'data')):
            
            # RUN
            response = lambda_handler({}, {})

            # ASSERT
            self.assertEqual(response['statusCode'], 200)
            self.assertEqual(response['body'], "Success")
            
            # Check S3 Update
            s3.put_object.assert_called_with(
                Bucket='test-bucket',
                Key='last_tweet_id.txt',
                Body='12345'
            )
            
            # Check FB Upload
            MockFB.return_value.put_video.assert_called()
            print("Test passed: New tweet detected and posted.")

    @patch('lambda_function.feedparser.parse')
    @patch('lambda_function.boto3.client')
    @patch.dict(os.environ, {'TWITTER_RSS_URL': 'http://rss.fake/feed', 'S3_BUCKET_NAME': 'test-bucket'})
    def test_no_new_tweet(self, MockBoto, MockFeed):
        # 1. RSS Mock
        mock_entry = MagicMock()
        mock_entry.link = "https://twitter.com/user/status/12345"
        MockFeed.return_value.entries = [mock_entry]

        # 2. S3 Mock (Same ID)
        s3 = MockBoto.return_value
        s3.get_object.return_value = {
            'Body': MagicMock(read=lambda: b'12345') # SAME ID
        }

        # RUN
        response = lambda_handler({}, {})

        # ASSERT
        self.assertEqual(response['body'], "Up to date")
        print("Test passed: No new tweet ignored.")

if __name__ == '__main__':
    unittest.main()
