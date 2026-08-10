import datetime
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
    PlatformState,
    PushRetryQueue,
    Scheduler,
    _effective_interval,
    _polling_bool,
    _polling_setting,
    _x_fallback_advice,
    extract_tweet_id,
    flush_digest,
    keepalive_weibo_cookie,
    keepalive_xueqiu_cookie,
    maybe_alert_x_fallback,
    notify_digest_subscribers,
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


def add_kol_subscribed(db, platform, name, external_id, **kw):
    """建大V + 自动建一个订阅用户，使抓取调度认为该大V有人订阅。

    调度按「无订阅者不抓取」优化后，纯抓取逻辑测试需要先建订阅关系。
    telegram_chat_id 有唯一索引，每个测试用户必须用不同值。
    """
    kid = db.add_kol(platform, name, external_id, **kw)
    uid = db.add_user(f"sub_{kid}", "h", telegram_chat_id=f"tg{kid}")
    db.add_subscription(uid, kid)
    return kid


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


def test_x_fallback_advice_categorizes_reasons():
    """降级原因分类：cookie 失效 / queryId 轮换 / 瞬时故障 给出对应建议。"""
    cookie_hint = "请检查 TWITTER_COOKIE"
    transient_hint = "暂时不可用"
    qid_hint = "DEFAULT_QUERY_IDS"

    # cookie 类错误 → 建议检查 Cookie
    for reason in (
        "X GraphQL UserTweets HTTP 401",
        "X GraphQL UserTweets HTTP 403",
        "X GraphQL UserTweets 错误: Could not authenticate you",
    ):
        assert cookie_hint in _x_fallback_advice(reason), reason

    # queryId 轮换类错误 → 提示更新默认 queryId
    for reason in (
        "X GraphQL UserTweets 错误: InvalidRequest",
        "X GraphQL UserTweets 错误: queryId not found",
    ):
        assert qid_hint in _x_fallback_advice(reason), reason

    # 瞬时故障（503/ServiceUnavailable/SSL/超时/DeadlineExceeded）→ 无需操作
    for reason in (
        "X GraphQL UserTweets HTTP 503",
        "X GraphQL UserTweets 错误: ServiceUnavailable: Unspecified",
        "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol",
        "Read timed out",
        "X GraphQL UserTweets 错误: DeadlineExceeded: Unspecified",
        "X GraphQL UserTweets 错误: deadline exceeded (timeout)",
    ):
        assert transient_hint in _x_fallback_advice(reason), reason
        assert cookie_hint not in _x_fallback_advice(reason), reason

    # 未知原因 → 通用兜底建议
    assert "持续降级" in _x_fallback_advice("some weird error")
    assert "持续降级" in _x_fallback_advice("")

    # code 353（guest 绑定要求，2026-08 X 反爬升级）→ 提示升级代码而非重新登录
    for reason in (
        "X GraphQL UserTweets HTTP 403 code 353",
        "X GraphQL UserTweets HTTP 401 code 353",
    ):
        assert "升级代码" in _x_fallback_advice(reason), reason
        assert cookie_hint not in _x_fallback_advice(reason), reason

    # code 89 / invalid token → 真 Cookie 失效，才建议重新登录
    for reason in (
        "X GraphQL UserTweets HTTP 401 code 89",
        "X GraphQL UserTweets 错误: Invalid or expired token",
    ):
        assert cookie_hint in _x_fallback_advice(reason), reason

    # 未配置 Cookie → 配置提示
    assert "TWITTER_COOKIE" in _x_fallback_advice("未配置 TWITTER_COOKIE")

    # 裸 401/403（无 code）→ 两者皆有可能，提示兼顾（仍含检查 Cookie 字样）
    assert cookie_hint in _x_fallback_advice("X GraphQL UserTweets HTTP 401")
    assert "升级代码" in _x_fallback_advice("X GraphQL UserTweets HTTP 403")


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


def test_alerts_enabled_flag_parsing(monkeypatch):
    """ALERTS_ENABLED 默认开；0/false/no/off 关。"""
    from app.scheduler import _alerts_enabled

    monkeypatch.delenv("ALERTS_ENABLED", raising=False)
    assert _alerts_enabled() is True
    for off in ("0", "false", "no", "off", "FALSE"):
        monkeypatch.setenv("ALERTS_ENABLED", off)
        assert _alerts_enabled() is False, off
    monkeypatch.setenv("ALERTS_ENABLED", "true")
    assert _alerts_enabled() is True


def test_alerts_disabled_suppresses_admin_alerts(monkeypatch):
    """ALERTS_ENABLED=false 时管理员告警全部抑制（本地开发防误报）。"""
    from app.scheduler import (
        maybe_alert_push_failure,
        maybe_alert_source_failure,
        maybe_alert_x_fallback,
        maybe_warn_xueqiu_cookie,
    )

    monkeypatch.setenv("ALERTS_ENABLED", "false")
    db = make_db()
    notifier = FakeNotifier()
    db.set_setting("x_direct_last_fallback_at", str(int(time.time())))
    db.set_setting("x_direct_fallback_reason", "HTTP 401")

    maybe_alert_x_fallback(db, [notifier])
    assert notifier.texts == []
    assert db.get_setting("x_direct_alert_at") is None  # 连告警时间戳都不写

    maybe_alert_source_failure(db, [notifier], "twitter", "A", "boom", 3)
    maybe_alert_push_failure(db, [notifier], "push boom")
    maybe_warn_xueqiu_cookie(db, [notifier], "waf")
    assert notifier.texts == []


def test_poll_once_fetches_platforms_concurrently():
    db = make_db()
    kids = {}
    for platform in ("xueqiu", "weibo", "twitter"):
        kids[platform] = add_kol_subscribed(db, platform, platform, platform)
    lock = threading.Lock()
    stats = {"active": 0, "max": 0}

    def make_fetcher(post):
        class SlowFetcher:
            def fetch(self, kol):
                with lock:
                    stats["active"] += 1
                    stats["max"] = max(stats["max"], stats["active"])
                # 长于轮内错峰上限（1.2s），确保跨平台并行能被观测到
                time.sleep(1.5)
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
    kid = add_kol_subscribed(db, "xueqiu", "A", "1")
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
    add_kol_subscribed(db, "xueqiu", "A", "1")
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


def test_digest_llm_summary_computed_once_for_multiple_subscribers(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid1 = db.add_user("u1", "h", telegram_chat_id="111")
    uid2 = db.add_user("u2", "h")
    db.update_user(uid2, wecom_webhook="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=wc2")
    db.add_subscription(uid1, kid)
    db.add_subscription(uid2, kid)
    post = make_post(kid)
    db.insert_post("xueqiu", kid, post.external_id, post.title, post.content, post.url, post.published_at)

    calls = {"n": 0}

    def fake_summarize(posts, cfg, client=None, cache=None):
        from app.llm import summary_cache_key

        key = summary_cache_key(posts, cfg.api_base, cfg.model) if cache is not None else None
        if key is not None and key in cache:
            return cache[key]
        calls["n"] += 1
        text = "AI 要点"
        if key is not None:
            cache[key] = text
        return text

    monkeypatch.setattr("app.llm.summarize_posts", fake_summarize)

    class FakeTG:
        def __init__(self, config, chat_id=None, client=None, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)

        def send_text(self, text):
            pass

        def send_digest(self, posts, kol_name, platform):
            pass

    class FakeWeCom:
        def __init__(self, config, client=None, webhook_url=None, favorite=False):
            self.client = SimpleNamespace(close=lambda: None)

        def send_text(self, text):
            pass

        def send_digest(self, posts, kol_name, platform):
            pass

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FakeTG)
    monkeypatch.setattr("app.notifiers.wecom.WeComNotifier", FakeWeCom)
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="t", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
    )
    llm_cfg = SimpleNamespace(api_key="sk-test", api_base="https://api.deepseek.com", model="deepseek-chat")
    flush_digest(db, {kid: [post]}, [], ncfg, llm_config=llm_cfg)
    assert calls["n"] == 1


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


def test_dnd_summary_failure_enters_retry_queue(monkeypatch):
    """免打扰汇总发送失败时，帖子必须写失败日志并入重试队列而不是静默丢失。"""
    clock = {"t": 1000.0}
    monkeypatch.setattr("app.scheduler.time.monotonic", lambda: clock["t"])
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    db.insert_post("xueqiu", kid, "p1", "t", "c", "u", "")
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
    post = make_post(kid)
    scheduler._dnd_buffer[uid] = [post]
    # 免打扰已结束（_in_dnd_window 返回 False 才触发发送）
    monkeypatch.setattr("app.scheduler._in_dnd_window", lambda user, now=None: False)

    class FailingTG:
        def __init__(self, *args, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)

        def send_dnd_summary(self, posts):
            raise RuntimeError("boom")

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FailingTG)
    scheduler._flush_dnd_buffers()
    # 唯一渠道失败：帖子进重试队列 + 失败日志，不静默丢失
    assert scheduler.retry_queue.pending() == 1
    assert len(db.list_push_logs(channel="telegram", status="failed")) == 1
    assert db.list_push_logs(channel="telegram", status="success") == []

    # 发送恢复后，重试能完成推送
    retried = FakeNotifier()
    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", lambda *a, **k: retried)
    clock["t"] = 2000  # 越过 60 秒退避
    for item in scheduler.retry_queue.due():
        scheduler._retry_push(item)
    assert len(retried.calls) == 1 and retried.calls[0].external_id == "p1"
    assert scheduler.retry_queue.pending() == 0
    # 帖子已入库：重试成功后失败日志翻转为 success
    assert len(db.list_push_logs(channel="telegram", status="success")) == 1


def test_dnd_summary_success_does_not_duplicate(monkeypatch):
    """免打扰汇总成功时不入重试队列，避免已成功渠道重复发送。"""
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    db.insert_post("xueqiu", kid, "p1", "t", "c", "u", "")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_subscription(uid, kid)
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
    post = make_post(kid)
    scheduler._dnd_buffer[uid] = [post]
    monkeypatch.setattr("app.scheduler._in_dnd_window", lambda user, now=None: False)

    class OkTG:
        def __init__(self, *args, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)

        def send_dnd_summary(self, posts):
            pass

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", OkTG)
    scheduler._flush_dnd_buffers()
    assert scheduler.retry_queue.pending() == 0
    assert len(db.list_push_logs(channel="telegram", status="success")) == 1


class MixedFetcher:
    """按 KOL 区分成功/失败的假抓取器。"""

    def __init__(self, ok_posts, fail_kols):
        self.ok_posts = ok_posts
        self.fail_kols = fail_kols

    def fetch(self, kol):
        if kol["id"] in self.fail_kols:
            raise RuntimeError("boom")
        return self.ok_posts


def test_poll_once_logs_source_events_and_next_retry():
    db = make_db()
    ok_kid = add_kol_subscribed(db, "xueqiu", "OK", "1")
    fail_kid = add_kol_subscribed(db, "xueqiu", "FAIL", "2")
    poll_once(
        db,
        {"xueqiu": MixedFetcher([make_post(ok_kid)], {fail_kid})},
        [],
    )
    events = db.recent_source_events()
    assert {e["platform"] for e in events} == {"xueqiu"}
    assert {e["status"] for e in events} == {"ok", "fail"}
    assert any("boom" in e["detail"] for e in events)
    stats = db.source_event_stats("xueqiu", 24)
    assert stats["ok"] == 1 and stats["fail"] == 1
    retry = db.get_setting("source_next_retry_at_xueqiu")
    assert retry and int(retry) > 0  # 本轮有失败，保留重试倒计时


def test_source_health_reflects_mixed_round(monkeypatch):
    """同平台并发一轮：成功与失败并存时，健康状态必须反映整轮混合结果。

    曾出现 worker 在锁外各自写 source_ok/err/fails 最终状态，最后完成的成功
    worker 会把同一平台失败 worker 写的错误信息与连续失败计数随机清空。
    """
    db = make_db()
    ok_kid = add_kol_subscribed(db, "xueqiu", "OK", "1")
    fail_kid = add_kol_subscribed(db, "xueqiu", "FAIL", "2")

    class SlowOkMixedFetcher(MixedFetcher):
        def fetch(self, kol):
            if kol["id"] in self.fail_kols:
                raise RuntimeError("boom")
            time.sleep(0.15)  # 成功 worker 慢一步完成，曾导致它最后清空失败状态
            return self.ok_posts

    poll_once(db, {"xueqiu": SlowOkMixedFetcher([make_post(ok_kid)], {fail_kid})}, [])
    err = db.get_setting("source_err_xueqiu")
    fails = db.get_setting("source_fails_xueqiu")
    assert err and "boom" in err, "成功 worker 不应清空本轮失败的错误信息"
    assert fails == "1", "成功 worker 不应把连续失败计数归零"
    stats = db.source_event_stats("xueqiu", 24)
    assert stats["ok"] == 1 and stats["fail"] == 1
    assert db.get_setting("source_next_retry_at_xueqiu")  # 整轮有失败，保留重试倒计时


def test_source_health_cleared_when_all_success():
    """整轮全成功：错误信息与失败计数被清空，健康状态正常。"""
    db = make_db()
    kid = add_kol_subscribed(db, "xueqiu", "A", "1")
    db.set_setting("source_err_xueqiu", "旧错误")
    db.set_setting("source_fails_xueqiu", "3")
    poll_once(db, {"xueqiu": FakeFetcher([make_post(kid)])}, [])
    assert db.get_setting("source_err_xueqiu") == ""
    assert db.get_setting("source_fails_xueqiu") == "0"
    assert db.get_setting("source_ok_xueqiu")


def test_poll_once_clears_next_retry_on_all_success():
    db = make_db()
    kid = add_kol_subscribed(db, "xueqiu", "A", "1")
    db.set_setting("source_next_retry_at_xueqiu", "9999999999")
    poll_once(db, {"xueqiu": FakeFetcher([make_post(kid)])}, [])
    assert db.get_setting("source_next_retry_at_xueqiu") == ""


def test_empty_rounds_stretch_interval_then_reset_on_new_post():
    """无新帖空轮越多间隔越长（2 倍步进），有新帖立即重置回基础间隔。"""
    db = make_db()
    state = PlatformState()
    kol_normal = {"id": 1, "priority": 0, "platform": "xueqiu"}
    kol_priority = {"id": 2, "priority": 1, "platform": "xueqiu"}
    # 基础间隔
    assert _effective_interval(db, kol_normal, state, 180, 60) == 180
    assert _effective_interval(db, kol_priority, state, 180, 60) == 60
    # 空轮拉伸：普通 180→360→720→封顶 900；优先 60→120→180 封顶
    for n, expect in ((1, 360), (2, 720), (3, 900), (4, 900)):
        state.empty_rounds[1] = n
        assert _effective_interval(db, kol_normal, state, 180, 60) == expect
    for n, expect in ((1, 120), (2, 180), (3, 180)):
        state.empty_rounds[2] = n
        assert _effective_interval(db, kol_priority, state, 180, 60) == expect
    # 有新帖重置
    state.empty_rounds[1] = 0
    assert _effective_interval(db, kol_normal, state, 180, 60) == 180


def test_x_fallback_multiplies_interval():
    """X 处于 RSSHub 降级时有效间隔 ×4（封顶 1800s），避免打爆备用通道。"""
    db = make_db()
    db.set_setting("x_direct_last_fallback_at", str(int(time.time())))
    db.set_setting("x_direct_last_ok_at", str(int(time.time()) - 600))  # 降级晚于成功
    state = PlatformState()
    kol_x = {"id": 1, "priority": 0, "platform": "twitter"}
    # 基础 180 ×4 = 720；空轮 1 轮 360 ×4 = 1440；空轮 2 轮封顶 1800
    assert _effective_interval(db, kol_x, state, 180, 60) == 720
    state.empty_rounds[1] = 1
    assert _effective_interval(db, kol_x, state, 180, 60) == 1440
    state.empty_rounds[1] = 2
    assert _effective_interval(db, kol_x, state, 180, 60) == 1800
    # 降级恢复（直抓成功晚于降级）→ 回到基础间隔（空轮计数也重置后）
    db.set_setting("x_direct_last_ok_at", str(int(time.time())))
    state.empty_rounds[1] = 0
    assert _effective_interval(db, kol_x, state, 180, 60) == 180


def test_poll_once_records_empty_rounds():
    """空轮计数：无新帖空轮 +1，有新帖归零。"""
    db = make_db()
    kid = add_kol_subscribed(db, "xueqiu", "A", "1")
    db.set_setting("source_next_retry_at_xueqiu", "9999999999")
    states: dict = {}
    poll_once(db, {"xueqiu": FakeFetcher([])}, [], states=states)  # 空轮
    assert states["xueqiu"].empty_rounds.get(kid) == 1
    # 推进 last_fetched（空轮后间隔 360s，需把上次抓取时间推远让第二轮到期）
    states["xueqiu"].last_fetched[kid] = time.monotonic() - 1000
    poll_once(db, {"xueqiu": FakeFetcher([make_post(kid)])}, [], states=states)  # 有新帖
    assert states["xueqiu"].empty_rounds.get(kid) == 0


def test_poll_once_interval_stretch_skips_due():
    """间隔被空轮拉伸后，未到期的 KOL 本轮不抓取；空轮归零后恢复到期判断。"""
    db = make_db()
    kid = add_kol_subscribed(db, "xueqiu", "A", "1")
    calls = []

    class CountingFetcher:
        def fetch(self, kol):
            calls.append(kol["id"])
            return []

    state = PlatformState()
    now = time.monotonic()
    state.last_fetched[kid] = now - 400  # 距今 400s
    # 空轮 2 轮 → 有效间隔 720s > 400s → 本轮跳过
    state.empty_rounds[kid] = 2
    poll_once(db, {"xueqiu": CountingFetcher()}, [], states={"xueqiu": state})
    assert calls == []
    # 空轮归零 → 有效间隔 180s < 400s → 本轮抓取
    state.empty_rounds[kid] = 0
    poll_once(db, {"xueqiu": CountingFetcher()}, [], states={"xueqiu": state})
    assert calls == [kid]


def test_poll_once_skips_kol_without_subscribers():
    """无订阅者的大V不抓取：没有接收者就不白耗抓取配额。"""
    db = make_db()
    db.add_kol("xueqiu", "无订阅", "1")  # 无人订阅
    calls = []

    class CountingFetcher:
        def fetch(self, kol):
            calls.append(kol["id"])
            return [make_post(kol["id"])]

    poll_once(db, {"xueqiu": CountingFetcher()}, [])
    assert calls == []  # 不被抓取
    assert db.list_posts() == []  # 不产生帖子


def test_poll_once_fetches_kol_after_subscription():
    """有订阅者后才开始抓取：订阅动作使 KOL 进入抓取范围。"""
    db = make_db()
    kid = db.add_kol("xueqiu", "刚订阅", "1")
    calls = []

    class CountingFetcher:
        def fetch(self, kol):
            calls.append(kol["id"])
            return []

    poll_once(db, {"xueqiu": CountingFetcher()}, [])
    assert calls == []  # 未订阅不抓
    uid = db.add_user("new_sub", "h", telegram_chat_id="tg999")
    db.add_subscription(uid, kid)
    poll_once(db, {"xueqiu": CountingFetcher()}, [])
    assert calls == [kid]  # 订阅后开始抓取


def test_source_events_retention():
    db = make_db()
    db.add_source_event("xueqiu", "fail", "x")
    db._execute("UPDATE source_events SET created_at = datetime('now', '-8 days') WHERE id = 1")
    assert db.delete_source_events_older_than(7) == 1
    assert db.recent_source_events() == []


def test_source_event_stats_counting_and_legacy_compat():
    """source_event_stats 按 ok_count/fail_count 求和；旧版 0/0 事件按 1 次计，兼容升级。"""
    db = make_db()
    # 新口径：带 ok_count/fail_count 的正常事件按尝试次数统计
    db.add_source_event("xueqiu", "ok", "ok=5 fail=0", ok_count=5)
    db.add_source_event("xueqiu", "fail", "fail=1 ok=0", fail_count=1)
    assert db.source_event_stats("xueqiu", 24) == {"ok": 5, "fail": 1, "warn": 0}
    # 旧版事件（迁移前 ok_count=0/fail_count=0）按 1 次计，避免升级后成功率瞬时归零
    db.add_source_event("xueqiu", "ok", "legacy ok")
    db.add_source_event("xueqiu", "fail", "legacy fail")
    db.add_source_event("xueqiu", "warn", "降级")
    stats = db.source_event_stats("xueqiu", 24)
    assert stats == {"ok": 6, "fail": 2, "warn": 1}
    # 混合：ok_count=0 但 detail 表示有成功的旧版 ok 事件，仍按 1 次计
    db.add_source_event("xueqiu", "ok", "legacy mixed")
    assert db.source_event_stats("xueqiu", 24)["ok"] == 7
    # 其他平台不受影响
    assert db.source_event_stats("weibo", 24) == {"ok": 0, "fail": 0, "warn": 0}


def test_poll_once_fetches_never_fetched_kol_with_small_monotonic(monkeypatch):
    """容器启动早期 monotonic 可能小于轮询间隔，首轮不应被误跳过（CI 回归）。"""
    db = make_db()
    kid = add_kol_subscribed(db, "xueqiu", "A", "1")
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
    db.add_subscription(uid, kid)
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
    db.add_subscription(uid, kid)
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
    db.add_subscription(uid, kid, type="reply")  # 收到回复推送失败说明订阅类型覆盖回复
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


def test_startup_message_respects_push_channels(monkeypatch):
    """管理员只勾选 telegram 时，启动提示不应发到已绑定的飞书渠道。"""
    import asyncio

    db = make_db()
    uid = db.add_user("kale", "h", telegram_chat_id="111", feishu_chat_id="fc1", is_admin=True)
    db.update_user(uid, push_channels="telegram")
    sent = {"tg": [], "fs": []}

    class FakeTG:
        def __init__(self, config, chat_id=None, client=None, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)
            self.chat_id = chat_id

        def send_text(self, text):
            sent["tg"].append((self.chat_id, text))

    class FakeFS:
        def __init__(self, config, client=None, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)

        def send_text(self, text):
            sent["fs"].append(text)

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FakeTG)
    monkeypatch.setattr("app.notifiers.feishu.FeishuNotifier", FakeFS)
    monkeypatch.setattr(
        "app.feishu_personal.build_personal_feishu_kwargs",
        lambda db, cfg, user: {"open_id": "o1", "chat_id": "fc1", "app_id": "a", "app_secret": "s"},
    )
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

    assert sent["tg"] == [("111", "✅ 大V订阅服务已启动")]
    assert sent["fs"] == []  # 未勾选飞书 → 不发


def test_startup_message_defaults_to_all_bound_channels(monkeypatch):
    """push_channels 未设置时，已绑定渠道都应收到启动提示（默认行为）。"""
    import asyncio

    db = make_db()
    db.add_user("kale", "h", telegram_chat_id="111", feishu_chat_id="fc1", is_admin=True)
    sent = {"tg": [], "fs": []}

    class FakeTG:
        def __init__(self, config, chat_id=None, client=None, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)
            self.chat_id = chat_id

        def send_text(self, text):
            sent["tg"].append((self.chat_id, text))

    class FakeFS:
        def __init__(self, config, client=None, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)

        def send_text(self, text):
            sent["fs"].append(text)

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FakeTG)
    monkeypatch.setattr("app.notifiers.feishu.FeishuNotifier", FakeFS)
    monkeypatch.setattr(
        "app.feishu_personal.build_personal_feishu_kwargs",
        lambda db, cfg, user: {"open_id": "o1", "chat_id": "fc1", "app_id": "a", "app_secret": "s"},
    )
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

    assert len(sent["tg"]) == 1
    assert len(sent["fs"]) == 1  # 未设置 push_channels → 默认全推


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


def test_daily_report_sends_ai_summary(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    db.insert_post("xueqiu", kid, "p1", "t", "今日内容", "u", "")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.update_user(uid, daily_report=True)
    db.add_subscription(uid, kid)

    fake = FakeDailyNotifier()
    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", lambda *a, **k: fake)
    from app.llm import DailyPoint, DailySummary

    monkeypatch.setattr(
        "app.llm.summarize_daily",
        lambda posts, cfg, client=None: DailySummary(
            overview="今日共 1 条动态，围绕 AI 与宏观。",
            points=[DailyPoint(text="美联储释放降息信号", post_indexes=[0])],
        ),
    )
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
        llm_config=SimpleNamespace(api_key="sk-test", api_base="https://api.deepseek.com", model="deepseek-chat"),
    )
    scheduler._send_daily_report()
    # 综述走 send_text（含标题），不再发原始列表（send_daily 不被调用）
    assert any("今日大V精选" in t for t in fake.texts)
    assert fake.daily == []


def test_daily_report_falls_back_to_raw_list_without_llm(monkeypatch):
    """未配置 LLM 或综述失败时，降级发送原始贴文列表，保底不空发。"""
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    db.insert_post("xueqiu", kid, "p1", "t", "今日内容", "u", "")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.update_user(uid, daily_report=True)
    db.add_subscription(uid, kid)

    fake = FakeDailyNotifier()
    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", lambda *a, **k: fake)
    # LLM 综述返回 None（失败/无法解析）
    monkeypatch.setattr("app.llm.summarize_daily", lambda posts, cfg, client=None: None)
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
        llm_config=SimpleNamespace(api_key="sk-test", api_base="https://api.deepseek.com", model="deepseek-chat"),
    )
    scheduler._send_daily_report()
    assert fake.daily and fake.daily[0][0].kol_name == "A"
    assert fake.texts == []


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


def test_daily_report_users_includes_bark():
    """只绑定 Bark 的用户应进入每日精选名单（SQL 资格条件含 bark_key）。"""
    db = make_db()
    uid = db.add_user("barker", "h")
    db.update_user(uid, bark_key="AaBbCcDdEeFf1234567890")
    db.update_user(uid, daily_report=True)
    assert [u["id"] for u in db.daily_report_users()] == [uid]


def test_daily_report_bark_user(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    db.insert_post("xueqiu", kid, "p1", "t", "今日内容", "u", "")
    uid = db.add_user("barker", "h")
    db.update_user(uid, bark_key="AaBbCcDdEeFf1234567890")
    db.update_user(uid, daily_report=True)
    db.add_subscription(uid, kid)

    fake = FakeDailyNotifier()
    fake.channel = "bark"
    monkeypatch.setattr("app.notifiers.bark.BarkNotifier", lambda *a, **k: fake)
    scheduler = Scheduler(
        db,
        {},
        [],
        SimpleNamespace(daily_report_hour=20),
        notifiers_config=SimpleNamespace(
            telegram=SimpleNamespace(bot_token="", chat_id=""),
            feishu=SimpleNamespace(app_id="", app_secret=""),
        ),
        xueqiu_config=SimpleNamespace(cookie=""),
        weibo_config=SimpleNamespace(cookie="", username="", password=""),
    )
    scheduler._send_daily_report()
    assert len(fake.daily) == 1 and fake.daily[0][0].kol_name == "A"
    assert len(db.list_push_logs(channel="bark")) == 1


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
    kid = add_kol_subscribed(db, "twitter", "Semi", "https://x.com/Semi")
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


def test_new_posts_tagged_by_rules_on_ingest():
    """新帖入库前按关键词规则打标（纯本地，无需 LLM 配置）。"""
    db = make_db()
    kid = add_kol_subscribed(db, "xueqiu", "A", "1")
    post = make_post(kid)
    post.content = "央行宣布降息，AI 芯片板块走强"
    post2 = make_post(kid)
    post2.external_id = "p2"
    post2.content = "今天天气不错"
    poll_once(db, {"xueqiu": FakeFetcher([post, post2])}, [FakeNotifier()], interval_seconds=0)
    rows = db.list_posts(limit=5)
    # list_posts 按 id 倒序：post2（后插入）在前、无关键词不命中；post 命中宏观+板块+科技
    assert rows[0]["tags"] == []
    assert rows[1]["tags"] == ["宏观", "板块", "科技"]


def test_new_posts_tagged_with_stock_names():
    """新帖含 $股票名(代码)$ 标记或命中常用股票名表时，叠加股票标签（话题+股票，上限 5）。"""
    db = make_db()
    kid = add_kol_subscribed(db, "xueqiu", "A", "1")
    post = make_post(kid)
    post.content = "$中船特气(SH688146)$ 涨价，央行降息受益"
    post2 = make_post(kid)
    post2.external_id = "p2"
    post2.content = "梭哈了长鑫，$宁德时代(SZ300750)$ 也反弹"
    poll_once(db, {"xueqiu": FakeFetcher([post, post2])}, [FakeNotifier()], interval_seconds=0)
    rows = db.list_posts(limit=5)
    # rows[0] = post2（后插入）：$标记$ 提取的宁德时代在前、名表命中的长鑫在后
    assert rows[0]["tags"] == ["宁德时代", "长鑫"]
    # rows[1] = post：话题「宏观」+ 股票「中船特气」
    assert rows[1]["tags"] == ["宏观", "中船特气"]


def test_new_posts_without_keyword_hits_not_tagged(monkeypatch):
    """无关键词命中的新帖不打标签，原样入库（规则打标不再依赖 LLM 配置）。"""
    db = make_db()
    kid = add_kol_subscribed(db, "xueqiu", "A", "1")
    calls = {"n": 0}

    def fake_rule(posts, rules):
        calls["n"] += 1
        return {}

    monkeypatch.setattr("app.tagging.rule_tag_posts", fake_rule)
    poll_once(db, {"xueqiu": FakeFetcher([make_post(kid)])}, [FakeNotifier()], interval_seconds=0)
    assert calls["n"] == 1  # 规则打标无条件执行
    rows = db.list_posts(limit=5)
    assert rows and rows[0]["tags"] == []


def test_tagging_failure_does_not_block_ingest(monkeypatch):
    """打标抛异常时贴文仍入库（静默降级）。"""
    db = make_db()
    kid = add_kol_subscribed(db, "xueqiu", "A", "1")

    def boom(posts, rules):
        raise RuntimeError("rule error")

    monkeypatch.setattr("app.tagging.rule_tag_posts", boom)
    poll_once(db, {"xueqiu": FakeFetcher([make_post(kid)])}, [FakeNotifier()], interval_seconds=0)
    rows = db.list_posts(limit=5)
    assert rows and rows[0]["tags"] == []


def test_existing_posts_not_retagged(monkeypatch):
    """第二轮回抓时帖子已存在，不再调用打标。"""
    db = make_db()
    kid = add_kol_subscribed(db, "xueqiu", "A", "1")
    post = make_post(kid)
    calls = {"n": 0}

    def fake_rule(posts, rules):
        calls["n"] += 1
        return {0: ["宏观"]}

    monkeypatch.setattr("app.tagging.rule_tag_posts", fake_rule)
    poll_once(db, {"xueqiu": FakeFetcher([post])}, [FakeNotifier()], interval_seconds=0)
    assert calls["n"] == 1
    poll_once(db, {"xueqiu": FakeFetcher([post])}, [FakeNotifier()], interval_seconds=0)
    assert calls["n"] == 1


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
    kid = add_kol_subscribed(db, "twitter", "Semi", "https://x.com/Semi")
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
    db.add_kol("xueqiu", "A", "1")  # 默认 enabled
    db.set_setting("xueqiu_cookie", "xq_a_token=old; u=1")
    notifier = FakeNotifier()

    def handler(request):
        # 保活探测 timeline JSON 接口：200 + 合法 JSON + 下发新 cookie
        return httpx.Response(
            200,
            json={"count": 1, "statuses": []},
            headers={"set-cookie": "xq_a_token=new; Path=/; Domain=.xueqiu.com"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    keepalive_xueqiu_cookie(
        db, [notifier], SimpleNamespace(cookie=""), client=client
    )
    assert "xq_a_token=new" in db.get_setting("xueqiu_cookie")
    assert db.get_setting("xueqiu_cookie_updated_at")
    assert db.get_setting("source_ok_xueqiu")  # 保活成功刷新「正常」状态
    assert db.get_setting("source_err_xueqiu") in (None, "")
    assert notifier.texts == []


def test_xueqiu_cookie_keepalive_expired_alerts():
    db = make_db()
    db.add_kol("xueqiu", "A", "1")  # 默认 enabled
    db.set_setting("xueqiu_cookie", "xq_a_token=expired; u=1")
    notifier = FakeNotifier()

    def handler(request):
        # 失效 cookie → timeline 返回 400 需登录（实测行为）
        return httpx.Response(
            400,
            text='{"error_description":"遇到错误，请刷新页面或者重新登录帐号后再试"}',
            headers={"content-type": "application/json;charset=UTF-8"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    keepalive_xueqiu_cookie(
        db, [notifier], SimpleNamespace(cookie=""), client=client
    )
    assert "无效或已过期" in (db.get_setting("source_err_xueqiu") or "")
    assert any("雪球" in t for t in notifier.texts)
    assert db.get_setting("cookie_keepalive_alert_at")


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
    add_kol_subscribed(db, "weibo", "微博大V", "123")

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
    add_kol_subscribed(db, "xueqiu", "A", "1")

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
    normal_id = add_kol_subscribed(db, "xueqiu", "普通", "1")
    priority_id = add_kol_subscribed(db, "xueqiu", "优先", "2", priority=True)
    calls = []
    kid_counter = [0]

    class CountingFetcher:
        def fetch(self, kol):
            calls.append(kol["id"])
            # 每次返回唯一 external_id 的新帖：入库不重复 → 空轮计数保持 0，
            # 间隔不被拉伸（聚焦优先级频率本身）
            post = make_post(kol["id"])
            post.external_id = f"p{kid_counter[0]}"
            kid_counter[0] += 1
            return [post]

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


def test_scheduler_loop_delay_uses_min_interval():
    from app.scheduler import _scheduler_loop_delay

    assert _scheduler_loop_delay(180, 60, 0) == 60
    assert _scheduler_loop_delay(180, 180, 0) == 180
    assert _scheduler_loop_delay(60, 180, 0) == 60
    assert 60 <= _scheduler_loop_delay(180, 60, 30) <= 90


def test_scheduler_run_loop_sleeps_priority_interval(monkeypatch):
    """主循环单轮等待时长应取优先间隔，而非全局间隔。"""
    import asyncio

    db = make_db()
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
    )
    polling = SimpleNamespace(
        notify_on_start=False,
        jitter_seconds=0,
        interval_seconds=180,
        priority_interval_seconds=60,
        digest_interval_seconds=0,
        source_probe_interval_seconds=0,
        cookie_keepalive_interval_seconds=0,
        daily_report_hour=23,
        posts_retention_days=0,
        push_logs_retention_days=0,
    )
    scheduler = Scheduler(
        db,
        {},
        [],
        polling,
        notifiers_config=ncfg,
        xueqiu_config=SimpleNamespace(cookie=""),
        weibo_config=SimpleNamespace(cookie="", username="", password=""),
    )
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)
        scheduler._stop.set()  # 睡一次就停，只验证单轮等待时长

    monkeypatch.setattr("app.scheduler.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("app.scheduler.poll_once", lambda *a, **k: None)
    asyncio.run(scheduler.run())

    assert sleeps, "主循环应至少 sleep 一次"
    assert 59 < sleeps[0] <= 60, f"应约为优先间隔 60s，实际 {sleeps[0]}"


def test_scheduler_loop_delay_floors_at_one():
    from app.scheduler import _scheduler_loop_delay

    assert _scheduler_loop_delay(180, 0, 0) == 1
    assert _scheduler_loop_delay(180, -30, 0) == 1


def test_dnd_summary_writes_push_logs(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_subscription(uid, kid)
    post = make_post(kid)
    db.insert_post("xueqiu", kid, post.external_id, post.title, post.content, post.url, post.published_at)
    sent = []

    class FakeTG:
        channel = "telegram"

        def __init__(self, config, chat_id=None, client=None, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)

        def send_dnd_summary(self, posts):
            sent.append(posts)

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

    scheduler._send_dnd_summary(db.get_user(uid), [post])

    assert len(sent) == 1
    logs = db.list_push_logs(user_id=uid)
    assert len(logs) == 1
    assert logs[0]["channel"] == "telegram"
    assert logs[0]["status"] == "success"


_retry_tg_instances: list = []


class _RetryTG:
    """_retry_push 用的 Telegram 假通知器：模块级记录所有实例与发送。"""

    channel = "telegram"

    def __init__(self, config, chat_id=None, client=None, **kwargs):
        self.client = SimpleNamespace(close=lambda: None)
        self.sent = []
        _retry_tg_instances.append(self)

    def notify(self, post):
        self.sent.append(post)

    def send_daily(self, posts):
        self.sent.extend(posts)


class _FailingRetryTG(_RetryTG):
    def notify(self, post):
        raise RuntimeError("boom")

    def send_daily(self, posts):
        raise RuntimeError("boom")


def _retry_scheduler(db, monkeypatch, tg_cls=_RetryTG):
    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", tg_cls)
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="t", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
    )
    return Scheduler(
        db,
        {},
        [],
        SimpleNamespace(),
        notifiers_config=ncfg,
        xueqiu_config=SimpleNamespace(cookie=""),
        weibo_config=SimpleNamespace(cookie="", username="", password=""),
    )


def test_retry_push_sends_when_still_subscribed(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_subscription(uid, kid)
    post = make_post(kid)
    db.insert_post("xueqiu", kid, post.external_id, post.title, post.content, post.url, post.published_at)

    scheduler = _retry_scheduler(db, monkeypatch)
    _retry_tg_instances.clear()
    scheduler.retry_queue.add(post, "telegram", uid)
    item = next(iter(scheduler.retry_queue._items.values()))
    scheduler._retry_push(item)

    assert scheduler.retry_queue.pending() == 0
    assert len(_retry_tg_instances) == 1
    assert len(_retry_tg_instances[0].sent) == 1


def test_retry_push_drops_when_unsubscribed(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_subscription(uid, kid)
    post = make_post(kid)
    db.insert_post("xueqiu", kid, post.external_id, post.title, post.content, post.url, post.published_at)

    scheduler = _retry_scheduler(db, monkeypatch)
    _retry_tg_instances.clear()
    db.remove_subscription(uid, kid)  # 重试前用户已退订
    scheduler.retry_queue.add(post, "telegram", uid)
    item = next(iter(scheduler.retry_queue._items.values()))
    scheduler._retry_push(item)

    assert scheduler.retry_queue.pending() == 0
    assert _retry_tg_instances == []


def test_retry_push_drops_when_notify_disabled(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_subscription(uid, kid)
    db.update_user(uid, notify_enabled=False)
    post = make_post(kid)
    db.insert_post("xueqiu", kid, post.external_id, post.title, post.content, post.url, post.published_at)

    scheduler = _retry_scheduler(db, monkeypatch)
    _retry_tg_instances.clear()
    scheduler.retry_queue.add(post, "telegram", uid)
    item = next(iter(scheduler.retry_queue._items.values()))
    scheduler._retry_push(item)

    assert scheduler.retry_queue.pending() == 0
    assert _retry_tg_instances == []


def test_retry_push_drops_when_channel_deselected(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_subscription(uid, kid)
    db.update_user(uid, push_channels="feishu")  # 用户只选飞书，不推 Telegram
    post = make_post(kid)
    db.insert_post("xueqiu", kid, post.external_id, post.title, post.content, post.url, post.published_at)

    scheduler = _retry_scheduler(db, monkeypatch)
    _retry_tg_instances.clear()
    scheduler.retry_queue.add(post, "telegram", uid)
    item = next(iter(scheduler.retry_queue._items.values()))
    scheduler._retry_push(item)

    assert scheduler.retry_queue.pending() == 0
    assert _retry_tg_instances == []


def test_retry_recovery_skips_unsubscribed(monkeypatch):
    """重启恢复失败推送时，已退订用户的失败记录不再入队。"""
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    pid = db.insert_post("xueqiu", kid, "p1", "t", "c", "u", "")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_push_log(pid, "telegram", "failed", "boom", user_id=uid)
    db._execute("UPDATE push_logs SET created_at = datetime('now', '-1 hours') WHERE id = 1")
    db.remove_subscription(uid, kid)  # 用户已退订

    scheduler = _retry_scheduler(db, monkeypatch)
    scheduler._recover_failed_pushes()
    assert scheduler.retry_queue.pending() == 0


def test_daily_report_returns_false_on_failure(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.update_user(uid, daily_report=1)
    db.add_subscription(uid, kid)
    post = make_post(kid)
    db.insert_post("xueqiu", kid, post.external_id, post.title, post.content, post.url, post.published_at)

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", _FailingRetryTG)
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="t", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
    )
    scheduler = Scheduler(
        db,
        {},
        [FakeNotifier()],
        SimpleNamespace(),
        notifiers_config=ncfg,
        xueqiu_config=SimpleNamespace(cookie=""),
        weibo_config=SimpleNamespace(cookie="", username="", password=""),
    )
    _retry_tg_instances.clear()
    assert scheduler._send_daily_report() is False
    assert len(_retry_tg_instances) == 1
    assert _retry_tg_instances[0].sent == []
    # 失败时不应标记今日已发
    assert db.get_setting("daily_report_last_date") is None


def test_daily_report_returns_true_on_success(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.update_user(uid, daily_report=1)
    db.add_subscription(uid, kid)
    post = make_post(kid)
    db.insert_post("xueqiu", kid, post.external_id, post.title, post.content, post.url, post.published_at)

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", _RetryTG)
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
    _retry_tg_instances.clear()
    assert scheduler._send_daily_report() is True
    assert len(_retry_tg_instances) == 1
    assert len(_retry_tg_instances[0].sent) == 1


def test_delete_posts_older_than_batches():
    """删除过期帖子分批执行，避免单条 IN 列表过大。"""
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    for i in range(5):
        db.insert_post("xueqiu", kid, f"p{i}", "t", "c", "u", "")
        db._execute(
            "UPDATE posts SET fetched_at = datetime('now', '-31 days') WHERE external_id = ?",
            (f"p{i}",),
        )
    assert db.delete_posts_older_than(30, batch_size=2) == 5
    assert db.count_posts() == 0


def test_admin_logs_retention():
    """管理员操作日志按保留天数清理，避免无限增长。"""
    db = make_db()
    db.log_admin_action(1, "add_kol", "x", "d")
    db.log_admin_action(1, "delete_user", "y", "d")
    # 一条改到 200 天前，一条保持最新
    db._execute("UPDATE admin_logs SET created_at = datetime('now', '-200 days') WHERE action = 'add_kol'")
    assert db.delete_admin_logs_older_than(180) == 1
    assert db.list_admin_logs(10)[0]["action"] == "delete_user"
    assert db.delete_admin_logs_older_than(180) == 0


# ---- 关键词提醒 ----
def test_keyword_hit():
    from app.scheduler import _keyword_hit

    post = make_post(1)  # content="c", title="t"
    assert not _keyword_hit([], post)
    assert not _keyword_hit(["ETF"], post)
    assert not _keyword_hit([" ", ""], post)

    hit = Post(
        platform="xueqiu", kol_id=1, kol_name="A",
        external_id="p2", title="ETF 观察", content="正文", url="u", published_at="",
    )
    assert _keyword_hit(["etf"], hit)  # 大小写不敏感
    assert _keyword_hit(["观察"], hit)  # 标题命中
    assert _keyword_hit(["正"], hit)  # 正文命中


def test_notify_subscribers_dnd_keyword_penetration(monkeypatch):
    """免打扰时段：关键词命中的帖子实时推送（穿透），未命中的进缓冲。"""
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_subscription(uid, kid)
    db.set_user_keywords(uid, ["ETF"])

    monkeypatch.setattr("app.scheduler._in_dnd_window", lambda user, now=None: True)

    sent = []
    dnd_buffer: dict[int, list[Post]] = {}

    class FakeTG:
        channel = "telegram"

        def __init__(self, *args, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)

        def notify(self, post):
            sent.append(post.external_id)

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FakeTG)
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="t", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
        bark=SimpleNamespace(bark_server="", bark_key=""),
    )

    hit = Post(
        platform="xueqiu", kol_id=kid, kol_name="A",
        external_id="p1", title="ETF 大涨", content="内容", url="u", published_at="",
    )
    notify_subscribers(db, 1, hit, ncfg, notifiers=[], retry_queue=None, dnd_buffer=dnd_buffer)
    assert sent == ["p1"]  # 关键词命中 → 实时穿透
    assert uid not in dnd_buffer

    sent.clear()
    normal = Post(
        platform="xueqiu", kol_id=kid, kol_name="A",
        external_id="p2", title="普通动态", content="内容", url="u", published_at="",
    )
    notify_subscribers(db, 2, normal, ncfg, notifiers=[], retry_queue=None, dnd_buffer=dnd_buffer)
    assert sent == []  # 未命中 → 缓冲
    assert uid in dnd_buffer


def test_notify_subscribers_bark_channel(monkeypatch):
    """用户绑定 Bark key 时走 Bark 推送并记录推送日志。"""
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("u", "h")
    db.update_user(uid, bark_key="AaBbCcDdEeFf1234567890")
    db.add_subscription(uid, kid)
    post = make_post(kid)
    db.insert_post(
        post.platform, kid, post.external_id, post.title, post.content,
        post.url, post.published_at,
    )
    post_id = db.get_post_id(post.platform, post.external_id)
    received = {}

    class FakeBark:
        channel = "bark"

        def __init__(self, *args, **kwargs):
            received.update(kwargs)
            self.client = SimpleNamespace(close=lambda: None)

        def notify(self, post):
            pass

    monkeypatch.setattr("app.notifiers.bark.BarkNotifier", FakeBark)
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
        bark=SimpleNamespace(bark_server="", bark_key=""),
    )
    notify_subscribers(db, post_id, post, ncfg, notifiers=[], retry_queue=None)
    assert received.get("bark_key") == "AaBbCcDdEeFf1234567890"
    logs = db.list_push_logs()
    assert logs and logs[0]["channel"] == "bark" and logs[0]["status"] == "success"


def test_notify_subscribers_bark_skipped_without_key(monkeypatch):
    """未绑定 Bark key 的用户不会触发 Bark 推送。"""
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("u", "h")
    db.add_subscription(uid, kid)

    called = {"n": 0}

    class FakeBark:
        channel = "bark"

        def __init__(self, *args, **kwargs):
            called["n"] += 1

        def notify(self, post):
            pass

    monkeypatch.setattr("app.notifiers.bark.BarkNotifier", FakeBark)
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
        bark=SimpleNamespace(bark_server="", bark_key=""),
    )
    notify_subscribers(db, 1, make_post(kid), ncfg, notifiers=[], retry_queue=None)
    assert called["n"] == 0
    assert db.list_push_logs() == []


def test_digest_pushes_to_bark_user(monkeypatch):
    """只绑定 Bark 的用户也应收到合并摘要并记录推送日志（此前缺口）。"""
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("barker", "h")
    db.update_user(uid, bark_key="AaBbCcDdEeFf1234567890")
    db.add_subscription(uid, kid)
    posts = [make_post(kid), make_post(kid)]
    posts[1].external_id = "p2"
    for p in posts:
        db.insert_post(p.platform, kid, p.external_id, p.title, p.content, p.url, p.published_at)

    received = {"kwargs": None, "digests": []}

    class FakeBark:
        channel = "bark"

        def __init__(self, *args, **kwargs):
            received["kwargs"] = kwargs
            self.client = SimpleNamespace(close=lambda: None)

        def send_text(self, text):
            pass

        def send_digest(self, posts, kol_name, platform):
            received["digests"].append((len(posts), kol_name))

    monkeypatch.setattr("app.notifiers.bark.BarkNotifier", FakeBark)
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
        bark=SimpleNamespace(bark_server="", bark_key=""),
    )
    notify_digest_subscribers(db, posts, db.get_kol(kid), ncfg, notifiers=[])
    assert received["kwargs"].get("bark_key") == "AaBbCcDdEeFf1234567890"
    assert received["digests"] == [(2, "A")]
    logs = db.list_push_logs(channel="bark")
    assert len(logs) == 2
    assert all(l["status"] == "success" for l in logs)


def test_digest_bark_failure_enters_retry_queue(monkeypatch):
    """Bark 摘要推送失败：写失败日志 + 进重试队列 + 告警管理员。"""
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("barker", "h")
    db.update_user(uid, bark_key="AaBbCcDdEeFf1234567890")
    db.add_subscription(uid, kid)
    post = make_post(kid)
    db.insert_post(post.platform, kid, post.external_id, post.title, post.content, post.url, post.published_at)
    retry_queue = SimpleNamespace(add=lambda post, channel, uid: retry_queue.calls.append((channel, uid)))
    retry_queue.calls = []

    class FakeBark:
        channel = "bark"

        def __init__(self, *args, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)

        def send_digest(self, posts, kol_name, platform):
            raise RuntimeError("boom")

    monkeypatch.setattr("app.notifiers.bark.BarkNotifier", FakeBark)
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
        bark=SimpleNamespace(bark_server="", bark_key=""),
    )
    alerts = []

    class FakeNotifier:
        channel = "telegram"

        def send_text(self, text):
            alerts.append(text)

    notify_digest_subscribers(
        db, [post], db.get_kol(kid), ncfg, notifiers=[FakeNotifier()], retry_queue=retry_queue
    )
    assert retry_queue.calls == [("bark", uid)]
    logs = db.list_push_logs(channel="bark")
    assert len(logs) == 1 and logs[0]["status"] == "failed"
    assert any("用户推送失败" in a and "channel=bark" in a for a in alerts)


def test_readable_subscribed_kol_ids_filters_private_without_acl():
    """可读订阅集合：普通用户只拿公开 + ACL 私有大V；管理员不过滤。"""
    db = make_db()
    public_id = db.add_kol("xueqiu", "公开", "1")
    private_id = db.add_kol("xueqiu", "私有", "2")
    db.update_kol(private_id, is_private=True)
    uid = db.add_user("u", "h")
    db.add_subscription(uid, public_id)
    db.add_subscription(uid, private_id)

    assert db.readable_subscribed_kol_ids(uid) == {public_id}
    db.set_kol_acl(private_id, [uid])
    assert db.readable_subscribed_kol_ids(uid) == {public_id, private_id}
    # 管理员保留已订阅私有大V
    admin_id = db.add_user("admin", "h", is_admin=True)
    db.add_subscription(admin_id, private_id)
    assert db.readable_subscribed_kol_ids(admin_id, is_admin=True) == {private_id}


def test_daily_report_skips_private_kol_content_without_acl(monkeypatch):
    """每日精选不向无权用户生成已私有大V的内容。"""
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    db.insert_post("xueqiu", kid, "p1", "t", "私有内容", "u", "")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.update_user(uid, daily_report=True)
    db.add_subscription(uid, kid)

    fake = FakeDailyNotifier()
    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", lambda *a, **k: fake)
    # 转私有后每日精选不再生成该大V内容
    db.update_kol(kid, is_private=True)
    scheduler = Scheduler(
        db, {}, [],
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


class _CountingTG:
    """统计 send_text/send_daily 调用次数的 TG fake，无 client 连接。"""
    channel = "telegram"

    def __init__(self, *a, **k):
        self.calls = {"text": 0, "daily": 0}

    def send_text(self, text):
        self.calls["text"] += 1

    def send_daily(self, posts):
        self.calls["daily"] += 1


class _FailingWeCom:
    channel = "wecom"

    def __init__(self, *a, **k):
        self.client = SimpleNamespace(close=lambda: None)

    def send_text(self, text):
        raise RuntimeError("wecom down")

    def send_daily(self, posts):
        raise RuntimeError("wecom down")


def _make_daily_scheduler(db):
    return Scheduler(
        db, {}, [],
        SimpleNamespace(daily_report_hour=20, push_logs_retention_days=90),
        notifiers_config=SimpleNamespace(
            telegram=SimpleNamespace(bot_token="t", chat_id=""),
            feishu=SimpleNamespace(app_id="", app_secret=""),
            wecom=SimpleNamespace(webhook_url=""),
        ),
        xueqiu_config=SimpleNamespace(cookie=""),
        weibo_config=SimpleNamespace(cookie="", username="", password=""),
    )


def test_daily_report_retries_only_failed_channel(monkeypatch):
    """Telegram 成功、企业微信失败：第二次调用只重试企业微信，Telegram 不重复发送。"""
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    db.insert_post("xueqiu", kid, "p1", "t", "内容", "u", "")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.update_user(uid, daily_report=True, wecom_webhook="https://qyapi.weixin.qq.com/hook")
    db.add_subscription(uid, kid)

    tg = _CountingTG()
    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", lambda *a, **k: tg)
    monkeypatch.setattr("app.notifiers.wecom.WeComNotifier", _FailingWeCom)
    scheduler = _make_daily_scheduler(db)

    assert scheduler._send_daily_report() is False  # wecom 失败 → 整体 False
    assert tg.calls["daily"] == 1
    assert db.daily_report_delivered(uid, datetime.datetime.now().date().isoformat(), "telegram")

    # 第二次：只重试 wecom，telegram 已成功不重复发
    assert scheduler._send_daily_report() is False
    assert tg.calls["daily"] == 1
    assert tg.calls["text"] == 0


def test_daily_report_channel_idempotent_across_restart(monkeypatch):
    """成功渠道的状态持久化：重建 DB/scheduler（模拟进程重启）后仍不重复发送。"""
    import tempfile
    from pathlib import Path

    tmp = tempfile.mkdtemp()
    db = DB(Path(tmp) / "restart.db")
    kid = db.add_kol("xueqiu", "A", "1")
    db.insert_post("xueqiu", kid, "p1", "t", "内容", "u", "")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.update_user(uid, daily_report=True)
    db.add_subscription(uid, kid)

    tg = _CountingTG()
    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", lambda *a, **k: tg)
    scheduler = _make_daily_scheduler(db)
    assert scheduler._send_daily_report() is True
    assert tg.calls["daily"] == 1

    # 模拟重启：重新打开同一 DB、新建 scheduler，成功渠道不再重复发送
    db.close()
    db2 = DB(Path(tmp) / "restart.db")
    scheduler2 = _make_daily_scheduler(db2)
    assert scheduler2._send_daily_report() is True
    assert tg.calls["daily"] == 1
    db2.close()


def test_stock_alias_task_writes_aliases_and_cleans(monkeypatch):
    """每日别名任务：LLM 返回 high 别名 → 写入别名表；同时清理过期标签。"""
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    pid = db.insert_post("xueqiu", kid, "al1", "宁王大涨", "宁王今天创新高，市场沸腾", "u", "")
    db.update_post_tags(pid, ["观点", "宏观"])  # 观点是过期标签

    monkeypatch.setattr(
        "app.llm.suggest_stock_aliases",
        lambda cands, stocks, cfg, client=None: [{"alias": "宁王", "stock": "宁德时代", "confidence": "high"}],
    )
    scheduler = Scheduler(
        db, {}, [],
        SimpleNamespace(),
        notifiers_config=SimpleNamespace(
            telegram=SimpleNamespace(bot_token="t", chat_id=""),
            feishu=SimpleNamespace(app_id="", app_secret=""),
        ),
        xueqiu_config=SimpleNamespace(cookie=""),
        weibo_config=SimpleNamespace(cookie="", username="", password=""),
        llm_config=SimpleNamespace(api_key="sk-test", api_base="https://api.deepseek.com", model="deepseek-chat"),
    )
    scheduler._run_stock_alias_task()
    # 别名写入
    aliases = db.get_stock_aliases()
    assert any(a["alias"] == "宁王" and a["stock"] == "宁德时代" for a in aliases)
    # 过期标签「观点」被清理，保留「宏观」
    tags = db.list_posts(limit=5)[0]["tags"]
    assert "观点" not in tags and "宏观" in tags


def test_stock_alias_task_without_llm_skips_but_cleans(monkeypatch):
    """未配置 LLM：跳过识别，但误标清理照常执行。"""
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    pid = db.insert_post("xueqiu", kid, "al2", "t", "c", "u", "")
    db.update_post_tags(pid, ["观点"])
    calls = {"n": 0}

    def boom(cands, stocks, cfg, client=None):
        calls["n"] += 1
        return []

    monkeypatch.setattr("app.llm.suggest_stock_aliases", boom)
    scheduler = Scheduler(
        db, {}, [],
        SimpleNamespace(),
        notifiers_config=SimpleNamespace(
            telegram=SimpleNamespace(bot_token="", chat_id=""),
            feishu=SimpleNamespace(app_id="", app_secret=""),
        ),
        xueqiu_config=SimpleNamespace(cookie=""),
        weibo_config=SimpleNamespace(cookie="", username="", password=""),
        llm_config=None,  # 未配置 LLM
    )
    scheduler._run_stock_alias_task()
    assert calls["n"] == 0
    # 过期标签仍被清理
    assert db.list_posts(limit=5)[0]["tags"] == []


def test_stock_alias_due_once_per_day():
    """日期键控制：今天跑过后不再触发。"""
    db = make_db()
    scheduler = Scheduler(
        db, {}, [],
        SimpleNamespace(),
        notifiers_config=SimpleNamespace(),
        xueqiu_config=SimpleNamespace(cookie=""),
        weibo_config=SimpleNamespace(cookie="", username="", password=""),
    )
    assert scheduler._stock_alias_due() is True
    db.set_setting("stock_alias_last_date", datetime.datetime.now().strftime("%Y-%m-%d"))
    assert scheduler._stock_alias_due() is False


def test_stock_alias_task_expands_names_from_marks(monkeypatch):
    """每日任务：$标记$ 里的新官方名进名表、戏称进别名表。"""
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    db.insert_post(
        "xueqiu", kid, "mk1",
        "$盐湖股份(SZ000792)$ 反弹", "$涂改液(SZ000858)$ 是真五粮液", "u", "",
    )
    monkeypatch.setattr(
        "app.llm.resolve_stock_marks",
        lambda marks, cfg, client=None: [
            {"name": "盐湖股份", "code": "SZ000792", "official": "盐湖股份", "is_alias": False},
            {"name": "涂改液", "code": "SZ000858", "official": "五粮液", "is_alias": True},
        ],
    )
    # 跳过正文候选识别（返回空即可），只测 $标记$ 扩充
    monkeypatch.setattr("app.llm.suggest_stock_aliases", lambda c, s, cfg, client=None: [])
    scheduler = Scheduler(
        db, {}, [],
        SimpleNamespace(),
        notifiers_config=SimpleNamespace(
            telegram=SimpleNamespace(bot_token="t", chat_id=""),
            feishu=SimpleNamespace(app_id="", app_secret=""),
        ),
        xueqiu_config=SimpleNamespace(cookie=""),
        weibo_config=SimpleNamespace(cookie="", username="", password=""),
        llm_config=SimpleNamespace(api_key="sk-test", api_base="https://api.deepseek.com", model="deepseek-chat"),
    )
    scheduler._run_stock_alias_task()
    # 官方名进名表
    assert "盐湖股份" in db.get_stock_names()
    # 戏称进别名表 + 正式名补进名表
    aliases = db.get_stock_aliases()
    assert any(a["alias"] == "涂改液" and a["stock"] == "五粮液" for a in aliases)
    assert "五粮液" in db.get_stock_names()
