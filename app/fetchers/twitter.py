"""X/Twitter 官方 GraphQL 直抓（主通道），失败时自动回退 RSSHub（备用通道）。

直抓依赖登录 Cookie（TWITTER_COOKIE 里的 auth_token / ct0），调用 X 网页端同源
GraphQL 接口：UserByScreenName（拿 userId/头像）+ UserTweets（拿时间线）。
queryId 由 X 前端轮换，启动后每 6 小时自动从前端 main bundle 提取一次，
提取失败时用内置默认值兜底；接口失效则整体回退 RSSHub。

2026-08 起 X 把 api.twitter.com 升级成 Cloudflare managed challenge（裸客户端
一律 403），但 x.com/i/api 的 GraphQL/typeahead 只是 passive TLS/HTTP2 指纹检测——
用 curl_cffi 模拟 Chrome 指纹即可过（实测），且直抓并不需要 guest token
（_graphql 不带 guest 头也 200）。因此：
- HTTP 客户端从 httpx 换成 curl_cffi.Session(impersonate=chrome124)；
- 删掉 guest token 获取逻辑（guest/activate 已被 CF 锁死，属于无效请求）。
curl_cffi.Session 非线程安全：生产同平台 2 并发共享 fetcher，用 threading.local
每线程懒建一个 session；外部注入的 client（测试 mock / 解析头像）直接复用。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import threading
import time

import httpx
from curl_cffi import requests as cffi
from curl_cffi.requests.errors import RequestsError

from ..avatar_cache import cache_avatar
from .base import Fetcher, Post, format_published_at
from .rss import RssFetcher

logger = logging.getLogger(__name__)

# X 网页端公开的 guest bearer token（来自 abs.twimg.com 前端包）
GUEST_BEARER_TOKEN = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)
DEFAULT_QUERY_IDS = {
    "UserTweets": "T1x2zehUOKCWNpKwZCpnbg",
    "UserByScreenName": "Gb-d6r0vxPOADdG62OEBpQ",
}
QUERY_ID_TTL = 6 * 3600  # 每 6 小时重新从前端提取一次 queryId
QUERY_ID_RETRY_COOLDOWN = 300  # 提取失败后 5 分钟重试，避免每次轮询都打前端
FETCH_COUNT = 20

# UserTweets 时间线所需的标准 feature switches（X 网页端常用集合）
FEATURES = {
    "rweb_video_screen_enabled": False,
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": False,
    "tweet_awards_web_tipping_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_query_ids: dict[str, str] = dict(DEFAULT_QUERY_IDS)
_query_ids_loaded = 0.0
_query_ids_error_until = 0.0
_query_ids_lock = threading.Lock()


def _cookie_parts(cookie: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (cookie or "").split(";"):
        part = part.strip()
        if "=" in part:
            key, _, value = part.partition("=")
            out[key.strip()] = value.strip()
    return out


def _auth_headers(cookie: str) -> dict[str, str]:
    parts = _cookie_parts(cookie)
    auth, ct0 = parts.get("auth_token", ""), parts.get("ct0", "")
    return {
        "Authorization": f"Bearer {GUEST_BEARER_TOKEN}",
        "Cookie": f"auth_token={auth}; ct0={ct0}; lang=zh-CN",
        "x-csrf-token": ct0,
        "x-twitter-active-user": "yes",
        "User-Agent": UA,
        "Content-Type": "application/json",
    }


def _html_headers(cookie: str) -> dict[str, str]:
    """浏览器式请求头：只带 UA + Cookie，用于拉取 x.com 页面与前端 bundle。

    不能复用 _auth_headers——带 Authorization / x-csrf-token 的请求打到 HTML
    路由会直接返回 401（实测 2026-08），导致 queryId 提取永远失败。
    """
    parts = _cookie_parts(cookie)
    auth, ct0 = parts.get("auth_token", ""), parts.get("ct0", "")
    return {
        "User-Agent": UA,
        "Cookie": f"auth_token={auth}; ct0={ct0}; lang=zh-CN",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


def _refresh_query_ids(client, cookie: str) -> None:
    """从 X 前端 main bundle 提取最新的 UserTweets / UserByScreenName queryId。"""
    global _query_ids_loaded, _query_ids_error_until
    with _query_ids_lock:
        now = time.time()
        if now - _query_ids_loaded < QUERY_ID_TTL:
            return
        if now < _query_ids_error_until:
            return  # 上次提取失败，冷却期内不重复打前端
        try:
            headers = _html_headers(cookie)
            page = client.get("https://x.com/", headers=headers)
            page.raise_for_status()
            match = re.search(
                r'src="(https://abs\.twimg\.com/responsive-web/client-web/main\.[^"]+\.js)"',
                page.text,
            )
            if not match:
                return
            bundle = client.get(match.group(1))
            bundle.raise_for_status()
            text = bundle.text
            for op in ("UserTweets", "UserByScreenName"):
                found = re.search(
                    r'queryId:"([^"]+)"[^}]{0,300}?operationName:"'
                    + re.escape(op)
                    + r'"',
                    text,
                )
                if found:
                    _query_ids[op] = found.group(1)
            _query_ids_loaded = now
            logger.info("X queryId 已从前端更新: %s", _query_ids)
        except Exception as exc:  # noqa: BLE001 - 提取失败用内置默认值兜底
            _query_ids_error_until = now + QUERY_ID_RETRY_COOLDOWN
            logger.warning(
                "X queryId 提取失败，使用默认值，%.0f 秒后重试: %s",
                QUERY_ID_RETRY_COOLDOWN,
                exc,
            )


def extract_screen_name(external_id: str) -> str:
    """从 x.com/twitter.com 主页链接或纯用户名（含 @前缀）里提取 screen_name。"""
    value = (external_id or "").strip()
    match = re.search(r"(?:x\.com|twitter\.com)/(?:@?)([A-Za-z0-9_]+)", value)
    if match:
        return match.group(1)
    if re.fullmatch(r"@?[A-Za-z0-9_]{1,15}", value):
        return value.lstrip("@")
    return ""


def extract_twitter_images(legacy: dict) -> list[str]:
    """X 推文图片：extended_entities.media 里的照片 URL（最多 4 张）。"""
    out: list[str] = []
    for media in (legacy.get("extended_entities") or {}).get("media") or []:
        if media.get("type") != "photo":
            continue
        url = media.get("media_url_https") or media.get("media_url") or ""
        if url and url not in out:
            out.append(url)
        if len(out) >= 4:
            break
    return out


def resolve_x_profile(external_id: str, cookie: str = "") -> dict:
    """按 X 用户名/主页链接解析昵称与头像（UserByScreenName，需登录 Cookie）。

    失败（cookie 失效/风控/未配置）时返回空 dict，调用方回退占位名。
    """
    cookie = cookie or os.environ.get("TWITTER_COOKIE", "")
    screen_name = extract_screen_name(external_id)
    if not screen_name or not cookie:
        return {}
    client = cffi.Session(impersonate="chrome124", timeout=20)
    try:
        fetcher = TwitterFetcher(db=None, client=client)
        picked = fetcher._typeahead_pick(screen_name, cookie)
        if picked:
            avatar = (
                picked.get("profile_image_url_https")
                or picked.get("profile_image_url")
                or ""
            ).replace("_normal", "_400x400")
            return {
                "name": picked.get("name") or "",
                "avatar_url": avatar,
                "screen_name": picked.get("screen_name") or screen_name,
            }
        data = fetcher._graphql(
            "UserByScreenName",
            {"screen_name": screen_name, "withSafetyModeUserFields": True},
            cookie,
        )
        result = ((data.get("data") or {}).get("user") or {}).get("result") or {}
        name = (
            (result.get("core") or {}).get("name")
            or (result.get("legacy") or {}).get("name")
            or ""
        )
        avatar = ((result.get("avatar") or {}).get("image_url") or "").replace(
            "_normal", "_400x400"
        )
        return {"name": name, "avatar_url": avatar, "screen_name": screen_name}
    except Exception as exc:  # noqa: BLE001 - 解析失败退回占位名
        logger.warning("X 昵称解析失败 screen=%s err=%s", screen_name, exc)
        return {}
    finally:
        client.close()


def _walk_tweet_results(entry: dict, out: list[dict]) -> None:
    """递归展开时间线条目（单条推文 / 模块内多推文 / 置顶）。"""
    content = entry.get("content") or {}
    typename = content.get("__typename") or content.get("entryType") or ""
    if typename == "TimelineTimelineItem":
        _append_tweet(content.get("itemContent"), out)
        return
    if typename == "TimelineTimelineModule":
        for item in content.get("items") or []:
            _walk_tweet_results({"content": item.get("item") or item}, out)
    else:
        _append_tweet(content, out)


def _append_tweet(node, out: list[dict]) -> None:
    """从 itemContent 里取出推文；结构不标准时向下找 itemContent。"""
    if not isinstance(node, dict):
        return
    tweet = (node.get("tweet_results") or {}).get("result")
    if isinstance(tweet, dict):
        # 受限可见性推文包一层 TweetWithVisibilityResults，真实内容在 .tweet 里
        if (
            tweet.get("__typename") == "TweetWithVisibilityResults"
            and isinstance(tweet.get("tweet"), dict)
        ):
            tweet = tweet["tweet"]
        out.append(tweet)
        return
    item_content = node.get("itemContent")
    if isinstance(item_content, dict):
        _append_tweet(item_content, out)


class TwitterFetcher(Fetcher):
    platform = "twitter"

    def __init__(self, source_config=None, db=None, client=None):
        super().__init__(source_config)
        self.db = db
        self._client = client  # 外部注入（测试 mock / 头像解析）时复用；None 则按线程懒建
        self._thread_local = threading.local()
        self._user_ids: dict[str, str] = {}
        self._fallback = RssFetcher(source_config, db, client=client)

    def _client_for(self):
        """curl_cffi.Session 非线程安全：每线程懒建一个；外部注入的 client 直接复用。"""
        if self._client is not None:
            return self._client
        sess = getattr(self._thread_local, "session", None)
        if sess is None:
            sess = cffi.Session(impersonate="chrome124", timeout=25)
            self._thread_local.session = sess
        return sess

    def fetch(self, kol: dict) -> list[Post]:
        """优先 X 直抓；失败时按错误类型分流。

        - 网络类错误（SSL/超时/连接重置）：不降级 RSSHub——备用通道大概率同样不通，
          只记 warn 事件后抛出，让调度器退避等网络恢复，避免抖动时刷降级事件/告警；
        - 鉴权/接口类错误（401/403/GraphQL errors/cookie 失效）：降级 RSSHub 备用通道。
        """
        cookie = os.environ.get("TWITTER_COOKIE", "")
        try:
            posts = self._fetch_direct(kol, cookie)
            if self.db is not None:
                self.db.set_setting("x_direct_last_ok_at", str(int(time.time())))
            return posts
        except (httpx.TransportError, RequestsError) as exc:
            if self.db is not None:
                self.db.add_source_event(
                    "twitter",
                    "warn",
                    f"X网络抖动(直抓): {str(exc)[:200]}",
                )
            logger.warning("X 直抓网络错误，跳过降级 kol=%s err=%s", kol["name"], exc)
            raise
        except Exception as exc:  # noqa: BLE001 - 回退备用通道
            if self.db is not None:
                self.db.set_setting("x_direct_last_fallback_at", str(int(time.time())))
                self.db.set_setting("x_direct_fallback_reason", str(exc)[:300])
                self.db.add_source_event(
                    "twitter",
                    "warn",
                    f"X直抓降级RSSHub: {str(exc)[:200]}",
                )
            logger.warning(
                "X 直抓失败，回退 RSSHub kol=%s err=%s",
                kol["name"],
                exc,
            )
            return self._fallback.fetch(kol)

    def _graphql(
        self,
        operation: str,
        variables: dict,
        cookie: str,
    ) -> dict:
        _refresh_query_ids(self._client_for(), cookie)
        query_id = _query_ids.get(operation) or DEFAULT_QUERY_IDS[operation]
        payload = {"variables": variables, "features": FEATURES}
        headers = _auth_headers(cookie)
        resp = self._client_for().post(
            f"https://x.com/i/api/graphql/{query_id}/{operation}",
            params={
                "variables": json.dumps(variables, separators=(",", ":")),
                "features": json.dumps(FEATURES, separators=(",", ":")),
            },
            json=payload,
            headers=headers,
        )
        if resp.status_code != 200:
            hint = ""
            detail = ""
            with contextlib.suppress(Exception):  # noqa: BLE001 - 非 JSON 响应体忽略
                err = resp.json()
                errs = err.get("errors") or []
                code = err.get("code") or next(
                    (e.get("code") for e in errs if e.get("code")), ""
                )
                if code:
                    detail = f" code {code}"
                else:
                    msg = next(
                        (e.get("message") for e in errs if e.get("message")), ""
                    )
                    if msg:
                        detail = f" {str(msg)[:80]}"
            if resp.status_code in (400, 404):
                hint = "（可能是 X 轮换了 GraphQL queryId，需更新 DEFAULT_QUERY_IDS）"
            raise RuntimeError(f"X GraphQL {operation} HTTP {resp.status_code}{detail}{hint}")
        data = resp.json()
        if data.get("errors"):
            msg = str(data["errors"][0].get("message", data["errors"]))
            if "queryid" in msg.lower() or "invalidrequest" in msg.lower():
                msg += "（可能是 X 轮换了 GraphQL queryId，需更新 DEFAULT_QUERY_IDS）"
            raise RuntimeError(f"X GraphQL {operation} 错误: {msg}")
        return data

    def _typeahead_pick(self, screen_name: str, cookie: str) -> dict | None:
        """typeahead 解析：只认精确匹配 screen_name 的结果。

        不能取 users[0] 兜底——typeahead 搜索结果可能把显示名相同但 handle
        不同的账号排前面（实测搜 qinbafrank 只返回停更镜像号 qinbafrank9），
        取首个会静默解析到错误账号，永远抓不到新帖。无精确匹配返回 None，
        由调用方回退 UserByScreenName。
        """
        headers = _auth_headers(cookie)
        resp = self._client_for().get(
            "https://x.com/i/api/1.1/search/typeahead.json",
            params={"q": screen_name, "result_type": "users"},
            headers=headers,
        )
        if resp.status_code != 200:
            return None
        users = (resp.json() or {}).get("users") or []
        target = screen_name.lower()
        return next(
            (u for u in users if (u.get("screen_name") or "").lower() == target),
            None,
        )

    def _typeahead_users(
        self, screen_name: str, cookie: str
    ) -> tuple[str, str]:
        """经 typeahead 接口解析 uid（2026-08 起 UserByScreenName 对第三方账号返回空壳，
        typeahead 仍可用）；返回 (user_id, avatar_url)，解析失败返回空。"""
        picked = self._typeahead_pick(screen_name, cookie)
        if not picked:
            return "", ""
        user_id = picked.get("id_str") or ""
        img = picked.get("profile_image_url_https") or picked.get("profile_image_url") or ""
        return user_id, img.replace("_normal", "_400x400") if img else ""

    def _resolve_user(self, screen_name: str, cookie: str) -> dict:
        if screen_name in self._user_ids:
            return {"user_id": self._user_ids[screen_name], "avatar": ""}
        user_id, avatar = self._typeahead_users(screen_name, cookie)
        if not user_id:
            # 回退 UserByScreenName（目前仅账号本人可解析）
            data = self._graphql(
                "UserByScreenName",
                {"screen_name": screen_name, "withSafetyModeUserFields": True},
                cookie,
            )
            result = ((data.get("data") or {}).get("user") or {}).get("result") or {}
            user_id = result.get("rest_id") or ""
            avatar = ((result.get("avatar") or {}).get("image_url") or "").replace(
                "_normal", "_400x400"
            )
        if not user_id:
            raise RuntimeError(f"X 未找到用户 {screen_name}")
        self._user_ids[screen_name] = user_id
        return {"user_id": user_id, "avatar": avatar}

    def _fetch_direct(self, kol: dict, cookie: str) -> list[Post]:
        if not cookie:
            raise RuntimeError("未配置 TWITTER_COOKIE")
        screen_name = extract_screen_name(kol["external_id"])
        if not screen_name:
            raise RuntimeError(f"无法识别 X 用户名: {kol['external_id']}")
        user = self._resolve_user(screen_name, cookie)
        data = self._graphql(
            "UserTweets",
            {
                "userId": user["user_id"],
                "count": FETCH_COUNT,
                "includePromotedContent": True,
                "withQuickPromoteEligibilityTweetFields": True,
                "withVoice": True,
                "withV2Timeline": True,
            },
            cookie,
        )
        instructions = ((data.get("data") or {}).get("user") or {}).get(
            "result", {}
        )
        if (
            not instructions
            or instructions.get("__typename") == "UserUnavailable"
        ):
            raise RuntimeError(f"X 用户不存在或已停用: {screen_name}")
        instructions = (
            (instructions.get("timeline") or {}).get("timeline") or {}
        ).get("instructions") or []
        tweets: list[dict] = []
        for instruction in instructions:
            if instruction.get("type") == "TimelineAddEntries":
                for entry in instruction.get("entries") or []:
                    _walk_tweet_results(entry, tweets)
            elif instruction.get("type") == "TimelinePinEntry":
                _walk_tweet_results(instruction.get("entry") or {}, tweets)
        posts = []
        for tweet in tweets:
            legacy = tweet.get("legacy") or {}
            tweet_id = tweet.get("rest_id") or legacy.get("id_str") or ""
            if not tweet_id:
                continue
            text = (legacy.get("full_text") or legacy.get("text") or "").strip()
            if not text:
                continue
            post_type = "reply" if legacy.get("in_reply_to_status_id_str") else ""
            posts.append(
                Post(
                    platform=self.platform,
                    kol_id=kol["id"],
                    kol_name=kol["name"],
                    external_id=tweet_id,
                    title=text[:80],
                    content=text,
                    url=f"https://x.com/{screen_name}/status/{tweet_id}",
                    published_at=format_published_at(
                        str(legacy.get("created_at") or "")
                    ),
                    post_type=post_type,
                    images=extract_twitter_images(legacy),
                )
            )
        if user.get("avatar") and self.db is not None:
            current = (self.db.get_kol(kol["id"]) or {}).get("avatar_url") or ""
            if user["avatar"] != current:
                self.db.update_kol_avatar(
                    kol["id"], cache_avatar(self.db, kol["id"], user["avatar"])
                )
        return posts
