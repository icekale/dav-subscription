"""DB 层单元测试：迁移、唯一性与事务一致性。"""
import sqlite3

import pytest

from app.db import DB


def test_db_migrates_secondary_column(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    cols = {r["name"] for r in db._rows("PRAGMA table_info(kols)")}
    assert "secondary" in cols


def test_add_kol_with_secondary(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    kid = db.add_kol("xueqiu", "测试", "999", priority=False, secondary=True)
    kol = db.get_kol(kid)
    assert kol["secondary"] == 1
    assert kol["priority"] == 0


def test_update_kol_secondary_and_mutex(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    kid = db.add_kol("xueqiu", "测试", "999", priority=True)
    # 设 secondary 必须自动清 priority（互斥）
    db.update_kol(kid, secondary=True)
    kol = db.get_kol(kid)
    assert kol["secondary"] == 1 and kol["priority"] == 0
    # 设 priority 必须自动清 secondary
    db.update_kol(kid, priority=True)
    kol = db.get_kol(kid)
    assert kol["priority"] == 1 and kol["secondary"] == 0


def test_add_kol_priority_wins_over_secondary(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    kid = db.add_kol("xueqiu", "测试", "999", priority=True, secondary=True)
    kol = db.get_kol(kid)
    assert kol["priority"] == 1
    assert kol["secondary"] == 0


def test_db_migrates_subscription_secondary_column(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    cols = {r["name"] for r in db._rows("PRAGMA table_info(subscriptions)")}
    assert "secondary" in cols


def test_set_subscription_secondary(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    uid = db.add_user("u", "h", telegram_chat_id="111")
    kid = db.add_kol("xueqiu", "A", "1")
    db.add_subscription(uid, kid)
    assert db.set_subscription_secondary(uid, kid, True)
    assert kid in db.subscribed_secondary_ids(uid)
    db.set_subscription_secondary(uid, kid, False)
    assert kid not in db.subscribed_secondary_ids(uid)


def test_subscribers_of_kol_includes_secondary(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    uid = db.add_user("u", "h", telegram_chat_id="111")
    kid = db.add_kol("xueqiu", "A", "1")
    db.add_subscription(uid, kid)
    db.set_subscription_secondary(uid, kid, True)
    subs = db.subscribers_of_kol(kid)
    assert subs and subs[0]["secondary"] == 1


def test_list_subscriptions_returns_personal_secondary(tmp_path):
    """list_subscriptions 的 secondary 必须是订阅关系（个人）的，而非 kols 全局列。

    kols 表也有 secondary（全局次要）列，SELECT k.* 与其同名冲突时
    dict(row) 会取到全局值导致个人状态丢失（刷新后铃铛复位）。
    """
    db = DB(str(tmp_path / "t.db"))
    uid = db.add_user("u", "h", telegram_chat_id="111")
    kid = db.add_kol("xueqiu", "A", "1")  # kols.secondary = 0
    db.add_subscription(uid, kid)
    db.set_subscription_secondary(uid, kid, True)  # subscriptions.secondary = 1
    subs = db.list_subscriptions(uid)
    assert subs and subs[0]["secondary"] == 1


def test_post_tag_state_distinguishes_pending_from_no_match(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    kid = db.add_kol("xueqiu", "测试", "tag-state")
    pending_id = db.insert_post("xueqiu", kid, "pending", "t", "c", "u", "")
    no_match_id = db.insert_post(
        "xueqiu", kid, "no-match", "t", "c", "u", "", tags=[]
    )
    assert pending_id is not None and no_match_id is not None
    pending_row = db.get_post(pending_id)
    no_match_row = db.get_post(no_match_id)
    assert pending_row is not None and no_match_row is not None

    assert pending_row["tags"] == ""
    assert no_match_row["tags"] == "[]"
    assert [p["external_id"] for p in db.list_posts(untagged_only=True)] == ["pending"]
    assert db.tag_stats() == {
        "total": 2,
        "processed": 1,
        "tagged": 0,
        "pending": 1,
    }


def test_duplicate_kol_migration_merges_subscription_flags(tmp_path):
    path = tmp_path / "legacy.db"
    db = DB(str(path))
    uid = db.add_user("merge", "h")
    keep_id = db.add_kol("xueqiu", "A", "same")
    db.add_subscription(uid, keep_id, type="post")
    db.close()

    conn = sqlite3.connect(path)
    conn.execute("DROP INDEX uq_kols_platform_external")
    duplicate_id = conn.execute(
        "INSERT INTO kols (platform, name, external_id) VALUES ('xueqiu', 'B', 'same')"
    ).lastrowid
    conn.execute(
        "INSERT INTO subscriptions (user_id, kol_id, type, favorite, secondary) "
        "VALUES (?, ?, 'reply', 1, 1)",
        (uid, duplicate_id),
    )
    conn.commit()
    conn.close()

    migrated = DB(str(path))
    rows = migrated.list_subscriptions(uid)
    assert len(rows) == 1
    assert rows[0]["subscribe_type"] == "both"
    assert rows[0]["favorite"] == 1
    assert rows[0]["secondary"] == 1


def test_kol_and_pending_request_unique_indexes(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    uid = db.add_user("unique", "h")
    db.add_kol("xueqiu", "A", "same")
    with pytest.raises(ValueError):
        db.add_kol("xueqiu", "B", "same")
    db.add_kol_request("weibo", "same", uid)
    with pytest.raises(ValueError):
        db.add_kol_request("weibo", "same", uid)

    indexes = {r["name"] for r in db._rows("PRAGMA index_list(kols)")}
    assert "uq_kols_platform_external" in indexes
    request_indexes = {r["name"] for r in db._rows("PRAGMA index_list(kol_requests)")}
    assert "uq_kol_requests_pending" in request_indexes


def test_delete_kol_rolls_back_on_failure(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    uid = db.add_user("rollback", "h")
    kid = db.add_kol("xueqiu", "A", "rollback")
    db.add_subscription(uid, kid)
    post_id = db.insert_post("xueqiu", kid, "p1", "t", "c", "u", "")
    db.add_push_log(post_id, "telegram", "success", user_id=uid)
    db._execute(
        "CREATE TRIGGER fail_post_delete BEFORE DELETE ON posts "
        "BEGIN SELECT RAISE(ABORT, 'stop'); END"
    )

    with pytest.raises(sqlite3.IntegrityError):
        db.delete_kol(kid)

    assert db.get_kol(kid) is not None
    assert db.list_subscriptions(uid)
    assert db.list_push_logs(user_id=uid)


def test_delete_user_rolls_back_on_failure(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    uid = db.add_user("rollback", "h")
    kid = db.add_kol("xueqiu", "A", "rollback-user")
    db.add_subscription(uid, kid)
    db._execute(
        "CREATE TRIGGER fail_user_delete BEFORE DELETE ON users "
        "BEGIN SELECT RAISE(ABORT, 'stop'); END"
    )

    with pytest.raises(sqlite3.IntegrityError):
        db.delete_user(uid)

    assert db.get_user(uid) is not None
    assert db.list_subscriptions(uid)


def test_update_post_tags_empty_list_marks_post_processed(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    kid = db.add_kol("xueqiu", "测试", "tag-update")
    post_id = db.insert_post("xueqiu", kid, "p1", "t", "c", "u", "")
    assert post_id is not None

    db.update_post_tags(post_id, [])

    row = db.get_post(post_id)
    assert row is not None
    assert row["tags"] == "[]"
    assert db.tag_stats()["pending"] == 0


def test_insert_post_ignore_does_not_leave_open_txn(tmp_path):
    """IGNORE 命中唯一约束后不能留下悬空事务（否则下一个 BEGIN 报 nested transaction）。"""
    db = DB(str(tmp_path / "t.db"))
    kid = db.add_kol("xueqiu", "A", "txn-ignore")
    assert db.insert_post("xueqiu", kid, "p1", "t", "c", "u", "") is not None
    assert db.insert_post("xueqiu", kid, "p1", "t", "c", "u", "") is None  # IGNORE 命中
    assert db.insert_post("xueqiu", kid, "p2", "t", "c", "u", "") is not None
    # 悬空事务会在这里抛 sqlite3.OperationalError: cannot start a transaction within a transaction
    db._conn.execute("BEGIN")
    db._conn.execute("SELECT 1")
    db._conn.commit()


def test_register_codes_migrate_batch_columns(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE register_codes (
            code TEXT PRIMARY KEY,
            note TEXT NOT NULL DEFAULT '',
            used_by INTEGER,
            used_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.execute(
        "INSERT INTO register_codes (code, note) VALUES ('OLDCODE1', '朋友'), ('OLDCODE2', '内部')"
    )
    conn.commit()
    conn.close()

    db = DB(str(path))
    cols = {r["name"] for r in db._rows("PRAGMA table_info(register_codes)")}
    assert {"batch_id", "expires_at", "revoked_at", "created_by"} <= cols
    rows = db.list_register_codes()
    assert len(rows) == 2
    assert all(r["batch_id"] for r in rows)
    assert rows[0]["batch_id"] != rows[1]["batch_id"]
    assert all(r["expires_at"] in (None, "") for r in rows)
    assert all(r["revoked_at"] in (None, "") for r in rows)
    db.close()


def test_add_and_list_register_code_batch_fields(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    admin_id = db.add_user("admin01", "h", is_admin=True)
    db.add_register_code(
        "ABCD2345",
        note="朋友",
        batch_id="batch01",
        expires_at="2030-01-01 00:00:00",
        created_by=admin_id,
    )
    db.add_register_code("EFGH6789", note="朋友", batch_id="batch01")
    rows = [r for r in db.list_register_codes() if r["batch_id"] == "batch01"]
    assert {r["code"] for r in rows} == {"ABCD2345", "EFGH6789"}
    one = next(r for r in rows if r["code"] == "ABCD2345")
    assert one["created_by_name"] == "admin01"
    assert one["expires_at"] == "2030-01-01 00:00:00"
    db.close()


def test_register_with_code_rejects_revoked_and_expired(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    db.add_register_code("AVAIL001")
    uid = db.register_with_code("AVAIL001", "user01", "hash")
    assert uid > 0
    with pytest.raises(ValueError, match="无效或已被使用"):
        db.register_with_code("AVAIL001", "user02", "hash")

    db.add_register_code("REVOKED1")
    assert db.revoke_register_code("REVOKED1")
    with pytest.raises(ValueError, match="已作废"):
        db.register_with_code("REVOKED1", "user03", "hash")

    db.add_register_code("EXPIRED1")
    db._execute(
        "UPDATE register_codes SET expires_at = datetime('now', '-1 day') WHERE code = 'EXPIRED1'"
    )
    with pytest.raises(ValueError, match="已过期"):
        db.register_with_code("EXPIRED1", "user04", "hash")
    assert db.get_user_by_username_ci("user03") is None
    assert db.get_user_by_username_ci("user04") is None
    db.close()


def test_revoke_and_update_register_code_note(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    db.add_register_code("NOTE0001", note="朋友", batch_id="b1")
    db.add_register_code("NOTE0002", note="朋友", batch_id="b1")
    db.register_with_code("NOTE0001", "used01", "hash")
    assert db.revoke_register_code("NOTE0001") is False
    assert db.revoke_register_code("NOTE0002") is True
    row = db.get_register_code("NOTE0002")
    assert row["revoked_at"]
    assert db.revoke_unused_in_batch("b1") == 0
    db.add_register_code("NOTE0003", note="x", batch_id="b2")
    db.add_register_code("NOTE0004", note="x", batch_id="b2")
    db.register_with_code("NOTE0003", "used02", "hash")
    assert db.revoke_unused_in_batch("b2") == 1
    assert db.get_register_code("NOTE0003")["revoked_at"] in (None, "")
    assert db.get_register_code("NOTE0004")["revoked_at"]
    db.update_register_code_note("NOTE0003", "给张三")
    assert db.get_register_code("NOTE0003")["note"] == "给张三"
    db.close()
