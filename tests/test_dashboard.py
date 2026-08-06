"""数据看板聚合统计测试。"""
from app.db import DB


def test_dashboard_stats_empty_db():
    db = DB(":memory:")
    d = db.dashboard_stats()
    assert d["users"]["total"] == 0
    assert d["users"]["bound"] == 0
    assert d["subscriptions"]["total"] == 0
    assert d["posts"]["total"] == 0
    assert d["pushes"]["total_7d"] == 0
    assert d["pushes"]["success_rate"] == 100.0  # 无推送视为 100%
    assert d["pushes"]["trend_14d"] == []
    assert d["sources_fail_24h"] == {}


def test_dashboard_stats_aggregates():
    from app.fetchers.base import Post

    db = DB(":memory:")
    # 两个用户，一个绑定渠道
    u1 = db.add_user("alice", "hash1")
    u2 = db.add_user("bob", "hash2")
    db.update_user(u1, telegram_chat_id="111")
    # 订阅与帖子
    k1 = db.add_kol("twitter", "大V甲", "https://x.com/a")
    db.add_subscription(u1, k1)
    db.add_subscription(u2, k1)
    db.insert_posts_batch([
        Post("twitter", k1, "大V甲", "t1", "内容一", "", "", "2026-08-05 10:00"),
        Post("twitter", k1, "大V甲", "t2", "内容二", "", "", "2026-08-06 10:00"),
    ])
    # 推送记录（7 天内：3 成功 1 失败）
    post = db.list_posts(limit=10)[0]
    for ch, status in [("telegram", "success"), ("feishu", "success"), ("wecom", "success"), ("telegram", "failed")]:
        db.add_push_log(post["id"], ch, status, user_id=u1)

    d = db.dashboard_stats()
    assert d["users"]["total"] == 2
    assert d["users"]["bound"] == 1
    assert d["subscriptions"]["total"] == 2
    assert d["subscriptions"]["favorite"] == 0
    assert d["posts"]["total"] == 2
    assert d["posts"]["by_platform"] == {"twitter": 2}
    assert d["pushes"]["total_7d"] == 4
    assert d["pushes"]["ok_7d"] == 3
    assert d["pushes"]["fail_7d"] == 1
    assert d["pushes"]["success_rate"] == 75.0
    assert d["pushes"]["by_channel"]["telegram"] == {"total": 2, "ok": 1}
    assert d["pushes"]["by_channel"]["feishu"] == {"total": 1, "ok": 1}
    assert d["pushes"]["trend_14d"], "应有 14 天趋势数据"
    assert sum(t["pushed"] for t in d["pushes"]["trend_14d"]) == 4
