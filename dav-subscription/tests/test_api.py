import sqlite3
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Config, WeChatConfig
from app.db import DB
from app.main import create_app


def make_client(name="test.db"):
    tmp = tempfile.mkdtemp()
    app = create_app(db_path=Path(tmp) / name)
    return TestClient(app)


def register(client, username="admin", password="secret123", expect=200):
    resp = client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
    )
    assert resp.status_code == expect, resp.text
    return resp


def auth_headers(client, username="admin", password="secret123"):
    data = register(client, username, password).json()
    # 测试辅助：注册后通过 DB 提升为管理员（生产环境只能由管理员指定）
    client.app.state.db.update_user(data["user"]["id"], is_admin=True)
    token = data["token"]
    return {"Authorization": f"Bearer {token}"}


def user_headers(client, username, password="pass123456"):
    token = register(client, username, password).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_kol_crud_api():
    client = make_client()
    headers = auth_headers(client)

    assert client.get("/api/kols", headers=headers).json() == []

    resp = client.post(
        "/api/kols", headers=headers, json={"platform": "xueqiu", "name": "大V", "external_id": "123"}
    )
    assert resp.status_code == 200
    kid = resp.json()["id"]

    assert (
        client.post(
            "/api/kols", headers=headers, json={"platform": "facebook", "name": "x", "external_id": "1"}
        ).status_code
        == 400
    )

    resp = client.put(f"/api/kols/{kid}", headers=headers, json={"enabled": False})
    assert resp.status_code == 200
    assert resp.json()["enabled"] == 0

    assert client.delete(f"/api/kols/{kid}", headers=headers).status_code == 200
    assert client.get("/api/kols", headers=headers).json() == []


def test_kol_add_with_xueqiu_homepage_link():
    client = make_client()
    headers = auth_headers(client)
    resp = client.post(
        "/api/kols",
        headers=headers,
        json={"platform": "xueqiu", "name": "大V", "external_id": "https://xueqiu.com/u/8790885129"},
    )
    assert resp.status_code == 200
    assert resp.json()["external_id"] == "8790885129"


def test_posts_and_push_logs_api():
    client = make_client()
    headers = auth_headers(client)
    kid = client.post(
        "/api/kols", headers=headers, json={"platform": "xueqiu", "name": "A", "external_id": "1"}
    ).json()["id"]
    client.app.state.db.insert_post("xueqiu", kid, "p1", "t", "c", "u", "")
    assert client.get("/api/posts", headers=headers).json()[0]["title"] == "t"
    assert client.get("/api/push-logs", headers=headers).json() == []


def test_category_crud_and_kol_assignment():
    client = make_client()
    headers = auth_headers(client)

    resp = client.post("/api/categories", headers=headers, json={"name": "实盘"})
    assert resp.status_code == 200
    cid = resp.json()["id"]
    assert client.post("/api/categories", headers=headers, json={"name": "实盘"}).status_code == 400

    kid = client.post(
        "/api/kols",
        headers=headers,
        json={"platform": "xueqiu", "name": "A", "external_id": "1", "category_id": cid},
    ).json()["id"]
    assert client.get("/api/kols", headers=headers).json()[0]["category_name"] == "实盘"
    assert client.get(f"/api/kols?category_id={cid}", headers=headers).json()[0]["id"] == kid

    resp = client.put(f"/api/kols/{kid}", headers=headers, json={"category_id": None})
    assert resp.status_code == 200
    assert resp.json()["category_name"] is None

    assert client.post(
        "/api/kols", headers=headers, json={"platform": "xueqiu", "name": "B", "external_id": "2", "category_id": 999}
    ).status_code == 400

    client.post(
        "/api/kols", headers=headers, json={"platform": "xueqiu", "name": "C", "external_id": "3", "category_id": cid}
    )
    assert client.delete(f"/api/categories/{cid}", headers=headers).status_code == 200
    kols = client.get("/api/kols", headers=headers).json()
    assert all(k["category_name"] is None for k in kols)


def test_auth_flow():
    client = make_client()
    # 注册用户默认不是管理员
    headers = user_headers(client, "admin")
    me = client.get("/api/me", headers=headers).json()
    assert me["username"] == "admin" and me["is_admin"] is False

    # 弱密码 / 重复用户名
    assert client.post("/api/auth/register", json={"username": "u2", "password": "123"}).status_code == 400
    assert client.post(
        "/api/auth/register", json={"username": "admin", "password": "secret123"}
    ).status_code == 400

    # 登录失败/成功
    assert client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    token = client.post("/api/auth/login", json={"username": "admin", "password": "pass123456"}).json()["token"]
    assert client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    # 普通用户不能访问管理接口
    assert client.get("/api/kols", headers=headers).status_code == 403
    assert client.get("/api/posts", headers=headers).status_code == 403

    # 管理员在后台指定另一个用户为管理员
    admin_headers = auth_headers(client, "boss", "secret123")
    target_id = client.get("/api/users", headers=admin_headers).json()[0]["id"]
    resp = client.put(f"/api/users/{target_id}", headers=admin_headers, json={"is_admin": True})
    assert resp.status_code == 200 and resp.json()["is_admin"] is True
    # 不能取消自己的管理员权限
    self_id = client.get("/api/me", headers=admin_headers).json()["id"]
    assert client.put(f"/api/users/{self_id}", headers=admin_headers, json={"is_admin": False}).status_code == 400


def test_subscription_flow():
    client = make_client()
    admin_headers = auth_headers(client)
    kid = client.post(
        "/api/kols", headers=admin_headers, json={"platform": "xueqiu", "name": "超级鹿鼎公", "external_id": "8790885129"}
    ).json()["id"]

    customer_headers = user_headers(client, "customer")
    catalog = client.get("/api/catalog", headers=customer_headers).json()
    assert catalog[0]["subscribed"] is False

    assert client.post("/api/subscriptions", headers=customer_headers, json={"kol_id": kid}).status_code == 200
    assert client.get("/api/catalog", headers=customer_headers).json()[0]["subscribed"] is True
    assert client.get("/api/my/subscriptions", headers=customer_headers).json()[0]["id"] == kid

    # 订阅后能看到该大V的动态
    client.app.state.db.insert_post("xueqiu", kid, "p1", "t", "c", "u", "")
    feed = client.get("/api/my/feed", headers=customer_headers).json()
    assert len(feed) == 1 and feed[0]["kol_name"] == "超级鹿鼎公"

    # 取消订阅后动态清空
    assert client.delete(f"/api/subscriptions/{kid}", headers=customer_headers).status_code == 200
    assert client.get("/api/my/feed", headers=customer_headers).json() == []

    # 大V详情与动态（未订阅也可查看）
    detail = client.get(f"/api/kols/{kid}", headers=customer_headers).json()
    assert detail["name"] == "超级鹿鼎公" and detail["subscribed"] is False
    posts = client.get(f"/api/kols/{kid}/posts", headers=customer_headers).json()
    assert len(posts) == 1

    # 资料绑定
    resp = client.put(
        "/api/me",
        headers=customer_headers,
        json={"telegram_chat_id": "tg123", "feishu_open_id": "open456", "notify_enabled": True},
    )
    assert resp.status_code == 200
    assert resp.json()["telegram_chat_id"] == "tg123"


def test_wechat_login(monkeypatch):
    cfg = Config()
    cfg.wechat.app_id = "wx_app"
    cfg.wechat.app_secret = "wx_secret"
    tmp = tempfile.mkdtemp()
    app = create_app(config=cfg, db_path=Path(tmp) / "wx.db")
    client = TestClient(app)

    # 未配置时返回明确错误
    app2 = create_app(db_path=Path(tmp) / "wx2.db")
    assert (
        TestClient(app2).post("/api/auth/wechat", json={"code": "c"}).status_code == 400
    )

    monkeypatch.setattr(
        "app.wechat.code2session",
        lambda code, app_id, app_secret: {"openid": "openid_abc", "session_key": "k"},
    )
    resp = client.post("/api/auth/wechat", json={"code": "c1"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["user"]["username"].startswith("wx_")
    assert data["user"]["is_admin"] is False  # 小程序用户不会自动成为管理员

    # 再次登录返回同一用户
    resp2 = client.post("/api/auth/wechat", json={"code": "c2"})
    assert resp2.json()["user"]["id"] == data["user"]["id"]


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
    uid = db.add_user("admin", "hash", is_admin=True)
    db.add_subscription(uid, 1)
    assert db.subscribers_of_kol(1) == []
    db.close()


def test_healthz():
    client = make_client("api3.db")
    assert client.get("/healthz").json() == {"status": "ok"}
