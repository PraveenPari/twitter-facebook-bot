import asyncio
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import main as bot_main
from twitter_fetcher import TwitterFetcher


def _response(status_code=200, payload=None):
    response = MagicMock()
    response.status_code = status_code
    response.headers = {}
    response.text = json.dumps(payload or {})
    response.json.return_value = payload or {}
    return response


def _media_tweet(tweet_id, timestamp, *, video=False, author="NewsUser"):
    return {
        "id": tweet_id,
        "text": f"TVK news {tweet_id}",
        "link": f"https://x.com/{author}/status/{tweet_id}",
        "media_url": f"https://pbs.twimg.com/media/{tweet_id}.jpg",
        "video_url": f"https://video.twimg.com/{tweet_id}.mp4" if video else None,
        "media_urls": [],
        "has_video": video,
        "created_timestamp": timestamp,
        "date_str": "2026-11-22T04:00:00Z",
        "is_pinned": False,
        "is_retweet": False,
    }


def test_hashtag_config_post_limits_and_catchup_window(monkeypatch):
    now_ts = 1_800_000_000.0
    config = {
        "settings": {
            "post_window_minutes": 60,
            "hashtag_search": {
                "enabled": True,
                "queries": [
                    {"id": "tvk", "query": "TVK"},
                    {"id": "duplicate_tvk", "query": "#TVK"},
                    {"query": "#TVKParty"},
                ],
            },
        }
    }

    assert bot_main.extract_hashtags(config) == [
        {"id": "tvk", "query": "#TVK"},
        {"id": "hashtag_TVKParty", "query": "#TVKParty"},
    ]
    assert bot_main.extract_hashtags({"settings": {"hashtag_search": {"enabled": False, "queries": ["#TVK"]}}}) == []
    assert bot_main.extract_hashtags({}) == [{"id": "hashtag_tvk", "query": "#TVK"}]
    assert bot_main.resolve_max_posts_per_account({}) == 3
    assert bot_main.resolve_max_posts_per_run({}) == 10

    picks, truncated = bot_main.select_tweets_for_posting(
        [
            _media_tweet("new", now_ts - 10),
            _media_tweet("older", now_ts - 20),
            _media_tweet("oldest", now_ts - 30),
        ],
        "test_feed",
        {"global_posted_ids": []},
        60,
        now_ts,
        2,
        return_backlog=True,
    )
    assert [tweet[0]["id"] for tweet in picks] == ["new", "older"]
    assert truncated is True

    previous_run = now_ts - 4 * 60 * 60
    effective = bot_main.resolve_effective_lookback(
        {"settings": {"post_window_minutes": 60}},
        {"last_run_ts": previous_run},
        now_ts=now_ts,
    )
    assert effective == 245  # four hours plus five minutes of clock slack

    capped = bot_main.resolve_effective_lookback(
        {"settings": {"post_window_minutes": 60, "max_lookback_minutes": 120}},
        {"last_run_ts": previous_run},
        now_ts=now_ts,
    )
    assert capped == 120

    monkeypatch.setenv("MAX_POSTS_PER_ACCOUNT", "2")
    assert bot_main.resolve_max_posts_per_account({"settings": {"max_posts_per_account": 3}}) == 2


def test_fxtwitter_hashtag_search_parses_posts_and_uses_latest_feed():
    fetcher = TwitterFetcher(enable_guest_gql=False, enable_syndication=False)
    session = MagicMock()
    session.get.return_value = _response(payload={
        "code": 200,
        "results": [{
            "type": "status",
            "id": "2121061779321303888",
            "text": "TVK rally video #TVK",
            "created_timestamp": 1794550000,
            "author": {"id": "100", "screen_name": "NewsUser"},
            "media": {"videos": [{
                "url": "https://video.twimg.com/tvk.mp4",
                "thumbnail_url": "https://pbs.twimg.com/tvk.jpg",
            }]},
        }],
    })
    fetcher.session = session

    tweets, source = asyncio.run(fetcher.asearch_tweets("#TVK", limit=7))

    assert source == "fxtwitter-search"
    assert len(tweets) == 1
    assert tweets[0]["text"] == "TVK rally video #TVK"
    assert tweets[0]["has_video"] is True
    assert tweets[0]["video_url"] == "https://video.twimg.com/tvk.mp4"
    call = session.get.call_args
    assert call.args[0].endswith("/2/search")
    assert call.kwargs["params"] == {"q": "#TVK", "feed": "latest", "count": 7}


def test_hashtag_search_falls_back_to_cookie_authenticated_twifork(monkeypatch):
    requested = {}
    fake_twikit = types.ModuleType("twikit")

    class _FakeClient:
        def __init__(self, language):
            self.language = language
            self.cookies = None

        def set_cookies(self, cookies):
            self.cookies = cookies

        async def search_tweet(self, query, product, count=20):
            requested.update(query=query, product=product, count=count)
            media = types.SimpleNamespace(
                type="photo",
                source_url="https://pbs.twimg.com/media/search.jpg?name=orig",
            )
            return [types.SimpleNamespace(
                id="2121061779321303999",
                full_text="Cookie search result #TVK",
                text="Cookie search result #TVK",
                created_at_datetime=datetime(2026, 11, 22, 4, 0, tzinfo=timezone.utc),
                created_at="Sun Nov 22 04:00:00 +0000 2026",
                retweeted_tweet=None,
                quote=None,
                media=[media],
                user=types.SimpleNamespace(screen_name="Reporter"),
            )]

    fake_twikit.Client = _FakeClient
    monkeypatch.setitem(sys.modules, "twikit", fake_twikit)

    fetcher = TwitterFetcher(
        cookies={"auth_token": "test-auth", "ct0": "test-csrf"},
        enable_guest_gql=False,
        enable_syndication=False,
    )
    fetcher._search_fxtwitter = lambda *args: None

    tweets, source = asyncio.run(fetcher.asearch_tweets("#TVK", limit=9))

    assert source == "twikit-search"
    assert tweets[0]["id"] == "2121061779321303999"
    assert tweets[0]["media_url"] == "https://pbs.twimg.com/media/search.jpg?name=orig"
    assert requested == {"query": "#TVK", "product": "Latest", "count": 9}


def test_main_drains_hashtag_and_account_backlog_without_dropping_posts(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    now_ts = 1_800_000_000.0
    monkeypatch.setattr(bot_main.time, "time", lambda: now_ts)

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(bot_main.asyncio, "sleep", _no_sleep)

    news_posts = [
        _media_tweet("news_video", now_ts - 30, video=True),
        _media_tweet("news_image_1", now_ts - 45),
        _media_tweet("news_image_2", now_ts - 60),
    ]
    hashtag_posts = [
        _media_tweet("hashtag_video", now_ts - 35, video=True, author="Reporter"),
        # Duplicate with the account timeline must only be posted once.
        _media_tweet("news_image_1", now_ts - 45, author="NewsUser"),
    ]
    search_calls = []

    class _FakeFetcher:
        def __init__(self, user_id_cache=None, cookies=None, include_retweets=True):
            pass

        async def afetch_user_tweets(self, username, limit=20):
            assert username == "NewsUser"
            return news_posts, "fxtwitter-profile"

        async def asearch_tweets(self, query, limit=40, media_only=False):
            search_calls.append((query, limit, media_only))
            return hashtag_posts, "fxtwitter-search"

    monkeypatch.setattr(bot_main, "TwitterFetcher", _FakeFetcher)

    download_count = 0

    def _fake_download(url, is_video=False, tweet_link=None):
        nonlocal download_count
        download_count += 1
        suffix = ".mp4" if is_video else ".jpg"
        path = tmp_path / f"temp_media_{download_count}{suffix}"
        path.write_bytes(b"fake-media")
        return str(path)

    monkeypatch.setattr(bot_main, "download_media", _fake_download)

    facebook_calls = []

    def _fake_facebook(page_id, token, message, media_path=None, is_video=False, is_sched=False, sched_time=None):
        facebook_calls.append({"is_video": is_video, "is_sched": is_sched, "sched_time": sched_time})
        return {"id": f"fb_{len(facebook_calls)}"}

    monkeypatch.setattr(bot_main, "post_facebook", _fake_facebook)

    config = {
        "twitter_accounts": [{"id": "news", "username": "NewsUser"}],
        "facebook": {"page_id": "page", "access_token": "token"},
        "instagram": {"enabled": False},
        "settings": {
            "post_window_minutes": 60,
            "max_lookback_minutes": 1440,
            "max_posts_per_account": 3,
            "max_posts_per_run": 2,
            "schedule_gap_minutes": 10,
            "hashtag_search": {
                "enabled": True,
                "queries": [{"id": "tvk_search", "query": "#TVK"}],
                "limit": 12,
                "media_only": False,
            },
        },
        "youtube_restream": {"enabled": False},
    }
    Path("config.json").write_text(json.dumps(config), encoding="utf-8")

    # First run posts two videos and keeps the previous watermark because two more items remain.
    asyncio.run(bot_main.main_async())
    state_after_first_run = json.loads(Path("state.json").read_text(encoding="utf-8"))
    assert len(facebook_calls) == 2
    assert state_after_first_run["last_run_ts"] == now_ts - 3600
    assert len(state_after_first_run["global_posted_ids"]) == 2

    # The second run sees the same source window, filters already-posted IDs, and drains the rest.
    asyncio.run(bot_main.main_async())
    saved_state = json.loads(Path("state.json").read_text(encoding="utf-8"))
    report = json.loads(Path("run_report.json").read_text(encoding="utf-8"))

    assert len(facebook_calls) == 4
    assert facebook_calls[0]["is_sched"] is False
    assert facebook_calls[1]["is_sched"] is True
    assert facebook_calls[1]["sched_time"] == int(now_ts) + 1200
    assert facebook_calls[2]["is_sched"] is False
    assert facebook_calls[3]["is_sched"] is True
    assert facebook_calls[3]["sched_time"] == int(now_ts) + 1200
    assert len(saved_state["global_posted_ids"]) == 4
    assert saved_state["last_run_ts"] == now_ts
    assert search_calls == [("#TVK", 12, False), ("#TVK", 12, False)]
    assert report["accounts_checked"] == 1
    assert report["searches_checked"] == 1
    assert report["hashtag_queries"] == ["#TVK"]
    assert report["fetch_sources"]["#TVK"] == "fxtwitter-search"
    assert report["new_posts_found"] == 2
