import json
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import httpx

from app.config import FeishuConfig, NotifiersConfig, TelegramConfig
from app.db import DB
from app.fetchers.base import Post
from app.scheduler import (
    PushRetryQueue,
    Scheduler,
    _polling_bool,
    _polling_setting,
    extract_tweet_id,
    flush_digest,
    keepalive_weibo_cookie,
    keepalive_xueqiu_cookie,
    maybe_alert_x_fallback,
    notify_subscribers,
    parse_twitter_cookie,
    poll_once,
    translate_text,
)


class FakeFetcher:
    def __init__(self, posts):
        self.posts = posts

    def fetch(self, kol):
        return self.posts


class FakeFetcherError:
    def fetch(self, kol):
        raise RuntimeError("boom")


class FakeNotifier:
    channel = "test"

    def __init__(self):
        self.calls = []
        self.texts = []

    def notify(self, post):
        self.calls.append(post)

    def send_text(self, text):
        self.texts.append(text)


class FakeDigestNotifier(FakeNotifier):
    channel = "digest"

    def __init__(self):
        super().__init__()
        self.digests = []

    def send_digest(self, posts, kol_name, platform):
        self.digests.append((posts, kol_name, platform))


class FailAlwaysNotifier(FakeNotifier):
    channel = "test"

    def notify(self, post):
        raise RuntimeError("boom")


class FakeDailyNotifier(FakeNotifier):
    channel = "telegram"

    def __init__(self):
        super().__init__()
        self.daily = []
        self.client = SimpleNamespace(close=lambda: None)

    def send_daily(self, posts):
        self.daily.append(posts)


def make_db() -> DB:
    tmp = tempfile.mkdtemp()
    return DB(Path(tmp) / "test.db")


def make_post(kol_id):
    return Post(
        platform="xueqiu",
        kol_id=kol_id,
        kol_name="A",
        external_id="p1",
        title="t",
        content="c",
        url="u",
        published_at="",
    )


def test_new_post_pushed_once(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    cid = db.add_category("实盘")
    db.update_kol(kid, category_id=cid)
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_subscription(uid, kid)
    post = make_post(kid)
    calls = []

    class FakeTG:
        def __init__(self, config, chat_id=None, client=None, **kwargs):
            calls.append(("init", chat_id))
            self.client = SimpleNamespace(close=lambda: None)
            self.channel = "telegram"

        def notify(self, post):
            calls.append(("notify", post.external_id, post.category))

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FakeTG)
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="t", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
    )

    poll_once(db, {"xueqiu": FakeFetcher([post])}, [], notifiers_config=ncfg)
    assert ("notify", post.external_id, "实盘") in calls
    assert len(db.list_posts()) == 1
    assert db.list_push_logs()[0]["status"] == "success"

    poll_once(db, {"xueqiu": FakeFetcher([post])}, [], notifiers_config=ncfg)
    assert calls.count(("notify", post.external_id, "实盘")) == 1
    assert len(db.list_posts()) == 1


def test_fetch_error_does_not_crash():
    db = make_db()
    db.add_kol("xueqiu", "A", "1")
    notifier = FakeNotifier()
    poll_once(db, {"xueqiu": FakeFetcherError()}, [notifier])
    assert len(db.list_posts()) == 0
    assert len(notifier.calls) == 0


def test_maybe_alert_x_fallback_once_per_episode():
    db = make_db()
    notifier = FakeNotifier()
    db.set_setting("x_direct_last_fallback_at", str(int(time.time())))
    db.set_setting("x_direct_fallback_reason", "HTTP 401")

    maybe_alert_x_fallback(db, [notifier])
    assert len(notifier.texts) == 1
    assert "HTTP 401" in notifier.texts[0]

    # 同一降级事件不会重复告警
    maybe_alert_x_fallback(db, [notifier])
    assert len(notifier.texts) == 1

    # 新的降级事件（时间更新）且已过冷却期后再次告警
    db.set_setting("x_direct_alert_at", str(int(time.time()) - 7 * 3600))
    db.set_setting("x_direct_last_fallback_at", str(int(time.time()) + 60))
    maybe_alert_x_fallback(db, [notifier])
    assert len(notifier.texts) == 2


def test_poll_once_fetches_platforms_concurrently():
    db = make_db()
    kids = {}
    for platform in ("xueqiu", "weibo", "twitter"):
        kids[platform] = db.add_kol(platform, platform, platform)
    lock = threading.Lock()
    stats = {"active": 0, "max": 0}

    def make_fetcher(post):
        class SlowFetcher:
            def fetch(self, kol):
                with lock:
                    stats["active"] += 1
                    stats["max"] = max(stats["max"], stats["active"])
                time.sleep(0.15)
                with lock:
                    stats["active"] -= 1
                return [post]

        return SlowFetcher()

    posts = [
        Post(
            platform=platform,
            kol_id=kid,
            kol_name=platform,
            external_id=f"p{i}",
            title="t",
            content="c",
            url="u",
            published_at="",
        )
        for i, (platform, kid) in enumerate(kids.items(), 1)
    ]
    fetchers = {
        "xueqiu": make_fetcher(posts[0]),
        "weibo": make_fetcher(posts[1]),
        "twitter": make_fetcher(posts[2]),
    }
    poll_once(db, fetchers, [])
    # 跨平台并行抓取：峰值并发应大于 1（串行时为 1）
    assert stats["max"] >= 2
    assert len(db.list_posts()) == 3


def test_posts_pushed_in_time_order(monkeypatch):
    db = make_db()
    kid = db.add_kol("weibo", "A", "1")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_subscription(uid, kid)
    # 抓取返回乱序（置顶/接口顺序），发布时间为三种不同格式
    posts = [
        Post(
            platform="weibo", kol_id=kid, kol_name="A",
            external_id="p3", title="t3", content="c", url="u",
            published_at="2026-08-04 21:00:00",
        ),
        Post(
            platform="weibo", kol_id=kid, kol_name="A",
            external_id="p1", title="t1", content="c", url="u",
            published_at="Tue Aug 04 20:00:00 +0800 2026",
        ),
        Post(
            platform="weibo", kol_id=kid, kol_name="A",
            external_id="p2", title="t2", content="c", url="u",
            published_at="Tue, 04 Aug 2026 20:30:00 +0800",
        ),
    ]
    order = []

    class FakeTG:
        def __init__(self, config, chat_id=None, client=None, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)

        def notify(self, post):
            order.append(post.external_id)

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FakeTG)
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="t", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
    )
    poll_once(db, {"weibo": FakeFetcher(posts)}, [], notifiers_config=ncfg)
    assert order == ["p1", "p2", "p3"]


def test_private_kol_subscribers_acl_filtered():
    db = make_db()
    kid = db.add_kol("xueqiu", "私有大V", "1")
    db.update_kol(kid, is_private=True)
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_subscription(uid, kid)
    # 不在白名单的订阅者不会收到推送
    assert db.subscribers_of_kol(kid) == []
    db.set_kol_acl(kid, [uid])
    assert [u["id"] for u in db.subscribers_of_kol(kid)] == [uid]


def test_subscribers_include_feishu_chat_only():
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("fs_chat", "h", feishu_chat_id="oc_chat1")
    db.add_subscription(uid, kid)
    # 只绑了飞书 p2p 会话、没有 open_id 的用户也要收到推送
    assert [u["id"] for u in db.subscribers_of_kol(kid)] == [uid]
    # 每日精选同样纳入此类用户
    assert db.daily_report_users() == []
    db.update_user(uid, daily_report=1)
    assert [u["id"] for u in db.daily_report_users()] == [uid]


def test_notify_subscribers_feishu_chat_only(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("fs_chat", "h", feishu_chat_id="oc_chat1")
    db.add_subscription(uid, kid)
    post = Post(
        platform="xueqiu", kol_id=kid, kol_name="A",
        external_id="p1", title="t", content="c", url="u", published_at="",
    )
    sent = {"ok": False}

    class FakeFS:
        def __init__(self, *args, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)
            self.channel = "feishu"

        def notify(self, post):
            sent["ok"] = True

    notifiers_config = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="", chat_id=""),
        feishu=SimpleNamespace(),
    )
    monkeypatch.setattr("app.notifiers.feishu.FeishuNotifier", FakeFS)
    notify_subscribers(db, 1, post, notifiers_config, notifiers=[], retry_queue=None)
    assert sent["ok"] is True


def test_notify_subscribers_wecom_webhook_only(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("wc_user", "h")
    db.update_user(uid, wecom_webhook="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=wc1")
    db.add_subscription(uid, kid)
    post = Post(
        platform="xueqiu", kol_id=kid, kol_name="A",
        external_id="p1", title="t", content="c", url="u", published_at="",
    )
    sent = {"ok": False}

    class FakeWC:
        def __init__(self, *args, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)
            self.channel = "wecom"

        def notify(self, post):
            sent["ok"] = True

    notifiers_config = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
    )
    monkeypatch.setattr("app.notifiers.wecom.WeComNotifier", FakeWC)
    notify_subscribers(db, 1, post, notifiers_config, notifiers=[], retry_queue=None)
    assert sent["ok"] is True


def test_notify_subscribers_uses_custom_tg_bot_token(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("tg_user", "h", telegram_chat_id="999")
    db.update_user(uid, telegram_bot_token="123:custom")
    db.add_subscription(uid, kid)
    post = Post(
        platform="xueqiu", kol_id=kid, kol_name="A",
        external_id="p1", title="t", content="c", url="u", published_at="",
    )
    received = {}

    class FakeTG:
        def __init__(self, *args, **kwargs):
            received.update(kwargs)
            self.client = SimpleNamespace(close=lambda: None)
            self.channel = "telegram"

        def notify(self, post):
            pass

    notifiers_config = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="shared", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
    )
    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FakeTG)
    notify_subscribers(db, 1, post, notifiers_config, notifiers=[], retry_queue=None)
    assert received.get("bot_token") == "123:custom"
    assert received.get("chat_id") == "999"


def test_subscription_type_db_ops():
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    assert db.add_subscription(uid, kid, type="reply") is True
    assert db.subscribed_kol_types(uid) == {kid: "reply"}
    assert db.update_subscription_type(uid, kid, "both") is True
    assert db.subscribed_kol_types(uid) == {kid: "both"}
    assert db.list_subscriptions(uid)[0]["subscribe_type"] == "both"
    assert db.subscribers_of_kol(kid)[0]["subscribe_type"] == "both"
    assert db.update_subscription_type(uid, 9999, "post") is False
    try:
        db.update_subscription_type(uid, kid, "bad")
        raise AssertionError("应拒绝非法类型")
    except ValueError:
        pass


def test_notify_subscribers_filters_by_subscribe_type(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    post_user = db.add_user("post_only", "h", telegram_chat_id="111")
    reply_user = db.add_user("reply_only", "h", telegram_chat_id="222")
    both_user = db.add_user("both", "h", telegram_chat_id="333")
    db.add_subscription(post_user, kid, type="post")
    db.add_subscription(reply_user, kid, type="reply")
    db.add_subscription(both_user, kid, type="both")
    sent = []

    class FakeTG:
        channel = "telegram"

        def __init__(self, *args, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)
            self.chat_id = kwargs.get("chat_id")

        def notify(self, post):
            sent.append((self.chat_id, post.post_type))

    notifiers_config = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="t", chat_id="999"),  # 全局 chat 不覆盖任一用户
        feishu=SimpleNamespace(),
    )
    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FakeTG)
    post_item = Post(
        platform="xueqiu", kol_id=kid, kol_name="A",
        external_id="p1", title="t", content="c", url="u", published_at="", post_type="post",
    )
    notify_subscribers(db, 1, post_item, notifiers_config, notifiers=[], retry_queue=None)
    assert sorted(chat for chat, _ in sent) == ["111", "333"]
    sent.clear()
    reply_item = Post(
        platform="xueqiu", kol_id=kid, kol_name="A",
        external_id="p2", title="t", content="c", url="u", published_at="", post_type="reply",
    )
    notify_subscribers(db, 2, reply_item, notifiers_config, notifiers=[], retry_queue=None)
    assert sorted(chat for chat, _ in sent) == ["222", "333"]


def test_notify_subscribers_respects_selected_channels(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("multi", "h", telegram_chat_id="111", feishu_chat_id="oc_1")
    db.update_user(uid, wecom_webhook="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=wc1")
    db.add_subscription(uid, kid)
    post = Post(
        platform="xueqiu", kol_id=kid, kol_name="A",
        external_id="p1", title="t", content="c", url="u", published_at="",
    )
    hits = []

    class FakeTG:
        def __init__(self, *args, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)

        def notify(self, post):
            hits.append("telegram")

    class FakeFS:
        def __init__(self, *args, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)

        def notify(self, post):
            hits.append("feishu")

    class FakeWC:
        def __init__(self, *args, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)

        def notify(self, post):
            hits.append("wecom")

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FakeTG)
    monkeypatch.setattr("app.notifiers.feishu.FeishuNotifier", FakeFS)
    monkeypatch.setattr("app.notifiers.wecom.WeComNotifier", FakeWC)
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="t", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
    )

    # 未设置选择：全部已绑定渠道都推
    notify_subscribers(db, 1, post, ncfg, notifiers=[], retry_queue=None)
    assert sorted(hits) == ["feishu", "telegram", "wecom"]
    hits.clear()

    # 只选 Telegram
    db.update_user(uid, push_channels="telegram")
    notify_subscribers(db, 1, post, ncfg, notifiers=[], retry_queue=None)
    assert hits == ["telegram"]
    hits.clear()

    # 选飞书 + 企业微信
    db.update_user(uid, push_channels="feishu,wecom")
    notify_subscribers(db, 1, post, ncfg, notifiers=[], retry_queue=None)
    assert sorted(hits) == ["feishu", "wecom"]


def test_source_failure_alert_and_recovery(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    notifier = FakeNotifier()
    states = {}
    clock = {"t": 0.0}
    monkeypatch.setattr("app.scheduler.time.monotonic", lambda: clock["t"])

    # 前 2 次失败不打扰
    for _ in range(2):
        clock["t"] += 3600
        poll_once(db, {"xueqiu": FakeFetcherError()}, [notifier], states, interval_seconds=0)
    assert not any("数据源告警" in t for t in notifier.texts)

    # 第 3 次连续失败触发告警
    clock["t"] += 3600
    poll_once(db, {"xueqiu": FakeFetcherError()}, [notifier], states, interval_seconds=0)
    assert any("数据源告警" in t and "连续失败 3 次" in t for t in notifier.texts)

    # 6 小时内重复失败不再重复告警（冷却期）
    for _ in range(7):
        clock["t"] += 60
        poll_once(db, {"xueqiu": FakeFetcherError()}, [notifier], states, interval_seconds=0)
    assert sum("数据源告警" in t for t in notifier.texts) == 1

    # 恢复后发送恢复通知
    clock["t"] += 3600
    poll_once(db, {"xueqiu": FakeFetcher([make_post(kid)])}, [notifier], states, interval_seconds=0)
    assert any("数据源已恢复" in t for t in notifier.texts)


def test_digest_buffers_non_priority_and_flushes(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")  # 普通大V
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_subscription(uid, kid)
    digest: dict[int, list] = {}
    posts = [make_post(kid), make_post(kid)]
    posts[1].external_id = "p2"
    sent = []

    class FakeTG:
        def __init__(self, config, chat_id=None, client=None, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)

        def send_digest(self, posts, kol_name, platform):
            sent.append((len(posts), kol_name))

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FakeTG)
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="t", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
    )
    poll_once(
        db,
        {"xueqiu": FakeFetcher(posts)},
        [],
        interval_seconds=0,
        digest=digest,
        notifiers_config=ncfg,
    )
    # 普通大V不立即推送，进入摘要缓冲
    assert sent == []
    assert len(digest.get(kid, [])) == 2

    flush_digest(db, digest, [], ncfg)
    assert sent == [(2, "A")]
    assert digest == {}


def test_priority_kol_bypasses_digest(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "P", "1", priority=True)
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_subscription(uid, kid)
    calls = []

    class FakeTG:
        def __init__(self, config, chat_id=None, client=None, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)

        def notify(self, post):
            calls.append(post.external_id)

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FakeTG)
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="t", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
    )
    digest: dict[int, list] = {}
    poll_once(
        db,
        {"xueqiu": FakeFetcher([make_post(kid)])},
        [],
        interval_seconds=0,
        digest=digest,
        notifiers_config=ncfg,
    )
    assert len(calls) == 1
    assert digest == {}


def test_source_health_recorded():
    db = make_db()
    db.add_kol("xueqiu", "A", "1")
    poll_once(db, {"xueqiu": FakeFetcherError()}, [FakeNotifier()], interval_seconds=0)
    assert db.get_setting("source_fails_xueqiu") == "1"
    assert db.get_setting("source_err_xueqiu") == "boom"
    poll_once(db, {"xueqiu": FakeFetcher([make_post(1)])}, [FakeNotifier()], interval_seconds=0)
    assert db.get_setting("source_fails_xueqiu") == "0"
    assert db.get_setting("source_ok_xueqiu") is not None


def test_push_logs_retention():
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    pid = db.insert_post("xueqiu", kid, "p1", "t", "c", "u", "")
    db.add_push_log(pid, "telegram", "success")
    db._execute("UPDATE push_logs SET created_at = datetime('now', '-10 days') WHERE id = ?", (1,))
    assert db.delete_push_logs_older_than(7) == 1
    assert db.delete_push_logs_older_than(7) == 0


def test_push_retry_queue_enqueued_on_failure_and_backoff_drops(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr("app.scheduler.time.monotonic", lambda: clock["t"])
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_subscription(uid, kid)

    class FailingTelegram:
        def __init__(self, config, chat_id=None, client=None, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)

        def notify(self, post):
            raise RuntimeError("boom")

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FailingTelegram)
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="t", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
    )
    q = PushRetryQueue()
    poll_once(
        db,
        {"xueqiu": FakeFetcher([make_post(kid)])},
        [],
        interval_seconds=0,
        retry_queue=q,
        notifiers_config=ncfg,
    )
    assert q.pending() == 1
    clock["t"] = 2000  # 越过 60 秒退避
    item = q.due()[0]
    assert q.fail(item) is True
    assert q.fail(item) is True
    assert q.fail(item) is False  # 3 次后放弃
    assert q.due() == []


def test_retry_queue_keys_include_platform():
    """不同平台相同 external_id 的帖子不能互相覆盖重试任务。"""
    q = PushRetryQueue()
    p1 = make_post(1)
    p1.platform = "xueqiu"
    p1.external_id = "123"
    p2 = make_post(1)
    p2.platform = "weibo"
    p2.external_id = "123"
    q.add(p1, "telegram", 1)
    q.add(p2, "telegram", 1)
    assert q.pending() == 2


def test_digest_failure_alerts_admin(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_subscription(uid, kid)
    post = make_post(kid)
    db.insert_post("xueqiu", kid, post.external_id, post.title, post.content, post.url, post.published_at)
    digest = {kid: [post]}

    class FailingTG:
        def __init__(self, config, chat_id=None, client=None, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)

        def send_digest(self, posts, kol_name, platform):
            raise RuntimeError("boom")

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FailingTG)
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="t", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
    )
    notifier = FakeNotifier()
    flush_digest(db, digest, [notifier], ncfg)
    assert any("推送失败" in t for t in notifier.texts)


def test_dnd_summary_failure_alerts_admin(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_subscription(uid, kid)
    notifier = FakeNotifier()
    scheduler = Scheduler(
        db,
        {},
        [notifier],
        SimpleNamespace(),
        notifiers_config=SimpleNamespace(
            telegram=SimpleNamespace(bot_token="t", chat_id=""),
            feishu=SimpleNamespace(),
            wecom=SimpleNamespace(),
        ),
        xueqiu_config=SimpleNamespace(cookie=""),
        weibo_config=SimpleNamespace(cookie="", username="", password=""),
    )

    class FailingTG:
        def __init__(self, *args, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)

        def send_dnd_summary(self, posts):
            raise RuntimeError("boom")

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FailingTG)
    scheduler._send_dnd_summary(db.get_user(uid), [make_post(kid)])
    assert any("推送失败" in t for t in notifier.texts)


def test_poll_once_fetches_never_fetched_kol_with_small_monotonic(monkeypatch):
    """容器启动早期 monotonic 可能小于轮询间隔，首轮不应被误跳过（CI 回归）。"""
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    calls = []

    class CountingFetcher:
        def fetch(self, kol):
            calls.append(kol["id"])
            return []

    monkeypatch.setattr("app.scheduler.time.monotonic", lambda: 5.0)
    poll_once(db, {"xueqiu": CountingFetcher()}, [])
    assert calls == [kid]


def test_retry_recovery_from_failed_logs():
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    pid = db.insert_post("xueqiu", kid, "p1", "t", "c", "u", "")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_push_log(pid, "telegram", "failed", "boom", user_id=uid)
    db._execute("UPDATE push_logs SET created_at = datetime('now', '-1 hours') WHERE id = 1")

    scheduler = Scheduler(
        db,
        {},
        [],
        SimpleNamespace(),
        notifiers_config=SimpleNamespace(telegram=SimpleNamespace(bot_token="t", chat_id="111")),
        xueqiu_config=SimpleNamespace(cookie=""),
        weibo_config=SimpleNamespace(cookie="", username="", password=""),
    )
    scheduler._recover_failed_pushes()
    assert scheduler.retry_queue.pending() == 1


def test_transfer_subscriptions_preserves_and_merges_type():
    db = make_db()
    kid1 = db.add_kol("xueqiu", "A", "1")
    kid2 = db.add_kol("xueqiu", "B", "2")
    target = db.add_user("web", "h")
    bot = db.add_user("bot", "h")
    db.add_subscription(target, kid1, type="post")
    db.add_subscription(bot, kid1, type="reply")
    db.add_subscription(bot, kid2, type="both")

    db.transfer_subscriptions(bot, target)

    types = {row["id"]: row["subscribe_type"] for row in db.list_subscriptions(target)}
    assert types[kid1] == "both"  # post + reply 合并为 both
    assert types[kid2] == "both"
    assert db.list_subscriptions(bot) == []


def test_insert_post_persists_detail_and_recovery_restores_fields():
    db = make_db()
    kid = db.add_kol("combination", "组合A", "ZH123")
    cid = db.add_category("实盘")
    db.update_kol(kid, category_id=cid)
    detail = {
        "stats": [["年化", "12.3%"], ["净值", "1.500"]],
        "actions": [{"type": "增持", "stock": "贵州茅台", "symbol": "600519"}],
        "cash": "5.0%",
    }
    pid = db.insert_post(
        "combination", kid, "c1", "组合A 调仓", "内容", "u", "",
        detail=detail,
        images=["https://x.img/a.jpg", "https://x.img/b.jpg"],
    )
    row = db.get_post(pid)
    assert json.loads(row["detail"]) == detail
    assert json.loads(row["images"]) == ["https://x.img/a.jpg", "https://x.img/b.jpg"]

    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_push_log(pid, "telegram", "failed", "boom", user_id=uid)
    db._execute("UPDATE push_logs SET created_at = datetime('now', '-1 hours') WHERE id = ?", (pid,))

    scheduler = Scheduler(
        db,
        {},
        [],
        SimpleNamespace(),
        notifiers_config=SimpleNamespace(telegram=SimpleNamespace(bot_token="t", chat_id="111")),
        xueqiu_config=SimpleNamespace(cookie=""),
        weibo_config=SimpleNamespace(cookie="", username="", password=""),
    )
    scheduler._recover_failed_pushes()
    assert scheduler.retry_queue.pending() == 1
    item = next(iter(scheduler.retry_queue._items.values()))
    assert item["post"].post_type == ""
    assert item["post"].category == "实盘"
    assert item["post"].detail == detail
    assert item["post"].images == ["https://x.img/a.jpg", "https://x.img/b.jpg"]


def test_retry_recovery_restores_post_type():
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    pid = db.insert_post("xueqiu", kid, "p9", "t", "c", "u", "", post_type="reply")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_push_log(pid, "telegram", "failed", "boom", user_id=uid)
    db._execute("UPDATE push_logs SET created_at = datetime('now', '-1 hours') WHERE id = ?", (pid,))

    scheduler = Scheduler(
        db,
        {},
        [],
        SimpleNamespace(),
        notifiers_config=SimpleNamespace(telegram=SimpleNamespace(bot_token="t", chat_id="111")),
        xueqiu_config=SimpleNamespace(cookie=""),
        weibo_config=SimpleNamespace(cookie="", username="", password=""),
    )
    scheduler._recover_failed_pushes()
    assert scheduler.retry_queue.pending() == 1
    item = next(iter(scheduler.retry_queue._items.values()))
    assert item["post"].post_type == "reply"


def test_scheduler_stop_flushes_pending_digest(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_subscription(uid, kid)
    sent = []

    class FakeTG:
        def __init__(self, config, chat_id=None, client=None, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)

        def send_digest(self, posts, kol_name, platform):
            sent.append((len(posts), kol_name))

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FakeTG)
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="t", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
    )
    scheduler = Scheduler(
        db,
        {},
        [],
        SimpleNamespace(),
        notifiers_config=ncfg,
        xueqiu_config=SimpleNamespace(cookie=""),
        weibo_config=SimpleNamespace(cookie="", username="", password=""),
    )
    post = make_post(kid)
    post.external_id = "p2"
    scheduler._digest = {kid: [post]}

    scheduler.stop()

    assert sent == [(1, "A")]
    assert scheduler._digest == {}


def test_startup_message_only_to_admins(monkeypatch):
    import asyncio

    db = make_db()
    db.add_user("kale", "h", telegram_chat_id="111", is_admin=True)
    db.add_user("user", "h", telegram_chat_id="222")
    sent = []

    class FakeTG:
        def __init__(self, config, chat_id=None, client=None, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)
            self.chat_id = chat_id

        def send_text(self, text):
            sent.append((self.chat_id, text))

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FakeTG)
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="t", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
    )
    scheduler = Scheduler(
        db,
        {},
        [],
        SimpleNamespace(),
        notifiers_config=ncfg,
        xueqiu_config=SimpleNamespace(cookie=""),
        weibo_config=SimpleNamespace(cookie="", username="", password=""),
    )

    asyncio.run(scheduler._send_startup_message())

    assert sent == [("111", "✅ 大V订阅服务已启动")]


def test_dnd_window_math():
    from datetime import UTC, datetime

    from app.scheduler import _in_dnd_window

    dt = lambda h, m: datetime(2026, 8, 5, h, m, tzinfo=UTC)
    u = {"dnd_start": "23:00", "dnd_end": "07:00"}
    assert _in_dnd_window(u, dt(0, 30))
    assert _in_dnd_window(u, dt(23, 30))
    assert not _in_dnd_window(u, dt(12, 0))
    assert not _in_dnd_window(u, dt(7, 0))  # 结束时间不含
    assert not _in_dnd_window({"dnd_start": "", "dnd_end": ""}, dt(0, 30))
    assert not _in_dnd_window({"dnd_start": "23:00", "dnd_end": "23:00"}, dt(23, 0))
    u2 = {"dnd_start": "13:00", "dnd_end": "15:00"}
    assert _in_dnd_window(u2, dt(14, 0))
    assert not _in_dnd_window(u2, dt(16, 0))


def test_notify_subscribers_buffers_during_dnd(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.update_user(uid, dnd_start="23:00", dnd_end="07:00")
    db.add_subscription(uid, kid)
    post = make_post(kid)
    dnd = {}
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="t", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
    )
    monkeypatch.setattr("app.scheduler._in_dnd_window", lambda user, now=None: True)
    notify_subscribers(db, 1, post, ncfg, notifiers=[], retry_queue=None, dnd_buffer=dnd)
    assert dnd.get(uid) == [post]
    assert db.list_push_logs() == []


def test_notify_subscribers_favorite_passthrough_dnd(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.update_user(uid, dnd_start="23:00", dnd_end="07:00", dnd_allow_favorite=True)
    db.add_subscription(uid, kid)
    db.set_subscription_favorite(uid, kid, True)
    post = make_post(kid)
    dnd = {}
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="t", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
    )
    monkeypatch.setattr("app.scheduler._in_dnd_window", lambda user, now=None: True)
    hits = []

    class FakeTG:
        def __init__(self, *args, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)
            hits.append(("init", kwargs.get("favorite")))

        def notify(self, post):
            hits.append(("notify",))

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FakeTG)
    notify_subscribers(db, 1, post, ncfg, notifiers=[], retry_queue=None, dnd_buffer=dnd)
    assert dnd == {}  # 特别关注 + 允许穿透：不缓冲
    assert ("init", True) in hits
    assert any(h[0] == "notify" for h in hits)


def test_flush_dnd_buffers_sends_summary(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_subscription(uid, kid)
    post = make_post(kid)
    scheduler = Scheduler(
        db,
        {},
        [],
        SimpleNamespace(),
        notifiers_config=SimpleNamespace(
            telegram=SimpleNamespace(bot_token="t", chat_id=""),
            feishu=SimpleNamespace(),
            wecom=SimpleNamespace(),
        ),
        xueqiu_config=SimpleNamespace(cookie=""),
        weibo_config=SimpleNamespace(cookie="", username="", password=""),
    )
    scheduler._dnd_buffer = {uid: [post]}
    sent = []

    class FakeTG:
        def __init__(self, *args, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)

        def send_dnd_summary(self, posts):
            sent.append(len(posts))

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FakeTG)
    # 仍在免打扰时段：不推
    monkeypatch.setattr("app.scheduler._in_dnd_window", lambda user, now=None: True)
    scheduler._flush_dnd_buffers()
    assert sent == []
    assert scheduler._dnd_buffer == {uid: [post]}
    # 时段结束：补推一条汇总
    monkeypatch.setattr("app.scheduler._in_dnd_window", lambda user, now=None: False)
    scheduler._flush_dnd_buffers()
    assert sent == [1]
    assert scheduler._dnd_buffer == {}


def test_transfer_subscriptions_preserves_favorite():
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    target = db.add_user("web", "h")
    bot = db.add_user("bot", "h")
    db.add_subscription(bot, kid)
    db.set_subscription_favorite(bot, kid, True)
    db.transfer_subscriptions(bot, target)
    assert db.subscribed_favorite_ids(target) == {kid}


def test_daily_report_sent_to_enabled_user(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    db.insert_post("xueqiu", kid, "p1", "t", "今日内容", "u", "")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.update_user(uid, daily_report=True)
    db.add_subscription(uid, kid)

    fake = FakeDailyNotifier()
    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", lambda *a, **k: fake)
    scheduler = Scheduler(
        db,
        {},
        [],
        SimpleNamespace(daily_report_hour=20),
        notifiers_config=SimpleNamespace(
            telegram=SimpleNamespace(bot_token="t", chat_id="111"),
            feishu=SimpleNamespace(app_id="", app_secret=""),
        ),
        xueqiu_config=SimpleNamespace(cookie=""),
        weibo_config=SimpleNamespace(cookie="", username="", password=""),
    )
    scheduler._send_daily_report()
    assert len(fake.daily) == 1 and fake.daily[0][0].kol_name == "A"
    assert len(db.list_push_logs(channel="telegram")) == 1


def test_daily_report_wecom_user(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    db.insert_post("xueqiu", kid, "p1", "t", "今日内容", "u", "")
    uid = db.add_user("wc", "h")
    db.update_user(
        uid,
        daily_report=True,
        wecom_webhook="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=wc1",
    )
    db.add_subscription(uid, kid)

    fake = FakeDailyNotifier()
    fake.channel = "wecom"
    monkeypatch.setattr("app.notifiers.wecom.WeComNotifier", lambda *a, **k: fake)
    scheduler = Scheduler(
        db,
        {},
        [],
        SimpleNamespace(daily_report_hour=20),
        notifiers_config=SimpleNamespace(
            telegram=SimpleNamespace(bot_token="", chat_id=""),
            feishu=SimpleNamespace(app_id="", app_secret=""),
            wecom=SimpleNamespace(webhook_url=""),
        ),
        xueqiu_config=SimpleNamespace(cookie=""),
        weibo_config=SimpleNamespace(cookie="", username="", password=""),
    )
    scheduler._send_daily_report()
    assert len(fake.daily) == 1 and fake.daily[0][0].kol_name == "A"
    assert len(db.list_push_logs(channel="wecom")) == 1


def test_daily_report_skips_user_without_posts():
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.update_user(uid, daily_report=True)
    db.add_subscription(uid, kid)
    fake = FakeDailyNotifier()
    scheduler = Scheduler(
        db,
        {},
        [],
        SimpleNamespace(daily_report_hour=20),
        notifiers_config=SimpleNamespace(
            telegram=SimpleNamespace(bot_token="t", chat_id="111"),
            feishu=SimpleNamespace(app_id="", app_secret=""),
        ),
        xueqiu_config=SimpleNamespace(cookie=""),
        weibo_config=SimpleNamespace(cookie="", username="", password=""),
    )
    scheduler._send_daily_report()
    assert fake.daily == []


def test_polling_setting_db_override():
    db = make_db()
    assert _polling_setting(db, "config_interval_seconds", 180) == 180
    db.set_setting("config_interval_seconds", "60")
    assert _polling_setting(db, "config_interval_seconds", 180) == 60
    db.set_setting("config_interval_seconds", "abc")
    assert _polling_setting(db, "config_interval_seconds", 180) == 180


def test_polling_bool_override():
    db = make_db()
    assert _polling_bool(db, "k", False) is False
    db.set_setting("k", "1")
    assert _polling_bool(db, "k") is True
    db.set_setting("k", "no")
    assert _polling_bool(db, "k", True) is False


def test_twitter_content_translated_once_for_new_posts(monkeypatch):
    db = make_db()
    kid = db.add_kol("twitter", "Semi", "https://x.com/Semi")
    db.set_setting("config_translate_twitter_content", "1")
    post = Post(
        platform="twitter", kol_id=kid, kol_name="Semi",
        external_id="t1", title="Hello world", content="Hello world",
        url="u", published_at="",
    )
    monkeypatch.setattr(
        "app.scheduler.translate_text",
        lambda text, target="zh-CN": "你好世界" if "Hello" in text else text,
    )
    poll_once(db, {"twitter": FakeFetcher([post])}, [FakeNotifier()], interval_seconds=0)
    rows = db.list_posts(limit=5)
    assert rows[0]["title"] == "你好世界" and rows[0]["content"] == "你好世界"

    # 第二轮：帖子已存在，不应再调用翻译
    calls = {"n": 0}

    def counting(text, target="zh-CN"):
        calls["n"] += 1
        return text

    monkeypatch.setattr("app.scheduler.translate_text", counting)
    poll_once(db, {"twitter": FakeFetcher([post])}, [FakeNotifier()], interval_seconds=0)
    assert calls["n"] == 0

    # 关闭开关后不翻译
    db.set_setting("config_translate_twitter_content", "0")
    post2 = Post(
        platform="twitter", kol_id=kid, kol_name="Semi",
        external_id="t2", title="Stay hungry", content="Stay hungry",
        url="u", published_at="",
    )
    poll_once(db, {"twitter": FakeFetcher([post2])}, [FakeNotifier()], interval_seconds=0)
    assert db.list_posts(limit=10)[0]["title"] == "Stay hungry"


def test_translate_text_google_first():
    def handler(request):
        return httpx.Response(
            200,
            json=[[["你好世界", "Hello world", None, None, 10]], None, "en"],
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert translate_text("Hello world", client=client) == "你好世界"


def test_translate_text_falls_back_to_mymemory():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if "translate.googleapis.com" in str(request.url):
            return httpx.Response(302)  # Google 不可用（302/被墙）
        return httpx.Response(
            200,
            json={"responseData": {"translatedText": "我们相信这款芯片是第一款"}},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert translate_text("We believe this chip is the first", client=client) == "我们相信这款芯片是第一款"
    assert len(calls) == 2


def test_translate_text_uses_grok_when_key_provided():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        assert request.headers.get("authorization") == "Bearer xai-test-key"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "我们相信这款芯片是第一款"}}
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = translate_text(
        "We believe this chip is the first",
        client=client,
        xai_key="xai-test-key",
        model="grok-2-latest",
    )
    assert result == "我们相信这款芯片是第一款"
    assert len(calls) == 1  # 不触发 google/mymemory 降级


def test_translate_text_grok_failure_falls_back():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if "api.x.ai" in str(request.url):
            return httpx.Response(401)  # Key 无效
        return httpx.Response(
            200,
            json={"responseData": {"translatedText": "回退译文"}},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert translate_text("hello", client=client, xai_key="bad") == "回退译文"
    assert len(calls) >= 2


def test_extract_tweet_id():
    assert extract_tweet_id("https://twitter.com/SemiAnalysis_/status/2084394819145674794") == "2084394819145674794"
    assert extract_tweet_id("https://x.com/a/status/123456789") == "123456789"
    assert extract_tweet_id("123456789") == "123456789"
    assert extract_tweet_id("") == ""


def test_parse_twitter_cookie():
    cookie = "guest_id=v1%3A1; auth_token=abc123; ct0=csrf-token; lang=zh-CN"
    assert parse_twitter_cookie(cookie) == {"auth_token": "abc123", "ct0": "csrf-token"}
    assert parse_twitter_cookie("") == {}


def test_translate_text_uses_x_official_translation():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        assert "api.x.com/2/grok/translation.json" in str(request.url)
        assert request.headers.get("x-csrf-token") == "ct0-token"
        assert "auth_token=my-auth-token" in request.headers.get("cookie", "")
        assert request.headers.get("authorization", "").startswith("Bearer ")
        return httpx.Response(
            200,
            json={"result": {"content_type": "POST", "text": "Kimi K3，人之手，之神话，之传奇"}},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = translate_text(
        "Kimi K3, The Manos",
        client=client,
        tweet_id="2084394819145674794",
        twitter_cookie="auth_token=my-auth-token; ct0=ct0-token; lang=zh-CN",
    )
    assert result == "Kimi K3，人之手，之神话，之传奇"
    assert len(calls) == 1  # 不走 google/mymemory 降级


def test_translate_text_x_official_missing_cookie_falls_back():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if "translate.googleapis.com" in str(request.url):
            return httpx.Response(302)  # Google 不可用
        return httpx.Response(
            200,
            json={"responseData": {"translatedText": "回退译文"}},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = translate_text(
        "hello",
        client=client,
        tweet_id="123",
        twitter_cookie="guest_id=abc",  # 没有 auth_token/ct0，走降级
    )
    assert result == "回退译文"
    assert len(calls) == 2


def test_twitter_translation_uses_x_official_once_with_cookie(monkeypatch):
    db = make_db()
    kid = db.add_kol("twitter", "Semi", "https://x.com/Semi")
    db.set_setting("config_translate_twitter_content", "1")
    post = Post(
        platform="twitter", kol_id=kid, kol_name="Semi",
        external_id="https://twitter.com/SemiAnalysis_/status/2084394819145674794",
        title="Kimi K3, The Manos", content="Kimi K3, The Manos\nKimi K3's architecture",
        url="u", published_at="",
    )
    monkeypatch.setenv("TWITTER_COOKIE", "auth_token=my-auth-token; ct0=ct0-token")
    calls = {"n": 0}

    def fake_translate(text, target="zh-CN", client=None, xai_key=None, model=None, tweet_id=None, twitter_cookie=None):
        calls["n"] += 1
        calls["tweet_id"] = tweet_id
        return "Kimi K3，人之手，之神话，之传奇\nKimi K3 的架构"

    monkeypatch.setattr("app.scheduler.translate_text", fake_translate)
    poll_once(db, {"twitter": FakeFetcher([post])}, [FakeNotifier()], interval_seconds=0)
    rows = db.list_posts(limit=5)
    assert calls["n"] == 1  # X 官方翻译只调一次
    assert calls["tweet_id"] == "2084394819145674794"
    assert rows[0]["content"] == "Kimi K3，人之手，之神话，之传奇\nKimi K3 的架构"
    assert rows[0]["title"] == "Kimi K3，人之手，之神话，之传奇"


def test_xueqiu_cookie_keepalive():
    db = make_db()
    db.set_setting("xueqiu_cookie", "xq_a_token=old; u=1")
    notifier = FakeNotifier()

    def handler(request):
        return httpx.Response(
            200,
            headers={"set-cookie": "xq_a_token=new; Path=/; Domain=.xueqiu.com"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    keepalive_xueqiu_cookie(
        db, [notifier], SimpleNamespace(cookie=""), client=client
    )
    assert "xq_a_token=new" in db.get_setting("xueqiu_cookie")
    assert db.get_setting("xueqiu_cookie_updated_at")
    assert notifier.texts == []


def test_weibo_cookie_keepalive_refresh_and_expired_alert():
    db = make_db()
    db.set_setting("weibo_cookie", "SUB=old; UID=1")

    def handler(request):
        return httpx.Response(
            200,
            text="<html>ok</html>",
            headers={
                "content-type": "text/html",
                "set-cookie": "SUBP=newsubp; Path=/; Domain=.weibo.com",
            },
        )

    notifier = FakeNotifier()
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    keepalive_weibo_cookie(
        db,
        [notifier],
        SimpleNamespace(cookie="", username="", password=""),
        client=client,
    )
    cookie = db.get_setting("weibo_cookie")
    assert "SUB=old" in cookie  # 旧会话保留
    assert "SUBP=newsubp" in cookie  # 新 cookie 合并
    assert db.get_setting("weibo_cookie_updated_at")
    assert notifier.texts == []  # 不误报

    # 会话失效（无 SUB）且没有账号密码 → 告警
    def expired(request):
        if request.url.host == "passport.weibo.com":
            return httpx.Response(200, text="<html>login</html>", headers={"content-type": "text/html"})
        return httpx.Response(
            302,
            headers={"location": "https://passport.weibo.com/sso/signin?url=x"},
        )

    db.set_setting("weibo_cookie", "SUB=dead")
    notifier2 = FakeNotifier()
    client2 = httpx.Client(transport=httpx.MockTransport(expired), follow_redirects=True)
    keepalive_weibo_cookie(
        db,
        [notifier2],
        SimpleNamespace(cookie="", username="", password=""),
        client=client2,
    )
    assert any("保活失败" in t for t in notifier2.texts)
    assert "会话已失效" in db.get_setting("source_err_weibo")


def test_push_failure_logged(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    post = make_post(kid)
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_subscription(uid, kid)

    class FailingTelegram:
        def __init__(self, config, chat_id=None, client=None, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)

        def notify(self, post):
            raise RuntimeError("down")

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FailingTelegram)
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="t", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
    )
    poll_once(db, {"xueqiu": FakeFetcher([post])}, [], notifiers_config=ncfg)
    logs = db.list_push_logs()
    assert logs[0]["status"] == "failed"
    assert "down" in logs[0]["error"]


def test_weibo_login_failure_warns_once_per_day():
    db = make_db()
    db.add_kol("weibo", "微博大V", "123")

    class LoginErrorFetcher:
        def fetch(self, kol):
            raise RuntimeError("微博登录失败（可能需要验证码或凭据错误）")

    notifier = FakeNotifier()
    poll_once(db, {"weibo": LoginErrorFetcher()}, [notifier])
    assert len(notifier.texts) == 1
    assert "微博" in notifier.texts[0]

    # 同一天再次失败不再重复告警
    poll_once(db, {"weibo": LoginErrorFetcher()}, [notifier])
    assert len(notifier.texts) == 1


def test_backoff_skips_failing_platform():
    db = make_db()
    db.add_kol("xueqiu", "A", "1")

    class CountingFetcherError:
        def __init__(self):
            self.calls = 0

        def fetch(self, kol):
            self.calls += 1
            raise RuntimeError("boom")

    fetcher = CountingFetcherError()
    states = {}
    poll_once(db, {"xueqiu": fetcher}, [], states)
    assert fetcher.calls == 1
    poll_once(db, {"xueqiu": fetcher}, [], states)
    assert fetcher.calls == 1  # 退避期内不应再请求


def test_priority_kol_fetched_more_often(monkeypatch):
    clock = {"now": 1_000_000.0}
    monkeypatch.setattr("app.scheduler.time.monotonic", lambda: clock["now"])
    db = make_db()
    normal_id = db.add_kol("xueqiu", "普通", "1")
    priority_id = db.add_kol("xueqiu", "优先", "2", priority=True)
    calls = []

    class CountingFetcher:
        def fetch(self, kol):
            calls.append(kol["id"])
            return []

    states = {}
    kwargs = {"interval_seconds": 180, "priority_interval_seconds": 60}
    poll_once(db, {"xueqiu": CountingFetcher()}, [], states, **kwargs)
    assert sorted(calls) == sorted([normal_id, priority_id])

    # 120s 后：优先大V到期（60s），普通未到期（180s）
    calls.clear()
    clock["now"] = 1_000_120
    poll_once(db, {"xueqiu": CountingFetcher()}, [], states, **kwargs)
    assert calls == [priority_id]

    # 200s 后：普通大V到期（优先大V此时也已到期，两者都抓）
    calls.clear()
    clock["now"] = 1_000_200
    poll_once(db, {"xueqiu": CountingFetcher()}, [], states, **kwargs)
    assert sorted(calls) == sorted([normal_id, priority_id])


def test_subscriber_push_uses_user_channels(monkeypatch):
    calls = []

    class FakeTelegram:
        def __init__(self, config, chat_id=None, client=None, **kwargs):
            calls.append(("telegram", chat_id))

        def notify(self, post):
            pass

    class FakeFeishu:
        def __init__(self, config, open_id=None, chat_id=None, client=None, **kwargs):
            calls.append(("feishu", chat_id or open_id))

        def notify(self, post):
            pass

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FakeTelegram)
    monkeypatch.setattr("app.notifiers.feishu.FeishuNotifier", FakeFeishu)

    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user(
        "u1",
        "hash",
        telegram_chat_id="tg123",
        feishu_open_id="open456",
        feishu_chat_id="oc456",
    )
    db.add_subscription(uid, kid)
    uid2 = db.add_user("u2", "hash", feishu_open_id="open789")
    db.add_subscription(uid2, kid)
    ncfg = NotifiersConfig(
        telegram=TelegramConfig(bot_token="t"),
        feishu=FeishuConfig(app_id="a", app_secret="s"),
    )

    poll_once(db, {"xueqiu": FakeFetcher([make_post(kid)])}, [], notifiers_config=ncfg)
    assert ("telegram", "tg123") in calls
    assert ("feishu", "oc456") in calls  # 有 p2p 会话的优先走 chat_id
    assert ("feishu", "open789") in calls  # 没有会话的退化为 open_id
    logs = db.list_push_logs()
    assert len(logs) == 3
    assert all(log["status"] == "success" for log in logs)


def test_global_tg_chat_subscriber_still_receives(monkeypatch):
    calls = []

    class FakeTelegram:
        def __init__(self, config, chat_id=None, client=None, **kwargs):
            calls.append(("telegram", chat_id))

        def notify(self, post):
            pass

    class FailFeishu:
        def __init__(self, config, open_id=None, chat_id=None, client=None):
            raise AssertionError("本测试不应推送飞书")

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FakeTelegram)
    monkeypatch.setattr("app.notifiers.feishu.FeishuNotifier", FailFeishu)

    class GlobalNotifier:
        channel = "telegram"

        def __init__(self):
            self.calls = []

        def notify(self, post):
            self.calls.append(post)

        def send_text(self, text):
            pass

    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("u1", "hash", telegram_chat_id="777000")
    db.add_subscription(uid, kid)
    ncfg = NotifiersConfig(
        telegram=TelegramConfig(bot_token="t", chat_id="777000"),
        feishu=FeishuConfig(app_id="a", app_secret="s"),
    )

    # kale 场景：全局告警目标与订阅者 TG 相同；帖子只按订阅关系推，
    # 全局通知器不再推所有帖子
    global_notifier = GlobalNotifier()
    poll_once(
        db,
        {"xueqiu": FakeFetcher([make_post(kid)])},
        [global_notifier],
        notifiers_config=ncfg,
    )
    assert global_notifier.calls == []  # 全局不再推帖子
    assert calls == [("telegram", "777000")]  # 订阅者正常收到订阅的帖子
    logs = db.list_push_logs()
    assert len(logs) == 1 and logs[0]["status"] == "success"


def test_push_failure_alert_throttled(monkeypatch):
    class FailingTelegram:
        def __init__(self, config, chat_id=None, client=None, **kwargs):
            pass

        def notify(self, post):
            raise RuntimeError("boom")

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FailingTelegram)

    alerts = []

    class GlobalNotifier:
        channel = "telegram"

        def notify(self, post):
            pass

        def send_text(self, text):
            alerts.append(text)

    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("u1", "hash", telegram_chat_id="123")
    db.add_subscription(uid, kid)
    ncfg = NotifiersConfig(telegram=TelegramConfig(bot_token="t"))

    post1 = make_post(kid)
    post2 = Post(
        platform="xueqiu",
        kol_id=kid,
        kol_name="A",
        external_id="p2",
        title="t2",
        content="c2",
        url="u2",
        published_at="",
    )
    global_notifier = GlobalNotifier()
    poll_once(db, {"xueqiu": FakeFetcher([post1])}, [global_notifier], notifiers_config=ncfg)
    poll_once(db, {"xueqiu": FakeFetcher([post2])}, [global_notifier], notifiers_config=ncfg)
    assert len(alerts) == 1  # 每小时最多告警一次


def test_no_channel_no_user_push(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("未绑定渠道不应调用通知器")

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", fail)
    monkeypatch.setattr("app.notifiers.feishu.FeishuNotifier", fail)

    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("u1", "hash")
    db.add_subscription(uid, kid)
    poll_once(db, {"xueqiu": FakeFetcher([make_post(kid)])}, [])
    assert db.list_push_logs() == []


def test_delete_posts_older_than():
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    old_id = db.insert_post("xueqiu", kid, "old", "t", "c", "u", "")
    db.insert_post("xueqiu", kid, "new", "t", "c", "u", "")
    db.add_push_log(old_id, "telegram", "success")
    db._execute("UPDATE posts SET fetched_at = datetime('now', '-40 days') WHERE external_id = 'old'")
    assert db.delete_posts_older_than(30) == 1
    assert db.get_kol(kid)  # kols 不受影响
    remaining = db._rows("SELECT external_id FROM posts ORDER BY id")
    assert [r["external_id"] for r in remaining] == ["new"]
    assert db.list_push_logs() == []
