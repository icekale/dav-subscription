import tempfile
from pathlib import Path

from app.db import DB
from app.fetchers.base import Post


def make_db() -> DB:
    tmp = tempfile.mkdtemp()
    return DB(Path(tmp) / "test.db")


def test_kol_crud():
    db = make_db()
    kid = db.add_kol("xueqiu", "测试大V", "123")
    assert db.get_kol(kid)["name"] == "测试大V"
    db.update_kol(kid, enabled=False)
    assert db.get_kol(kid)["enabled"] == 0
    db.delete_kol(kid)
    assert db.get_kol(kid) is None


def test_insert_post_dedup():
    db = make_db()
    kid = db.add_kol("xueqiu", "测试大V", "123")
    pid1 = db.insert_post("xueqiu", kid, "p1", "标题", "内容", "https://x", "2026-01-01")
    pid2 = db.insert_post("xueqiu", kid, "p1", "标题", "内容", "https://x", "2026-01-01")
    assert pid1 is not None
    assert pid2 is None
    assert len(db.list_posts()) == 1


def test_insert_posts_batch_dedup_and_ids():
    db = make_db()
    kid = db.add_kol("xueqiu", "测试大V", "123")
    posts = [
        Post(platform="xueqiu", kol_id=kid, kol_name="测试大V", external_id="p1",
             title="t1", content="c1", url="u1", published_at="2026-01-01"),
        Post(platform="xueqiu", kol_id=kid, kol_name="测试大V", external_id="p2",
             title="t2", content="c2", url="u2", published_at="2026-01-01"),
        Post(platform="xueqiu", kol_id=kid, kol_name="测试大V", external_id="p1",
             title="dup", content="dup", url="u1", published_at="2026-01-01"),
    ]
    ids = db.insert_posts_batch(posts)
    assert ids[0] is not None and ids[1] is not None
    assert ids[2] is None  # p1 重复
    assert len(db.list_posts()) == 2


def test_invalid_platform_rejected():
    db = make_db()
    try:
        db.add_kol("facebook", "x", "1")
    except ValueError:
        return
    raise AssertionError("应拒绝不支持的平台")


def test_settings_roundtrip():
    db = make_db()
    assert db.get_setting("xueqiu_cookie") is None
    db.set_setting("xueqiu_cookie", "xq_a_token=abc")
    assert db.get_setting("xueqiu_cookie") == "xq_a_token=abc"
    db.set_setting("xueqiu_cookie", "xq_a_token=def")
    assert db.get_setting("xueqiu_cookie") == "xq_a_token=def"
