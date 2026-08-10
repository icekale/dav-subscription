"""DB 层单元测试：kols.secondary 列迁移、写入与 priority 互斥。"""
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
