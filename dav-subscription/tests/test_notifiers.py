import json
from urllib.parse import parse_qs

import httpx
import pytest

from app.config import FeishuConfig, TelegramConfig
from app.fetchers.base import Post
from app.notifiers.feishu import FeishuNotifier
from app.notifiers.feishu import build_feishu_digest_card
from app.notifiers.telegram import TelegramNotifier
from app.notifiers.telegram import build_telegram_digest


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


def test_telegram_unconfigured_raises():
    notifier = TelegramNotifier(TelegramConfig())
    with pytest.raises(RuntimeError):
        notifier.notify(make_post())


def test_telegram_unsub_button():
    sent = {}

    def handler(request):
        form = parse_qs(request.read().decode("utf-8"))
        sent.update(form)
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    notifier = TelegramNotifier(
        TelegramConfig(bot_token="123:abc", chat_id="456"),
        client=client,
        unsub_kol_id=7,
    )
    notifier.notify(make_post())
    markup = sent["reply_markup"][0]
    assert "退订" in markup and '"callback_data": "unsub:7"' in markup


def test_feishu_unsub_button():
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
        unsub_kol_id=7,
    )
    notifier.notify(make_post())
    body = sent["calls"][-1]
    assert "退订" in body and '"kol_id\\": 7' in body


def test_digest_builders():
    posts = [make_post(), make_post()]
    posts[0].external_id = "w1"
    posts[1].external_id = "w2"
    posts[1].content = "d"

    text = build_telegram_digest(posts, "李四", "weibo")
    assert "📌 李四 · 微博" in text and "2 条新动态" in text and "1." in text and "2." in text

    card = build_feishu_digest_card(posts, "李四", "weibo")
    assert "2 条新动态" in card["header"]["title"]["content"]
    assert len(card["elements"]) >= 2
