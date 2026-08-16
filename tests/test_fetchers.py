import json
import re
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import rsa

from app.config import XueqiuConfig
from app.db import DB
from app.fetchers.combination import CombinationFetcher, extract_cube_symbol
from app.fetchers.rss import RssFetcher
from app.fetchers.xueqiu import (
    XueqiuFetcher,
    _crop_watermark,
    _dewatermark_image,
    _dewatermark_images,
    _load_waf_cookies,
    classify_status,
    merge_waf_cookie,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_xueqiu_dewatermark_crops_corner(monkeypatch, tmp_path):
    """雪球图片处理不得改变画布尺寸；失败降级原 URL；仅精确官方域名处理。"""
    class FakeImage:
        size = (400, 300)

        def copy(self):
            return self

    # 兼容函数不得改变画布或像素对象。
    img = FakeImage()
    assert _crop_watermark(img) is img

    # 水印与正文同层，无法可靠移除时保留原图，不再下载和破坏像素。
    monkeypatch.setattr(
        "app.fetchers.xueqiu.httpx.get",
        lambda url, **kw: (_ for _ in ()).throw(AssertionError("不应下载处理")),
    )
    original = "https://xqimg.imedao.com/abc.png"
    assert _dewatermark_image(original, tmp_path) == original

    db_fake = SimpleNamespace(path=str(tmp_path / "db.sqlite"))
    out_list = _dewatermark_images(
        [
            "https://xqimg.imedao.com/zz.png",
            "https://other.example.com/a.jpg?next=xqimg.imedao.com",
            "https://xqimg.imedao.com.evil.test/a.jpg",
        ], db_fake
    )
    assert out_list == [
        "https://xqimg.imedao.com/zz.png",
        "https://other.example.com/a.jpg?next=xqimg.imedao.com",
        "https://xqimg.imedao.com.evil.test/a.jpg",
    ]


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


def test_xueqiu_waf_cookie_merged_into_request(monkeypatch, tmp_path):
    """waf-bot 写的整套通关 cookie 整体使用：请求 cookie 与文件一致（含 acw_tc）。"""
    waf_file = tmp_path / "waf_cookies.json"
    waf_file.write_text(
        json.dumps(
            {
                "fetched_at": 1786289000,
                "seed_sha256": __import__("hashlib").sha256(
                    b"xq_a_token=abc; u=123"
                ).hexdigest(),
                "cookies": [
                    {"name": "acw_tc", "value": "NEW_ACW"},
                    {"name": "u", "value": "999"},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.fetchers.xueqiu.WAF_COOKIE_FILE", str(waf_file))

    seen: dict[str, str] = {}

    def handler(request):
        seen["cookie"] = request.headers.get("Cookie", "")
        return httpx.Response(200, json={"statuses": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = XueqiuFetcher(XueqiuConfig(cookie="xq_a_token=abc; u=123"), db=DB(":memory:"), client=client)
    fetcher.fetch({"id": 1, "name": "大V", "external_id": "123"})
    cookie = seen["cookie"]
    assert "acw_tc=NEW_ACW" in cookie
    assert "u=999" in cookie
    assert "xq_a_token=abc" not in cookie  # 整套覆盖，不再 merge 旧登录态


def test_xueqiu_waf_cookie_missing_falls_back(monkeypatch, tmp_path):
    """waf-bot 文件缺失时退回原配置 cookie，不报错。"""
    monkeypatch.setattr("app.fetchers.xueqiu.WAF_COOKIE_FILE", str(tmp_path / "nope.json"))
    assert _load_waf_cookies() == []


def test_xueqiu_waf_cookie_from_old_seed_does_not_override_new_login_cookie(monkeypatch, tmp_path):
    import hashlib

    old_cookie = "xq_a_token=old"
    new_cookie = "xq_a_token=new"
    waf_file = tmp_path / "waf_cookies.json"
    waf_file.write_text(
        json.dumps({
            "seed_sha256": hashlib.sha256(old_cookie.encode()).hexdigest(),
            "cookies": [{"name": "acw_tc", "value": "challenge"}],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.fetchers.xueqiu.WAF_COOKIE_FILE", str(waf_file))
    assert merge_waf_cookie(new_cookie) == new_cookie

    seen: dict[str, str] = {}

    def handler(request):
        seen["cookie"] = request.headers.get("Cookie", "")
        return httpx.Response(200, json={"statuses": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = XueqiuFetcher(XueqiuConfig(cookie="xq_a_token=abc"), db=DB(":memory:"), client=client)
    fetcher.fetch({"id": 1, "name": "大V", "external_id": "123"})
    assert seen["cookie"] == "xq_a_token=abc"


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


def test_xueqiu_uses_full_text_for_truncated_long_post():
    """时间线 description 截断（尾部 ...）时，用同响应的 text 完整字段补全。"""
    payload = {
        "statuses": [
            {
                "id": 201,
                "title": "",
                "description": (
                    "关于明年1.6T有没有加单，今天问的比较多。我们的信息比较早，"
                    "对市场来说是新信息，对我们来讲不一定是新信息。我们的观点，"
                    "请参考7/24 9:30我们给各位推送的观点。总结说就是基本面一直在上行，"
                    "订单一直在上修，但是很多投资者担忧大的..."
                ),
                "text": (
                    "关于明年1.6T有没有加单，今天问的比较多。我们的信息比较早，"
                    "对市场来说是新信息，对我们来讲不一定是新信息。我们的观点，"
                    "请参考7/24 9:30我们给各位推送的观点。总结说就是基本面一直在上行，"
                    "订单一直在上修，但是很多投资者担忧大的。完整结尾在这里。"
                ),
                "target": "/201",
            }
        ]
    }

    def handler(request):
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = XueqiuFetcher(XueqiuConfig(cookie="xq_a_token=abc"), db=DB(":memory:"), client=client)
    posts = fetcher.fetch({"id": 1, "name": "大V", "external_id": "123"})
    assert len(posts) == 1
    assert "完整结尾在这里" in posts[0].content
    assert not posts[0].content.endswith("...")


def test_xueqiu_truncated_post_without_text_keeps_description():
    """text 字段缺失时退回截断的 description，不报错。"""
    payload = {
        "statuses": [
            {
                "id": 202,
                "title": "",
                "description": "这段被截断了，没有 text 字段兜底...",
                "text": "",
                "target": "/202",
            }
        ]
    }

    def handler(request):
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = XueqiuFetcher(XueqiuConfig(cookie="xq_a_token=abc"), db=DB(":memory:"), client=client)
    posts = fetcher.fetch({"id": 1, "name": "大V", "external_id": "123"})
    assert posts[0].content == "这段被截断了，没有 text 字段兜底..."


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


def test_xueqiu_fetch_full_text_for_truncated_long_post():
    """长文截断时用时间线同响应的 text 字段补全（详情接口 show.json 已下线）。"""
    def handler(request):
        return httpx.Response(
            200,
            json={
                "statuses": [
                    {
                        "id": 101,
                        "description": "时间线里的截断长文……",
                        "text": "这是完整的长文正文，远超时间线截断长度。",
                        "target": "/101",
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = XueqiuFetcher(XueqiuConfig(cookie="xq_a_token=abc"), db=DB(":memory:"), client=client)
    posts = fetcher.fetch({"id": 1, "name": "大V", "external_id": "123"})
    assert posts[0].content == "这是完整的长文正文，远超时间线截断长度。"


def test_xueqiu_cookie_expired_401_raises_clear_error():
    """401（会话失效）→ 抛清晰错误，不再访问已死续期的首页，也不重试。"""
    homepage_hits = {"n": 0}

    def handler(request):
        if request.url.path == "/":
            homepage_hits["n"] += 1
            return httpx.Response(200, text="homepage")
        return httpx.Response(401)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    db = DB(":memory:")
    fetcher = XueqiuFetcher(XueqiuConfig(cookie="xq_a_token=old"), db=db, client=client)
    try:
        fetcher.fetch({"id": 1, "name": "大V", "external_id": "123"})
    except RuntimeError as exc:
        assert "cookie 已失效" in str(exc)
        assert "手动更新" in str(exc)
    else:
        raise AssertionError("401 时应抛出 cookie 失效错误")
    assert homepage_hits["n"] == 0  # 首页续期通道已废弃，不应再访问
    assert db.get_setting("xueqiu_cookie") is None  # 不写入任何新 cookie


def test_xueqiu_cookie_expired_keeps_stored_cookie():
    """会话失效抛错时，数据库里已保存的 cookie 不能被覆盖或清除。"""
    fixture = json.loads((FIXTURES / "xueqiu_sample.json").read_text(encoding="utf-8"))

    def handler(request):
        return httpx.Response(401)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    db = DB(":memory:")
    db.set_setting("xueqiu_cookie", "xq_a_token=goodtoken; u=2964068165; device_id=d1")
    fetcher = XueqiuFetcher(
        XueqiuConfig(cookie="xq_a_token=old; u=2964068165; device_id=d1"),
        db=db,
        client=client,
    )
    try:
        fetcher.fetch({"id": 1, "name": "大V", "external_id": "123"})
    except RuntimeError:
        pass
    else:
        raise AssertionError("401 时应抛出 cookie 失效错误")
    assert fixture  # 引用 fixture 保持导入一致性
    saved = db.get_setting("xueqiu_cookie")
    assert "xq_a_token=goodtoken" in saved
    assert "u=2964068165" in saved and "device_id=d1" in saved


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
                "cash": 80.0,  # 伪值：100 − Σ变动targets
                "cash_value": 0.0,  # 真实现金：净值 1.8472 → 0.0%
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
                    # 未变动持仓（全量快照记录会列出），应被跳过
                    {
                        "stock_name": "中国平安",
                        "stock_symbol": "SH601318",
                        "prev_weight": 30.0,
                        "target_weight": 30.0,
                    },
                ],
            },
            {
                "id": 236548180,
                "status": "success",
                "cash": 100.0,  # 伪值
                "cash_value": 0.4618,  # 真实现金：净值 1.8472 → 25.0%
                "updated_at": 1785000000000,
                "rebalancing_histories": [
                    {
                        "stock_name": "三星电子",
                        "stock_symbol": "KRX005930",
                        "prev_weight": 25.0,
                        "target_weight": 0.0,
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

    quote_payload = {"data": {"net_value": 1.8472, "day_percent_gain": 0.55}}
    holdings_payload = {
        "data": {
            "holdings": [
                {"stock_name": "贵州茅台", "stock_symbol": "SH600519", "weight": 5.2},
                {"stock_name": "中国平安", "stock_symbol": "SH601318", "weight": 30.0},
            ]
        }
    }
    nav_payload = [
        {
            "symbol": "ZH3623878",
            "name": "伯言-A股",
            "list": [
                {"time": 1785000000000, "date": "2026-07-01", "value": 1.8000, "percent": 80.0},
                {"time": 1785086400000, "date": "2026-07-02", "value": 1.8472, "percent": 84.7},
            ],
        },
        {"symbol": "SH000300", "name": "沪深300", "list": [{"date": "2026-07-02", "value": 4000.0}]},
    ]

    def handler(request):
        if request.url.path == "/cubes/rebalancing/history.json":
            assert request.url.params.get("cube_symbol") == "ZH3623878"
            return httpx.Response(200, json=payload)
        if request.url.path == "/cubes/quote.json":
            return httpx.Response(200, json=quote_payload)
        if request.url.path == "/cubes/rebalancing/current.json":
            return httpx.Response(200, json=holdings_payload)
        if request.url.path == "/cubes/nav_daily/all.json":
            return httpx.Response(200, json=nav_payload)
        assert request.url.path == "/query/v1/cube/search.json"
        return httpx.Response(200, json=search_payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = CombinationFetcher(
        XueqiuConfig(cookie="xq_a_token=abc"), db=DB(":memory:"), client=client
    )
    posts = fetcher.fetch(
        {"id": 1, "name": "伯言-A股", "external_id": "https://xueqiu.com/P/ZH3623878"}
    )
    assert len(posts) == 2
    p = posts[0]
    assert p.external_id == "237035355"
    assert p.platform == "combination"
    assert p.url == "https://xueqiu.com/P/ZH3623878"
    assert "年化 27.1%" in p.content and "净值 1.847" in p.content
    # 调仓卡附当日涨跌（quote 快照，取 fetch 前刷新到的最新值）
    assert "今日 +0.55%" in p.content
    assert p.detail["stats"][0] == ("今日", "+0.55%")
    assert "🗑 永杉锂业 清仓 21.1%" in p.content
    assert "➕ 贵州茅台 0.0% → 5.2%" in p.content
    # 现金取 cash_value/净值（真实现金 0.0%），不显示接口伪值 80.0%
    assert "现金 0.0%" in p.content and "现金 80.0%" not in p.content
    # 未变动持仓（中国平安 30.0% → 30.0%）不渲染
    assert "中国平安" not in p.content
    assert p.title == "伯言-A股 调仓"
    assert p.detail["actions"][0]["type"] == "清仓"
    assert p.detail["actions"][1]["type"] == "增持"
    assert len(p.detail["actions"]) == 2  # 未变动行不入 actions
    assert p.detail["cash"] == "0.0%"
    # 第二笔：真实现金非零（清仓 25% 后现金 25.0%），不显示伪值 100.0%
    assert "现金 25.0%" in posts[1].content and "现金 100.0%" not in posts[1].content
    assert posts[1].detail["cash"] == "25.0%"


def test_combination_snapshots_stored_and_ttl_skips_refetch():
    """快照写入 cube_snapshots；TTL 内第二轮 fetch 不再请求雪球快照接口。"""
    counts = {"quote": 0, "current": 0, "nav": 0}
    rebalancing_payload = {"list": []}  # 无新调仓，仍应刷新快照

    def handler(request):
        path = request.url.path
        if path == "/cubes/rebalancing/history.json":
            return httpx.Response(200, json=rebalancing_payload)
        if path == "/cubes/quote.json":
            counts["quote"] += 1
            return httpx.Response(200, json={"data": {"net_value": 1.5, "day_percent_gain": -0.32}})
        if path == "/cubes/rebalancing/current.json":
            counts["current"] += 1
            return httpx.Response(200, json={"data": [{"stock_name": "贵州茅台", "stock_symbol": "SH600519", "weight": 10.0}]})
        if path == "/cubes/nav_daily/all.json":
            counts["nav"] += 1
            return httpx.Response(200, json=[{"symbol": "ZH1", "name": "n", "list": [{"date": "2026-07-01", "value": 1.0}]}])
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    db = DB(":memory:")
    fetcher = CombinationFetcher(XueqiuConfig(cookie="xq_a_token=abc"), db=db, client=client)
    kol = {"id": 7, "name": "测试组合", "external_id": "ZH000007"}

    fetcher.fetch(kol)
    assert counts == {"quote": 1, "current": 1, "nav": 1}
    snap = db.get_cube_snapshot(7, "holdings")
    assert snap and snap["payload"] == [{"name": "贵州茅台", "symbol": "SH600519", "weight": 10.0}]
    snap = db.get_cube_snapshot(7, "nav")
    assert snap and snap["payload"] == [{"date": "2026-07-01", "value": 1.0}]
    snap = db.get_cube_snapshot(7, "quote")
    assert snap and snap["payload"]["day_percent_gain"] == -0.32

    fetcher.fetch(kol)  # TTL 内：快照接口不再请求，只请求调仓历史
    assert counts == {"quote": 1, "current": 1, "nav": 1}


def test_cube_snapshot_fresh_uses_real_timestamps():
    """回归：strftime 返回文本，与整数比较恒真导致快照永不刷新（见 2026-08 生产事故）。"""
    db = DB(":memory:")
    db.set_cube_snapshot(1, "quote", {"net_value": 1.0})
    assert db.cube_snapshot_fresh(1, "quote", 60)  # 刚写入：fresh
    # 把 fetched_at 改成 10 分钟前（模拟 TTL 过期）
    db._execute(
        "UPDATE cube_snapshots SET fetched_at = datetime('now', '-10 minutes') "
        "WHERE kol_id = 1 AND kind = 'quote'"
    )
    assert not db.cube_snapshot_fresh(1, "quote", 60)  # 过期：不 fresh
    assert db.cube_snapshot_fresh(1, "quote", 3600)  # 但 1 小时 TTL 内仍 fresh
    assert not db.cube_snapshot_fresh(2, "quote", 60)  # 无行：不 fresh


def test_combination_snapshot_failure_does_not_break_rebalancing():
    """快照接口失败（WAF/超时）只记日志，调仓推送照常。"""
    payload = {
        "list": [
            {
                "id": 1,
                "status": "success",
                "cash": 0.0,
                "cash_value": 0.0,
                "updated_at": 1785822205799,
                "rebalancing_histories": [
                    {"stock_name": "贵州茅台", "stock_symbol": "SH600519", "prev_weight": None, "target_weight": 5.2}
                ],
            }
        ]
    }

    def handler(request):
        path = request.url.path
        if path == "/cubes/rebalancing/history.json":
            return httpx.Response(200, json=payload)
        if path == "/query/v1/cube/search.json":
            return httpx.Response(200, json={"list": []})
        raise AssertionError(f"快照接口不应被重试：{path}")  # 作为异常抛出，验证被吞

    client = httpx.Client(transport=httpx.MockTransport(handler))
    db = DB(":memory:")
    fetcher = CombinationFetcher(XueqiuConfig(cookie="xq_a_token=abc"), db=db, client=client)
    posts = fetcher.fetch({"id": 1, "name": "伯言-A股", "external_id": "ZH3623878"})
    assert len(posts) == 1
    assert "🆕 贵州茅台 新建 5.2%" in posts[0].content
    # 无 quote 快照：不显示今日涨跌，调仓卡其余信息完整
    assert "今日" not in posts[0].content
    assert db.get_cube_snapshot(1, "quote") is None


def test_combination_parse_helpers_accept_known_shapes():
    from app.fetchers.combination import parse_holdings, parse_nav, parse_quote

    # quote：直接对象 / data 包装 / percent 兜底 / 实测顶层 {symbol: {...}} + 字符串值
    assert parse_quote({"net_value": 1.2, "day_percent_gain": 0.5}) == {
        "net_value": 1.2,
        "day_percent_gain": 0.5,
    }
    assert parse_quote({"data": {"net_value": 1.2, "percent": 0.5}})["day_percent_gain"] == 0.5
    real = parse_quote(
        {"ZH3623878": {"symbol": "ZH3623878", "net_value": "1.4207", "daily_gain": "2.35"}}
    )
    assert real == {"net_value": 1.4207, "day_percent_gain": 2.35}
    assert parse_quote({"ZH3623878": {"net_value": "abc", "daily_gain": "x"}}) == {
        "net_value": None,
        "day_percent_gain": None,
    }
    assert parse_quote({}).get("day_percent_gain") is None

    # holdings：顶层数组 / data 数组 / data.holdings / last_rb.holdings（真实结构）/ 缺 weight 行跳过
    assert parse_holdings([{"stock_name": "A", "weight": 3.5}]) == [{"name": "A", "symbol": "", "weight": 3.5}]
    assert parse_holdings({"data": {"holdings": [{"stock_name": "B", "stock_symbol": "SH600000", "weight": 1.0}]}})[0]["symbol"] == "SH600000"
    assert parse_holdings({"data": [{"stock_name": "C", "target_weight": 2.0}]})[0]["weight"] == 2.0
    # 实测结构：{"last_rb": {"holdings": [...]}}
    real = parse_holdings({"last_rb": {"holdings": [{"stock_name": "康龙化成", "stock_symbol": "SZ300759", "weight": 16.07}]}})
    assert real == [{"name": "康龙化成", "symbol": "SZ300759", "weight": 16.07}]
    assert parse_holdings([{"stock_name": "无权重"}]) == []
    assert parse_holdings(None) == []

    # nav：取第一个元素（组合自身）的 list，跳过基准与异常行
    series = parse_nav(
        [
            {"symbol": "ZH1", "name": "n", "list": [{"date": "2026-07-01", "value": 1.0}, {"date": "bad", "value": "x"}]},
            {"symbol": "SH000300", "name": "基准", "list": [{"date": "2026-07-01", "value": 4000.0}]},
        ]
    )
    assert series == [{"date": "2026-07-01", "value": 1.0}]
    assert parse_nav({}) == []
    assert parse_nav([]) == []


def test_xueqiu_cookie_expired_403_raises_clear_error():
    """403 与 401 同为会话失效，抛同样的清晰错误（403 不再走首页续期）。"""

    def handler(request):
        if request.url.path == "/":
            raise AssertionError("首页续期通道已废弃，不应再访问")
        return httpx.Response(403)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = XueqiuFetcher(XueqiuConfig(cookie="xq_a_token=old"), db=DB(":memory:"), client=client)
    try:
        fetcher.fetch({"id": 1, "name": "大V", "external_id": "123"})
    except RuntimeError as exc:
        assert "手动更新" in str(exc)
        return
    raise AssertionError("403 时应抛出清晰错误")


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
    assert format_published_at("Tue Aug 04 21:00:00 +0800 2026") == "2026-08-04 21:00"
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
    # 新版接口：pic 字段逗号分隔 + !thumb 缩略图后缀
    assert _extract_images(
        {
            "pic": (
                "https://x.img/a.jpg!thumb.jpg,"
                "//x.img/b.jpg!thumb.jpg,"
                "https://x.img/c.jpg!thumb.jpg"
            )
        }
    ) == ["https://x.img/a.jpg", "https://x.img/b.jpg", "https://x.img/c.jpg"]


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
    # mymblog 接口格式：pic_ids + pic_infos
    mblog2 = {
        "pic_ids": ["pid1", "pid2"],
        "pic_infos": {
            "pid1": {"original": {"url": "//w/o1.jpg"}, "large": {"url": "//w/l1.jpg"}},
            "pid2": {"mw690": {"url": "https://w/m2.jpg"}},
        },
    }
    assert extract_weibo_images(mblog2) == ["https://w/o1.jpg", "https://w/m2.jpg"]
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
    import datetime
    import email.utils

    recent = email.utils.format_datetime(
        datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=10)
    )
    feed_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel>'
        '<image><url>https://pbs.twimg.com/avatar.jpg</url></image>'
        "<item><title>今日观点</title>"
        "<link>https://x.com/SemiAnalysis_/status/1</link>"
        "<description>市场动态</description>"
        f"<pubDate>{recent}</pubDate>"
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
    assert posts[0].external_id == "1"  # URL 归一化为数字 tweet id，与直抓一致去重
    assert db.get_kol(kid)["avatar_url"] == "https://pbs.twimg.com/avatar.jpg"


def test_rss_normalize_twitter_id():
    fetcher = RssFetcher(SimpleNamespace(rsshub_base="https://rsshub.app"))
    assert (
        fetcher._normalize_twitter_id("https://twitter.com/SemiAnalysis_/status/2085154080037429715")
        == "2085154080037429715"
    )
    assert (
        fetcher._normalize_twitter_id("https://x.com/@foo/status/12345")
        == "12345"
    )
    # 非 URL 原样返回（其它 RSS 源）
    assert fetcher._normalize_twitter_id("abc123") == "abc123"


def test_rss_fetch_skips_stale_entries():
    import datetime
    import email.utils

    fresh = email.utils.format_datetime(
        datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)
    )
    stale = email.utils.format_datetime(
        datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=200)
    )
    feed_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel>'
        f"<item><title>新帖</title><link>https://x.com/A/status/101</link><pubDate>{fresh}</pubDate></item>"
        f"<item><title>老帖</title><link>https://x.com/A/status/102</link><pubDate>{stale}</pubDate></item>"
        "</channel></rss>"
    ).encode()

    def handler(request):
        return httpx.Response(200, content=feed_xml, headers={"content-type": "application/rss+xml"})

    db = DB(":memory:")
    kid = db.add_kol("twitter", "A", "https://x.com/A")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = RssFetcher(SimpleNamespace(rsshub_base="https://rsshub.app"), db, client=client)
    posts = fetcher.fetch(db.get_kol(kid))
    assert [p.external_id for p in posts] == ["101"]  # 200 天前的旧帖被跳过


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
    assert posts[0].published_at == "2026-08-04 21:00"


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


def test_weibo_login_failure_sets_cooldown():
    """登录失败后记录冷却时间戳，冷却期内不再打登录接口。"""
    db = DB(":memory:")
    login_hits = {"n": 0}

    def handler(request):
        if request.url.path == "/sso/prelogin.php":
            _, priv = rsa.newkeys(512)
            return httpx.Response(
                200,
                text=(
                    'sinaSSOController.preloginCallBack({"retcode":0,'
                    f'"pubkey":"{format(priv.n, "x")}","nonce":"abc","rsakv":"1",'
                    '"servertime":"1700000000","pcid":""})'
                ),
            )
        if request.url.path == "/sso/login.php":
            login_hits["n"] += 1
            return httpx.Response(200, text="retcode=101 密码错误")
        return httpx.Response(200, json={"ok": 0, "msg": "请先登录"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = WeiboFetcher(WeiboConfig(username="user", password="wrong"), db=db, client=client)
    try:
        fetcher.fetch({"id": 2, "name": "微博大V", "external_id": "1234567890"})
    except RuntimeError:
        pass
    else:
        raise AssertionError("登录失败时应抛出异常")
    assert login_hits["n"] == 1
    assert db.get_setting("weibo_login_last_attempt_at")  # 冷却时间戳已写

    # 冷却期内再次抓取：不再调用登录接口，直接报「冷却中」
    try:
        fetcher.fetch({"id": 2, "name": "微博大V", "external_id": "1234567890"})
    except RuntimeError as exc:
        assert "冷却" in str(exc)
    else:
        raise AssertionError("冷却期内应报冷却错误")
    assert login_hits["n"] == 1  # 登录接口未再被打

    # 冷却过期后恢复尝试
    db.set_setting("weibo_login_last_attempt_at", str(int(time.time()) - 31 * 60))
    try:
        fetcher.fetch({"id": 2, "name": "微博大V", "external_id": "1234567890"})
    except RuntimeError:
        pass
    else:
        raise AssertionError("恢复后登录仍应失败并抛异常")
    assert login_hits["n"] == 2  # 恢复后重新尝试登录


def test_weibo_login_success_clears_cooldown():
    """登录成功后清空冷却标记，后续抓取正常走登录流程。"""
    db = DB(":memory:")
    client, _ = _make_weibo_login_mocks(
        json.loads((FIXTURES / "weibo_sample.json").read_text(encoding="utf-8"))
    )
    db.set_setting("weibo_login_last_attempt_at", str(int(time.time()) - 31 * 60))  # 冷却已过
    fetcher = WeiboFetcher(WeiboConfig(username="user", password="pass"), db=db, client=client)
    posts = fetcher.fetch({"id": 2, "name": "微博大V", "external_id": "1234567890"})
    assert len(posts) == 1
    assert db.get_setting("weibo_login_last_attempt_at") in (None, "")  # 冷却标记已清


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
    import datetime
    import email.utils

    content = (FIXTURES / "rss_sample.xml").read_bytes()
    # fixture 的 pubDate 是固定旧日期，换成当前时间避免触发陈旧过滤
    fresh = email.utils.format_datetime(
        datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)
    )
    content = re.sub(rb"<pubDate>[^<]*</pubDate>", f"<pubDate>{fresh}</pubDate>".encode(), content)

    def handler(request):
        return httpx.Response(200, content=content)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = RssFetcher(client=client)
    posts = fetcher.fetch({"id": 3, "name": "X大V", "external_id": "https://rss.example/feed"})
    assert len(posts) == 1
    assert posts[0].external_id == "1"
    assert posts[0].url == "https://x.com/status/1"
    assert "world" in posts[0].content


def test_weibo_login_lock_serializes(monkeypatch):
    """并发触发登录时同一时刻只有一个登录流程在跑。"""
    import threading
    import time
    from typing import ClassVar

    from app.fetchers.weibo import WeiboFetcher

    db = DB(":memory:")
    cfg = SimpleNamespace(cookie="", token="", username="u", password="p")
    fetcher = WeiboFetcher(cfg, db)

    counter = {"active": 0, "max_active": 0, "calls": 0}
    cl = threading.Lock()

    def fake_prelogin(self):
        with cl:
            counter["active"] += 1
            counter["max_active"] = max(counter["max_active"], counter["active"])
            counter["calls"] += 1
        time.sleep(0.05)
        with cl:
            counter["active"] -= 1
        return {"pcid": "", "rsakv": "", "servertime": "1", "nonce": "n", "pubkey": "1"}

    class FakeCookie:
        name = "SUB"
        value = "x"
        domain = "weibo.com"

    class FakeCookies:
        jar: ClassVar[list] = [FakeCookie()]

        def get(self, name, default=None):
            return "x" if name == "SUB" else default

    class FakeClient:
        cookies = FakeCookies()

        def post(self, *a, **k):
            return httpx.Response(
                200,
                text="callback(retcode=0)",
                request=httpx.Request("POST", "https://login.sina.com.cn/sso/login.php"),
            )

    monkeypatch.setattr(WeiboFetcher, "_prelogin", fake_prelogin)
    monkeypatch.setattr(
        WeiboFetcher, "_encrypt_password", staticmethod(lambda pwd, pub, nonce: "enc")
    )
    fetcher.client = FakeClient()

    threads = [threading.Thread(target=fetcher._login) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert counter["calls"] == 2
    assert counter["max_active"] == 1  # 串行：无并发登录


def test_normalize_xueqiu_id():
    from app.fetchers.xueqiu import normalize_xueqiu_id

    # URL 形式 → 提取数字 ID
    assert normalize_xueqiu_id("https://xueqiu.com/u/4514680565") == "4514680565"
    assert normalize_xueqiu_id("https://xueqiu.com/u/4514680565/") == "4514680565"
    assert normalize_xueqiu_id("https://www.xueqiu.com/u/123") == "123"
    assert normalize_xueqiu_id("https://xueqiu.com/u/123?foo=bar") == "123"
    # 纯数字原样
    assert normalize_xueqiu_id("4514680565") == "4514680565"
    # 无法识别时原样返回（保留原错误信息），不抛异常
    assert normalize_xueqiu_id("https://xueqiu.com/Syedc") == "https://xueqiu.com/Syedc"
    assert normalize_xueqiu_id("") == ""
    assert normalize_xueqiu_id(None) == ""


def test_shared_fetchers_use_thread_local_http_clients():
    """同平台并发 worker 不得共享一个 httpx.Client。"""
    from app.fetchers.weibo import WeiboFetcher

    cfg = SimpleNamespace(cookie="", token="")
    fetchers = [
        XueqiuFetcher(XueqiuConfig(), db=None),
        WeiboFetcher(cfg, db=None),
        CombinationFetcher(cfg, db=None),
    ]
    for fetcher in fetchers:
        ids = []

        def grab(f=fetcher):
            ids.append(id(f.client))

        t1 = threading.Thread(target=grab)
        t2 = threading.Thread(target=grab)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert len(set(ids)) == 2, type(fetcher).__name__
