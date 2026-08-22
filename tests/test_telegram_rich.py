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


def make_combination_post() -> Post:
    return Post(
        platform="combination",
        kol_id=2,
        kol_name="伯言-A股",
        external_id="1",
        title="伯言-A股 调仓",
        content="年化 27.1%",
        url="https://xueqiu.com/P/ZH3623878",
        published_at="2026-08-04",
        detail={
            "stats": [("年化", "27.1%"), ("净值", "1.271")],
            "actions": [
                {"type": "清仓", "stock": "永杉锂业", "symbol": "SH603399", "prev": "21.1%", "target": "0.0%"},
                {"type": "新建", "stock": "天华新能", "symbol": "SZ300390", "prev": "0.0%", "target": "20.0%"},
            ],
            "cash": "80.0%",
        },
    )


def test_combination_rich_uses_tables():
    from app.notifiers.telegram_rich import build_combination_rich_html

    html = build_combination_rich_html(make_combination_post())
    assert "<p><b>📌 伯言-A股 · 雪球组合 · 调仓</b></p>" in html
    assert "🕐 2026-08-04" in html
    assert html.count("<table") == 1
    assert "年化" in html and "27.1%" in html
    assert "清仓" in html and "永杉锂业" in html and "SH603399" in html
    assert "21.1%" in html and "0.0%" in html
    assert "💵 现金 80.0%" in html
    assert "🗑 清仓" in html and "🆕 新建" in html
    assert "查看原文" not in html


def test_single_post_rich_has_heading_paragraphs_tags():
    html = build_telegram_rich_html(make_post())
    assert "<p><b>📌 张三 · 雪球</b></p>" in html
    assert "&lt;b&gt;大涨&lt;/b&gt;" in html
    assert "今天 &lt;b&gt;大涨&lt;/b&gt;<br>第二段" in html
    assert "<hr>" not in html
    assert "<footer>" in html
    assert "宏观" in html and "白酒" in html
    assert "🗂 实盘" in html
    assert "🕐 2026-08-04" in html
    assert "查看原文" not in html
    assert "href=" not in html
    assert "<script>" not in html
    assert "🔔" not in html
    assert html.count("📌") == 1


def test_single_post_rich_marks_badges_and_reply_quote():
    post = make_post()
    post.post_type = "reply"
    html = build_telegram_rich_html(post, favorite=True, keyword=True)
    assert "🔔 特别关注" in html
    assert "🔑 命中关键词" in html
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


def test_rich_html_embeds_single_figure():
    from app.notifiers.telegram_rich import build_telegram_rich_html

    post = make_post()
    post.images = ["https://a/1.jpg"]
    html = build_telegram_rich_html(post)
    assert "<figure>" in html
    assert 'src="tg://photo?id=p0"' in html
    assert "https://a/1.jpg" not in html
    assert "<tg-collage>" not in html


def test_rich_html_embeds_collage():
    from app.notifiers.telegram_rich import build_telegram_rich_html

    post = make_post()
    post.images = [f"https://a/{i}.jpg" for i in range(12)]
    html = build_telegram_rich_html(post)
    assert "<tg-collage>" in html
    assert html.count("<img ") == 9
    assert 'src="tg://photo?id=p8"' in html
    assert "https://a/9.jpg" not in html
    assert "tg://photo?id=p9" not in html


def test_notify_with_images_sends_one_rich_message():
    sent = {}

    def handler(request):
        sent["url"] = str(request.url)
        sent.update(parse_qs(request.read().decode("utf-8")))
        return httpx.Response(200, json={"ok": True})

    from app.fetchers.base import Post
    from app.notifiers.telegram import TelegramNotifier

    post = Post(
        platform="weibo", kol_id=1, kol_name="李四", external_id="w1",
        title="t", content="c", url="https://weibo.com/1", published_at="",
        images=["https://a/1.jpg", "https://a/2.jpg"],
    )
    TelegramNotifier(
        TelegramConfig(bot_token="t", chat_id="1"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    ).notify(post)
    assert sent["url"].endswith("/sendRichMessage")
    rich = json.loads(sent["rich_message"][0])
    assert rich["html"].count("<img ") == 2
    assert rich["media"][0]["id"] == "p0"
    assert rich["media"][0]["media"]["media"] == "https://a/1.jpg"
    assert rich["media"][1]["media"]["media"] == "https://a/2.jpg"


def test_notify_images_fall_back_to_text_then_album():
    calls = []

    class Fake(TelegramNotifier):
        def _send_rich(self, html, reply_markup=None, media=None):
            calls.append(("rich", html, media))
            raise RuntimeError("no collage")

        def _send(self, data):
            calls.append(("text", data.get("text")))

        def _send_media_group(self, post):
            calls.append(("album", post.images))

    post = make_post()
    post.images = ["https://a/1.jpg", "https://a/2.jpg"]
    Fake(TelegramConfig(bot_token="t", chat_id="1"), client=httpx.Client()).notify(post)
    assert calls[0][0] == "rich" and "<tg-collage>" in calls[0][1]
    assert calls[0][2][0]["media"]["media"] == "https://a/1.jpg"
    assert calls[1][0] == "text"
    assert calls[2] == ("album", ["https://a/1.jpg", "https://a/2.jpg"])


def test_digest_rich_is_ordered_list():
    from app.notifiers.telegram_rich import build_telegram_digest_rich

    posts = [make_post(), make_post()]
    posts[1].content = "另一条"
    html = build_telegram_digest_rich(posts, "张三", "xueqiu")
    assert "<p><b>📌 张三 · 雪球</b></p>" in html
    assert "<ol>" in html and html.count("<li>") == 2
    assert "<details>" not in html


def test_digest_rich_overflow_uses_details():
    from app.notifiers.telegram_rich import DIGEST_MAX_ITEMS, build_telegram_digest_rich

    posts = [make_post() for _ in range(DIGEST_MAX_ITEMS + 3)]
    html = build_telegram_digest_rich(posts, "张三", "xueqiu")
    assert html.count("<li>") == DIGEST_MAX_ITEMS + 3
    assert "<details>" in html
    assert "还有 3 条" in html


def test_send_digest_hits_rich_and_keeps_numbered_buttons():
    sent = {}

    def handler(request):
        sent["url"] = str(request.url)
        sent.update(parse_qs(request.read().decode("utf-8")))
        return httpx.Response(200, json={"ok": True})

    from app.fetchers.base import Post
    from app.notifiers.telegram import TelegramNotifier

    def weibo_post(eid="w1") -> Post:
        return Post(
            platform="weibo", kol_id=1, kol_name="李四", external_id=eid,
            title="t", content="c", url="https://weibo.com/1", published_at="",
        )

    posts = [weibo_post("w1"), weibo_post("w2")]
    TelegramNotifier(
        TelegramConfig(bot_token="123:abc", chat_id="456"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    ).send_digest(posts, "李四", "weibo")
    assert sent["url"].endswith("/sendRichMessage")
    kb = json.loads(sent["reply_markup"][0])["inline_keyboard"]
    assert kb[0][0]["text"] == "1 🔗"


def test_dnd_rich_names_each_item():
    from app.notifiers.telegram_rich import build_telegram_dnd_rich

    html = build_telegram_dnd_rich([make_post()])
    assert "📵 免打扰时段汇总" in html
    assert "<ol>" not in html
    assert "<b>张三</b>" in html


def test_digest_single_uses_paragraphs():
    from app.notifiers.telegram_rich import build_telegram_digest_rich

    html = build_telegram_digest_rich([make_post()], "张三", "xueqiu")
    assert "<ol>" not in html
    assert "今天 &lt;b&gt;大涨&lt;/b&gt;<br>第二段" in html


def test_daily_rich_is_named_list():
    from app.notifiers.telegram_rich import build_telegram_daily_rich

    fav = make_post()
    fav.favorite = True
    fav.kol_name = "重点"
    other = make_post()
    other.kol_name = "普通"
    html = build_telegram_daily_rich([other, fav])
    assert "<p><b>📊 今日大V精选</b></p>" in html
    assert "⭐ 重点" in html
    assert "<ol>" in html
    assert "<table>" not in html
    assert html.index("重点") < html.index("普通")
    assert "<b>⭐ 重点</b>" in html
    assert "<b>普通</b>" in html
