import tempfile
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.db import DB


def test_kol_crud_api():
    tmp = tempfile.mkdtemp()
    app = create_app(db_path=Path(tmp) / "api.db")
    client = TestClient(app)

    resp = client.get("/api/kols")
    assert resp.status_code == 200
    assert resp.json() == []

    resp = client.post("/api/kols", json={"platform": "xueqiu", "name": "大V", "external_id": "123"})
    assert resp.status_code == 200
    kid = resp.json()["id"]

    resp = client.post("/api/kols", json={"platform": "facebook", "name": "x", "external_id": "1"})
    assert resp.status_code == 400

    resp = client.put(f"/api/kols/{kid}", json={"enabled": False})
    assert resp.status_code == 200
    assert resp.json()["enabled"] == 0

    resp = client.delete(f"/api/kols/{kid}")
    assert resp.status_code == 200
    assert client.get("/api/kols").json() == []


def test_posts_and_push_logs_api():
    tmp = tempfile.mkdtemp()
    app = create_app(db_path=Path(tmp) / "api2.db")
    client = TestClient(app)
    kid = client.post("/api/kols", json={"platform": "xueqiu", "name": "A", "external_id": "1"}).json()["id"]
    app.state.db.insert_post("xueqiu", kid, "p1", "t", "c", "u", "")
    assert client.get("/api/posts").json()[0]["title"] == "t"
    assert client.get("/api/push-logs").json() == []


def test_category_crud_and_kol_assignment():
    tmp = tempfile.mkdtemp()
    app = create_app(db_path=Path(tmp) / "cat.db")
    client = TestClient(app)

    resp = client.post("/api/categories", json={"name": "实盘"})
    assert resp.status_code == 200
    cid = resp.json()["id"]
    assert client.post("/api/categories", json={"name": "实盘"}).status_code == 400

    kid = client.post(
        "/api/kols",
        json={"platform": "xueqiu", "name": "A", "external_id": "1", "category_id": cid},
    ).json()["id"]
    assert client.get("/api/kols").json()[0]["category_name"] == "实盘"
    assert client.get(f"/api/kols?category_id={cid}").json()[0]["id"] == kid

    # 清除分类
    resp = client.put(f"/api/kols/{kid}", json={"category_id": None})
    assert resp.status_code == 200
    assert resp.json()["category_name"] is None

    # 分类不存在时报错
    assert client.post(
        "/api/kols", json={"platform": "xueqiu", "name": "B", "external_id": "2", "category_id": 999}
    ).status_code == 400

    # 删除分类后 KOL 变为未分类
    client.post("/api/kols", json={"platform": "xueqiu", "name": "C", "external_id": "3", "category_id": cid})
    assert client.delete(f"/api/categories/{cid}").status_code == 200
    kols = client.get("/api/kols").json()
    assert all(k["category_name"] is None for k in kols)


def test_old_db_migrates_category_column():
    tmp = tempfile.mkdtemp()
    path = Path(tmp) / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE kols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            name TEXT NOT NULL,
            external_id TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            kol_id INTEGER NOT NULL,
            external_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '',
            published_at TEXT NOT NULL DEFAULT '',
            fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (platform, external_id)
        );
        CREATE TABLE push_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            channel TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    conn.execute("INSERT INTO kols (platform, name, external_id) VALUES ('xueqiu', '旧大V', '1')")
    conn.commit()
    conn.close()

    db = DB(path)
    cid = db.add_category("宏观")
    db.update_kol(1, category_id=cid)
    assert db.get_kol(1)["category_name"] == "宏观"
    db.close()


def test_healthz():
    tmp = tempfile.mkdtemp()
    app = create_app(db_path=Path(tmp) / "api3.db")
    client = TestClient(app)
    assert client.get("/healthz").json() == {"status": "ok"}
