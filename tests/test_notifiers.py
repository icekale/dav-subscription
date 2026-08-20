import json
import time
from urllib.parse import parse_qs

import httpx
import pytest

from app.config import FeishuConfig, TelegramConfig, WeComConfig
from app.fetchers.base import Post
from app.notifiers.feishu import FeishuNotifier, build_feishu_digest_card
from app.notifiers.telegram import (
    TelegramNotifier,
    _RateLimiter,
    _tg_rate_limiter,
    build_telegram_digest,
)
from app.notifiers.wecom import (
    WeComNotifier,
    build_wecom_daily,
    build_wecom_digest,
    build_wecom_dnd_summary,
    is_valid_wecom_webhook,
)


def make_post() -> Post:
    return Post(
        platform="weibo",
        kol_id=1,
        kol_name="李四",
        external_id="w1",
        title="t",
        content="c",
        url="https://weibo.com/1",
        published_at="",
        category="实盘",
    )


def test_feishu_success():
    def handler(request):
        payload = json.loads(request.read())
        assert "open.feishu.cn" in str(request.url)
        assert "实盘" in json.dumps(payload, ensure_ascii=False)
        return httpx.Response(200, json={"code": 0, "msg": "success"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    notifier = FeishuNotifier(
        FeishuConfig(webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/x"),
        client=client,
    )
    notifier.notify(make_post())  # 不抛异常即成功


def test_feishu_business_error_raises():
    def handler(request):
        return httpx.Response(200, json={"code": 19001, "msg": "bad"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    notifier = FeishuNotifier(
        FeishuConfig(webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/x"),
        client=client,
    )
    with pytest.raises(RuntimeError):
        notifier.notify(make_post())


def test_feishu_app_send_open_id_and_chat_id():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if "tenant_access_token" in str(request.url):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "tok"})
        return httpx.Response(200, json={"code": 0, "msg": "success"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    cfg = FeishuConfig(app_id="a", app_secret="s")

    FeishuNotifier(cfg, client=client, open_id="ou_test").notify(make_post())
    assert any("receive_id_type=open_id" in u for u in calls)

    calls.clear()
    FeishuNotifier(cfg, client=client, chat_id="oc_test").notify(make_post())
    assert any("receive_id_type=chat_id" in u for u in calls)

    # 未配置凭据时报错
    try:
        FeishuNotifier(FeishuConfig(), client=client, open_id="ou_test").notify(make_post())
    except RuntimeError as exc:
        assert "凭据" in str(exc)
        return
    raise AssertionError("未配置凭据应报错")


def test_telegram_success():
    sent = {}

    def handler(request):
        assert "api.telegram.org" in str(request.url)
        form = parse_qs(request.read().decode("utf-8"))
        assert "实盘" in form.get("text", [""])[0]
        assert "<b>📌 李四 · 微博</b>" in form.get("text", [""])[0]
        # 头部已包含大V信息，正文不再重复出现「📌 李四 · 微博」这一行
        text = form.get("text", [""])[0]
        assert text.count("📌 李四 · 微博") == 1
        # 卡片式：带「查看原文」内联按钮
        assert "查看原文" in form.get("reply_markup", [""])[0]
        assert '"url": "https://weibo.com/1"' in form.get("reply_markup", [""])[0]
        sent.update(form)
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    notifier = TelegramNotifier(
        TelegramConfig(bot_token="123:abc", chat_id="456"),
        client=client,
    )
    notifier.notify(make_post())
    assert "reply_markup" in sent


def test_telegram_text_marks_favorite():
    from app.notifiers.telegram import build_telegram_text

    assert "特别关注" in build_telegram_text(make_post(), favorite=True)
    assert "特别关注" not in build_telegram_text(make_post())


def test_telegram_text_marks_keyword():
    from app.notifiers.telegram import build_telegram_text

    assert "命中关键词" in build_telegram_text(make_post(), keyword=True)
    assert "命中关键词" not in build_telegram_text(make_post())
    assert "命中关键词" in build_telegram_text(make_post(), favorite=True, keyword=True)


def test_feishu_card_marks_favorite():
    from app.notifiers.feishu import build_feishu_card

    card = build_feishu_card(make_post(), favorite=True)
    body = json.dumps(card["card"], ensure_ascii=False)
    assert "特别关注" in body
    assert "特别关注" not in json.dumps(
        build_feishu_card(make_post())["card"], ensure_ascii=False
    )


def test_feishu_card_summary_for_notification():
    # schema 2.0 + config.summary：控制聊天列表预览与手机推送通知正文
    from app.notifiers.feishu import build_feishu_card

    card = build_feishu_card(make_post(), favorite=True)["card"]
    assert card["schema"] == "2.0"
    summary = card["config"]["summary"]["content"]
    assert "李四" in summary and "c" in summary
    assert len(summary) <= 120


def test_feishu_batch_cards_have_summary_and_schema():
    from app.notifiers.feishu import (
        build_feishu_combination_card,
        build_feishu_daily_card,
        build_feishu_digest_card,
        build_feishu_dnd_summary_card,
    )

    post = make_post()
    cards = [
        build_feishu_combination_card(post)["card"],
        build_feishu_digest_card([post], "李四", "weibo"),
        build_feishu_daily_card([post]),
        build_feishu_dnd_summary_card([post]),
    ]
    for card in cards:
        assert card["schema"] == "2.0"
        assert "summary" in card["config"]
        assert card["config"]["summary"]["content"]
        assert len(card["config"]["summary"]["content"]) <= 120


def test_feishu_combination_card_summary_uses_stats():
    from app.notifiers.feishu import build_feishu_combination_card

    post = make_post()
    post.platform = "combination"
    post.detail = {
        "stats": [("总资产", "100万"), ("当日收益", "+1.2%")],
        "actions": [{"type": "增持", "stock": "腾讯", "symbol": "00700"}],
        "cash": "5万",
    }
    summary = build_feishu_combination_card(post)["card"]["config"]["summary"]["content"]
    assert "总资产" in summary and "当日收益" in summary

    post.detail = {"stats": [], "actions": [{"type": "清仓", "stock": "茅台"}], "cash": ""}
    summary2 = build_feishu_combination_card(post)["card"]["config"]["summary"]["content"]
    assert "清仓" in summary2 and "茅台" in summary2


def test_telegram_unconfigured_raises():
    notifier = TelegramNotifier(TelegramConfig())
    with pytest.raises(RuntimeError):
        notifier.notify(make_post())


def test_telegram_notify_retries_once_on_transient_error():
    # 瞬时网络故障（如 TLS 握手超时）应换新请求立即重试一次，而不是直接失败
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("_ssl.c:993: The handshake operation timed out")
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    notifier = TelegramNotifier(
        TelegramConfig(bot_token="123:abc", chat_id="456"),
        client=client,
    )
    notifier.notify(make_post())  # 不抛异常即重试成功
    assert len(calls) == 2


def test_telegram_notify_raises_after_retry_still_fails():
    def handler(request):
        raise httpx.ConnectError("still down")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    notifier = TelegramNotifier(
        TelegramConfig(bot_token="123:abc", chat_id="456"),
        client=client,
    )
    with pytest.raises(httpx.ConnectError):
        notifier.notify(make_post())


def test_telegram_notify_has_no_manage_buttons():
    sent = {}

    def handler(request):
        form = parse_qs(request.read().decode("utf-8"))
        sent.update(form)
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    notifier = TelegramNotifier(
        TelegramConfig(bot_token="123:abc", chat_id="456"),
        client=client,
    )
    notifier.notify(make_post())
    markup = sent["reply_markup"][0]
    assert "查看原文" in markup
    assert "退订" not in markup
    assert "unsub:" not in markup and "sec:" not in markup
    assert "设为次要" not in markup and "取消次要" not in markup


def test_telegram_digest_per_post_buttons():
    sent = {}

    def handler(request):
        form = parse_qs(request.read().decode("utf-8"))
        sent.update(form)
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    notifier = TelegramNotifier(
        TelegramConfig(bot_token="123:abc", chat_id="456"),
        client=client,
    )
    posts = [make_post(), make_post()]
    posts[1].external_id = "w2"
    notifier.send_digest(posts, "李四", "weibo")
    kb = json.loads(sent["reply_markup"][0])["inline_keyboard"]
    assert kb[0][0]["text"] == "1 🔗" and kb[0][0]["url"] == "https://weibo.com/1"
    assert kb[0][1]["text"] == "2 🔗" and kb[0][1]["url"] == "https://weibo.com/1"
    assert not any(b.get("callback_data") for row in kb for b in row)


def test_telegram_notify_sends_text_then_image_album():
    calls = []

    class FakeTelegram(TelegramNotifier):
        def _send(self, data):
            calls.append(("text", data.get("text")))

        def _send_media_group(self, post):
            calls.append(("album", post.images))

    tg = FakeTelegram(
        TelegramConfig(bot_token="t", chat_id="1"),
        client=httpx.Client(),
    )
    post = make_post()
    post.images = ["https://a/1.jpg", "https://a/2.jpg"]
    tg.notify(post)
    assert calls == [
        ("text", calls[0][1]),
        ("album", ["https://a/1.jpg", "https://a/2.jpg"]),
    ]
    assert "📌" in calls[0][1] and "查看原文" in calls[0][1]


def test_telegram_image_album_fails_falls_back_to_photo():
    calls = []

    class FakeTelegram(TelegramNotifier):
        def _send(self, data):
            calls.append(("text", data.get("text")))

        def _send_media_group(self, post):
            raise RuntimeError("album fail")

        def _send_photo_url(self, photo_url, caption=""):
            calls.append(("photo", photo_url))

    tg = FakeTelegram(
        TelegramConfig(bot_token="t", chat_id="1"),
        client=httpx.Client(),
    )
    post = make_post()
    post.images = ["https://a/1.jpg"]
    tg.notify(post)
    assert calls[0][0] == "text"
    assert calls[1] == ("photo", "https://a/1.jpg")


def test_feishu_notify_adds_images(monkeypatch):
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"code": 0, "msg": "success"}))
    )
    notifier = FeishuNotifier(
        FeishuConfig(
            app_id="a",
            app_secret="s",
            webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/x",
        ),
        client=client,
    )
    post = make_post()
    post.images = ["https://a/1.jpg"]
    monkeypatch.setattr(notifier, "_upload_images", lambda urls: ["img_key_1"])
    card_sent = {}
    monkeypatch.setattr(notifier, "_send_card", lambda card: card_sent.update(card=card))

    notifier.notify(post)

    assert any(
        el.get("tag") == "img" and el.get("img_key") == "img_key_1"
        for el in card_sent["card"]["body"]["elements"]
    )


def test_feishu_dnd_summary_card_structure():
    from app.notifiers.feishu import build_feishu_dnd_summary_card

    card = build_feishu_dnd_summary_card([make_post()])
    assert {"config", "header", "body"} <= set(card.keys())
    assert "免打扰" in card["header"]["title"]["content"]
    assert card["body"]["elements"]


def test_feishu_dnd_overflow_uses_v2_div_not_note():
    # schema 2.0 已移除 note；超过 DND_MAX_ITEMS 时必须用 _more_note（div）
    from app.notifiers.feishu import DND_MAX_ITEMS, build_feishu_dnd_summary_card

    posts = [make_post() for _ in range(DND_MAX_ITEMS + 1)]
    elements = build_feishu_dnd_summary_card(posts)["body"]["elements"]
    assert all(el.get("tag") != "note" for el in elements)
    more = next(el for el in elements if "还有" in json.dumps(el, ensure_ascii=False))
    assert more["tag"] == "div"
    assert more["text"]["text_size"] == "notation"


def test_daily_and_dnd_summaries_mark_truncated():
    from app.notifiers.feishu import (
        build_feishu_daily_card,
        build_feishu_dnd_summary_card,
    )
    from app.notifiers.telegram import build_telegram_daily, build_telegram_dnd_summary

    long_post = make_post()
    long_post.content = "长" * 300
    short_post = make_post()
    short_post.content = "短"

    assert "…" in build_telegram_daily([long_post])
    assert "…" in build_telegram_dnd_summary([long_post])
    assert "…" not in build_telegram_daily([short_post])

    assert "…" in build_feishu_daily_card([long_post])["body"]["elements"][0]["text"]["content"]
    assert "…" in build_feishu_dnd_summary_card([long_post])["body"]["elements"][0]["text"]["content"]
    assert "…" not in build_feishu_daily_card([short_post])["body"]["elements"][0]["text"]["content"]

    assert "…" in build_wecom_daily([long_post])
    assert "…" in build_wecom_dnd_summary([long_post])
    assert "…" not in build_wecom_daily([short_post])


def test_feishu_send_dnd_summary():
    def handler(request):
        payload = json.loads(request.read())
        assert "免打扰" in json.dumps(payload, ensure_ascii=False)
        return httpx.Response(200, json={"code": 0, "msg": "success"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    notifier = FeishuNotifier(
        FeishuConfig(webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/x"),
        client=client,
    )
    notifier.send_dnd_summary([make_post()])


def test_telegram_rate_limiter_smooths_burst():
    limiter = _RateLimiter(max_per_second=5)
    started = time.monotonic()
    for _ in range(20):
        limiter.wait()
    elapsed = time.monotonic() - started
    # 20 条按 5 条/秒需要至少 3 秒
    assert elapsed >= 2.8


def test_telegram_rate_limiter_free_flow_under_limit():
    limiter = _RateLimiter(max_per_second=100)
    started = time.monotonic()
    for _ in range(20):
        limiter.wait()
    assert time.monotonic() - started < 0.5


def test_telegram_429_retry_once():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                200,
                json={"ok": False, "error_code": 429, "parameters": {"retry_after": 0}},
            )
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    notifier = TelegramNotifier(
        TelegramConfig(bot_token="123:abc", chat_id="456"),
        client=client,
    )
    notifier.send_text("hi")
    assert calls["n"] == 2


def test_tg_limiter_is_shared_singleton():
    # 全局限速器是进程级单例，所有 TG 发送共享额度
    assert _tg_rate_limiter is not None and isinstance(_tg_rate_limiter, _RateLimiter)


def test_wecom_success():
    sent = {}

    def handler(request):
        payload = json.loads(request.read())
        assert "qyapi.weixin.qq.com" in str(request.url)
        assert payload["msgtype"] == "markdown"
        content = payload["markdown"]["content"]
        assert "**📌 李四 · 微博**" in content
        assert "实盘" in content
        assert "[查看原文](https://weibo.com/1)" in content
        sent.update(payload)
        return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    notifier = WeComNotifier(
        WeComConfig(webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x"),
        client=client,
    )
    notifier.notify(make_post())
    assert sent["msgtype"] == "markdown"


def test_wecom_business_error_raises():
    def handler(request):
        return httpx.Response(200, json={"errcode": 45009, "errmsg": "rate limited"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    notifier = WeComNotifier(
        WeComConfig(webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x"),
        client=client,
    )
    with pytest.raises(RuntimeError, match="企业微信"):
        notifier.notify(make_post())


def test_wecom_unconfigured_raises():
    notifier = WeComNotifier(WeComConfig())
    with pytest.raises(RuntimeError):
        notifier.notify(make_post())


def test_wecom_digest_and_webhook_validation():
    posts = [make_post(), make_post()]
    text = build_wecom_digest(posts, "李四", "weibo")
    assert "（2 条新动态）" in text
    assert "[查看原文](https://weibo.com/1)" in text
    assert is_valid_wecom_webhook("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc") is True
    assert is_valid_wecom_webhook("https://example.com/hook") is False
    assert is_valid_wecom_webhook("") is False


def test_feishu_notify_has_no_manage_buttons():
    sent = {}

    def handler(request):
        sent.setdefault("calls", []).append(request.read().decode("utf-8"))
        if "tenant_access_token" in str(request.url):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "tok"})
        return httpx.Response(200, json={"code": 0, "msg": "success"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    notifier = FeishuNotifier(
        FeishuConfig(app_id="a", app_secret="s"),
        client=client,
        open_id="ou_1",
    )
    notifier.notify(make_post())
    body = sent["calls"][-1]
    assert "查看原文" in body
    assert "退订" not in body
    assert "设为次要" not in body and "取消次要" not in body


def test_feishu_digest_has_no_manage_buttons():
    sent = {}

    def handler(request):
        sent.setdefault("calls", []).append(request.read().decode("utf-8"))
        if "tenant_access_token" in str(request.url):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "tok"})
        return httpx.Response(200, json={"code": 0, "msg": "success"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    notifier = FeishuNotifier(
        FeishuConfig(app_id="a", app_secret="s"),
        client=client,
        open_id="ou_1",
    )
    notifier.send_digest([make_post()], "李四", "weibo")
    body = sent["calls"][-1]
    assert "查看原文" in body
    assert "退订" not in body
    assert "设为次要" not in body and "取消次要" not in body


def test_digest_builders():
    posts = [make_post(), make_post()]
    posts[0].external_id = "w1"
    posts[1].external_id = "w2"
    posts[1].content = "d"

    text = build_telegram_digest(posts, "李四", "weibo")
    assert "📌 李四 · 微博" in text and "2 条新动态" in text and "1." in text and "2." in text

    card = build_feishu_digest_card(posts, "李四", "weibo")
    assert "2 条新动态" in card["header"]["title"]["content"]
    assert len(card["body"]["elements"]) >= 2

    # 单条动态不加序号，避免出现孤立的 "1."
    single = [posts[0]]
    text1 = build_telegram_digest(single, "李四", "weibo")
    assert "（1 条新动态）" in text1 and "1." not in text1
    assert "\n1. " not in text1

    card1 = build_feishu_digest_card(single, "李四", "weibo")
    assert "（1 条新动态）" in card1["header"]["title"]["content"]
    body1 = card1["body"]["elements"][0]["text"]["content"]
    assert not body1.startswith("1. ")
    button1 = card1["body"]["elements"][1]["text"]["content"]
    assert button1 == "查看原文"

    text_w1 = build_wecom_digest(single, "李四", "weibo")
    assert "（1 条新动态）" in text_w1 and "\n1. " not in text_w1


def test_digest_single_item_shows_full_content():
    # 单条摘要显示完整正文，不再截到 120 字
    single = [make_post()]
    long = "今天市场高开低走，" * 30  # 300 字长文
    single[0].content = long
    for text in (build_telegram_digest(single, "李四", "weibo"),):
        assert "（1 条新动态）" in text
        assert long[:120] in text
        assert "…" not in text

    card = build_feishu_digest_card(single, "李四", "weibo")
    body1 = card["body"]["elements"][0]["text"]["content"]
    assert long[:120] in body1 and "…" not in body1

    wtext = build_wecom_digest(single, "李四", "weibo")
    assert long[:120] in wtext and "…" not in wtext


def test_digest_multi_item_marks_truncated_preview():
    # 多条摘要保留 120 字预览，截断处补省略号，避免"看起来没发完"
    posts = [make_post(), make_post()]
    posts[0].content = "长" * 300
    posts[1].content = "短"

    text = build_telegram_digest(posts, "李四", "weibo")
    assert "…" in text

    card = build_feishu_digest_card(posts, "李四", "weibo")
    assert "…" in card["body"]["elements"][0]["text"]["content"]

    wtext = build_wecom_digest(posts, "李四", "weibo")
    assert "…" in wtext
