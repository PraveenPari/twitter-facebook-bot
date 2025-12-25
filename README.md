# Twitter (RSS) to Facebook Bot

A serverless bot that monitors a Twitter RSS feed for new videos and cross-posts them to Facebook using AWS Lambda.

## Project Structure
- `src/lambda_function.py`: Core logic (RSS check -> Check S3 -> Download -> Post FB).
- `src/requirements.txt`: Dependencies (`yt-dlp`, `facebook-sdk`, `feedparser`).
- `template.yaml`: AWS SAM definition for Lambda, S3, and Scheduler.
- `run_setup.bat`: **Run this first** to install Python dependencies locally.
- `run_tests.bat`: Run this to verify the code works (uses mock data).

## Quick Start on Windows

1. **Prerequisite**: Ensure [Python 3.10](https://www.python.org/downloads/) is installed and added to your PATH.
2. **Install Dependencies**:
   Double-click `run_setup.bat` or run:
   ```cmd
   run_setup.bat
   ```
   This will install the required libraries into the `src/` folder so they can be deployed to AWS.

3. **Verify Logic**:
   Double-click `run_tests.bat` to run the test and ensure the bot logic handles RSS feeds correctly.

4. **Deploy to AWS**:
   ```cmd
   sam build
   sam deploy --guided
   ```
   *Enter your RSS URL and Facebook Tokens when prompted.*

## Configuration Details
- **RSS URL**: Get this from [RSS.app](https://rss.app) using the target Twitter URL.
- **S3 Bucket**: Stores `last_tweet_id.txt` to remember the last posted tweet.
- **Frequency**: Runs every 30 minutes by default.
