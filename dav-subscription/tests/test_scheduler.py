import tempfile
from pathlib import Path

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
    post = make_post(kid)
    notifier = FakeNotifier()

    poll_once(db, {"xueqiu": FakeFetcher([post])}, [notifier])
    assert len(notifier.calls) == 1
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
