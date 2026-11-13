"""
Multi-channel X/Twitter timeline fetcher (replaces Nitter).

Channels tried in order (until one returns tweets or detects a suspended account):
1. FxTwitter v2 API (https://api.fxtwitter.com/2/...) - zero auth, fast, structured JSON
   1a. /2/profile/{id:user_id | handle}/statuses
   1b. /2/search?q=from:{handle}&feed=latest (handles transient profile 404s & renames)
2. FxTwitter RSS Feed (https://fxtwitter.com/{handle}/feed.xml)
3. twikit / twifork (optional, when X cookies are provided via TWITTER_COOKIES or twitter_cookies.json)
4. X Guest GraphQL (api.x.com guest token + x.com/i/api/graphql)
5. X Syndication Embed API (https://syndication.twitter.com/srv/timeline-profile/screen-name/{handle})
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

FXTWITTER_API_BASE = "https://api.fxtwitter.com"
FXTWITTER_WEB_BASE = "https://fxtwitter.com"
SYNDICATION_URL = "https://syndication.twitter.com/srv/timeline-profile/screen-name/{handle}"

# Public X web client bearer token (used for guest activation / GraphQL fallback)
X_WEB_BEARER_TOKEN = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)
X_GQL_BASE = "https://x.com/i/api/graphql"
X_OP_USER_BY_SCREEN = "Gb-d6r0vxPOADdG62OEBpQ/UserByScreenName"
X_OP_USER_TWEETS = "SXVCYB8XHSS25nzIljNtZA/UserTweets"

# Max estimated MP4 size (bytes) to target when choosing a bitrate variant for FB/IG compatibility
MAX_PREFERRED_VIDEO_BYTES = 100 * 1024 * 1024


class UserSuspendedError(Exception):
    """Raised when an X/Twitter account is suspended or deactivated."""


def snowflake_to_timestamp(tweet_id: str | int | None) -> float | None:
    """Decode UTC Unix timestamp (seconds) from a Twitter snowflake ID."""
    if not tweet_id:
        return None
    try:
        tid = int(str(tweet_id).strip())
        if tid < 10**15:
            return None
        return ((tid >> 22) + 1288834974657) / 1000.0
    except (ValueError, TypeError):
        return None


def parse_timestamp(date_str: str | None, tweet_id: str | None = None) -> float | None:
    """Parse common Twitter/RSS/ISO timestamps into UTC Unix seconds."""
    if date_str:
        s = str(date_str).strip()
        # 1. Standard Twitter format: "Fri Nov 13 03:25:30 +0000 2026"
        for fmt in (
            "%a %b %d %H:%M:%S %z %Y",
            "%b %d, %Y · %I:%M %p",
            "%b %d, %Y %I:%M %p",
        ):
            try:
                dt = datetime.strptime(s.replace("UTC", "").strip(), fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc).timestamp()
            except ValueError:
                pass

        # 2. ISO-8601
        try:
            iso = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).timestamp()
        except ValueError:
            pass

        # 3. RFC 2822 (RSS pubDate)
        try:
            dt = parsedate_to_datetime(s)
            if dt is not None:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc).timestamp()
        except (TypeError, ValueError):
            pass

    return snowflake_to_timestamp(tweet_id)


def format_utc_date(ts: float | None, fallback: str = "") -> str:
    if ts is None:
        return fallback
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _select_best_mp4_format(
    formats: list[dict[str, Any]],
    duration_sec: float | None = None,
    fallback_url: str | None = None,
) -> str | None:
    """Pick the best H.264 MP4 URL (preferring <= 100MB for reliable FB/IG upload)."""
    mp4s: list[dict[str, Any]] = []
    for fmt in formats or []:
        if not isinstance(fmt, dict):
            continue
        url = fmt.get("url")
        if not url:
            continue
        container = (fmt.get("container") or "").lower()
        ctype = (fmt.get("content_type") or fmt.get("content-type") or "").lower()
        if container == "mp4" or ctype == "video/mp4" or ".mp4" in url.split("?")[0]:
            mp4s.append(fmt)

    if not mp4s:
        if fallback_url and ".m3u8" not in fallback_url:
            return fallback_url
        return None

    h264 = [
        f for f in mp4s
        if (f.get("codec") or "h264").lower() == "h264"
        or (f.get("codec") or "").lower().startswith("avc1")
    ]
    pool = h264 or mp4s

    def _est_size(fmt: dict[str, Any]) -> float:
        if fmt.get("size"):
            return float(fmt["size"])
        bitrate = fmt.get("bitrate") or 0
        if bitrate and duration_sec:
            return (float(bitrate) * float(duration_sec)) / 8.0
        return 0.0

    under_limit = [f for f in pool if _est_size(f) <= MAX_PREFERRED_VIDEO_BYTES]
    if under_limit:
        best = max(under_limit, key=lambda f: f.get("bitrate") or 0)
    else:
        best = min(pool, key=lambda f: f.get("bitrate") or float("inf"))
    return best.get("url") or fallback_url


def _ensure_orig_image_url(url: str | None) -> str | None:
    if not url:
        return None
    if "pbs.twimg.com/media/" in url and "name=" not in url:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}name=orig"
    return url


def parse_cookie_input(raw: Any) -> dict[str, str]:
    """Normalize dict, browser-export list, JSON string, or HTTP Cookie header string."""
    if not raw:
        return {}
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        if s.startswith("{") or s.startswith("["):
            try:
                raw = json.loads(s)
            except json.JSONDecodeError:
                pass
        if isinstance(raw, str):
            out: dict[str, str] = {}
            for part in raw.split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if k:
                        out[k] = v
            return out
    if isinstance(raw, list):
        return {
            str(item["name"]): str(item["value"])
            for item in raw
            if isinstance(item, dict) and item.get("name") and "value" in item
        }
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items() if v is not None}
    return {}


def _sort_tweets_newest_first(tweets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _sort_key(t: dict[str, Any]) -> tuple[float, int]:
        ts = t.get("created_timestamp")
        if ts is None:
            ts = snowflake_to_timestamp(t.get("id")) or 0.0
        try:
            tid = int(str(t.get("id") or 0))
        except ValueError:
            tid = 0
        return (float(ts), tid)

    deduped: dict[str, dict[str, Any]] = {}
    for t in tweets:
        tid = str(t.get("id") or "").strip()
        if tid and tid not in deduped:
            deduped[tid] = t
    return sorted(deduped.values(), key=_sort_key, reverse=True)


class TwitterFetcher:
    """Fetches public X/Twitter user timelines without Nitter."""

    def __init__(
        self,
        user_id_cache: dict[str, str] | None = None,
        cookies: Any = None,
        timeout: int = 25,
        include_retweets: bool = True,
        enable_guest_gql: bool = True,
        enable_syndication: bool = True,
    ) -> None:
        self.user_id_cache: dict[str, str] = user_id_cache if user_id_cache is not None else {}
        self.timeout = timeout
        self.include_retweets = include_retweets
        self.enable_guest_gql = enable_guest_gql
        self.enable_syndication = enable_syndication

        self._lock = threading.Lock()
        self._thread_local = threading.local()
        self._session_override: requests.Session | None = None

        self._guest_token: str | None = None
        self._guest_failed: bool = False
        self._twikit_client: Any = None
        self._twikit_init_attempted: bool = False
        self._cookies = self._resolve_cookies(cookies)

    def _get_session(self) -> requests.Session:
        if self._session_override is not None:
            return self._session_override
        sess = getattr(self._thread_local, "session", None)
        if sess is None:
            sess = requests.Session()
            sess.headers.update({
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept-Language": "en-US,en;q=0.9",
            })
            self._thread_local.session = sess
        return sess

    @property
    def session(self) -> requests.Session:
        return self._get_session()

    @session.setter
    def session(self, sess: requests.Session | None) -> None:
        self._session_override = sess

    @staticmethod
    def _resolve_cookies(explicit_cookies: Any) -> dict[str, str]:
        if explicit_cookies:
            parsed = parse_cookie_input(explicit_cookies)
            if parsed:
                return parsed
        env_cookies = os.environ.get("TWITTER_COOKIES")
        if env_cookies:
            parsed = parse_cookie_input(env_cookies)
            if parsed:
                return parsed
        for path in ("twitter_cookies.json", "cookies.json"):
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        parsed = parse_cookie_input(json.load(f))
                        if parsed:
                            return parsed
                except Exception as e:
                    logger.warning(f"Failed loading cookies from {path}: {e}")
        return {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def afetch_user_tweets(self, username: str, limit: int = 20) -> tuple[list[dict[str, Any]], str]:
        """Fetch recent tweets for a username using multi-channel fallback (async)."""
        username = username.strip().lstrip("@")
        if not username:
            return [], "invalid_username"

        saw_empty_ok = False

        # 1. FxTwitter v2 Profile Statuses
        try:
            tweets = await asyncio.to_thread(self._fetch_fxtwitter_profile, username, limit)
            if tweets:
                return _sort_tweets_newest_first(tweets), "fxtwitter-profile"
            if tweets == []:
                saw_empty_ok = True
        except UserSuspendedError as e:
            logger.warning(f"[{username}] {e}")
            return [], "suspended"
        except Exception as e:
            logger.debug(f"[{username}] fxtwitter-profile error: {e}")

        # 2. FxTwitter v2 Search Latest (covers transient UserByScreenName 404s & handle renames)
        try:
            tweets = await asyncio.to_thread(self._fetch_fxtwitter_search, username, limit)
            if tweets:
                return _sort_tweets_newest_first(tweets), "fxtwitter-search"
            if tweets == []:
                saw_empty_ok = True
        except UserSuspendedError as e:
            logger.warning(f"[{username}] {e}")
            return [], "suspended"
        except Exception as e:
            logger.debug(f"[{username}] fxtwitter-search error: {e}")

        # 3. FxTwitter RSS feed
        try:
            tweets = await asyncio.to_thread(self._fetch_fxtwitter_rss, username, limit)
            if tweets:
                return _sort_tweets_newest_first(tweets), "fxtwitter-rss"
        except Exception as e:
            logger.debug(f"[{username}] fxtwitter-rss error: {e}")

        # 4. Optional twikit/twifork with user-supplied X cookies
        if self._cookies:
            try:
                tweets = await self._fetch_twikit(username, limit)
                if tweets:
                    return _sort_tweets_newest_first(tweets), "twikit-cookies"
                if tweets == []:
                    saw_empty_ok = True
            except UserSuspendedError as e:
                logger.warning(f"[{username}] {e}")
                return [], "suspended"
            except Exception as e:
                logger.warning(f"[{username}] twikit fallback error: {e}")

        # 5. Direct X Guest GraphQL
        if self.enable_guest_gql:
            try:
                tweets = await asyncio.to_thread(self._fetch_x_guest_graphql, username, limit)
                if tweets:
                    return _sort_tweets_newest_first(tweets), "x-guest-graphql"
            except UserSuspendedError as e:
                logger.warning(f"[{username}] {e}")
                return [], "suspended"
            except Exception as e:
                logger.debug(f"[{username}] x-guest-graphql error: {e}")

        # 6. X Syndication embed endpoint (effective from residential/non-rate-limited IPs)
        if self.enable_syndication:
            try:
                tweets = await asyncio.to_thread(self._fetch_x_syndication, username, limit)
                if tweets:
                    return _sort_tweets_newest_first(tweets), "x-syndication"
            except Exception as e:
                logger.debug(f"[{username}] x-syndication error: {e}")

        return [], ("empty" if saw_empty_ok else "none")

    def fetch_user_tweets(self, username: str, limit: int = 20) -> tuple[list[dict[str, Any]], str]:
        """Synchronous wrapper for afetch_user_tweets."""
        return asyncio.run(self.afetch_user_tweets(username, limit=limit))

    # ------------------------------------------------------------------
    # Channel 1: FxTwitter v2 API
    # ------------------------------------------------------------------

    def _set_cached_user_id(self, username: str, user_id: str) -> None:
        with self._lock:
            self.user_id_cache[username.lower()] = str(user_id)

    def _get_cached_user_id(self, username: str) -> str | None:
        with self._lock:
            return self.user_id_cache.get(username.lower())

    def _pop_cached_user_id(self, username: str) -> None:
        with self._lock:
            self.user_id_cache.pop(username.lower(), None)

    def _cache_user_id_from_fx_item(self, username: str, item: dict[str, Any]) -> None:
        reposted_by = item.get("reposted_by")
        if isinstance(reposted_by, dict) and reposted_by.get("id"):
            self._set_cached_user_id(username, str(reposted_by["id"]))
            return
        author = item.get("author")
        if isinstance(author, dict) and author.get("id"):
            if not reposted_by:
                self._set_cached_user_id(username, str(author["id"]))

    def _parse_fx_media(self, media: dict[str, Any] | None) -> tuple[str | None, str | None, list[str], bool, float | None]:
        if not isinstance(media, dict):
            return None, None, [], False, None

        videos = list(media.get("videos") or [])
        if not videos:
            videos = [
                m for m in (media.get("all") or [])
                if isinstance(m, dict) and m.get("type") in ("video", "gif")
            ]

        photos = list(media.get("photos") or [])
        if not photos:
            photos = [
                m for m in (media.get("all") or [])
                if isinstance(m, dict) and m.get("type") == "photo"
            ]

        photo_urls = [
            _ensure_orig_image_url(p.get("url"))
            for p in photos
            if isinstance(p, dict) and p.get("url")
        ]
        photo_urls = [u for u in photo_urls if u]

        if videos:
            vid = videos[0]
            duration = vid.get("duration")
            video_url = _select_best_mp4_format(
                vid.get("formats") or [],
                duration_sec=duration,
                fallback_url=vid.get("url"),
            )
            thumb = vid.get("thumbnail_url") or (photo_urls[0] if photo_urls else None) or video_url
            return thumb, video_url, photo_urls, True, duration

        if photo_urls:
            return photo_urls[0], None, photo_urls, False, None

        return None, None, [], False, None

    def _parse_fxtwitter_statuses(
        self,
        results: list[dict[str, Any]],
        username: str,
        source: str,
        filter_other_replies: bool = False,
    ) -> list[dict[str, Any]]:
        parsed: list[dict[str, Any]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            if item.get("type") not in (None, "status"):
                continue

            tid = str(item.get("id") or "").strip()
            if not tid:
                continue

            is_retweet = bool(item.get("reposted_by"))
            if is_retweet and not self.include_retweets:
                continue

            author = item.get("author") or {}
            author_screen = (author.get("screen_name") or username).strip()

            # When querying via search `from:handle`, skip replies to other users
            replying_to = item.get("replying_to")
            if filter_other_replies and not is_retweet and isinstance(replying_to, dict):
                reply_target = (replying_to.get("screen_name") or "").strip().lower()
                if reply_target and reply_target != author_screen.lower():
                    continue

            self._cache_user_id_from_fx_item(username, item)

            media_url, video_url, media_urls, has_video, duration = self._parse_fx_media(item.get("media"))

            # Fallback to quoted tweet media if primary tweet has none (matches Nitter quote behavior)
            if not has_video and not media_url:
                quote_obj = item.get("quote")
                if isinstance(quote_obj, dict) and quote_obj.get("type") == "status":
                    media_url, video_url, media_urls, has_video, duration = self._parse_fx_media(
                        quote_obj.get("media")
                    )

            ts = item.get("created_timestamp")
            if ts is not None:
                try:
                    ts = float(ts)
                except (TypeError, ValueError):
                    ts = None
            if ts is None:
                ts = parse_timestamp(item.get("created_at"), tid)

            canonical_link = item.get("url") or f"https://x.com/{author_screen}/status/{tid}"
            text = item.get("text") or ""

            parsed.append({
                "id": tid,
                "text": text,
                "link": canonical_link,
                "media_url": media_url,
                "video_url": video_url,
                "media_urls": media_urls,
                "has_video": has_video,
                "video_duration": duration,
                "created_timestamp": ts,
                "date_str": format_utc_date(ts, item.get("created_at") or ""),
                "is_pinned": False,
                "is_retweet": is_retweet,
                "source": source,
            })
        return parsed

    def _request_fxtwitter_json(self, path: str, params: dict[str, Any] | None = None, attempts: int = 3) -> tuple[dict[str, Any] | None, int]:
        url = f"{FXTWITTER_API_BASE}{path}"
        last_status = 0
        session = self._get_session()
        for attempt in range(attempts):
            try:
                resp = session.get(
                    url,
                    params=params,
                    headers={"Accept": "application/json"},
                    timeout=self.timeout,
                )
                last_status = resp.status_code
                try:
                    data = resp.json()
                except ValueError:
                    data = None

                if resp.status_code == 200 and isinstance(data, dict):
                    code = data.get("code", 200)
                    if code == 200:
                        return data, 200
                    if data.get("reason") == "suspended":
                        raise UserSuspendedError(data.get("message") or "User is suspended")
                    last_status = int(code) if str(code).isdigit() else resp.status_code

                if isinstance(data, dict) and data.get("reason") == "suspended":
                    raise UserSuspendedError(data.get("message") or "User is suspended")

            except UserSuspendedError:
                raise
            except requests.RequestException as e:
                logger.debug(f"FxTwitter request error on {path} (attempt {attempt + 1}/{attempts}): {e}")

            if attempt < attempts - 1:
                time.sleep(0.5 * (attempt + 1))

        return None, last_status

    def _fetch_fxtwitter_profile(self, username: str, limit: int = 20) -> list[dict[str, Any]] | None:
        cached_id = self._get_cached_user_id(username)
        if cached_id:
            data, status = self._request_fxtwitter_json(
                f"/2/profile/id:{cached_id}/statuses",
                params={"count": min(max(limit, 1), 100)},
                attempts=2,
            )
            if data and isinstance(data.get("results"), list) and data["results"]:
                return self._parse_fxtwitter_statuses(
                    data["results"][:limit], username, source="fxtwitter-profile"
                )
            if status == 404:
                # Cached numeric ID may be stale/invalid; fall back to handle
                self._pop_cached_user_id(username)

        data, _ = self._request_fxtwitter_json(
            f"/2/profile/{quote(username)}/statuses",
            params={"count": min(max(limit, 1), 100)},
            attempts=3,
        )
        if data and isinstance(data.get("results"), list) and data["results"]:
            return self._parse_fxtwitter_statuses(
                data["results"][:limit], username, source="fxtwitter-profile"
            )
        return None

    def _fetch_fxtwitter_search(self, username: str, limit: int = 20) -> list[dict[str, Any]] | None:
        data, _ = self._request_fxtwitter_json(
            "/2/search",
            params={
                "q": f"from:{username}",
                "feed": "latest",
                "count": min(max(limit, 1), 100),
            },
            attempts=2,
        )
        if not data:
            return None
        results = data.get("results")
        if not isinstance(results, list):
            return None
        if not results:
            # Check profile endpoint once to detect explicit suspension so caller logs clearly
            prof, _ = self._request_fxtwitter_json(f"/2/profile/{quote(username)}", attempts=1)
            if prof and prof.get("reason") == "suspended":
                raise UserSuspendedError(prof.get("message") or "User is suspended")
            return []
        return self._parse_fxtwitter_statuses(
            results[:limit], username, source="fxtwitter-search", filter_other_replies=True
        )

    # ------------------------------------------------------------------
    # Channel 2: FxTwitter RSS Feed
    # ------------------------------------------------------------------

    def _fetch_fxtwitter_rss(self, username: str, limit: int = 20) -> list[dict[str, Any]] | None:
        url = f"{FXTWITTER_WEB_BASE}/{quote(username)}/feed.xml"
        resp = self._get_session().get(
            url,
            params={"count": min(max(limit, 1), 100)},
            headers={"Accept": "application/rss+xml, application/xml, text/xml"},
            timeout=self.timeout,
        )
        if resp.status_code != 200 or not resp.text.strip():
            return None

        root = ET.fromstring(resp.text)
        channel = root.find("channel")
        if channel is None:
            return None

        mrss_ns = {"media": "http://search.yahoo.com/mrss/"}
        tweets: list[dict[str, Any]] = []

        for item in channel.findall("item")[:limit]:
            link = (item.findtext("link") or item.findtext("guid") or "").strip()
            guid = (item.findtext("guid") or link).strip()
            m_id = re.search(r"/status/(\d+)", guid) or re.search(r"/status/(\d+)", link)
            if not m_id:
                continue
            tid = m_id.group(1)

            pub_date = (item.findtext("pubDate") or "").strip()
            ts = parse_timestamp(pub_date, tid)

            desc_html = item.findtext("description") or item.findtext("title") or ""
            soup = BeautifulSoup(desc_html, "html.parser")
            text = soup.get_text(separator="\n").strip()

            has_video = False
            video_url = None
            media_url = None
            media_urls: list[str] = []

            enclosure = item.find("enclosure")
            if enclosure is not None:
                enc_url = enclosure.attrib.get("url")
                enc_type = (enclosure.attrib.get("type") or "").lower()
                if enc_url:
                    if enc_type.startswith("video/"):
                        has_video = True
                        video_url = enc_url
                        media_url = enc_url
                    elif enc_type.startswith("image/"):
                        media_url = _ensure_orig_image_url(enc_url)
                        if media_url:
                            media_urls.append(media_url)

            thumb_el = item.find("media:thumbnail", mrss_ns)
            if thumb_el is not None and thumb_el.attrib.get("url"):
                if has_video:
                    media_url = thumb_el.attrib["url"]
                elif not media_url:
                    media_url = thumb_el.attrib["url"]
                    media_urls.append(media_url)

            # HTML fallback inside description
            if not media_url and not video_url:
                video_tag = soup.find("video")
                if video_tag:
                    has_video = True
                    source_tag = video_tag.find("source")
                    video_url = video_tag.get("src") or (source_tag.get("src") if source_tag else None)
                    media_url = video_tag.get("poster") or video_url
                else:
                    img_tag = soup.find("img")
                    if img_tag and img_tag.get("src"):
                        media_url = _ensure_orig_image_url(img_tag["src"])
                        if media_url:
                            media_urls.append(media_url)

            tweets.append({
                "id": tid,
                "text": text,
                "link": link or f"https://x.com/{username}/status/{tid}",
                "media_url": media_url,
                "video_url": video_url,
                "media_urls": media_urls,
                "has_video": has_video,
                "video_duration": None,
                "created_timestamp": ts,
                "date_str": format_utc_date(ts, pub_date),
                "is_pinned": False,
                "is_retweet": False,
                "source": "fxtwitter-rss",
            })

        return tweets if tweets else None

    # ------------------------------------------------------------------
    # Channel 3: Optional twikit/twifork with X cookies
    # ------------------------------------------------------------------

    def _get_twikit_client(self) -> Any:
        if self._twikit_init_attempted:
            return self._twikit_client
        self._twikit_init_attempted = True
        try:
            from twikit import Client  # provided by twifork or twikit
        except ImportError:
            logger.debug("twikit/twifork not installed; skipping cookie channel.")
            return None

        client = Client("en-US")
        client.set_cookies(self._cookies)
        self._twikit_client = client
        return client

    async def _fetch_twikit(self, username: str, limit: int = 20) -> list[dict[str, Any]] | None:
        client = self._get_twikit_client()
        if client is None:
            return None

        user_id = self._get_cached_user_id(username)
        pinned_ids: set[str] = set()

        if not user_id:
            user = await client.get_user_by_screen_name(username)
            user_id = str(user.id)
            self._set_cached_user_id(username, user_id)
            for pid in getattr(user, "pinned_tweet_ids", None) or []:
                pinned_ids.add(str(pid))

        tweets_res = await client.get_user_tweets(user_id, "Tweets", count=limit)
        out: list[dict[str, Any]] = []

        for tw in list(tweets_res)[:limit]:
            tid = str(getattr(tw, "id", "") or "").strip()
            if not tid:
                continue

            retweeted = getattr(tw, "retweeted_tweet", None)
            is_retweet = retweeted is not None
            if is_retweet and not self.include_retweets:
                continue

            src_tw = retweeted if (retweeted is not None and not getattr(tw, "media", None)) else tw
            text = getattr(src_tw, "full_text", None) or getattr(tw, "text", "") or ""

            dt = getattr(tw, "created_at_datetime", None)
            if dt is not None:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                ts = dt.astimezone(timezone.utc).timestamp()
            else:
                ts = parse_timestamp(getattr(tw, "created_at", None), tid)

            media_list = list(getattr(src_tw, "media", None) or [])
            if not media_list and getattr(src_tw, "quote", None) is not None:
                media_list = list(getattr(src_tw.quote, "media", None) or [])

            has_video = False
            video_url = None
            media_url = None
            media_urls: list[str] = []
            duration = None

            for m in media_list:
                m_type = getattr(m, "type", "")
                if m_type in ("video", "animated_gif"):
                    has_video = True
                    dur_ms = getattr(m, "duration_millis", None)
                    duration = dur_ms / 1000.0 if dur_ms else None
                    streams = getattr(m, "streams", None) or []
                    fmt_dicts = [
                        {
                            "url": getattr(s, "url", None),
                            "bitrate": getattr(s, "bitrate", 0) or 0,
                            "content_type": getattr(s, "content_type", "") or "",
                        }
                        for s in streams
                    ]
                    video_url = _select_best_mp4_format(fmt_dicts, duration_sec=duration)
                    media_url = getattr(m, "media_url", None) or video_url
                    break
                elif m_type == "photo":
                    u = getattr(m, "source_url", None) or _ensure_orig_image_url(getattr(m, "media_url", None))
                    if u:
                        media_urls.append(u)
                        if not media_url:
                            media_url = u

            author_handle = getattr(getattr(tw, "user", None), "screen_name", None) or username
            out.append({
                "id": tid,
                "text": text,
                "link": f"https://x.com/{author_handle}/status/{tid}",
                "media_url": media_url,
                "video_url": video_url,
                "media_urls": media_urls,
                "has_video": has_video,
                "video_duration": duration,
                "created_timestamp": ts,
                "date_str": format_utc_date(ts, str(getattr(tw, "created_at", ""))),
                "is_pinned": tid in pinned_ids,
                "is_retweet": is_retweet,
                "source": "twikit-cookies",
            })

        return out

    # ------------------------------------------------------------------
    # Channel 4: Direct X Guest GraphQL
    # ------------------------------------------------------------------

    def _ensure_guest_token(self, force_refresh: bool = False) -> str | None:
        with self._lock:
            if not force_refresh and self._guest_token:
                return self._guest_token
            if not force_refresh and self._guest_failed:
                return None
            session = self._get_session()
            for attempt in range(2):
                try:
                    r = session.post(
                        "https://api.x.com/1.1/guest/activate.json",
                        headers={"Authorization": f"Bearer {X_WEB_BEARER_TOKEN}"},
                        timeout=self.timeout,
                    )
                    if r.status_code == 200:
                        token = r.json().get("guest_token")
                        if token:
                            self._guest_token = token
                            self._guest_failed = False
                            return token
                except Exception as e:
                    logger.debug(f"Guest token activation failed: {e}")
                time.sleep(1 + attempt)
            self._guest_failed = True
            return None

    def _gql_get(self, op: str, variables: dict[str, Any]) -> requests.Response | None:
        token = self._ensure_guest_token()
        if not token:
            return None
        url = f"{X_GQL_BASE}/{op}"
        headers = {
            "Authorization": f"Bearer {X_WEB_BEARER_TOKEN}",
            "x-guest-token": token,
            "x-twitter-active-user": "yes",
            "x-twitter-client-language": "en",
        }
        params = {"variables": json.dumps(variables, separators=(",", ":"))}
        session = self._get_session()
        resp = session.get(url, headers=headers, params=params, timeout=self.timeout)
        if resp.status_code in (401, 403):
            token = self._ensure_guest_token(force_refresh=True)
            if token:
                headers["x-guest-token"] = token
                resp = session.get(url, headers=headers, params=params, timeout=self.timeout)
        return resp

    def _extract_gql_media(self, legacy: dict[str, Any]) -> tuple[str | None, str | None, list[str], bool, float | None]:
        ext = legacy.get("extended_entities") or legacy.get("entities") or {}
        media_items = ext.get("media") or []
        photo_urls: list[str] = []

        for m in media_items:
            if not isinstance(m, dict):
                continue
            mtype = m.get("type")
            if mtype in ("video", "animated_gif"):
                vinfo = m.get("video_info") or {}
                dur_ms = vinfo.get("duration_millis")
                duration = dur_ms / 1000.0 if dur_ms else None
                video_url = _select_best_mp4_format(vinfo.get("variants") or [], duration_sec=duration)
                thumb = m.get("media_url_https") or video_url
                return thumb, video_url, photo_urls, True, duration
            if mtype == "photo":
                u = _ensure_orig_image_url(m.get("media_url_https"))
                if u:
                    photo_urls.append(u)

        if photo_urls:
            return photo_urls[0], None, photo_urls, False, None
        return None, None, [], False, None

    def _parse_gql_tweet_result(self, result_obj: dict[str, Any], username: str, is_pinned: bool = False) -> dict[str, Any] | None:
        if not isinstance(result_obj, dict) or not result_obj:
            return None
        tw = result_obj.get("tweet") if "tweet" in result_obj else result_obj
        if not isinstance(tw, dict):
            return None

        legacy = tw.get("legacy") or {}
        rt_result = ((legacy.get("retweeted_status_result") or {}).get("result"))
        is_retweet = isinstance(rt_result, dict) and bool(rt_result)
        if is_retweet and not self.include_retweets:
            return None

        src_tw = rt_result.get("tweet", rt_result) if is_retweet else tw
        src_legacy = src_tw.get("legacy") or legacy

        tid = str(legacy.get("id_str") or tw.get("rest_id") or "").strip()
        if not tid:
            return None

        note_text = (
            ((src_tw.get("note_tweet") or {}).get("note_tweet_results") or {})
            .get("result", {})
            .get("text")
        )
        text = note_text or src_legacy.get("full_text") or src_legacy.get("text") or ""

        media_url, video_url, media_urls, has_video, duration = self._extract_gql_media(src_legacy)
        if not has_video and not media_url:
            quoted = ((src_tw.get("quoted_status_result") or {}).get("result"))
            if isinstance(quoted, dict):
                q_tw = quoted.get("tweet", quoted)
                media_url, video_url, media_urls, has_video, duration = self._extract_gql_media(
                    q_tw.get("legacy") or {}
                )

        user_res = ((tw.get("core") or {}).get("user_results") or {}).get("result") or {}
        u_leg = user_res.get("legacy") or {}
        u_core = user_res.get("core") or {}
        screen = u_leg.get("screen_name") or u_core.get("screen_name") or user_res.get("screen_name") or username

        created_at = legacy.get("created_at") or ""
        ts = parse_timestamp(created_at, tid)

        return {
            "id": tid,
            "text": text,
            "link": f"https://x.com/{screen}/status/{tid}",
            "media_url": media_url,
            "video_url": video_url,
            "media_urls": media_urls,
            "has_video": has_video,
            "video_duration": duration,
            "created_timestamp": ts,
            "date_str": format_utc_date(ts, created_at),
            "is_pinned": is_pinned,
            "is_retweet": is_retweet,
            "source": "x-guest-graphql",
        }

    def _fetch_x_guest_graphql(self, username: str, limit: int = 20) -> list[dict[str, Any]] | None:
        uid = self._get_cached_user_id(username)
        if not uid:
            resp = self._gql_get(
                X_OP_USER_BY_SCREEN,
                {"screen_name": username, "withSafetyModeUserFields": True},
            )
            if resp is None or resp.status_code != 200:
                return None
            user_res = ((resp.json().get("data") or {}).get("user") or {}).get("result") or {}
            if user_res.get("__typename") == "UserUnavailable":
                reason = str(user_res.get("reason") or user_res.get("message") or "").lower()
                if "suspend" in reason:
                    raise UserSuspendedError("User is suspended")
                return None
            uid = user_res.get("rest_id")
            if not uid and isinstance(user_res.get("id"), str) and user_res["id"].startswith("VXNlcjo"):
                uid = base64.b64decode(user_res["id"]).decode(errors="ignore").split(":")[-1]
            if not uid:
                return None
            self._set_cached_user_id(username, str(uid))

        resp = self._gql_get(
            X_OP_USER_TWEETS,
            {
                "userId": str(uid),
                "count": limit,
                "includePromotedContent": False,
                "withQuickPromoteEligibilityTweetFields": True,
                "withVoice": True,
                "withV2Timeline": True,
            },
        )
        if resp is None or resp.status_code != 200:
            return None

        result = ((resp.json().get("data") or {}).get("user") or {}).get("result") or {}
        if result.get("__typename") == "UserUnavailable":
            return None

        tl = result.get("timeline_v2") or result.get("timeline") or {}
        instructions = (tl.get("timeline") or {}).get("instructions") or []
        if not instructions:
            return None

        out: list[dict[str, Any]] = []
        for instr in instructions:
            if not isinstance(instr, dict):
                continue
            if instr.get("type") == "TimelinePinEntry":
                pin_res = (
                    ((instr.get("entry") or {}).get("content") or {})
                    .get("itemContent", {})
                    .get("tweet_results", {})
                    .get("result")
                )
                parsed_pin = self._parse_gql_tweet_result(pin_res, username, is_pinned=True)
                if parsed_pin:
                    out.append(parsed_pin)
                continue

            for entry in instr.get("entries") or []:
                eid = entry.get("entryId") or ""
                if eid and not eid.startswith("tweet-"):
                    continue
                tw_res = (
                    ((entry.get("content") or {}).get("itemContent") or {})
                    .get("tweet_results", {})
                    .get("result")
                )
                parsed_tw = self._parse_gql_tweet_result(tw_res, username, is_pinned=False)
                if parsed_tw:
                    out.append(parsed_tw)

        return out[:limit] if out else None

    # ------------------------------------------------------------------
    # Channel 5: X Syndication Embed Endpoint
    # ------------------------------------------------------------------

    def _fetch_x_syndication(self, username: str, limit: int = 20) -> list[dict[str, Any]] | None:
        resp = self._get_session().get(
            SYNDICATION_URL.format(handle=quote(username)),
            headers={
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Referer": "https://platform.twitter.com/",
            },
            timeout=self.timeout,
        )
        if resp.status_code != 200 or "__NEXT_DATA__" not in resp.text:
            return None

        m = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">([\s\S]*?)</script>',
            resp.text,
        )
        if not m:
            return None
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return None

        entries: list[dict[str, Any]] = []

        def _walk(node: Any) -> None:
            if isinstance(node, dict):
                if isinstance(node.get("entries"), list):
                    entries.extend(x for x in node["entries"] if isinstance(x, dict))
                for v in node.values():
                    _walk(v)
            elif isinstance(node, list):
                for v in node:
                    _walk(v)

        _walk(data)

        out: list[dict[str, Any]] = []
        for entry in entries:
            tw = (entry.get("content") or {}).get("tweet")
            if not isinstance(tw, dict) or not tw:
                continue
            tid = str(tw.get("id_str") or tw.get("conversation_id_str") or "").strip()
            if not tid:
                continue

            user = tw.get("user") or {}
            screen = user.get("screen_name") or username
            if user.get("id_str") and not self._get_cached_user_id(username):
                self._set_cached_user_id(username, str(user["id_str"]))

            media_details = tw.get("mediaDetails") or (tw.get("entities") or {}).get("media") or []
            has_video = False
            video_url = None
            media_url = None
            media_urls: list[str] = []
            duration = None

            for md in media_details:
                if not isinstance(md, dict):
                    continue
                mtype = md.get("type")
                if mtype in ("video", "animated_gif"):
                    has_video = True
                    vinfo = md.get("video_info") or {}
                    dur_ms = vinfo.get("duration_millis")
                    duration = dur_ms / 1000.0 if dur_ms else None
                    video_url = _select_best_mp4_format(vinfo.get("variants") or [], duration_sec=duration)
                    media_url = md.get("media_url_https") or video_url
                    break
                if mtype == "photo":
                    u = _ensure_orig_image_url(md.get("media_url_https"))
                    if u:
                        media_urls.append(u)
                        if not media_url:
                            media_url = u

            created_at = tw.get("created_at") or ""
            ts = parse_timestamp(created_at, tid)
            text = tw.get("full_text") or tw.get("text") or ""

            out.append({
                "id": tid,
                "text": text,
                "link": f"https://x.com/{screen}/status/{tid}",
                "media_url": media_url,
                "video_url": video_url,
                "media_urls": media_urls,
                "has_video": has_video,
                "video_duration": duration,
                "created_timestamp": ts,
                "date_str": format_utc_date(ts, created_at),
                "is_pinned": False,
                "is_retweet": bool(tw.get("retweeted_status")),
                "source": "x-syndication",
            })

        return out[:limit] if out else None
