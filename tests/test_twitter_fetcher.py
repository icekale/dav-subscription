from types import SimpleNamespace

import httpx
import pytest

from app.db import DB
from app.fetchers.twitter import (
    TwitterFetcher,
    extract_screen_name,
    resolve_x_profile,
)


def _user_response():
    return {
        "data": {
            "user": {
                "result": {
                    "__typename": "User",
                    "rest_id": "1745106082790318080",
                    "core": {"name": "SemiAnalysis", "screen_name": "SemiAnalysis_"},
                    "avatar": {
                        "image_url": "https://pbs.twimg.com/profile_images/1_normal.jpg"
                    },
                    "legacy": {},
                }
            }
        }
    }


def test_query_id_refresh_failure_backs_off(monkeypatch):
    """提取 queryId 失败后进入短冷却，而不是锁死 6 小时。"""
    from app.fetchers import twitter as tw_mod

    saved_loaded = tw_mod._query_ids_loaded
    saved_error = tw_mod._query_ids_error_until
    tw_mod._query_ids_loaded = 0.0
    tw_mod._query_ids_error_until = 0.0
    clock = {"t": 100000.0}  # 足够大，确保越过 6 小时 TTL 的"从未加载"判定
    monkeypatch.setattr(tw_mod.time, "time", lambda: clock["t"])

    class Handler:
        def __init__(self, fail):
            self.fail = fail
            self.requests = 0

        def __call__(self, request):
            self.requests += 1
            if self.fail:
                raise httpx.ConnectError("boom", request=request)
            if "abs.twimg.com" in str(request.url):
                return httpx.Response(
                    200,
                    text='queryId:"abc123"xxxoperationName:"UserTweets"',
                )
            return httpx.Response(
                200,
                text='<script src="https://abs.twimg.com/responsive-web/client-web/main.abc.js"></script>',
            )

    try:
        fail_handler = Handler(fail=True)
        fail_client = httpx.Client(transport=httpx.MockTransport(fail_handler))
        tw_mod._refresh_query_ids(fail_client, "auth_token=x; ct0=y")
        assert fail_handler.requests == 1  # 只打了首页一次

        ok_handler = Handler(fail=False)
        ok_client = httpx.Client(transport=httpx.MockTransport(ok_handler))
        tw_mod._refresh_query_ids(ok_client, "auth_token=x; ct0=y")
        assert ok_handler.requests == 0  # 冷却期内不重试

        clock["t"] += tw_mod.QUERY_ID_RETRY_COOLDOWN + 1
        tw_mod._refresh_query_ids(ok_client, "auth_token=x; ct0=y")
        assert ok_handler.requests == 2  # 冷却期后重试（首页 + bundle）
    finally:
        tw_mod._query_ids_loaded = saved_loaded
        tw_mod._query_ids_error_until = saved_error


def _timeline_response():
    tweet = lambda tid, text, created="Tue Aug 04 12:00:00 +0000 2026", reply_to="": {  # noqa: E731
        "result": {
            "rest_id": tid,
            "legacy": {
                "full_text": text,
                "created_at": created,
                "id_str": tid,
                **({"in_reply_to_status_id_str": reply_to} if reply_to else {}),
            },
        }
    }
    return {
        "data": {
            "user": {
                "result": {
                    "__typename": "User",
                    "timeline": {
                        "timeline": {
                            "instructions": [
                                {"type": "TimelineClearCache"},
                                {
                                    "type": "TimelineAddEntries",
                                    "entries": [
                                        {
                                            "content": {
                                                "__typename": "TimelineTimelineItem",
                                                "itemContent": {
                                                    "tweet_results": tweet("111", "第一帖")
                                                },
                                            }
                                        },
                                        {
                                            "content": {
                                                "__typename": "TimelineTimelineItem",
                                                "itemContent": {
                                                    "tweet_results": tweet(
                                                        "222", "回复帖", reply_to="111"
                                                    )
                                                },
                                            }
                                        },
                                        {
                                            "content": {
                                                "__typename": "TimelineTimelineModule",
                                                "items": [
                                                    {
                                                        "item": {
                                                            "itemContent": {
                                                                "tweet_results": tweet(
                                                                    "333",
                                                                    "模块帖",
                                                                    created="",
                                                                )
                                                            }
                                                        }
                                                    }
                                                ],
                                            }
                                        },
                                    ],
                                },
                            ]
                        }
                    },
                }
            }
        }
    }


def _make_fetcher(handler, db):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return TwitterFetcher(
        SimpleNamespace(rsshub_base="https://rsshub.app"),
        db,
        client=client,
    )


def test_extract_screen_name():
    assert extract_screen_name("https://x.com/SemiAnalysis_") == "SemiAnalysis_"
    assert extract_screen_name("https://twitter.com/elonmusk/") == "elonmusk"
    assert extract_screen_name("elonmusk") == "elonmusk"
    assert extract_screen_name("https://x.com/a/status/123") == "a"
    assert extract_screen_name("") == ""
    # 纯 @前缀用户名（此前无法识别，直接报「无法识别 X 用户名」）
    assert extract_screen_name("@elonmusk") == "elonmusk"
    assert extract_screen_name("@SemiAnalysis_") == "SemiAnalysis_"
    assert extract_screen_name("@") == ""
    assert extract_screen_name("@too_long_username_12345") == ""


def test_twitter_fetch_pin_entry_and_visibility_wrapper(monkeypatch):
    """置顶推文（TimelinePinEntry）与受限可见性推文（TweetWithVisibilityResults）也能解析。"""
    monkeypatch.setenv("TWITTER_COOKIE", "auth_token=a; ct0=b")

    def handler(request):
        if "UserByScreenName" in str(request.url):
            return httpx.Response(200, json=_user_response())
        if "UserTweets" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "user": {
                            "result": {
                                "__typename": "User",
                                "timeline": {
                                    "timeline": {
                                        "instructions": [
                                            {
                                                "type": "TimelinePinEntry",
                                                "entry": {
                                                    "content": {
                                                        "__typename": "TimelineTimelineItem",
                                                        "itemContent": {
                                                            "tweet_results": {
                                                                "result": {
                                                                    "rest_id": "pinned1",
                                                                    "legacy": {
                                                                        "full_text": "置顶帖",
                                                                        "created_at": "Tue Aug 04 12:00:00 +0000 2026",
                                                                        "id_str": "pinned1",
                                                                    },
                                                                }
                                                            }
                                                        },
                                                    }
                                                },
                                            },
                                            {
                                                "type": "TimelineAddEntries",
                                                "entries": [
                                                    {
                                                        "content": {
                                                            "__typename": "TimelineTimelineItem",
                                                            "itemContent": {
                                                                "tweet_results": {
                                                                    "result": {
                                                                        "__typename": "TweetWithVisibilityResults",
                                                                        "tweet": {
                                                                            "rest_id": "v1",
                                                                            "legacy": {
                                                                                "full_text": "受限可见性帖",
                                                                                "created_at": "Tue Aug 04 12:00:00 +0000 2026",
                                                                                "id_str": "v1",
                                                                            },
                                                                        },
                                                                    }
                                                                }
                                                            },
                                                        }
                                                    }
                                                ],
                                            },
                                        ]
                                    }
                                },
                            }
                        }
                    }
                },
            )
        return httpx.Response(404)

    db = DB(":memory:")
    kid = db.add_kol("twitter", "SemiAnalysis", "https://x.com/SemiAnalysis_")
    fetcher = _make_fetcher(handler, db)
    posts = fetcher.fetch(db.get_kol(kid))
    assert {p.external_id for p in posts} == {"pinned1", "v1"}
    assert {p.content for p in posts} == {"置顶帖", "受限可见性帖"}


def test_twitter_suspended_user_falls_back_no_false_ok(monkeypatch):
    """用户被封/不存在时 UserTweets 返回空壳，不应记「直抓成功」，应回退 RSSHub。"""
    monkeypatch.setenv("TWITTER_COOKIE", "auth_token=a; ct0=b")
    feed_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel></channel></rss>'
    ).encode()

    def handler(request):
        if request.url.host == "x.com":
            # 空壳：用户已停用（或不存在），无 timeline
            return httpx.Response(
                200,
                json={
                    "data": {
                        "user": {
                            "result": {"__typename": "UserUnavailable", "reason": "Suspended"}
                        }
                    }
                },
            )
        return httpx.Response(
            200,
            content=feed_xml,
            headers={"content-type": "application/rss+xml"},
        )

    db = DB(":memory:")
    kid = db.add_kol("twitter", "SemiAnalysis", "https://x.com/SemiAnalysis_")
    fetcher = _make_fetcher(handler, db)
    fetcher._user_ids["SemiAnalysis_"] = "1745"  # 模拟已缓存的 userId，跳过 UserByScreenName
    posts = fetcher.fetch(db.get_kol(kid))
    assert posts == []
    # 必须标记降级、不标记直抓成功
    assert db.get_setting("x_direct_last_fallback_at")
    assert not db.get_setting("x_direct_last_ok_at")
    assert "停用" in (db.get_setting("x_direct_fallback_reason") or "")


def test_resolve_x_profile(monkeypatch):
    monkeypatch.setenv("TWITTER_COOKIE", "auth_token=a; ct0=b")

    class FakeResp:
        def __init__(self, data):
            self._data = data
            self.status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return self._data

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def close(self):
            pass

        def get(self, url, params=None, headers=None):
            return FakeResp({"data": {"page": "x"}})

        def post(self, url, params=None, json=None, headers=None):
            if "UserByScreenName" in url:
                return FakeResp(
                    {
                        "data": {
                            "user": {
                                "result": {
                                    "rest_id": "1745",
                                    "core": {
                                        "name": "SemiAnalysis",
                                        "screen_name": "SemiAnalysis_",
                                    },
                                    "avatar": {
                                        "image_url": "https://pbs.twimg.com/x_normal.jpg"
                                    },
                                }
                            }
                        }
                    }
                )
            return FakeResp({"data": {}})

    monkeypatch.setattr("httpx.Client", FakeClient)
    profile = resolve_x_profile("https://x.com/SemiAnalysis_")
    assert profile["name"] == "SemiAnalysis"
    assert profile["avatar_url"] == "https://pbs.twimg.com/x_400x400.jpg"

    # 未配置 cookie 时返回空，调用方回退占位名
    monkeypatch.delenv("TWITTER_COOKIE")
    assert resolve_x_profile("https://x.com/SemiAnalysis_") == {}


def test_twitter_direct_fetch_parses_tweets_and_avatar(monkeypatch):
    monkeypatch.setenv("TWITTER_COOKIE", "auth_token=a; ct0=b; lang=zh-CN")

    def handler(request):
        assert request.url.host == "x.com"
        if "UserByScreenName" in str(request.url):
            return httpx.Response(200, json=_user_response())
        if "UserTweets" in str(request.url):
            return httpx.Response(200, json=_timeline_response())
        return httpx.Response(404)

    db = DB(":memory:")
    kid = db.add_kol("twitter", "SemiAnalysis", "https://x.com/SemiAnalysis_")
    fetcher = _make_fetcher(handler, db)
    posts = fetcher.fetch(db.get_kol(kid))
    assert [p.external_id for p in posts] == ["111", "222", "333"]
    assert posts[0].content == "第一帖"
    assert posts[0].post_type == ""
    assert posts[0].url == "https://x.com/SemiAnalysis_/status/111"
    assert posts[1].post_type == "reply"
    assert posts[2].content == "模块帖"
    assert posts[0].published_at == "2026-08-04 20:00"  # 12:00 UTC + 8h
    assert db.get_kol(kid)["avatar_url"] == "https://pbs.twimg.com/profile_images/1_400x400.jpg"
    assert db.get_setting("x_direct_last_ok_at")


def test_twitter_falls_back_to_rsshub(monkeypatch):
    monkeypatch.setenv("TWITTER_COOKIE", "auth_token=a; ct0=b")
    feed_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel>'
        "<item><title>备用源</title>"
        "<link>https://x.com/SemiAnalysis_/status/999</link>"
        "<description>来自 RSSHub 的内容</description>"
        "<pubDate>Tue, 04 Aug 2026 10:00:00 +0800</pubDate>"
        "</item></channel></rss>"
    ).encode()

    def handler(request):
        if request.url.host == "x.com":
            return httpx.Response(200, json={"errors": [{"message": "queryId 已失效"}]})
        assert request.url.path == "/twitter/user/SemiAnalysis_"
        return httpx.Response(
            200,
            content=feed_xml,
            headers={"content-type": "application/rss+xml"},
        )

    db = DB(":memory:")
    kid = db.add_kol("twitter", "SemiAnalysis", "https://x.com/SemiAnalysis_")
    fetcher = _make_fetcher(handler, db)
    posts = fetcher.fetch(db.get_kol(kid))
    assert len(posts) == 1
    assert posts[0].title == "备用源"
    assert posts[0].url == "https://x.com/SemiAnalysis_/status/999"
    assert db.get_setting("x_direct_last_fallback_at")
    assert "queryId 已失效" in (db.get_setting("x_direct_fallback_reason") or "")


def test_twitter_network_error_skips_rsshub_fallback(monkeypatch):
    """网络层错误（SSL/超时/连接重置）不触发降级，避免抖动时误报。"""
    monkeypatch.setenv("TWITTER_COOKIE", "auth_token=a; ct0=b")
    rss_calls = {"n": 0}

    def handler(request):
        if request.url.host == "x.com":
            raise httpx.ConnectError("connection reset", request=request)
        rss_calls["n"] += 1
        return httpx.Response(200, content=b"<rss/>")

    db = DB(":memory:")
    kid = db.add_kol("twitter", "SemiAnalysis", "https://x.com/SemiAnalysis_")
    fetcher = _make_fetcher(handler, db)
    with pytest.raises(httpx.TransportError):
        fetcher.fetch(db.get_kol(kid))
    assert rss_calls["n"] == 0  # 没有走到 RSSHub
    assert not db.get_setting("x_direct_last_fallback_at")  # 不标记降级
    events = db.recent_source_events()
    assert any("网络抖动" in e["detail"] for e in events)


def test_query_id_refresh_uses_browser_headers(monkeypatch):
    """x.com/ 页面拉取用浏览器式头（UA+Cookie），不带 Authorization/x-csrf-token。

    带这两个头打 HTML 路由会直接 401，导致 queryId 永远提取失败（2026-08 实测），
    只能靠默认 queryId 兜底；换浏览器头后页面返回 200 且能提取到最新 queryId。
    """
    from app.fetchers import twitter as tw_mod

    saved_loaded = tw_mod._query_ids_loaded
    saved_error = tw_mod._query_ids_error_until
    tw_mod._query_ids_loaded = 0.0
    tw_mod._query_ids_error_until = 0.0
    monkeypatch.setattr(tw_mod.time, "time", lambda: 100000.0)

    seen: dict[str, dict] = {}

    def handler(request):
        seen[str(request.url)] = dict(request.headers)
        if "abs.twimg.com" in str(request.url):
            return httpx.Response(
                200,
                text='queryId:"abc123"xxxoperationName:"UserTweets"',
            )
        return httpx.Response(
            200,
            text='<script src="https://abs.twimg.com/responsive-web/client-web/main.abc.js"></script>',
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        tw_mod._refresh_query_ids(client, "auth_token=x; ct0=y")
        page_headers = seen.get("https://x.com/")
        assert page_headers is not None
        assert "authorization" not in page_headers
        assert "x-csrf-token" not in page_headers
        assert page_headers.get("cookie") == "auth_token=x; ct0=y; lang=zh-CN"
        assert tw_mod._query_ids.get("UserTweets") == "abc123"
        assert tw_mod._query_ids_loaded > 0
    finally:
        tw_mod._query_ids_loaded = saved_loaded
        tw_mod._query_ids_error_until = saved_error


def test_query_id_refresh_single_fetch_within_ttl(monkeypatch):
    """TTL 内多次调用只拉取一次前端（避免并发雷群）。"""
    from app.fetchers import twitter as tw_mod

    saved_loaded = tw_mod._query_ids_loaded
    saved_error = tw_mod._query_ids_error_until
    tw_mod._query_ids_loaded = 0.0
    tw_mod._query_ids_error_until = 0.0
    clock = {"t": 100000.0}
    monkeypatch.setattr(tw_mod.time, "time", lambda: clock["t"])

    class Handler:
        def __init__(self):
            self.requests = 0

        def __call__(self, request):
            self.requests += 1
            if "abs.twimg.com" in str(request.url):
                return httpx.Response(
                    200,
                    text='queryId:"abc123"xxxoperationName:"UserTweets"',
                )
            return httpx.Response(
                200,
                text='<script src="https://abs.twimg.com/responsive-web/client-web/main.abc.js"></script>',
            )

    handler = Handler()
    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        tw_mod._refresh_query_ids(client, "auth_token=x; ct0=y")
        first = handler.requests
        assert first >= 1  # 首次调用确实请求了前端
        tw_mod._refresh_query_ids(client, "auth_token=x; ct0=y")
        assert handler.requests == first  # TTL 内不重复拉取
    finally:
        tw_mod._query_ids_loaded = saved_loaded
        tw_mod._query_ids_error_until = saved_error


def test_query_id_refresh_serialized_under_lock(monkeypatch):
    """4 个 worker 并发刷新时只拉取一次前端（page + bundle = 2 请求）。"""
    import threading
    import time

    from app.fetchers import twitter as tw_mod

    saved_loaded = tw_mod._query_ids_loaded
    saved_error = tw_mod._query_ids_error_until
    tw_mod._query_ids_loaded = 0.0
    tw_mod._query_ids_error_until = 0.0
    clock = {"t": 100000.0}
    monkeypatch.setattr(tw_mod.time, "time", lambda: clock["t"])

    class Handler:
        def __init__(self):
            self.requests = 0
            self.lock = threading.Lock()

        def __call__(self, request):
            with self.lock:
                self.requests += 1
            time.sleep(0.005)  # 让出 GIL，确保 4 个 worker 都越过 TTL 检查再取锁
            if "abs.twimg.com" in str(request.url):
                return httpx.Response(
                    200,
                    text='queryId:"abc123"xxxoperationName:"UserTweets"',
                )
            return httpx.Response(
                200,
                text='<script src="https://abs.twimg.com/responsive-web/client-web/main.abc.js"></script>',
            )

    handler = Handler()
    client = httpx.Client(transport=httpx.MockTransport(handler))
    barrier = threading.Barrier(5)  # 4 workers + 主线程

    def worker():
        barrier.wait()
        tw_mod._refresh_query_ids(client, "auth_token=x; ct0=y")

    try:
        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        barrier.wait()
        for t in threads:
            t.join()
        assert handler.requests == 2  # 只拉一次前端（page + bundle）
    finally:
        tw_mod._query_ids_loaded = saved_loaded
        tw_mod._query_ids_error_until = saved_error
