"""动态广场数据源显隐：自动（启用大V=0 隐藏）/ 显示 / 隐藏。"""
from app.db import DB
from app.plaza import (
    PLAZA_PLATFORMS,
    parse_plaza_visibility,
    plaza_hidden_platforms,
    plaza_source_rows,
    plaza_visible_platforms,
    set_plaza_visibility,
)

from test_api import auth_headers, make_client, user_headers


def test_parse_plaza_visibility_defaults_and_ignores_junk():
    assert parse_plaza_visibility(None) == {p: "auto" for p in PLAZA_PLATFORMS}
    assert parse_plaza_visibility("{")["zsxq"] == "auto"
    parsed = parse_plaza_visibility('{"zsxq":"hide","ima":"show","weibo":"nope"}')
    assert parsed["zsxq"] == "hide"
    assert parsed["weibo"] == "auto"
    assert "ima" not in parsed


def test_plaza_auto_hides_when_no_enabled_kol(tmp_path):
    db = DB(str(tmp_path / "plaza.db"))
    assert plaza_visible_platforms(db) == []
    db.add_kol("xueqiu", "雪球大V", "x1")
    zq = db.add_kol("zsxq", "前沿信息收录", "28888112822211")
    assert "xueqiu" in plaza_visible_platforms(db)
    assert "zsxq" in plaza_visible_platforms(db)
    db.set_kols_enabled([zq], False)
    assert "zsxq" not in plaza_visible_platforms(db)
    assert "zsxq" in plaza_hidden_platforms(db)
    set_plaza_visibility(db, {"zsxq": "show"})
    assert "zsxq" in plaza_visible_platforms(db)
    set_plaza_visibility(db, {"xueqiu": "hide"})
    assert "xueqiu" not in plaza_visible_platforms(db)
    row = next(r for r in plaza_source_rows(db) if r["platform"] == "xueqiu")
    assert row["mode"] == "hide" and row["enabled_kols"] == 1 and row["visible"] is False


def test_plaza_sources_api_and_feed_filter():
    client = make_client()
    admin = auth_headers(client)
    db = client.app.state.db
    xq = db.add_kol("xueqiu", "雪球大V", "x1")
    zq = db.add_kol("zsxq", "前沿信息收录", "28888112822211")
    uh = user_headers(client, "plazareader")
    reader_id = client.get("/api/me", headers=uh).json()["id"]
    db.add_subscription(reader_id, xq, type="post")
    db.add_subscription(reader_id, zq, type="post")
    db.insert_post("xueqiu", xq, "xq1", "雪球帖", "正文", "u1", "")
    db.insert_post("zsxq", zq, "zq1", "星球帖", "附件", "u2", "")

    me = client.get("/api/me", headers=uh).json()
    assert "xueqiu" in me["plaza_platforms"]
    assert "zsxq" in me["plaza_platforms"]

    assert client.get("/api/admin/plaza-sources", headers=uh).status_code == 403
    sources = client.get("/api/admin/plaza-sources", headers=admin).json()["sources"]
    assert {row["platform"] for row in sources} == set(PLAZA_PLATFORMS)
    assert all(row["mode"] == "auto" for row in sources)

    assert client.put(
        "/api/admin/plaza-sources",
        headers=admin,
        json={"visibility": {"zsxq": "maybe"}},
    ).status_code == 400
    assert client.put(
        "/api/admin/plaza-sources",
        headers=admin,
        json={"visibility": {"ima": "hide"}},
    ).status_code == 400

    hid = client.put(
        "/api/admin/plaza-sources",
        headers=admin,
        json={"visibility": {"zsxq": "hide"}},
    )
    assert hid.status_code == 200
    zsxq = next(row for row in hid.json()["sources"] if row["platform"] == "zsxq")
    assert zsxq["visible"] is False and zsxq["mode"] == "hide"
    assert "zsxq" not in client.get("/api/me", headers=uh).json()["plaza_platforms"]
    assert all(k["platform"] != "zsxq" for k in client.get("/api/catalog", headers=uh).json())
    assert client.get("/api/catalog?platform=zsxq", headers=uh).json() == []
    assert all(r["platform"] != "zsxq" for r in client.get("/api/recommendations", headers=uh).json())
    assert all(k["platform"] != "zsxq" for k in client.get("/api/my/subscriptions", headers=uh).json())
    assert client.get(f"/api/kols/{zq}", headers=uh).status_code == 404
    assert client.get(f"/api/kols/{zq}/posts", headers=uh).status_code == 404
    assert client.get(f"/api/kols/{zq}", headers=admin).status_code == 200
    uh2 = user_headers(client, "plazahidden")
    assert (
        client.post("/api/subscriptions", headers=uh2, json={"kol_id": zq, "type": "post"}).status_code
        == 404
    )
    stats_zsxq = next(
        row
        for row in client.get("/api/stats", headers=admin).json()["plaza_sources"]
        if row["platform"] == "zsxq"
    )
    assert stats_zsxq["visible"] is False

    feed = client.get("/api/my/feed", headers=uh).json()
    assert [p["external_id"] for p in feed] == ["xq1"]
    assert client.get("/api/my/feed?platform=zsxq", headers=uh).json() == []

    client.put(
        "/api/admin/plaza-sources",
        headers=admin,
        json={"visibility": {"zsxq": "show"}},
    )
    assert [p["external_id"] for p in client.get("/api/my/feed?platform=zsxq", headers=uh).json()] == [
        "zq1"
    ]

    db.set_kols_enabled([zq], False)
    client.put(
        "/api/admin/plaza-sources",
        headers=admin,
        json={"visibility": {"zsxq": "auto"}},
    )
    assert "zsxq" not in client.get("/api/me", headers=uh).json()["plaza_platforms"]
    assert client.get("/api/my/feed?platform=zsxq", headers=uh).json() == []
    assert [p["external_id"] for p in client.get("/api/my/feed", headers=uh).json()] == ["xq1"]
    assert all(k["platform"] != "zsxq" for k in client.get("/api/catalog", headers=uh).json())
