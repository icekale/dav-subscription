import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import rsa

from app.config import XueqiuConfig
from app.db import DB
from app.fetchers.combination import CombinationFetcher, extract_cube_symbol
from app.fetchers.rss import RssFetcher
from app.fetchers.xueqiu import XueqiuFetcher, classify_status

FIXTURES = Path(__file__).parent / "fixtures"


def test_xueqiu_parse_fixture():
    payload = json.loads((FIXTURES / "xueqiu_sample.json").read_text(encoding="utf-8"))

    def handler(request):
        assert request.headers.get("Cookie", "").startswith("xq_a_token=")
        assert request.url.path == "/statuses/user_timeline.json"
        assert request.url.params.get("user_id") == "123"
        assert request.headers.get("Origin") == "https://xueqiu.com"
        assert request.headers.get("X-Requested-With") == "XMLHttpRequest"
        assert request.headers.get("Referer") == "https://xueqiu.com/u/123"
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = XueqiuFetcher(XueqiuConfig(cookie="xq_a_token=abc"), db=DB(":memory:"), client=client)
    posts = fetcher.fetch({"id": 1, "name": "大V", "external_id": "123"})
    assert len(posts) == 2
    assert posts[0].external_id == "101"
    assert posts[0].url == "https://xueqiu.com/101"
    assert "大涨" in posts[0].content
    assert "<strong>" not in posts[0].content
    assert posts[0].kol_name == "大V"


def test_xueqiu_skips_reposts():
    payload = {
        "statuses": [
            {"id": 101, "title": "原创", "description": "第一条", "target": "/101"},
            {
                "id": 102,
                "title": "转发",
                "description": "转发的",
                "target": "/102",
                "retweeted_status": {"id": 999, "title": "被转内容"},
            },
        ]
    }

    def handler(request):
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = XueqiuFetcher(XueqiuConfig(cookie="xq_a_token=abc"), db=DB(":memory:"), client=client)
    posts = fetcher.fetch({"id": 1, "name": "大V", "external_id": "123"})
    assert [p.external_id for p in posts] == ["101"]


def test_classify_status():
    assert classify_status({"id": 1, "description": "正文"}) == "post"
    assert classify_status({"id": 1, "description": "正文", "retweeted_status": {"id": 2}}) is None
    assert classify_status({"id": 1, "description": "回复<a>@x</a>: 内容", "commentId": 9}) == "reply"
    # 回复项也带 retweeted_status（被回复的原帖），不能被误判成转发
    assert (
        classify_status(
            {"id": 1, "description": "回复<a>@x</a>: 内容", "commentId": 9, "retweeted_status": {"id": 2}}
        )
        == "reply"
    )


def test_xueqiu_fetch_keeps_replies():
    payload = {
        "statuses": [
            {"id": 101, "description": "第一条", "target": "/101"},
            {"id": 102, "description": "转发的", "target": "/102", "retweeted_status": {"id": 999}},
            {
                "id": 103,
                "description": '回复<a href="https://xueqiu.com/n/foo" target="_blank">@foo</a>: 内容',
                "target": "/103",
                "commentId": 12345,
                "retweeted_status": {"id": 888},
            },
        ]
    }

    def handler(request):
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = XueqiuFetcher(XueqiuConfig(cookie="xq_a_token=abc"), db=DB(":memory:"), client=client)
    posts = fetcher.fetch({"id": 1, "name": "大V", "external_id": "123"})
    assert [(p.external_id, p.post_type) for p in posts] == [("101", "post"), ("103", "reply")]


def test_xueqiu_cookie_refresh_on_401():
    fixture = json.loads((FIXTURES / "xueqiu_sample.json").read_text(encoding="utf-8"))
    timeline_hits = {"n": 0}

    def handler(request):
        if request.url.path == "/":
            return httpx.Response(
                200,
                headers={"set-cookie": "xq_a_token=newtoken; Path=/; Domain=.xueqiu.com"},
            )
        timeline_hits["n"] += 1
        if timeline_hits["n"] == 1:
            return httpx.Response(401)
        assert request.headers.get("Cookie", "").startswith("xq_a_token=newtoken")
        return httpx.Response(200, json=fixture)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    db = DB(":memory:")
    fetcher = XueqiuFetcher(XueqiuConfig(cookie="xq_a_token=old"), db=db, client=client)
    posts = fetcher.fetch({"id": 1, "name": "大V", "external_id": "123"})
    assert len(posts) == 2
    assert "xq_a_token=newtoken" in db.get_setting("xueqiu_cookie")


def test_extract_cube_symbol():
    assert extract_cube_symbol("https://xueqiu.com/P/ZH3623878") == "ZH3623878"
    assert extract_cube_symbol("ZH3623878") == "ZH3623878"
    assert extract_cube_symbol("  ZH123456  ") == "ZH123456"
    assert extract_cube_symbol("") == ""


def test_combination_fetch_parses_rebalancing():
    payload = {
        "list": [
            {
                "id": 237035355,
                "status": "success",
                "cash": 80.0,
                "updated_at": 1785822205799,
                "rebalancing_histories": [
                    {
                        "stock_name": "永杉锂业",
                        "stock_symbol": "SH603399",
                        "prev_weight": 21.15,
                        "target_weight": 0.0,
                    },
                    {
                        "stock_name": "贵州茅台",
                        "stock_symbol": "SH600519",
                        "prev_weight": 0.0,
                        "target_weight": 5.2,
                    },
                ],
            },
            {"id": 999, "status": "failed", "rebalancing_histories": [{"stock_name": "X"}]},
            {"id": 888, "status": "success", "rebalancing_histories": []},
        ]
    }

    search_payload = {
        "list": [
            {
                "symbol": "ZH3623878",
                "name": "伯言-A股",
                "annualized_gain_rate": 27.13,
                "net_value": 1.8472,
                "owner": {"screen_name": "伯言2020", "photo_domain": "//xavatar.imedao.com/", "profile_image_url": "community/a.jpg"},
            }
        ]
    }

    def handler(request):
        if request.url.path == "/cubes/rebalancing/history.json":
            assert request.url.params.get("cube_symbol") == "ZH3623878"
            return httpx.Response(200, json=payload)
        assert request.url.path == "/query/v1/cube/search.json"
        return httpx.Response(200, json=search_payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = CombinationFetcher(
        XueqiuConfig(cookie="xq_a_token=abc"), db=DB(":memory:"), client=client
    )
    posts = fetcher.fetch(
        {"id": 1, "name": "伯言-A股", "external_id": "https://xueqiu.com/P/ZH3623878"}
    )
    assert len(posts) == 1
    p = posts[0]
    assert p.external_id == "237035355"
    assert p.platform == "combination"
    assert p.url == "https://xueqiu.com/P/ZH3623878"
    assert "年化 27.1%" in p.content and "净值 1.847" in p.content
    assert "🗑 永杉锂业 清仓 21.1%" in p.content
    assert "➕ 贵州茅台 0.0% → 5.2%" in p.content
    assert "现金 80.0%" in p.content
    assert p.title == "伯言-A股 调仓"
    assert p.detail["actions"][0]["type"] == "清仓"
    assert p.detail["actions"][1]["type"] == "增持"
    assert p.detail["cash"] == "80.0%"


def test_xueqiu_refresh_waf_html_raises_clear_error():
    def handler(request):
        if request.url.path == "/":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text='<textarea id="renderData">waf challenge</textarea><html>',
            )
        return httpx.Response(401)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = XueqiuFetcher(XueqiuConfig(cookie="xq_a_token=old"), db=DB(":memory:"), client=client)
    try:
        fetcher.fetch({"id": 1, "name": "大V", "external_id": "123"})
    except RuntimeError as exc:
        assert "反爬" in str(exc)
        assert "手动更新" in str(exc)
        return
    raise AssertionError("WAF 拦截首页时应抛出清晰错误")


def test_xueqiu_waf_html_raises_clear_error():
    def handler(request):
        return httpx.Response(200, text="<textarea id=\"renderData\">waf challenge</textarea><html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = XueqiuFetcher(XueqiuConfig(cookie="xq_a_token=abc"), db=DB(":memory:"), client=client)
    try:
        fetcher.fetch({"id": 1, "name": "大V", "external_id": "123"})
    except RuntimeError as exc:
        assert "反爬" in str(exc)
        return
    raise AssertionError("WAF HTML 应抛出清晰错误")


from app.config import WeiboConfig
from app.fetchers.base import format_published_at
from app.fetchers.weibo import WeiboFetcher, resolve_weibo_profile


def test_format_published_at():
    assert format_published_at("1785840071000") == "2026-08-04 18:41"
    assert format_published_at("1785840071") == "2026-08-04 18:41"
    assert format_published_at("Tue Aug 04 21:00:00 +0800 2026") == "Tue Aug 04 21:00:00 +0800 2026"
    assert format_published_at("") == ""


def test_xueqiu_extract_images():
    from app.fetchers.xueqiu import _extract_images

    status = {
        "original_pictures": [
            {"url": "https://x.img/a.jpg"},
            {"url": "//x.img/b.jpg"},
        ],
        "pics": [{"url": "https://x.img/c.jpg"}],
    }
    assert _extract_images(status) == [
        "https://x.img/a.jpg",
        "https://x.img/b.jpg",
        "https://x.img/c.jpg",
    ]
    assert _extract_images({}) == []


def test_weibo_extract_images():
    from app.fetchers.weibo import extract_weibo_images

    mblog = {
        "pics": [
            {"large": {"url": "//w/p1.jpg"}},
            {"original": {"url": "https://w/p2.jpg"}},
            {"url": "https://w/p3.jpg"},
        ]
    }
    assert extract_weibo_images(mblog) == [
        "https://w/p1.jpg",
        "https://w/p2.jpg",
        "https://w/p3.jpg",
    ]
    assert extract_weibo_images({}) == []


def test_twitter_extract_images():
    from app.fetchers.twitter import extract_twitter_images

    legacy = {
        "extended_entities": {
            "media": [
                {"type": "photo", "media_url_https": "https://pbs.twimg.com/1.jpg"},
                {"type": "video", "media_url_https": "https://pbs.twimg.com/v.mp4"},
                {"type": "photo", "media_url_https": "https://pbs.twimg.com/2.jpg"},
            ]
        }
    }
    assert extract_twitter_images(legacy) == [
        "https://pbs.twimg.com/1.jpg",
        "https://pbs.twimg.com/2.jpg",
    ]
    assert extract_twitter_images({}) == []


def test_rss_resolve_x_url():
    fetcher = RssFetcher(SimpleNamespace(rsshub_base="https://rsshub.app"))
    assert (
        fetcher._resolve_feed_url("https://x.com/SemiAnalysis_")
        == "https://rsshub.app/twitter/user/SemiAnalysis_"
    )
    assert (
        fetcher._resolve_feed_url("https://twitter.com/elonmusk/")
        == "https://rsshub.app/twitter/user/elonmusk"
    )
    assert (
        fetcher._resolve_feed_url("https://rsshub.app/twitter/user/elonmusk")
        == "https://rsshub.app/twitter/user/elonmusk"
    )


def test_rss_fetch_resolves_x_and_saves_avatar():
    feed_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel>'
        '<image><url>https://pbs.twimg.com/avatar.jpg</url></image>'
        "<item><title>今日观点</title>"
        "<link>https://x.com/SemiAnalysis_/status/1</link>"
        "<description>市场动态</description>"
        "<pubDate>Tue, 04 Aug 2026 10:00:00 +0800</pubDate>"
        "</item></channel></rss>"
    ).encode()

    def handler(request):
        assert request.url.path == "/twitter/user/SemiAnalysis_"
        return httpx.Response(200, content=feed_xml, headers={"content-type": "application/rss+xml"})

    db = DB(":memory:")
    kid = db.add_kol("twitter", "SemiAnalysis", "https://x.com/SemiAnalysis_")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = RssFetcher(SimpleNamespace(rsshub_base="https://rsshub.app"), db, client=client)
    posts = fetcher.fetch(db.get_kol(kid))
    assert len(posts) == 1 and posts[0].title == "今日观点"
    assert db.get_kol(kid)["avatar_url"] == "https://pbs.twimg.com/avatar.jpg"


def test_weibo_parse_fixture():
    payload = json.loads((FIXTURES / "weibo_sample.json").read_text(encoding="utf-8"))

    def handler(request):
        assert request.headers.get("Cookie", "").startswith("SUB=")
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = WeiboFetcher(WeiboConfig(cookie="SUB=xyz"), db=DB(":memory:"), client=client)
    posts = fetcher.fetch({"id": 2, "name": "微博大V", "external_id": "1234567890"})
    assert len(posts) == 1
    assert posts[0].external_id == "M1"
    assert posts[0].url == "https://weibo.com/detail/M1"
    assert "行情" in posts[0].content


def test_resolve_weibo_profile(monkeypatch):
    class FakeResp:
        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self._data

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None):
            if "weibo.com/ajax" in url:
                return FakeResp(
                    {
                        "ok": 1,
                        "data": {
                            "user": {
                                "screen_name": "wu2198",
                                "avatar_hd": "https://wx1.sinaimg.cn/ajax.jpg",
                            }
                        },
                    }
                )
            return FakeResp(
                {
                    "ok": 1,
                    "data": {
                        "userInfo": {
                            "screen_name": "wu2198",
                            "avatar_hd": "https://wx1.sinaimg.cn/mobile.jpg",
                        }
                    },
                }
            )

    monkeypatch.setattr("httpx.Client", FakeClient)
    profile = resolve_weibo_profile("123456", cookie="SUB=xyz")
    assert profile["name"] == "wu2198"
    assert profile["avatar_url"] == "https://wx1.sinaimg.cn/ajax.jpg"

    assert resolve_weibo_profile("abc") == {}


def _make_weibo_login_mocks(fixture):
    """返回 (handler, client) —— prelogin 返回测试公钥，login 返回 retcode=0 并下发 SUB cookie。"""
    _, priv = rsa.newkeys(512)
    pubkey_hex = format(priv.n, "x")
    timeline_hits = {"n": 0}

    def handler(request):
        path = request.url.path
        if path == "/sso/prelogin.php":
            body = (
                'sinaSSOController.preloginCallBack({"retcode":0,'
                f'"pubkey":"{pubkey_hex}","nonce":"abc","rsakv":"1",'
                '"servertime":"1700000000","pcid":"pc1"})'
            )
            return httpx.Response(200, text=body)
        if path == "/sso/login.php":
            assert request.url.params["client"] == "ssologin.js(v1.4.19)"
            return httpx.Response(
                200,
                text="location.replace('https://weibo.cn/?retcode=0')",
                headers={"set-cookie": "SUB=sub123; Path=/"},
            )
        # timeline
        timeline_hits["n"] += 1
        if timeline_hits["n"] == 1:
            return httpx.Response(200, json={"ok": 0, "msg": "请先登录"})
        assert "SUB=sub123" in request.headers.get("Cookie", "")
        return httpx.Response(200, json=fixture)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return client, timeline_hits


def test_weibo_auto_login_and_retry():
    fixture = json.loads((FIXTURES / "weibo_sample.json").read_text(encoding="utf-8"))
    client, timeline_hits = _make_weibo_login_mocks(fixture)
    db = DB(":memory:")
    fetcher = WeiboFetcher(
        WeiboConfig(username="user", password="pass"),
        db=db,
        client=client,
    )
    posts = fetcher.fetch({"id": 2, "name": "微博大V", "external_id": "1234567890"})
    assert len(posts) == 1
    assert timeline_hits["n"] == 2
    assert "SUB=sub123" in db.get_setting("weibo_cookie")


def test_weibo_html_login_redirect_triggers_auto_login():
    """会话过期时接口 302 到 passport 登录页（HTML），应触发自动登录并重试。"""
    import rsa

    fixture = json.loads((FIXTURES / "weibo_sample.json").read_text(encoding="utf-8"))
    _, priv = rsa.newkeys(512)
    pubkey_hex = format(priv.n, "x")
    timeline_hits = {"n": 0}

    def handler(request):
        path = request.url.path
        if path == "/sso/prelogin.php":
            return httpx.Response(
                200,
                text=(
                    'sinaSSOController.preloginCallBack({"retcode":0,'
                    f'"pubkey":"{pubkey_hex}","nonce":"abc","rsakv":"1",'
                    '"servertime":"1700000000","pcid":"pc1"})'
                ),
            )
        if path == "/sso/login.php":
            return httpx.Response(
                200,
                text="location.replace('https://weibo.cn/?retcode=0')",
                headers={"set-cookie": "SUB=sub123; Path=/"},
            )
        if request.url.host == "passport.weibo.com":
            return httpx.Response(
                200,
                text="<html>login</html>",
                headers={"content-type": "text/html"},
            )
        timeline_hits["n"] += 1
        if timeline_hits["n"] == 1:
            return httpx.Response(
                302,
                headers={"location": "https://passport.weibo.com/sso/signin?url=x"},
            )
        return httpx.Response(200, json=fixture)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    db = DB(":memory:")
    fetcher = WeiboFetcher(WeiboConfig(username="u", password="p"), db=db, client=client)
    posts = fetcher.fetch({"id": 2, "name": "微博大V", "external_id": "123"})
    assert len(posts) == 1
    assert timeline_hits["n"] == 2
    assert "SUB=sub123" in db.get_setting("weibo_cookie")


def test_weibo_login_failure_raises():
    def handler(request):
        if request.url.path == "/sso/prelogin.php":
            _, priv = rsa.newkeys(512)
            body = (
                'sinaSSOController.preloginCallBack({"retcode":0,'
                f'"pubkey":"{format(priv.n, "x")}","nonce":"abc","rsakv":"1",'
                '"servertime":"1700000000","pcid":""})'
            )
            return httpx.Response(200, text=body)
        if request.url.path == "/sso/login.php":
            return httpx.Response(200, text="retcode=101 密码错误")
        return httpx.Response(200, json={"ok": 0, "msg": "请先登录"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = WeiboFetcher(
        WeiboConfig(username="user", password="wrong"),
        db=DB(":memory:"),
        client=client,
    )
    try:
        fetcher.fetch({"id": 2, "name": "微博大V", "external_id": "1234567890"})
    except RuntimeError as exc:
        assert "登录失败" in str(exc)
        return
    raise AssertionError("登录失败时应抛出异常")


def test_weibo_432_raises_clear_error():
    def handler(request):
        return httpx.Response(432)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = WeiboFetcher(WeiboConfig(cookie="SUB=xyz"), db=DB(":memory:"), client=client)
    try:
        fetcher.fetch({"id": 2, "name": "微博大V", "external_id": "1234567890"})
    except RuntimeError as exc:
        assert "432" in str(exc)
        return
    raise AssertionError("432 应抛出清晰错误")


def test_weibo_prelogin_missing_pubkey_raises():
    def handler(request):
        if request.url.path == "/sso/prelogin.php":
            return httpx.Response(
                200,
                text='sinaSSOController.preloginCallBack({"retcode":0,"msg":"system error","exectime":60})',
            )
        return httpx.Response(200, json={"ok": 0, "msg": "请先登录"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = WeiboFetcher(
        WeiboConfig(username="user", password="pass"),
        db=DB(":memory:"),
        client=client,
    )
    try:
        fetcher.fetch({"id": 2, "name": "微博大V", "external_id": "1234567890"})
    except RuntimeError as exc:
        assert "预登录" in str(exc)
        return
    raise AssertionError("缺 pubkey 时应抛出清晰错误")




def test_rss_parse_fixture():
    content = (FIXTURES / "rss_sample.xml").read_bytes()

    def handler(request):
        return httpx.Response(200, content=content)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = RssFetcher(client=client)
    posts = fetcher.fetch({"id": 3, "name": "X大V", "external_id": "https://rss.example/feed"})
    assert len(posts) == 1
    assert posts[0].external_id == "1"
    assert posts[0].url == "https://x.com/status/1"
    assert "world" in posts[0].content
