import json
from urllib.parse import parse_qs

import httpx

from app import logging_setup
from app.config import TelegramConfig
from app.fetchers.base import Post
from app.notifiers.telegram import TelegramNotifier
from app.notifiers.telegram_rich import build_telegram_rich_html


def make_post() -> Post:
    return Post(
        platform="xueqiu",
        kol_id=1,
        kol_name="张三",
        external_id="1",
        title="看多",
        content="今天 <b>大涨</b>\n第二段",
        url="https://xueqiu.com/1",
        published_at="2026-08-04",
        category="实盘",
        tags=["宏观", "白酒"],
    )


def test_single_post_rich_has_heading_paragraphs_tags():
    html = build_telegram_rich_html(make_post())
    assert "<h2>" in html and "张三" in html and "雪球" in html
    assert "&lt;b&gt;大涨&lt;/b&gt;" in html
    assert "<p>第二段</p>" in html
    assert "<hr>" in html
    assert "宏观" in html and "白酒" in html
    assert "实盘" in html
    assert 'href="https://xueqiu.com/1"' in html
    assert "<script>" not in html


def test_single_post_rich_marks_badges_and_reply_quote():
    post = make_post()
    post.post_type = "reply"
    html = build_telegram_rich_html(post, favorite=True, keyword=True)
    assert "特别关注" in html
    assert "命中关键词" in html
    assert "回复" in html
    assert "<blockquote>" in html


def test_zsxq_rich_omits_original_link():
    post = make_post()
    post.platform = "zsxq"
    post.url = "https://wx.zsxq.com/1"
    html = build_telegram_rich_html(post)
    assert "查看原文" not in html
    assert "href=" not in html


def _form(request) -> dict:
    return parse_qs(request.read().decode("utf-8"))


def test_deliver_uses_send_rich_message():
    sent = {}

    def handler(request):
        sent["url"] = str(request.url)
        sent.update(_form(request))
        return httpx.Response(200, json={"ok": True})

    tg = TelegramNotifier(
        TelegramConfig(bot_token="123:abc", chat_id="456"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    tg._deliver("<h2>x</h2>", fallback_text="<b>x</b>", reply_markup=[[{"text": "🔗 查看原文", "url": "https://weibo.com/1"}]])
    assert sent["url"].endswith("/sendRichMessage")
    rich = json.loads(sent["rich_message"][0])
    assert rich["html"] == "<h2>x</h2>"
    assert rich["skip_entity_detection"] is True
    assert "parse_mode" not in sent
    kb = json.loads(sent["reply_markup"][0])
    assert kb["inline_keyboard"][0][0]["url"] == "https://weibo.com/1"


def test_deliver_falls_back_to_send_message_on_rich_error():
    urls = []
    fallback_form = {}

    def handler(request):
        urls.append(str(request.url))
        if "sendRichMessage" in str(request.url):
            return httpx.Response(200, json={"ok": False, "error_code": 400, "description": "Bad Request"})
        fallback_form.update(_form(request))
        return httpx.Response(200, json={"ok": True})

    tg = TelegramNotifier(
        TelegramConfig(bot_token="123:abc", chat_id="456"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    tg._deliver("<h2>x</h2>", fallback_text="<b>x</b>")
    assert any(u.endswith("/sendRichMessage") for u in urls)
    assert any(u.endswith("/sendMessage") for u in urls)
    assert "inline_keyboard" in json.loads(fallback_form["reply_markup"][0])


def test_deliver_skips_rich_when_flag_off():
    urls = []

    def handler(request):
        urls.append(str(request.url))
        form = _form(request)
        assert form.get("text") == ["<b>x</b>"]
        assert form.get("parse_mode") == ["HTML"]
        assert "inline_keyboard" in json.loads(form["reply_markup"][0])
        return httpx.Response(200, json={"ok": True})

    tg = TelegramNotifier(
        TelegramConfig(bot_token="123:abc", chat_id="456", rich_messages=False),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    tg._deliver("<h2>x</h2>", fallback_text="<b>x</b>")
    assert urls and all(u.endswith("/sendMessage") for u in urls)


def test_deliver_http_error_fallback_does_not_log_bot_token():
    logging_setup.setup_logging("DEBUG")
    token = "123456:secret-token"
    urls = []

    def handler(request):
        urls.append(str(request.url))
        if "sendRichMessage" in str(request.url):
            return httpx.Response(400, json={"ok": False, "description": "Bad Request"})
        return httpx.Response(200, json={"ok": True})

    tg = TelegramNotifier(
        TelegramConfig(bot_token=token, chat_id="456"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    tg._deliver("<h2>x</h2>", fallback_text="<b>x</b>")
    assert any(u.endswith("/sendRichMessage") for u in urls)
    assert any(u.endswith("/sendMessage") for u in urls)
    assert token not in "\n".join(logging_setup.recent_logs(limit=500))
