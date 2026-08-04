import json
from urllib.parse import parse_qs

import httpx
import pytest

from app.config import FeishuConfig, TelegramConfig
from app.fetchers.base import Post
from app.notifiers.feishu import FeishuNotifier
from app.notifiers.telegram import TelegramNotifier


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


def test_telegram_success():
    def handler(request):
        assert "api.telegram.org" in str(request.url)
        form = parse_qs(request.read().decode("utf-8"))
        assert "实盘" in form.get("text", [""])[0]
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    notifier = TelegramNotifier(
        TelegramConfig(bot_token="123:abc", chat_id="456"),
        client=client,
    )
    notifier.notify(make_post())


def test_telegram_unconfigured_raises():
    notifier = TelegramNotifier(TelegramConfig())
    with pytest.raises(RuntimeError):
        notifier.notify(make_post())
