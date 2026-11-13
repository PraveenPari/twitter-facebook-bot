import asyncio
import json
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure repository root is importable regardless of pytest invocation cwd
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import twitter_fetcher
from twitter_fetcher import (
    TwitterFetcher,
    UserSuspendedError,
    _select_best_mp4_format,
    parse_cookie_input,
    parse_timestamp,
    snowflake_to_timestamp,
)
import main as bot_main


# ---------------------------------------------------------------------------
# Helpers & Utilities
# ---------------------------------------------------------------------------

def _make_response(status_code=200, json_data=None, text="", headers=None, content=b""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.text = text
    resp.content = content
    if json_data is not None:
        resp.json.return_value = json_data
        if not text:
            resp.text = json.dumps(json_data)
    else:
        resp.json.side_effect = ValueError("No JSON")
    resp.iter_content.return_value = [content] if content else []
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


# ---------------------------------------------------------------------------
# Unit Tests: Timestamp, Cookie & Format Selection
# ---------------------------------------------------------------------------

def test_snowflake_and_timestamp_parsing():
    # Twitter snowflake for 2026-11-13-ish
    tid = "2121061779321303266"
    sf_ts = snowflake_to_timestamp(tid)
    assert sf_ts is not None
    assert sf_ts > 1700000000

    assert snowflake_to_timestamp("invalid") is None
    assert snowflake_to_timestamp("12345") is None

    # Standard Twitter timestamp
    ts_std = parse_timestamp("Fri Nov 13 03:25:30 +0000 2026")
    assert ts_std == datetime(2026, 11, 13, 3, 25, 30, tzinfo=timezone.utc).timestamp()

    # ISO-8601
    ts_iso = parse_timestamp("2026-11-13T03:25:30Z")
    assert ts_iso == ts_std

    # RFC 2822 RSS pubDate
    ts_rss = parse_timestamp("Fri, 13 Nov 2026 03:25:30 GMT")
    assert ts_rss == ts_std

    # Legacy Nitter timestamp format
    ts_nitter = parse_timestamp("Nov 13, 2026 · 03:25 AM")
    assert ts_nitter == datetime(2026, 11, 13, 3, 25, 0, tzinfo=timezone.utc).timestamp()

    # Fallback to snowflake when date string is empty/unparseable
    assert parse_timestamp("not-a-date", tid) == pytest.approx(sf_ts, rel=1e-6)


def test_parse_cookie_input_variants():
    assert parse_cookie_input({"auth_token": "abc", "ct0": "xyz"}) == {
        "auth_token": "abc",
        "ct0": "xyz",
    }
    assert parse_cookie_input([
        {"name": "auth_token", "value": "abc", "domain": ".x.com"},
        {"name": "ct0", "value": "xyz"},
    ]) == {"auth_token": "abc", "ct0": "xyz"}
    assert parse_cookie_input('{"auth_token": "abc", "ct0": "xyz"}') == {
        "auth_token": "abc",
        "ct0": "xyz",
    }
    assert parse_cookie_input('[{"name":"auth_token","value":"abc"}]') == {
        "auth_token": "abc",
    }
    assert parse_cookie_input("auth_token=abc; ct0=xyz; Path=/") == {
        "auth_token": "abc",
        "ct0": "xyz",
        "Path": "/",
    }
    assert parse_cookie_input("") == {}
    assert parse_cookie_input(None) == {}


def test_select_best_mp4_format():
    formats = [
        {"url": "https://video.twimg.com/ext/pl.m3u8", "container": "m3u8"},
        {"url": "https://video.twimg.com/ext/low.mp4", "container": "mp4", "codec": "h264", "bitrate": 632000, "size": 5_000_000},
        {"url": "https://video.twimg.com/ext/hd.mp4", "container": "mp4", "codec": "h264", "bitrate": 2176000, "size": 25_000_000},
        {"url": "https://video.twimg.com/ext/hevc.mp4", "container": "mp4", "codec": "hevc", "bitrate": 5000000, "size": 30_000_000},
        {"url": "https://video.twimg.com/ext/huge.mp4", "container": "mp4", "codec": "h264", "bitrate": 15000000, "size": 150_000_000},
    ]
    assert _select_best_mp4_format(formats) == "https://video.twimg.com/ext/hd.mp4"

    # When every MP4 exceeds 100 MB, choose smallest bitrate to stay uploadable
    oversized = [
        {"url": "https://video.twimg.com/ext/a.mp4", "container": "mp4", "bitrate": 9000000, "size": 120_000_000},
        {"url": "https://video.twimg.com/ext/b.mp4", "container": "mp4", "bitrate": 2000000, "size": 105_000_000},
    ]
    assert _select_best_mp4_format(oversized) == "https://video.twimg.com/ext/b.mp4"

    # Non-m3u8 fallback when formats empty
    assert _select_best_mp4_format([], fallback_url="https://video.twimg.com/ext/direct.mp4") == "https://video.twimg.com/ext/direct.mp4"
    assert _select_best_mp4_format([], fallback_url="https://video.twimg.com/ext/stream.m3u8") is None


# ---------------------------------------------------------------------------
# TwitterFetcher Channel Tests
# ---------------------------------------------------------------------------

def test_fxtwitter_profile_cached_id_and_quote_fallback():
    cache = {"tvkvijayhq": "1752702274466680832"}
    fetcher = TwitterFetcher(user_id_cache=cache, enable_guest_gql=False, enable_syndication=False)

    mock_session = MagicMock()
    payload = {
        "code": 200,
        "results": [
            {
                "type": "status",
                "id": "2121061779321303266",
                "url": "https://x.com/TVKVijayHQ/status/2121061779321303266",
                "text": "Video speech update",
                "created_timestamp": 1794540000,
                "author": {"id": "1752702274466680832", "screen_name": "TVKVijayHQ"},
                "media": {
                    "videos": [
                        {
                            "url": "https://video.twimg.com/vid_720.mp4",
                            "thumbnail_url": "https://pbs.twimg.com/thumb.jpg",
                            "duration": 42.5,
                            "formats": [
                                {"url": "https://video.twimg.com/vid_320.mp4", "container": "mp4", "codec": "h264", "bitrate": 632000},
                                {"url": "https://video.twimg.com/vid_720.mp4", "container": "mp4", "codec": "h264", "bitrate": 2176000},
                            ],
                        }
                    ]
                },
            },
            {
                "type": "status",
                "id": "2120900000000000000",
                "url": "https://x.com/TVKVijayHQ/status/2120900000000000000",
                "text": "Quoting photo announcement",
                "created_timestamp": 1794530000,
                "author": {"id": "1752702274466680832", "screen_name": "TVKVijayHQ"},
                "media": None,
                "quote": {
                    "type": "status",
                    "media": {"photos": [{"url": "https://pbs.twimg.com/media/QuoteImg.jpg"}]},
                },
            },
        ],
    }
    mock_session.get.return_value = _make_response(200, payload)
    fetcher.session = mock_session

    tweets, source = fetcher.fetch_user_tweets("TVKVijayHQ", limit=10)
    assert source == "fxtwitter-profile"
    assert len(tweets) == 2

    # First hit used cached id:1752702274466680832
    called_url = mock_session.get.call_args_list[0][0][0]
    assert "/2/profile/id:1752702274466680832/statuses" in called_url

    assert tweets[0]["has_video"] is True
    assert tweets[0]["video_url"] == "https://video.twimg.com/vid_720.mp4"
    assert tweets[1]["has_video"] is False
    assert tweets[1]["media_url"] == "https://pbs.twimg.com/media/QuoteImg.jpg?name=orig"


def test_fxtwitter_profile_stale_id_falls_back_to_search_and_filters_replies():
    cache = {"tvkpartyhq": "9999999999"}
    fetcher = TwitterFetcher(user_id_cache=cache, enable_guest_gql=False, enable_syndication=False)

    mock_session = MagicMock()

    def _side_effect(url, **kwargs):
        if "/2/profile/id:9999999999/statuses" in url:
            return _make_response(404, {"code": 404, "message": "User not found"})
        if "/2/profile/TVKPartyHQ/statuses" in url:
            return _make_response(404, {"code": 404, "message": "User not found"})
        if "/2/search" in url:
            return _make_response(200, {
                "code": 200,
                "results": [
                    # Reply to someone else -> filtered out
                    {
                        "type": "status",
                        "id": "2121061000000000001",
                        "text": "@otheruser thanks",
                        "created_timestamp": 1794541000,
                        "author": {"id": "1754106652066979840", "screen_name": "TVKPartyHQ"},
                        "replying_to": {"screen_name": "otheruser"},
                        "media": {"photos": [{"url": "https://pbs.twimg.com/media/Reply.jpg"}]},
                    },
                    # Self-reply thread -> retained
                    {
                        "type": "status",
                        "id": "2121061000000000002",
                        "text": "Thread part 2",
                        "created_timestamp": 1794542000,
                        "author": {"id": "1754106652066979840", "screen_name": "TVKPartyHQ"},
                        "replying_to": {"screen_name": "TVKPartyHQ"},
                        "media": {"photos": [{"url": "https://pbs.twimg.com/media/Thread2.jpg"}]},
                    },
                    # Retweet -> retained and caches reposted_by ID rather than original author ID
                    {
                        "type": "status",
                        "id": "2121061000000000003",
                        "text": "RT official update",
                        "created_timestamp": 1794543000,
                        "author": {"id": "11111111", "screen_name": "SomeoneElse"},
                        "reposted_by": {"id": "1754106652066979840", "screen_name": "TVKPartyHQ"},
                        "media": {"photos": [{"url": "https://pbs.twimg.com/media/RT.jpg"}]},
                    },
                ],
            })
        raise AssertionError(f"Unexpected URL: {url}")

    mock_session.get.side_effect = _side_effect
    fetcher.session = mock_session

    tweets, source = fetcher.fetch_user_tweets("TVKPartyHQ", limit=10)
    assert source == "fxtwitter-search"
    assert [t["id"] for t in tweets] == ["2121061000000000003", "2121061000000000002"]
    assert tweets[0]["is_retweet"] is True
    assert cache["tvkpartyhq"] == "1754106652066979840"


def test_fxtwitter_suspended_account_stops_immediately():
    fetcher = TwitterFetcher(enable_guest_gql=True, enable_syndication=True)
    mock_session = MagicMock()

    def _side_effect(url, **kwargs):
        if "/2/profile/TVKVijay24x7/statuses" in url:
            return _make_response(404, {"code": 404, "message": "User is suspended", "reason": "suspended"})
        raise AssertionError(f"Should not call fallback after UserSuspendedError: {url}")

    mock_session.get.side_effect = _side_effect
    fetcher.session = mock_session

    tweets, source = fetcher.fetch_user_tweets("TVKVijay24x7")
    assert tweets == []
    assert source == "suspended"


def test_fxtwitter_empty_search_falls_through_to_rss(monkeypatch):
    monkeypatch.setattr(twitter_fetcher.time, "sleep", lambda _: None)
    fetcher = TwitterFetcher(enable_guest_gql=False, enable_syndication=False)
    mock_session = MagicMock()

    rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
      <channel>
        <title>Test Feed</title>
        <item>
          <title>Photo Tweet</title>
          <link>https://x.com/VijayFansTrends/status/2121061779321303999</link>
          <guid>https://x.com/VijayFansTrends/status/2121061779321303999</guid>
          <pubDate>Fri, 13 Nov 2026 04:00:00 GMT</pubDate>
          <description><![CDATA[<p>Rally photos!</p>]]></description>
          <enclosure url="https://pbs.twimg.com/media/Rally.jpg" type="image/jpeg" length="12345" />
        </item>
        <item>
          <title>Video Tweet</title>
          <link>https://x.com/VijayFansTrends/status/2121061779321304000</link>
          <guid>https://x.com/VijayFansTrends/status/2121061779321304000</guid>
          <pubDate>Fri, 13 Nov 2026 04:10:00 GMT</pubDate>
          <description><![CDATA[<p>Stage video!</p>]]></description>
          <enclosure url="https://video.twimg.com/rally.mp4" type="video/mp4" length="99999" />
          <media:thumbnail url="https://pbs.twimg.com/thumb_vid.jpg" />
        </item>
      </channel>
    </rss>"""

    def _side_effect(url, **kwargs):
        if "/2/profile/VijayFansTrends/statuses" in url:
            return _make_response(404, {"code": 404, "message": "User not found"})
        if "/2/search" in url:
            # Search shadowbanned -> empty results
            return _make_response(200, {"code": 200, "results": []})
        if "/2/profile/VijayFansTrends" in url:
            return _make_response(200, {"code": 200, "user": {"screen_name": "VijayFansTrends"}})
        if "feed.xml" in url:
            return _make_response(200, text=rss_xml)
        raise AssertionError(f"Unexpected URL: {url}")

    mock_session.get.side_effect = _side_effect
    fetcher.session = mock_session

    tweets, source = fetcher.fetch_user_tweets("VijayFansTrends", limit=10)
    assert source == "fxtwitter-rss"
    assert len(tweets) == 2
    assert tweets[0]["id"] == "2121061779321304000"
    assert tweets[0]["has_video"] is True
    assert tweets[0]["video_url"] == "https://video.twimg.com/rally.mp4"
    assert tweets[0]["media_url"] == "https://pbs.twimg.com/thumb_vid.jpg"
    assert tweets[1]["has_video"] is False
    assert tweets[1]["media_url"] == "https://pbs.twimg.com/media/Rally.jpg?name=orig"


def test_twikit_cookies_channel(monkeypatch):
    # Inject fake twikit module if needed or monkeypatch Client
    fake_twikit = types.ModuleType("twikit")

    class _FakeStream:
        def __init__(self, url, bitrate, content_type):
            self.url = url
            self.bitrate = bitrate
            self.content_type = content_type

    class _FakeMedia:
        def __init__(self, mtype, **kw):
            self.type = mtype
            for k, v in kw.items():
                setattr(self, k, v)

    class _FakeTweet:
        def __init__(self, tid, text, dt, media, user_handle="TVKVijayHQ"):
            self.id = tid
            self.full_text = text
            self.text = text
            self.created_at_datetime = dt
            self.created_at = "Fri Nov 13 04:00:00 +0000 2026"
            self.retweeted_tweet = None
            self.quote = None
            self.media = media
            self.user = types.SimpleNamespace(screen_name=user_handle)

    class _FakeClient:
        def __init__(self, lang):
            self.cookies = None

        def set_cookies(self, cookies):
            self.cookies = cookies

        async def get_user_by_screen_name(self, username):
            return types.SimpleNamespace(id="1752702274466680832", pinned_tweet_ids=["2120000000000000001"])

        async def get_user_tweets(self, user_id, tab, count=20):
            return [
                _FakeTweet(
                    "2120000000000000001",
                    "Pinned tweet",
                    datetime(2026, 11, 13, 1, 0, tzinfo=timezone.utc),
                    [_FakeMedia("photo", source_url="https://pbs.twimg.com/media/Pin.jpg?name=orig")],
                ),
                _FakeTweet(
                    "2121061779321303888",
                    "Fresh video",
                    datetime(2026, 11, 13, 4, 20, tzinfo=timezone.utc),
                    [
                        _FakeMedia(
                            "video",
                            duration_millis=15000,
                            media_url="https://pbs.twimg.com/thumb.jpg",
                            streams=[
                                _FakeStream("https://video.twimg.com/hi.mp4", 2176000, "video/mp4"),
                            ],
                        )
                    ],
                ),
            ]

    fake_twikit.Client = _FakeClient
    monkeypatch.setitem(sys.modules, "twikit", fake_twikit)
    monkeypatch.setattr(twitter_fetcher.time, "sleep", lambda _: None)

    cache = {}
    fetcher = TwitterFetcher(
        user_id_cache=cache,
        cookies={"auth_token": "tok", "ct0": "csrf"},
        enable_guest_gql=False,
        enable_syndication=False,
    )
    mock_session = MagicMock()
    mock_session.get.return_value = _make_response(503, text="unavailable")
    fetcher.session = mock_session

    tweets, source = fetcher.fetch_user_tweets("TVKVijayHQ", limit=10)
    assert source == "twikit-cookies"
    assert len(tweets) == 2
    assert tweets[0]["id"] == "2121061779321303888"
    assert tweets[0]["has_video"] is True
    assert tweets[0]["video_url"] == "https://video.twimg.com/hi.mp4"
    assert tweets[0]["is_pinned"] is False
    assert tweets[1]["id"] == "2120000000000000001"
    assert tweets[1]["is_pinned"] is True
    assert cache["tvkvijayhq"] == "1752702274466680832"


def test_x_guest_graphql_channel(monkeypatch):
    monkeypatch.setattr(twitter_fetcher.time, "sleep", lambda _: None)
    cache = {}
    fetcher = TwitterFetcher(user_id_cache=cache, enable_guest_gql=True, enable_syndication=False)
    mock_session = MagicMock()

    mock_session.post.return_value = _make_response(200, {"guest_token": "gt-123"})

    gql_tweets_payload = {
        "data": {
            "user": {
                "result": {
                    "timeline_v2": {
                        "timeline": {
                            "instructions": [
                                {
                                    "type": "TimelinePinEntry",
                                    "entry": {
                                        "content": {
                                            "itemContent": {
                                                "tweet_results": {
                                                    "result": {
                                                        "rest_id": "2120000000000000002",
                                                        "legacy": {
                                                            "id_str": "2120000000000000002",
                                                            "full_text": "Pinned announcement",
                                                            "created_at": "Fri Nov 13 01:00:00 +0000 2026",
                                                            "extended_entities": {
                                                                "media": [
                                                                    {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/Pin2.jpg"}
                                                                ]
                                                            },
                                                        },
                                                    }
                                                }
                                            }
                                        }
                                    },
                                },
                                {
                                    "type": "TimelineAddEntries",
                                    "entries": [
                                        {
                                            "entryId": "tweet-2121061779321303777",
                                            "content": {
                                                "itemContent": {
                                                    "tweet_results": {
                                                        "result": {
                                                            "rest_id": "2121061779321303777",
                                                            "core": {
                                                                "user_results": {
                                                                    "result": {"core": {"screen_name": "BossTVK"}}
                                                                }
                                                            },
                                                            "note_tweet": {
                                                                "note_tweet_results": {
                                                                    "result": {"text": "Long form note tweet text"}
                                                                }
                                                            },
                                                            "legacy": {
                                                                "id_str": "2121061779321303777",
                                                                "full_text": "Short truncated...",
                                                                "created_at": "Fri Nov 13 04:30:00 +0000 2026",
                                                                "extended_entities": {
                                                                    "media": [
                                                                        {
                                                                            "type": "video",
                                                                            "media_url_https": "https://pbs.twimg.com/vid_thumb.jpg",
                                                                            "video_info": {
                                                                                "duration_millis": 12000,
                                                                                "variants": [
                                                                                    {"content_type": "video/mp4", "bitrate": 832000, "url": "https://video.twimg.com/gql_832.mp4"},
                                                                                ],
                                                                            },
                                                                        }
                                                                    ]
                                                                },
                                                            },
                                                        }
                                                    }
                                                }
                                            },
                                        }
                                    ],
                                },
                            ]
                        }
                    }
                }
            }
        }
    }

    def _get_side_effect(url, **kwargs):
        if "api.fxtwitter.com" in url or "fxtwitter.com" in url:
            return _make_response(503, text="down")
        if "UserByScreenName" in url:
            return _make_response(200, {"data": {"user": {"result": {"rest_id": "555666777"}}}})
        if "UserTweets" in url:
            return _make_response(200, gql_tweets_payload)
        raise AssertionError(f"Unexpected URL: {url}")

    mock_session.get.side_effect = _get_side_effect
    fetcher.session = mock_session

    tweets, source = fetcher.fetch_user_tweets("BossTVK", limit=10)
    assert source == "x-guest-graphql"
    assert cache["bosstvk"] == "555666777"
    assert len(tweets) == 2
    assert tweets[0]["id"] == "2121061779321303777"
    assert tweets[0]["text"] == "Long form note tweet text"
    assert tweets[0]["video_url"] == "https://video.twimg.com/gql_832.mp4"
    assert tweets[0]["is_pinned"] is False
    assert tweets[1]["is_pinned"] is True


def test_x_syndication_channel(monkeypatch):
    monkeypatch.setattr(twitter_fetcher.time, "sleep", lambda _: None)
    cache = {}
    fetcher = TwitterFetcher(user_id_cache=cache, enable_guest_gql=False, enable_syndication=True)
    mock_session = MagicMock()

    next_data = {
        "props": {
            "pageProps": {
                "timeline": {
                    "entries": [
                        {
                            "content": {
                                "tweet": {
                                    "id_str": "2121061779321303555",
                                    "full_text": "Syndication photo post",
                                    "created_at": "Fri Nov 13 04:45:00 +0000 2026",
                                    "user": {"id_str": "888999", "screen_name": "arunraajkg"},
                                    "mediaDetails": [
                                        {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/Syn.jpg"}
                                    ],
                                }
                            }
                        }
                    ]
                }
            }
        }
    }
    html = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script></html>'

    def _get_side_effect(url, **kwargs):
        if "syndication.twitter.com" in url:
            return _make_response(200, text=html)
        return _make_response(503, text="down")

    mock_session.get.side_effect = _get_side_effect
    fetcher.session = mock_session

    tweets, source = fetcher.fetch_user_tweets("arunraajkg", limit=10)
    assert source == "x-syndication"
    assert len(tweets) == 1
    assert tweets[0]["media_url"] == "https://pbs.twimg.com/media/Syn.jpg?name=orig"
    assert cache["arunraajkg"] == "888999"


# ---------------------------------------------------------------------------
# main.py Helpers & Integration Tests
# ---------------------------------------------------------------------------

def test_main_helpers_and_lookback_window(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    # clean_text strips URLs, nitter, leading @mentions
    cleaned = bot_main.clean_text("@user1 @user2 Big rally today! https://t.co/abc pic.x.com/xyz")
    assert cleaned == "Big rally today!"

    # extract_username handles @ and legacy nitter URLs
    assert bot_main.extract_username({"username": " @TVKVijayHQ "}) == "TVKVijayHQ"
    assert bot_main.extract_username({"url": "https://nitter.net/TVKPartyHQ/rss"}) == "TVKPartyHQ"

    # Lookback resolution preserves 60-min floor for legacy 10-min template
    monkeypatch.delenv("POST_WINDOW_MINUTES", raising=False)
    assert bot_main.resolve_lookback_minutes({"settings": {"post_window_minutes": 10}}) == 60.0
    assert bot_main.resolve_lookback_minutes({"settings": {"lookback_minutes": 120}}) == 120.0
    monkeypatch.setenv("POST_WINDOW_MINUTES", "25")
    assert bot_main.resolve_lookback_minutes({"settings": {"post_window_minutes": 60}}) == 25.0
    monkeypatch.delenv("POST_WINDOW_MINUTES", raising=False)

    # Window check
    now = 1794550000.0
    fresh_tweet = {"id": "1", "created_timestamp": now - 600}
    old_tweet = {"id": "2", "created_timestamp": now - 7200}
    assert bot_main.is_tweet_within_window(fresh_tweet, 3600, now_ts=now)[0] is True
    assert bot_main.is_tweet_within_window(old_tweet, 3600, now_ts=now)[0] is False

    # State migration & duplicate tracking
    Path("state.json").write_text(json.dumps({"last_posted_ids": {"acc1": "t_old"}}), encoding="utf-8")
    state = bot_main.load_state()
    assert state["posted_tweet_ids"] == {}
    assert state["user_ids"] == {}
    assert bot_main.is_already_posted(state, "acc1", "t_old") is True

    bot_main.record_posted_tweet(state, "acc1", "t_new")
    assert bot_main.is_already_posted(state, "acc1", "t_new") is True
    # Global cross-account dedup catches retweets of the same tweet ID on another feed
    assert bot_main.is_already_posted(state, "acc2", "t_new") is True


def test_download_media_direct_mp4_and_ytdlp_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(bot_main.tempfile, "gettempdir", lambda: str(tmp_path))

    # 1. Direct MP4 fast path
    fake_bytes = b"\x00\x00\x00\x18ftypmp42" + b"0" * 2048
    monkeypatch.setattr(
        bot_main.requests,
        "get",
        lambda url, **kw: _make_response(200, content=fake_bytes, headers={"Content-Type": "video/mp4"}),
    )
    path = bot_main.download_media("https://video.twimg.com/ext_tw_video/1/pu/vid/test.mp4", is_video=True)
    assert path is not None
    assert Path(path).exists()
    assert Path(path).read_bytes() == fake_bytes

    # 2. Direct MP4 fails -> yt-dlp fallback
    monkeypatch.setattr(
        bot_main.requests,
        "get",
        lambda url, **kw: _make_response(403),
    )

    fallback_file = tmp_path / "temp_ytdlp_999.mp4"

    class _FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=True):
            assert url == "https://x.com/TVKVijayHQ/status/999"
            fallback_file.write_bytes(b"ytdlp-video-bytes" * 100)
            return {"id": "999"}

        def prepare_filename(self, info):
            return str(fallback_file)

    monkeypatch.setattr(bot_main.yt_dlp, "YoutubeDL", _FakeYDL)
    fb_path = bot_main.download_media(
        "https://video.twimg.com/broken.mp4",
        is_video=True,
        tweet_link="https://x.com/TVKVijayHQ/status/999",
    )
    assert fb_path == str(fallback_file)


def test_main_async_end_to_end(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bot_main.tempfile, "gettempdir", lambda: str(tmp_path))

    now_ts = 1794550000.0
    monkeypatch.setattr(bot_main.time, "time", lambda: now_ts)

    config = {
        "twitter_accounts": [
            {"id": "vijay_hq", "username": "TVKVijayHQ"},
            {"id": "party_hq", "username": "TVKPartyHQ"},
            {"id": "it_wing", "username": "TVKHQITWingOffl"},
            {"id": "suspended_acc", "username": "TVKVijay24x7"},
        ],
        "facebook": {"page_id": "fb_page_1", "access_token": "fb_tok"},
        "instagram": {"enabled": True, "user_id": "ig_user_1", "access_token": "ig_tok"},
        "settings": {"post_window_minutes": 10, "schedule_gap_minutes": 15},
        "youtube_restream": {"enabled": False},
    }
    Path("config.json").write_text(json.dumps(config), encoding="utf-8")

    # Fake fetcher returning:
    # - TVKVijayHQ: fresh photo tweet
    # - TVKPartyHQ: fresh video tweet (should be prioritized BEFORE image!)
    # - TVKHQITWingOffl: retweet of TVKPartyHQ's exact video tweet ID (should be deduplicated!)
    # - TVKVijay24x7: suspended
    class _FakeFetcher:
        def __init__(self, user_id_cache=None, cookies=None, include_retweets=True):
            self.user_id_cache = user_id_cache if user_id_cache is not None else {}

        async def afetch_user_tweets(self, username, limit=20):
            if username == "TVKVijayHQ":
                self.user_id_cache["tvkvijayhq"] = "1752702274466680832"
                return ([
                    {
                        "id": "2121000000000000010",
                        "text": "Fresh photo post https://t.co/abc",
                        "link": "https://x.com/TVKVijayHQ/status/2121000000000000010",
                        "media_url": "https://pbs.twimg.com/media/Photo.jpg?name=orig",
                        "video_url": None,
                        "has_video": False,
                        "created_timestamp": now_ts - 300,
                        "date_str": "2026-11-13 05:00:00 UTC",
                        "is_pinned": False,
                        "is_retweet": False,
                        "source": "fxtwitter-profile",
                    }
                ], "fxtwitter-profile")
            if username == "TVKPartyHQ":
                self.user_id_cache["tvkpartyhq"] = "1754106652066979840"
                return ([
                    {
                        "id": "2121000000000000020",
                        "text": "Fresh video post",
                        "link": "https://x.com/TVKPartyHQ/status/2121000000000000020",
                        "media_url": "https://pbs.twimg.com/thumb.jpg",
                        "video_url": "https://video.twimg.com/party.mp4",
                        "has_video": True,
                        "created_timestamp": now_ts - 600,
                        "date_str": "2026-11-13 04:55:00 UTC",
                        "is_pinned": False,
                        "is_retweet": False,
                        "source": "fxtwitter-search",
                    }
                ], "fxtwitter-search")
            if username == "TVKHQITWingOffl":
                return ([
                    {
                        "id": "2121000000000000020",  # Same ID as TVKPartyHQ's original tweet
                        "text": "Fresh video post",
                        "link": "https://x.com/TVKPartyHQ/status/2121000000000000020",
                        "media_url": "https://pbs.twimg.com/thumb.jpg",
                        "video_url": "https://video.twimg.com/party.mp4",
                        "has_video": True,
                        "created_timestamp": now_ts - 600,
                        "date_str": "2026-11-13 04:55:00 UTC",
                        "is_pinned": False,
                        "is_retweet": True,
                        "source": "fxtwitter-profile",
                    }
                ], "fxtwitter-profile")
            if username == "TVKVijay24x7":
                return ([], "suspended")
            return ([], "none")

    monkeypatch.setattr(bot_main, "TwitterFetcher", _FakeFetcher)

    def _fake_download(url, is_video=False, tweet_link=None):
        p = tmp_path / ("temp_vid.mp4" if is_video else "temp_img.jpg")
        p.write_bytes(b"media-bytes")
        return str(p)

    monkeypatch.setattr(bot_main, "download_media", _fake_download)

    fb_calls = []
    ig_calls = []

    def _fake_fb(page_id, token, msg, media_path=None, is_video=False, is_sched=False, sched_time=None):
        fb_calls.append({"is_video": is_video, "is_sched": is_sched, "sched_time": sched_time, "msg": msg})
        return {"id": f"fb_{len(fb_calls)}"}

    def _fake_ig(ig_user_id, token, msg, media_path=None, is_video=False, is_sched=False, sched_time=None):
        ig_calls.append({"is_video": is_video, "is_sched": is_sched})
        return {"id": f"ig_{len(ig_calls)}"}

    monkeypatch.setattr(bot_main, "post_facebook", _fake_fb)
    monkeypatch.setattr(bot_main, "post_instagram", _fake_ig)

    asyncio.run(bot_main.main_async())

    # Only 2 posts (not 3, because duplicate retweet ID 2121000000000000020 was deduped)
    # Video prioritized first (immediate), then image (scheduled +20m)
    assert len(fb_calls) == 2
    assert fb_calls[0]["is_video"] is True
    assert fb_calls[0]["is_sched"] is False
    assert fb_calls[1]["is_video"] is False
    assert fb_calls[1]["is_sched"] is True
    assert fb_calls[1]["sched_time"] == int(now_ts) + 1200

    assert len(ig_calls) == 2
    assert ig_calls[0]["is_video"] is True
    assert ig_calls[0]["is_sched"] is False

    # State saved with posted IDs & cached X numeric user IDs
    saved_state = json.loads(Path("state.json").read_text(encoding="utf-8"))
    assert saved_state["last_posted_ids"]["party_hq"] == "2121000000000000020"
    assert saved_state["last_posted_ids"]["vijay_hq"] == "2121000000000000010"
    assert "2121000000000000020" in saved_state["global_posted_ids"]
    assert saved_state["user_ids"]["tvkvijayhq"] == "1752702274466680832"
    assert saved_state["user_ids"]["tvkpartyhq"] == "1754106652066979840"

    # Reports verified
    run_report = json.loads(Path("run_report.json").read_text(encoding="utf-8"))
    assert run_report["accounts_checked"] == 4
    assert run_report["lookback_minutes"] == 60.0
    assert run_report["new_posts_found"] == 2
    assert run_report["suspended_accounts"] == ["TVKVijay24x7"]
    assert run_report["fetch_sources"]["TVKPartyHQ"] == "fxtwitter-search"

    cucumber = json.loads(Path("cucumber_report.json").read_text(encoding="utf-8"))
    assert cucumber[0]["elements"][3]["steps"][0]["result"]["status"] == "skipped"

    # Temp files cleaned up
    assert not (tmp_path / "temp_vid.mp4").exists()
    assert not (tmp_path / "temp_img.jpg").exists()


def test_concurrent_fetcher_thread_safety(monkeypatch):
    cache = {}
    fetcher = TwitterFetcher(user_id_cache=cache, enable_guest_gql=False, enable_syndication=False)

    def _fake_session_get(self, url, **kwargs):
        if "/2/profile/UserA/statuses" in url:
            return _make_response(200, {
                "code": 200,
                "results": [{
                    "type": "status",
                    "id": "2121061779321303101",
                    "text": "Tweet A",
                    "created_timestamp": 1794540000,
                    "author": {"id": "101", "screen_name": "UserA"},
                    "media": {"photos": [{"url": "https://pbs.twimg.com/media/A.jpg"}]},
                }],
            })
        if "/2/profile/UserB/statuses" in url:
            return _make_response(200, {
                "code": 200,
                "results": [{
                    "type": "status",
                    "id": "2121061779321303102",
                    "text": "Tweet B",
                    "created_timestamp": 1794540000,
                    "author": {"id": "102", "screen_name": "UserB"},
                    "media": {"photos": [{"url": "https://pbs.twimg.com/media/B.jpg"}]},
                }],
            })
        if "/2/profile/UserC/statuses" in url:
            return _make_response(200, {
                "code": 200,
                "results": [{
                    "type": "status",
                    "id": "2121061779321303103",
                    "text": "Tweet C",
                    "created_timestamp": 1794540000,
                    "author": {"id": "103", "screen_name": "UserC"},
                    "media": {"photos": [{"url": "https://pbs.twimg.com/media/C.jpg"}]},
                }],
            })
        return _make_response(404, {"code": 404})

    monkeypatch.setattr(twitter_fetcher.requests.Session, "get", _fake_session_get)

    async def _run_batch():
        return await asyncio.gather(
            fetcher.afetch_user_tweets("UserA"),
            fetcher.afetch_user_tweets("UserB"),
            fetcher.afetch_user_tweets("UserC"),
        )

    res = asyncio.run(_run_batch())
    assert [src for _, src in res] == ["fxtwitter-profile"] * 3
    assert cache == {"usera": "101", "userb": "102", "userc": "103"}


def test_main_async_schedule_spacing_and_download_failure(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bot_main.tempfile, "gettempdir", lambda: str(tmp_path))

    now_ts = 1794550000.0
    monkeypatch.setattr(bot_main.time, "time", lambda: now_ts)

    config = {
        "twitter_accounts": [
            {"id": "acc_fail_dl", "username": "FailUser"},
            {"id": "acc_1", "username": "User1"},
            {"id": "acc_2", "username": "User2"},
            {"id": "acc_3", "username": "User3"},
        ],
        "facebook": {"page_id": "fb_page_1", "access_token": "fb_tok"},
        "instagram": {"enabled": False},
        "settings": {"post_window_minutes": 60, "schedule_gap_minutes": 15},
    }
    Path("config.json").write_text(json.dumps(config), encoding="utf-8")

    class _FakeFetcher:
        def __init__(self, user_id_cache=None, cookies=None, include_retweets=True):
            pass

        async def afetch_user_tweets(self, username, limit=20):
            idx = {"FailUser": 1, "User1": 2, "User2": 3, "User3": 4}[username]
            return ([
                {
                    "id": f"212100000000000000{idx}",
                    "text": f"Post from {username}",
                    "link": f"https://x.com/{username}/status/212100000000000000{idx}",
                    "media_url": f"https://pbs.twimg.com/media/{username}.jpg",
                    "video_url": None,
                    "has_video": False,
                    "created_timestamp": now_ts - 120,
                    "date_str": "2026-11-13 05:00:00 UTC",
                    "is_pinned": False,
                    "is_retweet": False,
                    "source": "fxtwitter-profile",
                }
            ], "fxtwitter-profile")

    monkeypatch.setattr(bot_main, "TwitterFetcher", _FakeFetcher)

    def _fake_download(url, is_video=False, tweet_link=None):
        if "FailUser" in url:
            return None
        p = tmp_path / f"temp_{Path(url).name}"
        p.write_bytes(b"img-bytes")
        return str(p)

    monkeypatch.setattr(bot_main, "download_media", _fake_download)

    fb_calls = []

    def _fake_fb(page_id, token, msg, media_path=None, is_video=False, is_sched=False, sched_time=None):
        fb_calls.append({"is_sched": is_sched, "sched_time": sched_time})
        return {"id": f"fb_{len(fb_calls)}"}

    monkeypatch.setattr(bot_main, "post_facebook", _fake_fb)

    asyncio.run(bot_main.main_async())

    # FailUser failed download -> User1 promoted to immediate, User2 at +20m, User3 at +35m
    assert len(fb_calls) == 3
    assert fb_calls[0] == {"is_sched": False, "sched_time": None}
    assert fb_calls[1] == {"is_sched": True, "sched_time": int(now_ts) + 1200}
    assert fb_calls[2] == {"is_sched": True, "sched_time": int(now_ts) + 2100}


def test_main_async_exits_nonzero_when_all_reachable_fail(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bot_main.tempfile, "gettempdir", lambda: str(tmp_path))

    async def _noop_sleep(_):
        return None

    monkeypatch.setattr(bot_main.asyncio, "sleep", _noop_sleep)

    config = {
        "twitter_accounts": [{"id": "a1", "username": "User1"}],
        "facebook": {"page_id": "fb_page_1", "access_token": "fb_tok"},
        "instagram": {"enabled": False},
    }
    Path("config.json").write_text(json.dumps(config), encoding="utf-8")

    class _AllFailFetcher:
        def __init__(self, user_id_cache=None, cookies=None, include_retweets=True):
            pass

        async def afetch_user_tweets(self, username, limit=20):
            return [], "none"

    monkeypatch.setattr(bot_main, "TwitterFetcher", _AllFailFetcher)

    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(bot_main.main_async())

    assert exc_info.value.code == 1
    report = json.loads(Path("run_report.json").read_text(encoding="utf-8"))
    assert report["fetch_sources"] == {"User1": "none"}


