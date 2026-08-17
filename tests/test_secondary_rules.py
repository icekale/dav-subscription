from types import SimpleNamespace

from app.fetchers.base import Post
from app.scheduler import (
    Scheduler,
    _buffer_personal_secondary,
    _buffer_secondary_subscribers,
)
from tests.test_scheduler import make_db, make_post


def _flush_scheduler(db, monkeypatch, sent):
    class FakeTG:
        def __init__(self, config, chat_id=None, client=None, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)

        def send_dnd_summary(self, posts, title=None):
            sent.append((title, [p.external_id for p in posts]))

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FakeTG)
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="t", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
    )
    return Scheduler(
        db, {}, [], SimpleNamespace(),
        notifiers_config=ncfg,
        xueqiu_config=SimpleNamespace(cookie=""),
        weibo_config=SimpleNamespace(cookie="", username="", password=""),
    )


def test_secondary_flush_hands_off_to_dnd_buffer(monkeypatch):
    """免打扰期间 flush 要把次要缓冲整包交给 dnd_buffer，结束时跟汇总一起发。"""
    db = make_db()
    kid = db.add_kol("xueqiu", "S", "1", secondary=True)
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_subscription(uid, kid)
    sent = []
    scheduler = _flush_scheduler(db, monkeypatch, sent)
    post = make_post(kid)
    scheduler._secondary_buffer[uid] = [post]
    monkeypatch.setattr("app.scheduler._in_dnd_window", lambda user, now=None: True)
    scheduler._flush_secondary_buffers()
    assert sent == []
    assert uid not in scheduler._secondary_buffer
    assert scheduler._dnd_buffer[uid] == [post]

    monkeypatch.setattr("app.scheduler._in_dnd_window", lambda user, now=None: False)
    scheduler._flush_dnd_buffers()
    assert sent == [(None, ["p1"])]
    assert scheduler._dnd_buffer == {}


def test_secondary_buffer_filters_subscribe_type():
    """入次要缓冲必须看订阅类型：只订帖子的人不能攒到回复。"""
    db = make_db()
    kid = db.add_kol("xueqiu", "S", "1", secondary=True)
    post_uid = db.add_user("post_only", "h", telegram_chat_id="111")
    both_uid = db.add_user("both", "h", telegram_chat_id="222")
    db.add_subscription(post_uid, kid, type="post")
    db.add_subscription(both_uid, kid, type="both")
    reply = Post(
        platform="xueqiu", kol_id=kid, kol_name="S", external_id="r1",
        title="t", content="c", url="u", published_at="", post_type="reply",
    )
    buf = {}
    _buffer_secondary_subscribers(db, kid, reply, buf)
    assert post_uid not in buf
    assert [p.external_id for p in buf[both_uid]] == ["r1"]

    kid2 = db.add_kol("xueqiu", "A", "2")
    uid = db.add_user("psec", "h", telegram_chat_id="333")
    db.add_subscription(uid, kid2, type="post")
    db.set_subscription_secondary(uid, kid2, True)
    personal = {}
    _buffer_personal_secondary(db, kid2, reply, personal)
    assert uid not in personal
    post = Post(
        platform="xueqiu", kol_id=kid2, kol_name="A", external_id="p2",
        title="t", content="c", url="u", published_at="", post_type="post",
    )
    _buffer_personal_secondary(db, kid2, post, personal)
    assert [p.external_id for p in personal[uid]] == ["p2"]


def test_secondary_flush_per_user_first_post_clock(monkeypatch):
    """次要 flush 按用户首帖入缓冲计时，刚进缓冲的人不能被别人的闹钟捎走。"""
    db = make_db()
    kid = db.add_kol("xueqiu", "S", "1", secondary=True)
    due_uid = db.add_user("due", "h", telegram_chat_id="111")
    wait_uid = db.add_user("wait", "h", telegram_chat_id="222")
    db.add_subscription(due_uid, kid)
    db.add_subscription(wait_uid, kid)
    sent = []
    scheduler = _flush_scheduler(db, monkeypatch, sent)
    monkeypatch.setattr("app.scheduler._in_dnd_window", lambda user, now=None: False)
    wait_post = Post(
        platform="xueqiu", kol_id=kid, kol_name="S", external_id="p2",
        title="t", content="c", url="u", published_at="",
    )
    scheduler._secondary_buffer[due_uid] = [make_post(kid)]
    scheduler._secondary_buffer[wait_uid] = [wait_post]
    now = 10_000.0
    scheduler._secondary_first_at[due_uid] = now - 3600
    scheduler._secondary_first_at[wait_uid] = now - 10
    scheduler._flush_secondary_buffers(interval=3600, now_mono=now)
    assert sent == [("\U0001f515 \u6b21\u8981\u5927V\u5408\u5e76\u6458\u8981", ["p1"])]
    assert due_uid not in scheduler._secondary_buffer
    assert [p.external_id for p in scheduler._secondary_buffer[wait_uid]] == ["p2"]


def test_secondary_flush_min_count_max_wait(monkeypatch):
    """min_count 未攒够时继续等；超过 2 个周期强制发，避免低频大V永远压着。"""
    db = make_db()
    kid = db.add_kol("xueqiu", "S", "1", secondary=True)
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_subscription(uid, kid)
    sent = []
    scheduler = _flush_scheduler(db, monkeypatch, sent)
    monkeypatch.setattr("app.scheduler._in_dnd_window", lambda user, now=None: False)
    scheduler._secondary_buffer[uid] = [make_post(kid)]
    now = 10_000.0
    scheduler._secondary_first_at[uid] = now - 3600
    scheduler._flush_secondary_buffers(min_count=2, interval=3600, now_mono=now)
    assert sent == []
    assert uid in scheduler._secondary_buffer
    scheduler._flush_secondary_buffers(min_count=2, interval=3600, now_mono=now + 3600)
    assert sent == [("\U0001f515 \u6b21\u8981\u5927V\u5408\u5e76\u6458\u8981", ["p1"])]
    assert scheduler._secondary_buffer == {}
