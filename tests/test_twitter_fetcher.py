from types import SimpleNamespace

import httpx

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
