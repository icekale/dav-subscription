import tempfile
from pathlib import Path
from types import SimpleNamespace

import httpx

from app.config import FeishuConfig, NotifiersConfig, TelegramConfig
from app.db import DB
from app.fetchers.base import Post
from app.scheduler import (
    PushRetryQueue,
    _polling_bool,
    _polling_setting,
    flush_digest,
    keepalive_weibo_cookie,
    keepalive_xueqiu_cookie,
    poll_once,
)
from app.scheduler import Scheduler


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


def test_new_post_pushed_once():
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    cid = db.add_category("实盘")
    db.update_kol(kid, category_id=cid)
    post = make_post(kid)
    notifier = FakeNotifier()

    poll_once(db, {"xueqiu": FakeFetcher([post])}, [notifier])
    assert len(notifier.calls) == 1
    assert notifier.calls[0].category == "实盘"
    assert len(db.list_posts()) == 1
    assert db.list_push_logs()[0]["status"] == "success"

    poll_once(db, {"xueqiu": FakeFetcher([post])}, [notifier])
    assert len(notifier.calls) == 1
    assert len(db.list_posts()) == 1


def test_fetch_error_does_not_crash():
    db = make_db()
    db.add_kol("xueqiu", "A", "1")
    notifier = FakeNotifier()
    poll_once(db, {"xueqiu": FakeFetcherError()}, [notifier])
    assert len(db.list_posts()) == 0
    assert len(notifier.calls) == 0


def test_posts_pushed_in_time_order():
    db = make_db()
    kid = db.add_kol("weibo", "A", "1")
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
    notifier = FakeNotifier()
    poll_once(db, {"weibo": FakeFetcher(posts)}, [notifier])
    assert [p.external_id for p in notifier.calls] == ["p1", "p2", "p3"]


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


def test_digest_buffers_non_priority_and_flushes():
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")  # 普通大V
    notifier = FakeDigestNotifier()
    digest: dict[int, list] = {}
    posts = [make_post(kid), make_post(kid)]
    posts[1].external_id = "p2"
    poll_once(
        db,
        {"xueqiu": FakeFetcher(posts)},
        [notifier],
        interval_seconds=0,
        digest=digest,
    )
    # 普通大V不立即推送，进入摘要缓冲
    assert notifier.calls == [] and notifier.digests == []
    assert len(digest.get(kid, [])) == 2

    flush_digest(db, digest, [notifier], None)
    assert len(notifier.digests) == 1
    assert notifier.digests[0][1] == "A" and len(notifier.digests[0][0]) == 2
    assert digest == {}


def test_priority_kol_bypasses_digest():
    db = make_db()
    kid = db.add_kol("xueqiu", "P", "1", priority=True)
    notifier = FakeNotifier()
    digest: dict[int, list] = {}
    poll_once(
        db,
        {"xueqiu": FakeFetcher([make_post(kid)])},
        [notifier],
        interval_seconds=0,
        digest=digest,
    )
    assert len(notifier.calls) == 1
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
    notifier = FailAlwaysNotifier()
    q = PushRetryQueue()
    poll_once(
        db,
        {"xueqiu": FakeFetcher([make_post(kid)])},
        [notifier],
        interval_seconds=0,
        retry_queue=q,
    )
    assert q.pending() == 1
    clock["t"] = 2000  # 越过 60 秒退避
    item = q.due()[0]
    assert q.fail(item) is True
    assert q.fail(item) is True
    assert q.fail(item) is False  # 3 次后放弃
    assert q.due() == []


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


def test_flush_digest_fallback_notify_without_send_digest():
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    notifier = FakeNotifier()  # 没有 send_digest，走逐条推送兜底
    digest: dict[int, list] = {}
    poll_once(
        db,
        {"xueqiu": FakeFetcher([make_post(kid)])},
        [notifier],
        interval_seconds=0,
        digest=digest,
    )
    flush_digest(db, digest, [notifier], None)
    assert len(notifier.calls) == 1


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


def test_push_failure_logged():
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    post = make_post(kid)

    class FailingNotifier(FakeNotifier):
        def notify(self, post):
            raise RuntimeError("down")

    notifier = FailingNotifier()
    poll_once(db, {"xueqiu": FakeFetcher([post])}, [notifier])
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
    kwargs = dict(interval_seconds=180, priority_interval_seconds=60)
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
        def __init__(self, config, chat_id=None, client=None):
            calls.append(("telegram", chat_id))

        def notify(self, post):
            pass

    class FakeFeishu:
        def __init__(self, config, open_id=None, chat_id=None, client=None):
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


def test_global_tg_chat_not_pushed_twice(monkeypatch):
    calls = []

    class FakeTelegram:
        def __init__(self, config, chat_id=None, client=None):
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

    # 全局 TG 通知目标与订阅者相同：只推一次（全局），不重复按用户推
    global_notifier = GlobalNotifier()
    poll_once(
        db,
        {"xueqiu": FakeFetcher([make_post(kid)])},
        [global_notifier],
        notifiers_config=ncfg,
    )
    assert len(global_notifier.calls) == 1
    assert calls == []  # 订阅者与全局目标相同，不再按用户重复推
    logs = db.list_push_logs()
    assert len(logs) == 1 and logs[0]["status"] == "success"


def test_push_failure_alert_throttled(monkeypatch):
    class FailingTelegram:
        def __init__(self, config, chat_id=None, client=None):
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
    new_id = db.insert_post("xueqiu", kid, "new", "t", "c", "u", "")
    db.add_push_log(old_id, "telegram", "success")
    db._execute("UPDATE posts SET fetched_at = datetime('now', '-40 days') WHERE external_id = 'old'")
    assert db.delete_posts_older_than(30) == 1
    assert db.get_kol(kid)  # kols 不受影响
    remaining = db._rows("SELECT external_id FROM posts ORDER BY id")
    assert [r["external_id"] for r in remaining] == ["new"]
    assert db.list_push_logs() == []
