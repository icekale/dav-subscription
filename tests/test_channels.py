"""渠道注册表：channel_bound / build_channel_notifier / deliver_post 统一分发。"""
from types import SimpleNamespace

import pytest

from app.channels import (
    CHANNELS,
    build_channel_notifier,
    channel_bound,
    channel_enabled,
    deliver_post,
)
from app.fetchers.base import Post


def make_config():
    return SimpleNamespace(
        telegram=SimpleNamespace(bot_token="t", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
        bark=SimpleNamespace(bark_server="", bark_key=""),
        webpush=SimpleNamespace(vapid_private_key="", vapid_public_key="", vapid_mailto=""),
    )


def make_user(**overrides):
    user = {
        "id": 1,
        "username": "u",
        "telegram_chat_id": "",
        "telegram_bot_token": "",
        "feishu_open_id": "",
        "feishu_chat_id": "",
        "wecom_webhook": "",
        "bark_key": "",
        "push_channels": "",
    }
    user.update(overrides)
    return user


def make_post() -> Post:
    return Post(
        platform="xueqiu", kol_id=1, kol_name="A",
        external_id="p1", title="t", content="c", url="u", published_at="",
        images=["https://img.example.com/1.jpg"],
    )


def test_channels_registry_has_all_four():
    assert CHANNELS == ("telegram", "feishu", "wecom", "bark", "webpush")


def test_channel_bound():
    cfg = make_config()
    no_bot_cfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
        bark=SimpleNamespace(),
    )
    assert not channel_bound(make_user(), "telegram", cfg)
    # 有会话但全局与自建 bot 都不可用 → 不算绑定
    assert not channel_bound(make_user(telegram_chat_id="1"), "telegram", no_bot_cfg)
    # 自建 bot 或全局 bot 任一满足即可
    assert channel_bound(make_user(telegram_chat_id="1", telegram_bot_token="x"), "telegram", no_bot_cfg)
    assert channel_bound(make_user(telegram_chat_id="1"), "telegram", cfg)
    assert channel_bound(make_user(feishu_open_id="o"), "feishu", cfg)
    assert channel_bound(make_user(feishu_chat_id="c"), "feishu", cfg)
    assert channel_bound(make_user(wecom_webhook="w"), "wecom", cfg)
    assert channel_bound(make_user(bark_key="k"), "bark", cfg)
    assert channel_bound(make_user(webpush_bound=True), "webpush", cfg)
    assert not channel_bound(make_user(), "webpush", cfg)
    assert not channel_bound(make_user(), "unknown", cfg)


def test_channel_enabled():
    u = make_user(push_channels="telegram,bark")
    assert channel_enabled(u, "telegram") and channel_enabled(u, "bark")
    assert not channel_enabled(u, "feishu")
    assert channel_enabled(make_user(), "wecom")  # 未设置默认全部启用


def test_build_channel_notifier_unbound_raises():
    cfg = make_config()
    for channel in CHANNELS:
        with pytest.raises(RuntimeError, match="未绑定"):
            build_channel_notifier(channel, make_user(), cfg)


def test_build_channel_notifier_binds_and_passes_flags(monkeypatch):
    cfg = make_config()
    seen = {}

    class Fake:
        def __init__(self, *args, **kwargs):
            seen.update(kwargs)

    for mod, channel, bind in (
        ("app.notifiers.telegram.TelegramNotifier", "telegram", {"telegram_chat_id": "1"}),
        ("app.notifiers.feishu.FeishuNotifier", "feishu", {"feishu_open_id": "o"}),
        ("app.notifiers.wecom.WeComNotifier", "wecom", {"wecom_webhook": "w"}),
        ("app.notifiers.bark.BarkNotifier", "bark", {"bark_key": "k"}),
        ("app.notifiers.webpush.WebPushNotifier", "webpush", {
            "webpush_subscriptions": [{"endpoint": "https://fcm.googleapis.com/fcm/send/x", "p256dh": "x", "auth": "x"}],
        }),
    ):
        monkeypatch.setattr(mod, Fake)
        seen.clear()
        build_channel_notifier(
            channel, make_user(**bind), cfg, favorite=True, keyword=True
        )
        assert seen.get("favorite") is True
        assert seen.get("keyword") is True  # 四个渠道都必须透传横切标记


def test_build_telegram_notifier_honors_admin_rich_flag(monkeypatch):
    cfg = make_config()
    cfg.telegram.rich_messages = True

    class Fake:
        def __init__(self, *args, **kwargs):
            self.rich_messages = True

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", Fake)
    off = SimpleNamespace(get_setting=lambda key: "0")
    n = build_channel_notifier("telegram", make_user(telegram_chat_id="1"), cfg, db=off)
    assert n.rich_messages is False
    unset = SimpleNamespace(get_setting=lambda key: None)
    n = build_channel_notifier("telegram", make_user(telegram_chat_id="1"), cfg, db=unset)
    assert n.rich_messages is True


def test_deliver_post_success_writes_log(monkeypatch):
    db = SimpleNamespace()
    notifier = SimpleNamespace(notify=lambda post: None)

    import app.channels as channels_mod

    monkeypatch.setattr(channels_mod, "build_channel_notifier", lambda *a, **k: notifier)
    logs = []
    db.add_push_log = lambda post_id, channel, status, user_id=None: logs.append(
        (post_id, channel, status, user_id)
    )
    deliver_post(
        db, 7, make_post(), make_user(), "telegram", make_config(), client=None,
        retry_queue=None, alert_notifiers=None, alert_cb=None,
    )
    assert logs == [(7, "telegram", "success", 1)]


def test_deliver_post_hides_images_in_copy_without_mutating_original(monkeypatch):
    db = SimpleNamespace(add_push_log=lambda *args, **kwargs: None)
    delivered = []

    import app.channels as channels_mod

    monkeypatch.setattr(
        channels_mod,
        "build_channel_notifier",
        lambda *args, **kwargs: SimpleNamespace(notify=delivered.append),
    )
    post = make_post()

    deliver_post(
        db, 7, post, make_user(hide_images=True), "telegram", make_config(), client=None,
    )

    assert delivered[0] is not post
    assert delivered[0].images == []
    assert post.images == ["https://img.example.com/1.jpg"]


def test_deliver_post_failure_writes_log_and_alerts(monkeypatch):
    db = SimpleNamespace()
    logs = []
    db.add_push_log = lambda post_id, channel, status, error="", user_id=None: logs.append(
        (post_id, channel, status)
    )
    alerts = []

    class Boom:
        def notify(self, post):
            raise RuntimeError("boom")

    import app.channels as channels_mod

    monkeypatch.setattr(channels_mod, "build_channel_notifier", lambda *a, **k: Boom())
    retry = SimpleNamespace(add=lambda post, channel, user_id: None)
    retry_calls = []
    retry.add = lambda post, channel, user_id: retry_calls.append((post, channel, user_id))
    post = make_post()

    deliver_post(
        db, 7, post, make_user(hide_images=True), "telegram", make_config(), client=None,
        retry_queue=retry, alert_notifiers=[], alert_cb=lambda db, notifiers, msg: alerts.append(msg),
    )
    assert any(c == "telegram" and s == "failed" for _, c, s in logs)
    assert retry_calls[0][0] is post
    assert retry_calls[0][1:] == ("telegram", 1)
    assert post.images == ["https://img.example.com/1.jpg"]
    assert alerts and "channel=telegram" in alerts[0]


def test_deliver_post_feishu_fallback_reuses_hidden_copy(monkeypatch):
    db = SimpleNamespace(add_push_log=lambda *args, **kwargs: None)
    received = []

    class FailingNotifier:
        def notify(self, post):
            received.append(post)
            raise RuntimeError("code=230101")

    class FallbackNotifier:
        def notify(self, post):
            received.append(post)

    import app.channels as channels_mod
    from app import feishu_personal

    notifiers = iter((FailingNotifier(), FallbackNotifier()))
    monkeypatch.setattr(
        channels_mod, "build_channel_notifier", lambda *args, **kwargs: next(notifiers)
    )
    monkeypatch.setattr(
        feishu_personal, "resolve_personal_target", lambda *args, **kwargs: {"chat_id": "c"}
    )
    monkeypatch.setattr(feishu_personal, "is_definitive_feishu_error", lambda exc: True)
    monkeypatch.setattr(feishu_personal, "mark_personal_degraded", lambda *args: None)
    post = make_post()

    deliver_post(
        db,
        7,
        post,
        make_user(feishu_open_id="o", hide_images=True),
        "feishu",
        make_config(),
        client=None,
    )

    assert received[0] is received[1]
    assert received[0] is not post
    assert received[0].images == []
    assert post.images == ["https://img.example.com/1.jpg"]
