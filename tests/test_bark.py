"""Bark 推送通道：key 校验、文本构建、通知器调用（MockTransport）。"""
from urllib.parse import unquote

import httpx
import pytest

from app.fetchers.base import Post
from app.notifiers.bark import (
    BarkNotifier,
    _normalize_key,
    build_bark_combination_text,
    build_bark_digest,
    build_bark_dnd_summary,
    build_bark_text,
    is_valid_bark_key,
)


def make_post() -> Post:
    return Post(
        platform="xueqiu",
        kol_id=1,
        kol_name="张三",
        external_id="p1",
        title="标题",
        content="正文内容\n第二行",
        url="https://xueqiu.com/1/2",
        published_at="2026-08-07 10:00:00",
        category="实盘",
    )


def make_combination_post() -> Post:
    return Post(
        platform="combination",
        kol_id=1,
        kol_name="张三",
        external_id="c1",
        title="调仓",
        content="",
        url="https://xueqiu.com/P/1",
        published_at="",
        detail={
            "stats": [["总收益", "+20.1%"]],
            "actions": [
                {"type": "增持", "stock": "贵州茅台", "symbol": "600519", "prev": "10.0%", "target": "12.5%"}
            ],
            "cash": "5.2%",
        },
    )


# ---- key 校验与归一化 ----
def test_is_valid_bark_key():
    assert is_valid_bark_key("AaBbCcDdEeFf1234567890")
    assert is_valid_bark_key("ABC-def_GHI-123456")
    assert not is_valid_bark_key("short")
    assert not is_valid_bark_key("")
    assert not is_valid_bark_key("带中文的key")
    # 完整 URL 写法
    assert is_valid_bark_key("https://api.day.app/AaBbCcDdEeFf123456")
    assert is_valid_bark_key("http://bark.local/AaBbCcDdEeFf123456")


def test_normalize_key():
    server, key = _normalize_key("AaBbCcDdEeFf1234567890")
    assert server == "https://api.day.app"
    assert key == "AaBbCcDdEeFf1234567890"
    server, key = _normalize_key("https://bark.example.com/AaBbCcDdEeFf123456")
    assert server == "https://bark.example.com"
    assert key == "AaBbCcDdEeFf123456"
    with pytest.raises(RuntimeError):
        _normalize_key("bad")


# ---- 文本构建 ----
def test_build_bark_text():
    text = build_bark_text(make_post())
    assert "张三" in text and "雪球" in text
    assert "正文内容" in text and "第二行" in text
    assert "实盘" in text
    assert "🔗 https://xueqiu.com/1/2" in text


def test_build_bark_text_marks():
    post = make_post()
    assert "⭐ " in build_bark_text(post, favorite=True)
    assert "🔑 " in build_bark_text(post, keyword=True)
    assert "🔑 " in build_bark_text(post, favorite=True, keyword=True)


def test_build_bark_combination_text():
    text = build_bark_combination_text(make_combination_post())
    assert "调仓" in text and "总收益 +20.1%" in text
    assert "增持" in text and "贵州茅台" in text and "600519" in text
    assert "10.0% → 12.5%" in text
    assert "💵 现金 5.2%" in text


def test_build_bark_digest_and_dnd():
    posts = [make_post(), make_post()]
    digest = build_bark_digest(posts, "张三", "xueqiu")
    assert "2 条新动态" in digest and "1. " in digest and "2. " in digest
    dnd = build_bark_dnd_summary(posts)
    assert "免打扰时段汇总" in dnd and "张三" in dnd


# ---- 通知器 ----
def test_bark_notify_success():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"code": 200, "message": "success"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    notifier = BarkNotifier(bark_key="AaBbCcDdEeFf1234567890", client=client)
    notifier.notify(make_post())
    assert "api.day.app/AaBbCcDdEeFf1234567890" in captured["url"]
    assert "group=dav" in captured["url"]
    # 中文标题/正文被 URL 编码
    assert "张三" in unquote(captured["url"])
    assert "正文内容" in unquote(captured["url"])


def test_bark_notify_bark_error_raises():
    def handler(request):
        return httpx.Response(200, json={"code": 400, "message": "bad key"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    notifier = BarkNotifier(bark_key="AaBbCcDdEeFf1234567890", client=client)
    with pytest.raises(RuntimeError, match="bad key"):
        notifier.notify(make_post())


def test_bark_notify_missing_key_raises():
    notifier = BarkNotifier(bark_key="", client=httpx.Client())
    with pytest.raises(RuntimeError, match="未配置 Bark key"):
        notifier.notify(make_post())


def test_bark_digest_and_dnd_summary_flows():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"code": 200})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    notifier = BarkNotifier(bark_key="AaBbCcDdEeFf1234567890", client=client)
    notifier.send_digest([make_post()], "张三", "xueqiu")
    notifier.send_dnd_summary([make_post()])
    notifier.send_text("第一行标题\n第二行正文")
    assert len(calls) == 3
    assert "新动态" in unquote(calls[0])
    assert "免打扰时段汇总" in unquote(calls[1])
    assert "第一行标题" in unquote(calls[2])
    assert "第二行正文" in unquote(calls[2])


def test_bark_custom_server_from_config():
    from types import SimpleNamespace

    def handler(request):
        return httpx.Response(200, json={"code": 200})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    notifier = BarkNotifier(
        config=SimpleNamespace(bark_server="https://bark.example.com"),
        bark_key="AaBbCcDdEeFf1234567890",
        client=client,
    )
    captured = {}

    def handler2(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"code": 200})

    notifier.client = httpx.Client(transport=httpx.MockTransport(handler2))
    notifier.notify(make_post())
    assert "bark.example.com" in captured["url"]
