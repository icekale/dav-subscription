import tempfile
from pathlib import Path

from app.config import FeishuConfig, NotifiersConfig, TelegramConfig
from app.db import DB
from app.fetchers.base import Post
from app.scheduler import poll_once


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
        def __init__(self, config, chat_id=None):
            calls.append(("telegram", chat_id))

        def notify(self, post):
            pass

    class FakeFeishu:
        def __init__(self, config, open_id=None):
            calls.append(("feishu", open_id))

        def notify(self, post):
            pass

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FakeTelegram)
    monkeypatch.setattr("app.notifiers.feishu.FeishuNotifier", FakeFeishu)

    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("u1", "hash", telegram_chat_id="tg123", feishu_open_id="open456")
    db.add_subscription(uid, kid)
    ncfg = NotifiersConfig(
        telegram=TelegramConfig(bot_token="t"),
        feishu=FeishuConfig(app_id="a", app_secret="s"),
    )

    poll_once(db, {"xueqiu": FakeFetcher([make_post(kid)])}, [], notifiers_config=ncfg)
    assert ("telegram", "tg123") in calls
    assert ("feishu", "open456") in calls
    logs = db.list_push_logs()
    assert len(logs) == 2
    assert all(log["status"] == "success" for log in logs)


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
