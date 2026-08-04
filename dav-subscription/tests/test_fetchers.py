import json
from pathlib import Path

import httpx
import rsa

from app.config import XueqiuConfig
from app.db import DB
from app.fetchers.xueqiu import XueqiuFetcher

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
from app.fetchers.weibo import WeiboFetcher


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


def test_weibo_login_failure_raises():
    fixture = json.loads((FIXTURES / "weibo_sample.json").read_text(encoding="utf-8"))

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


from app.fetchers.rss import RssFetcher


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
