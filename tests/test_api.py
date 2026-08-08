import json
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import Config
from app.db import DB
from app.main import create_app

_reg_code_seq = 0


def make_client(name="test.db", config=None):
    tmp = tempfile.mkdtemp()
    app = create_app(config=config, db_path=Path(tmp) / name)
    return TestClient(app)


def register(client, username="testadmin", password="secret123", expect=200, code=None):
    global _reg_code_seq
    if code is None:
        _reg_code_seq += 1
        code = f"TEST{_reg_code_seq:04d}"
        client.app.state.db.add_register_code(code)
    resp = client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "code": code},
    )
    assert resp.status_code == expect, resp.text
    return resp


def auth_headers(client, username="testadmin", password="secret123"):
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


def test_add_x_kol_auto_resolves_name_and_avatar(monkeypatch):
    from app import api as api_mod

    monkeypatch.setattr(
        api_mod,
        "resolve_x_profile",
        lambda external_id, cookie="": {
            "name": "SemiAnalysis",
            "avatar_url": "https://pbs.twimg.com/x_400x400.jpg",
            "screen_name": "SemiAnalysis_",
        },
    )
    client = make_client()
    headers = auth_headers(client)
    resp = client.post(
        "/api/kols",
        headers=headers,
        json={"platform": "twitter", "name": "", "external_id": "https://x.com/SemiAnalysis_"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "SemiAnalysis"
    assert resp.json()["avatar_url"] == "https://pbs.twimg.com/x_400x400.jpg"


def test_batch_import_x_kol_auto_resolves_name(monkeypatch):
    from app import api as api_mod

    monkeypatch.setattr(
        api_mod,
        "resolve_x_profile",
        lambda external_id, cookie="": {
            "name": "elonmusk",
            "avatar_url": "https://pbs.twimg.com/musk.jpg",
            "screen_name": "elonmusk",
        },
    )
    client = make_client()
    headers = auth_headers(client)
    resp = client.post(
        "/api/kols/batch",
        headers=headers,
        json={"platform": "twitter", "lines": "https://x.com/elonmusk"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] == 1
    kols = client.get("/api/kols", headers=headers).json()
    assert any(k["name"] == "elonmusk" for k in kols)


def test_batch_import_weibo_with_nickname_fetches_avatar(monkeypatch):
    from app import api as api_mod

    monkeypatch.setattr(
        api_mod,
        "resolve_weibo_profile",
        lambda external_id, cookie="": {
            "name": "新浪娱乐",
            "avatar_url": "https://wx1.sinaimg.cn/avatar.jpg",
            "uid": "1642591402",
        },
    )
    client = make_client()
    headers = auth_headers(client)
    resp = client.post(
        "/api/kols/batch",
        headers=headers,
        json={"platform": "weibo", "lines": "新浪娱乐 https://weibo.com/u/1642591402"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] == 1
    kols = client.get("/api/kols", headers=headers).json()
    target = next(k for k in kols if k["platform"] == "weibo")
    assert target["name"] == "新浪娱乐"
    assert target["avatar_url"] == "https://wx1.sinaimg.cn/avatar.jpg"


def test_add_weibo_kol_auto_resolves_name_and_avatar(monkeypatch):
    from app import api as api_mod

    monkeypatch.setattr(
        api_mod,
        "resolve_weibo_profile",
        lambda uid, cookie="": {
            "name": "wu2198",
            "avatar_url": "https://wx1.sinaimg.cn/orj360/wb.jpg",
            "uid": uid,
        },
    )
    client = make_client()
    headers = auth_headers(client)
    resp = client.post(
        "/api/kols",
        headers=headers,
        json={"platform": "weibo", "name": "", "external_id": "https://weibo.com/u/123456"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "wu2198"
    assert resp.json()["avatar_url"] == "https://wx1.sinaimg.cn/orj360/wb.jpg"


def test_stats_api():
    client = make_client()
    headers = auth_headers(client)
    client.post(
        "/api/kols", headers=headers, json={"platform": "xueqiu", "name": "A", "external_id": "1", "priority": True}
    )
    stats = client.get("/api/stats", headers=headers).json()
    assert stats["kols"] == 1
    assert stats["enabled_kols"] == 1
    assert stats["priority_kols"] == 1
    assert stats["users"] == 1
    assert stats["posts"] == 0
    assert "polling_interval_seconds" in stats


def test_recommendations_api_sorted_by_subscribers():
    client = make_client()
    admin = auth_headers(client)
    hot = client.post(
        "/api/kols", headers=admin, json={"platform": "xueqiu", "name": "热门", "external_id": "1"}
    ).json()["id"]
    cold = client.post(
        "/api/kols", headers=admin, json={"platform": "weibo", "name": "冷门", "external_id": "2"}
    ).json()["id"]
    u1 = user_headers(client, "sub_aa")
    u2 = user_headers(client, "sub_bb")
    for h in (u1, u2):
        assert client.post("/api/subscriptions", headers=h, json={"kol_id": hot, "type": "post"}).status_code == 200
    recs = client.get("/api/recommendations", headers=u1).json()
    assert [r["id"] for r in recs] == [hot, cold]
    assert recs[0]["subscriber_count"] == 2
    assert recs[0]["subscribed"] is True
    assert recs[1]["subscribed"] is False


def test_stats_x_direct_mode():
    client = make_client()
    headers = auth_headers(client)
    data = client.get("/api/stats", headers=headers).json()
    twitter = next(s for s in data["sources"] if s["platform"] == "twitter")
    assert twitter["direct_mode"] == "unknown"

    client.app.state.db.set_setting("x_direct_last_fallback_at", "1785900000")
    client.app.state.db.set_setting("x_direct_fallback_reason", "401 Unauthorized")
    data = client.get("/api/stats", headers=headers).json()
    twitter = next(s for s in data["sources"] if s["platform"] == "twitter")
    assert twitter["direct_mode"] == "fallback"
    assert "401" in twitter["direct_fallback_reason"]
    # 普通用户无权访问
    normal = user_headers(client, "viewer")
    assert client.get("/api/stats", headers=normal).status_code == 403


def test_kol_priority_toggle():
    client = make_client()
    headers = auth_headers(client)
    kid = client.post(
        "/api/kols", headers=headers, json={"platform": "xueqiu", "name": "A", "external_id": "1", "priority": True}
    ).json()["id"]
    assert client.get(f"/api/kols/{kid}", headers=headers).json()["priority"] == 1
    resp = client.put(f"/api/kols/{kid}", headers=headers, json={"priority": False})
    assert resp.json()["priority"] == 0


def test_bind_code_api():
    client = make_client()
    headers = user_headers(client, "someone")
    me = client.get("/api/me", headers=headers).json()
    resp = client.post("/api/me/bind-code", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["code"]) == 6
    assert data["expires_in_seconds"] == 600
    row = client.app.state.db.get_bind_code(data["code"])
    assert row["user_id"] == me["id"]


def test_system_logs_api():
    client = make_client()
    admin_headers = auth_headers(client)
    resp = client.get("/api/admin/system-logs?limit=50", headers=admin_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json()["lines"], list)
    # 级别 + 关键词过滤参数（供网页/Agent 精准取数）
    resp = client.get(
        "/api/admin/system-logs?level=ERROR&q=test&limit=50",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert isinstance(resp.json()["lines"], list)
    # 非法级别拒绝
    assert (
        client.get("/api/admin/system-logs?level=BOGUS", headers=admin_headers).status_code
        == 400
    )
    # 普通用户无权限
    uh = user_headers(client, "syslog_user")
    assert client.get("/api/admin/system-logs", headers=uh).status_code == 403


def test_version_api(monkeypatch):
    monkeypatch.setattr("app.version.latest_github_version", lambda db: ("1.6.2", True))
    client = make_client()
    resp = client.get("/api/version")
    assert resp.status_code == 200
    data = resp.json()
    assert data["current"] == "1.6.1"
    assert data["latest"] == "1.6.2"
    assert data["update_available"] is True
    assert "github.com" in data["url"]


def test_kol_request_notifies_admins(monkeypatch):
    client = make_client()
    auth_headers(client)
    admin = client.app.state.db.get_user_by_username("testadmin")
    # 自建 bot token 让通知分支与本地 config.yaml 解耦（CI 无 config.yaml 也能过）
    client.app.state.db.update_user(admin["id"], telegram_chat_id="111", telegram_bot_token="tok")
    sent = []

    class FakeTG:
        def __init__(self, *args, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)

        def send_text(self, text):
            sent.append(text)

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FakeTG)
    headers = user_headers(client, "requser")
    resp = client.post(
        "/api/kol-requests",
        headers=headers,
        json={"platform": "xueqiu", "external_id": "https://xueqiu.com/u/999999"},
    )
    assert resp.status_code == 200
    assert any("新的大V添加申请" in t and "999999" in t for t in sent)


def test_push_channels_api():
    client = make_client()
    headers = user_headers(client, "chuser")
    # 默认空 = 全部已绑定渠道推送
    assert client.get("/api/me", headers=headers).json()["push_channels"] == ""
    # 设置合法渠道
    resp = client.put("/api/me", headers=headers, json={"push_channels": "telegram,feishu"})
    assert resp.status_code == 200
    assert resp.json()["push_channels"] == "telegram,feishu"
    # 非法渠道被拒绝
    resp = client.put("/api/me", headers=headers, json={"push_channels": "sms"})
    assert resp.status_code == 400
    # 清空恢复默认（全部）
    resp = client.put("/api/me", headers=headers, json={"push_channels": ""})
    assert resp.status_code == 200
    assert resp.json()["push_channels"] == ""


def test_dnd_api_validation():
    client = make_client()
    headers = user_headers(client, "dnduser")
    resp = client.put("/api/me", headers=headers, json={"dnd_start": "23:00", "dnd_end": "07:00"})
    assert resp.status_code == 200
    me = resp.json()
    assert me["dnd_start"] == "23:00" and me["dnd_end"] == "07:00"
    # 非法时间格式被拒绝
    resp = client.put("/api/me", headers=headers, json={"dnd_start": "99:99"})
    assert resp.status_code == 400
    # 关闭：清空
    resp = client.put("/api/me", headers=headers, json={"dnd_start": "", "dnd_end": ""})
    assert resp.status_code == 200
    assert resp.json()["dnd_start"] == "" and resp.json()["dnd_end"] == ""


def test_favorite_api():
    client = make_client()
    admin = auth_headers(client)
    headers = user_headers(client, "favuser")
    kid = client.post(
        "/api/kols", headers=admin, json={"platform": "xueqiu", "name": "A", "external_id": "fav1"}
    ).json()["id"]
    kid2 = client.post(
        "/api/kols", headers=admin, json={"platform": "xueqiu", "name": "B", "external_id": "fav2"}
    ).json()["id"]
    client.post("/api/subscriptions", headers=headers, json={"kol_id": kid})

    resp = client.put(f"/api/subscriptions/{kid}/favorite", headers=headers, json={"favorite": True})
    assert resp.status_code == 200
    cat = client.get("/api/catalog", headers=headers).json()
    assert next(k for k in cat if k["id"] == kid)["favorite"] is True
    assert next(k for k in cat if k["id"] == kid2)["favorite"] is False
    # 未订阅的大V不能标星
    assert (
        client.put(f"/api/subscriptions/{kid2}/favorite", headers=headers, json={"favorite": True}).status_code
        == 404
    )
    # 取消特别关注
    client.put(f"/api/subscriptions/{kid}/favorite", headers=headers, json={"favorite": False})
    cat = client.get("/api/catalog", headers=headers).json()
    assert next(k for k in cat if k["id"] == kid)["favorite"] is False
    # 免打扰穿透开关
    resp = client.put("/api/me", headers=headers, json={"dnd_allow_favorite": True})
    assert resp.status_code == 200
    assert resp.json()["dnd_allow_favorite"] is True


def test_change_password_api():
    client = make_client()
    headers = user_headers(client, "pwuser")

    # 原密码错误
    resp = client.post(
        "/api/me/password",
        headers=headers,
        json={"old_password": "wrong", "new_password": "newpass123"},
    )
    assert resp.status_code == 400 and "原密码" in resp.json()["detail"]

    # 新密码太短
    resp = client.post(
        "/api/me/password",
        headers=headers,
        json={"old_password": "pass123456", "new_password": "123"},
    )
    assert resp.status_code == 400 and "至少6位" in resp.json()["detail"]

    # 正常修改后旧密码失效、新密码可登录
    resp = client.post(
        "/api/me/password",
        headers=headers,
        json={"old_password": "pass123456", "new_password": "newpass123"},
    )
    assert resp.status_code == 200
    assert client.post("/api/auth/login", json={"username": "pwuser", "password": "pass123456"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "pwuser", "password": "newpass123"}).status_code == 200


def test_channel_claim_conflict():
    client = make_client()
    headers_a = user_headers(client, "user_a")
    headers_b = user_headers(client, "user_b")
    wc_hook = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=wc1"

    assert client.put("/api/me", headers=headers_a, json={"telegram_chat_id": "111"}).status_code == 200
    resp = client.put("/api/me", headers=headers_b, json={"telegram_chat_id": "111"})
    assert resp.status_code == 400 and "已绑定" in resp.json()["detail"]

    assert client.put("/api/me", headers=headers_a, json={"feishu_open_id": "ou_1"}).status_code == 200
    resp = client.put("/api/me", headers=headers_b, json={"feishu_open_id": "ou_1"})
    assert resp.status_code == 400

    assert client.put("/api/me", headers=headers_a, json={"wecom_webhook": wc_hook}).status_code == 200
    resp = client.put("/api/me", headers=headers_b, json={"wecom_webhook": wc_hook})
    assert resp.status_code == 400 and "企业微信" in resp.json()["detail"]

    # 非法 webhook 地址被拒绝
    resp = client.put("/api/me", headers=headers_b, json={"wecom_webhook": "https://example.com/x"})
    assert resp.status_code == 400

    # 解绑自己的渠道不受影响
    assert client.put("/api/me", headers=headers_a, json={"telegram_chat_id": ""}).status_code == 200
    assert client.put("/api/me", headers=headers_a, json={"wecom_webhook": ""}).status_code == 200


def test_custom_telegram_bot_bind(monkeypatch):
    from app import api as api_mod

    monkeypatch.setattr(
        api_mod,
        "_resolve_telegram_bot",
        lambda token: ("my_bot", "777", ""),
    )
    client = make_client()
    h = user_headers(client, "custom_bot")
    assert client.put("/api/me", headers=h, json={"telegram_bot_token": "123:abc"}).status_code == 200
    me = client.get("/api/me", headers=h).json()
    assert me["custom_telegram_bot"] is True
    assert me["telegram_chat_id"] == "777"

    # 未先给自己的 bot 发消息 → 绑定失败并提示
    monkeypatch.setattr(
        api_mod,
        "_resolve_telegram_bot",
        lambda token: ("", "", "请先给你的机器人发一条消息"),
    )
    resp = client.put(
        "/api/me", headers=h, json={"telegram_bot_token": "999:abc"}
    )
    assert resp.status_code == 400 and "请先" in resp.json()["detail"]

    # 解绑自建机器人
    assert client.put("/api/me", headers=h, json={"telegram_bot_token": ""}).status_code == 200
    assert client.get("/api/me", headers=h).json()["custom_telegram_bot"] is False


def test_resolve_telegram_bot_parses_chat_id(monkeypatch):
    from app import api as api_mod

    calls = []

    class FakeResp:
        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self._data

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None):
            calls.append(url)
            if "getMe" in url:
                return FakeResp({"ok": True, "result": {"username": "my_bot"}})
            return FakeResp(
                {
                    "ok": True,
                    "result": [
                        {"message": {"chat": {"id": 111}}},
                        {"message": {"chat": {"id": 777}}},
                    ],
                }
            )

    monkeypatch.setattr("httpx.Client", FakeClient)
    username, chat_id, err = api_mod._resolve_telegram_bot("tok")
    assert username == "my_bot"
    assert chat_id == "777"  # 取最新的会话
    assert err == ""
    assert any("getMe" in u for u in calls)
    assert any("getUpdates" in u for u in calls)


def test_login_rate_limit():
    client = make_client()
    for _ in range(8):
        assert client.post("/api/auth/login", json={"username": "nobody", "password": "wrong123"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "nobody", "password": "wrong123"}).status_code == 429


def test_admin_delete_user_cascades():
    client = make_client()
    admin_headers = auth_headers(client, "boss01")
    reg = register(client, "doomed")
    uid = reg.json()["user"]["id"]
    doomed_headers = {"Authorization": f"Bearer {reg.json()['token']}"}
    kid = client.post("/api/kols", headers=admin_headers, json={"platform": "xueqiu", "name": "A", "external_id": "1"}).json()["id"]
    client.post("/api/subscriptions", headers=doomed_headers, json={"kol_id": kid})

    # 不能删除自己
    self_id = client.get("/api/me", headers=admin_headers).json()["id"]
    assert client.delete(f"/api/users/{self_id}", headers=admin_headers).status_code == 400

    resp = client.delete(f"/api/users/{uid}", headers=admin_headers)
    assert resp.status_code == 200
    remaining = client.get("/api/users", headers=admin_headers).json()
    assert all(u["id"] != uid for u in remaining)
    # 订阅关系一并清除
    assert client.app.state.db.list_subscriptions(uid) == []


def test_admin_reset_password():
    client = make_client()
    admin_headers = auth_headers(client, "boss01")
    user_headers(client, "victim", "oldpass123")

    users = client.get("/api/users", headers=admin_headers).json()
    uid = next(u["id"] for u in users if u["username"] == "victim")
    # 新密码太短
    assert client.put(f"/api/users/{uid}", headers=admin_headers, json={"password": "123"}).status_code == 400
    assert client.put(f"/api/users/{uid}", headers=admin_headers, json={"password": "newpass456"}).status_code == 200
    assert client.post("/api/auth/login", json={"username": "victim", "password": "oldpass123"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "victim", "password": "newpass456"}).status_code == 200


def test_admin_rename_username():
    client = make_client()
    admin_headers = auth_headers(client, "boss01")
    user_headers(client, "victim")

    users = client.get("/api/users", headers=admin_headers).json()
    uid = next(u["id"] for u in users if u["username"] == "victim")

    # 过短 / 重名
    assert client.put(f"/api/users/{uid}", headers=admin_headers, json={"username": "x"}).status_code == 400
    assert client.put(f"/api/users/{uid}", headers=admin_headers, json={"username": "boss01"}).status_code == 400
    # 改成自己的原名（不改动）应放行
    assert client.put(f"/api/users/{uid}", headers=admin_headers, json={"username": "victim"}).status_code == 200

    assert client.put(f"/api/users/{uid}", headers=admin_headers, json={"username": "renamed"}).status_code == 200
    assert client.post("/api/auth/login", json={"username": "victim", "password": "pass123456"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "renamed", "password": "pass123456"}).status_code == 200


def test_admin_test_push(monkeypatch):
    sent = []

    class FakeTelegram:
        def __init__(self, config, chat_id=None, client=None, **kwargs):
            self.chat_id = chat_id
            self.client = type("C", (), {"close": lambda self: None})()

        def send_text(self, text):
            sent.append(("tg", self.chat_id, text))

    class FakeFeishu:
        def __init__(self, config, open_id=None, chat_id=None, client=None, **kwargs):
            self.client = type("C", (), {"close": lambda self: None})()

        def send_text(self, text):
            sent.append(("fs", text))

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FakeTelegram)
    monkeypatch.setattr("app.notifiers.feishu.FeishuNotifier", FakeFeishu)

    cfg = Config()
    cfg.notifiers.telegram.bot_token = "t"
    cfg.notifiers.feishu.app_id = "a"
    cfg.notifiers.feishu.app_secret = "s"
    client = make_client(config=cfg)
    admin_headers = auth_headers(client, "boss01")
    reg = register(client, "victim")
    uid = reg.json()["user"]["id"]
    victim_headers = {"Authorization": f"Bearer {reg.json()['token']}"}
    client.put(
        "/api/me",
        headers=victim_headers,
        json={"telegram_chat_id": "111", "feishu_open_id": "ou_1", "feishu_chat_id": "oc_1"},
    )

    resp = client.post(
        "/api/admin/test-push",
        headers=admin_headers,
        json={"user_id": uid, "message": "hi"},
    )
    assert resp.status_code == 200
    assert resp.json()["results"] == [
        {"channel": "telegram", "ok": True},
        {"channel": "feishu", "ok": True},
    ]
    assert sent == [("tg", "111", "【测试推送】hi"), ("fs", "【测试推送】hi")]


def test_weibo_qr_login(monkeypatch):
    class FakeResp:
        def __init__(self, payload):
            # 模拟新浪 SSO 的 JSONP 响应
            self.text = f"window.CB && CB({json.dumps(payload, ensure_ascii=False)});"

    class FakeCookie:
        def __init__(self, name, value, domain=""):
            self.name, self.value, self.domain = name, value, domain

    class FakeCookies:
        def __init__(self, cookies):
            self.jar = cookies

        def get(self, key, default=None):
            matches = [c for c in self.jar if c.name == key]
            return matches[0].value if matches else default

        def items(self):
            return [(c.name, c.value) for c in self.jar]

    class FakeClient:
        def __init__(self, **kwargs):
            self.cookies = FakeCookies([])
            self.headers = {}
            self._check_calls = 0

        def get(self, url, params=None):
            if "qrcode/image" in url:
                return FakeResp({"retcode": 20000000, "data": {"qrid": "Q1", "image": "//qr.example/q.png"}})
            if "qrcode/check" in url:
                self._check_calls += 1
                if self._check_calls == 1:
                    return FakeResp({"retcode": 50114001, "data": None})
                return FakeResp({"retcode": 20000000, "data": {"alt": "ALT"}})
            if "login.php" in url:
                return FakeResp({"crossDomainUrlList": ["http://cross.example/1"]})
            if "cross.example" in url:
                # 模拟跨域登录后出现同名多域的 SUB cookie（httpx 的 get/items 会冲突）
                self.cookies = FakeCookies(
                    [
                        FakeCookie("SUB", "s1", ".weibo.com"),
                        FakeCookie("SUB", "s2", "login.sina.com.cn"),
                        FakeCookie("SUBP", "p1", ".weibo.com"),
                    ]
                )
            return FakeResp({})

        def close(self):
            pass

    monkeypatch.setattr("app.weibo_qr.httpx.Client", FakeClient)
    client = make_client()
    headers = auth_headers(client)
    start = client.post("/api/admin/weibo-qr/start", headers=headers)
    assert start.status_code == 200
    assert start.json()["qrurl"] == "https://qr.example/q.png"
    qrid = start.json()["qrid"]
    pending = client.get(f"/api/admin/weibo-qr/status?qrid={qrid}", headers=headers)
    assert pending.status_code == 200 and pending.json()["status"] == "pending"
    status = client.get(f"/api/admin/weibo-qr/status?qrid={qrid}", headers=headers)
    assert status.status_code == 200 and status.json()["status"] == "ok"
    assert client.app.state.db.get_setting("weibo_cookie") == "SUB=s1; SUBP=p1"


def test_batch_import_kols(monkeypatch):
    # 昵称已填的行也会补查头像，测试里避免真实网络请求
    monkeypatch.setattr("app.api.resolve_profile", lambda uid, cookie="": {})
    client = make_client()
    headers = auth_headers(client)
    resp = client.post(
        "/api/kols/batch",
        headers=headers,
        json={
            "platform": "xueqiu",
            "lines": (
                "https://xueqiu.com/8790885129\n"
                "段永平 https://xueqiu.com/u/12345\n"
                "67890\n"
                "不是链接也不是ID\n"
            ),
        },
    )
    data = resp.json()
    assert resp.status_code == 200
    assert data["total"] == 4 and data["ok"] == 3
    assert len(data["failed"]) == 1
    kols = client.get("/api/kols", headers=headers).json()
    names = {k["name"] for k in kols}
    assert "段永平" in names
    assert any(k["external_id"] == "8790885129" for k in kols)


def test_batch_import_auto_fills_xueqiu_nickname(monkeypatch):
    client = make_client()
    headers = auth_headers(client)
    monkeypatch.setattr(
        "app.api.resolve_profile",
        lambda uid, cookie="": (
            {"screen_name": "自动昵称", "avatar_url": "https://x/avatar.png"}
            if uid == "55555"
            else {}
        ),
    )
    resp = client.post(
        "/api/kols/batch",
        headers=headers,
        json={
            "platform": "xueqiu",
            "lines": (
                "https://xueqiu.com/u/55555\n"
                "https://xueqiu.com/u/66666\n"
                "段永平 77777"
            ),
        },
    )
    assert resp.status_code == 200 and resp.json()["ok"] == 3
    kols = client.get("/api/kols", headers=headers).json()
    names = {k["external_id"]: k["name"] for k in kols}
    assert names["55555"] == "自动昵称"
    assert next(k for k in kols if k["external_id"] == "55555")["avatar_url"] == "https://x/avatar.png"
    assert names["66666"] == "xueqiu_66666"  # 解析失败退回兜底名
    assert names["77777"] == "段永平"  # 已填昵称不覆盖


def test_weibo_kol_link_normalized():
    client = make_client()
    headers = auth_headers(client)
    resp = client.post(
        "/api/kols",
        headers=headers,
        json={"platform": "weibo", "name": "wu2198", "external_id": "https://weibo.com/u/1216826604"},
    )
    assert resp.status_code == 200
    kol = resp.json()
    assert kol["external_id"] == "1216826604"

    resp = client.put(
        f"/api/kols/{kol['id']}",
        headers=headers,
        json={"external_id": "https://weibo.com/u/9999999999"},
    )
    assert resp.status_code == 200
    assert resp.json()["external_id"] == "9999999999"

    resp = client.post(
        "/api/kols/batch",
        headers=headers,
        json={"platform": "weibo", "lines": "微博大V2 https://weibo.com/u/8888888888"},
    )
    assert resp.status_code == 200 and resp.json()["ok"] == 1
    assert resp.json()["failed"] == []


def test_xueqiu_cookie_write_and_batch_rss_url():
    client = make_client()
    headers = auth_headers(client)

    status = client.get("/api/admin/xueqiu-cookie", headers=headers)
    assert status.status_code == 200 and status.json()["set"] is False

    resp = client.post(
        "/api/admin/xueqiu-cookie",
        headers=headers,
        json={"cookie": "xq_a_token=abc; u=123"},
    )
    assert resp.status_code == 200
    status = client.get("/api/admin/xueqiu-cookie", headers=headers).json()
    assert status["set"] is True and status["preview"].startswith("xq_a_token=abc")

    assert (
        client.post("/api/admin/xueqiu-cookie", headers=headers, json={"cookie": "  "}).status_code
        == 400
    )

    # 批量导入支持 X/RSS 源地址
    resp = client.post(
        "/api/kols/batch",
        headers=headers,
        json={"platform": "twitter", "lines": "Elon Musk https://rsshub.app/twitter/user/elonmusk"},
    )
    assert resp.status_code == 200 and resp.json()["ok"] == 1
    assert resp.json()["failed"] == []
    kols = client.get("/api/kols", headers=headers).json()
    assert any(k["external_id"] == "https://rsshub.app/twitter/user/elonmusk" for k in kols)


def test_kol_request_flow(monkeypatch):
    # 审批时会自动解析昵称/头像，测试里避免真实网络请求
    monkeypatch.setattr("app.api.resolve_profile", lambda uid, cookie="": {})
    client = make_client()
    admin_headers = auth_headers(client)
    u1 = register(client, "user01", "pass123456")
    u_headers = {"Authorization": f"Bearer {u1.json()['token']}"}

    # 用户提交申请（雪球主页链接自动提取 UID）
    resp = client.post(
        "/api/kol-requests",
        headers=u_headers,
        json={"platform": "xueqiu", "external_id": "https://xueqiu.com/u/55555"},
    )
    assert resp.status_code == 200
    # 重复申请被拦截
    resp = client.post(
        "/api/kol-requests",
        headers=u_headers,
        json={"platform": "xueqiu", "external_id": "55555"},
    )
    assert resp.status_code == 400 and "处理中" in resp.json()["detail"]
    # 已存在的大V不允许申请
    client.app.state.db.add_kol("weibo", "已有", "66666")
    resp = client.post(
        "/api/kol-requests",
        headers=u_headers,
        json={"platform": "weibo", "external_id": "66666"},
    )
    assert resp.status_code == 400 and "已在目录中" in resp.json()["detail"]

    mine = client.get("/api/my/kol-requests", headers=u_headers).json()
    assert len(mine) == 1 and mine[0]["status"] == "pending" and mine[0]["external_id"] == "55555"

    pending = client.get("/api/admin/kol-requests?status=pending", headers=admin_headers).json()
    assert len(pending) == 1 and pending[0]["requester"] == "user01"

    req_id = pending[0]["id"]
    approved = client.post(f"/api/admin/kol-requests/{req_id}/approve", headers=admin_headers)
    assert approved.status_code == 200
    assert approved.json()["platform"] == "xueqiu" and approved.json()["external_id"] == "55555"
    # 审批通过后自动订阅申请人
    assert approved.json()["id"] in client.app.state.db.subscribed_kol_ids(u1.json()["user"]["id"])

    done = client.get("/api/admin/kol-requests", headers=admin_headers).json()
    assert done[0]["status"] == "approved" and done[0]["handled_at"]

    # 再次审批同一申请会 404
    assert (
        client.post(f"/api/admin/kol-requests/{req_id}/approve", headers=admin_headers).status_code
        == 404
    )


def test_kol_visibility_acl():
    client = make_client()
    admin_headers = auth_headers(client)
    r1 = register(client, "usera1", "pass123456")
    r2 = register(client, "userb1", "pass123456")
    u1_id = r1.json()["user"]["id"]
    user1_headers = {"Authorization": f"Bearer {r1.json()['token']}"}
    user2_headers = {"Authorization": f"Bearer {r2.json()['token']}"}
    db = client.app.state.db

    public_id = db.add_kol("xueqiu", "公开大V", "1")
    private_id = db.add_kol("xueqiu", "私有大V", "2")
    db.update_kol(private_id, is_private=True)
    db.set_kol_acl(private_id, [u1_id])

    cat1 = client.get("/api/catalog", headers=user1_headers).json()
    cat2 = client.get("/api/catalog", headers=user2_headers).json()
    assert {k["id"] for k in cat1} == {public_id, private_id}
    assert {k["id"] for k in cat2} == {public_id}

    # u2 无法订阅私有大V，u1 可以
    assert (
        client.post(
            "/api/subscriptions",
            headers=user2_headers,
            json={"kol_id": private_id},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/subscriptions",
            headers=user1_headers,
            json={"kol_id": private_id},
        ).status_code
        == 200
    )
    # u2 直接访问私有大V详情也是 404
    assert client.get(f"/api/kols/{private_id}", headers=user2_headers).status_code == 404

    detail = client.get(f"/api/kols/{private_id}", headers=admin_headers).json()
    assert detail["is_private"] == 1 and detail["visible_users"] == ["usera1"]

    # 管理员把白名单换成 u2，u1 立刻不可见
    resp = client.put(
        f"/api/kols/{private_id}",
        headers=admin_headers,
        json={"visible_users": ["userb1"]},
    )
    assert resp.status_code == 200
    assert private_id not in {k["id"] for k in client.get("/api/catalog", headers=user1_headers).json()}
    assert private_id in {k["id"] for k in client.get("/api/catalog", headers=user2_headers).json()}

    # 转为公开后所有人可见
    client.put(f"/api/kols/{private_id}", headers=admin_headers, json={"is_private": False})
    assert private_id in {k["id"] for k in client.get("/api/catalog", headers=user1_headers).json()}
    assert private_id in {k["id"] for k in client.get("/api/catalog", headers=user2_headers).json()}


def test_register_requires_invite_code():
    client = make_client()
    admin_headers = auth_headers(client)

    # 不带注册码
    resp = client.post(
        "/api/auth/register",
        json={"username": "nocode", "password": "secret123"},
    )
    assert resp.status_code == 400 and "邀请码" in resp.json()["detail"]

    # 无效注册码
    resp = client.post(
        "/api/auth/register",
        json={"username": "badcode", "password": "secret123", "code": "NOPE1234"},
    )
    assert resp.status_code == 400 and "无效或已被使用" in resp.json()["detail"]

    # 管理员生成 3 个注册码
    resp = client.post(
        "/api/admin/register-codes",
        headers=admin_headers,
        json={"count": 3, "note": "测试"},
    )
    assert resp.status_code == 200
    codes = resp.json()["codes"]
    assert len(codes) == 3 and len(set(codes)) == 3

    codes_list = client.get("/api/admin/register-codes", headers=admin_headers).json()
    assert all(c["code"] in codes or c["note"] == "测试" for c in codes_list if c["note"] == "测试")

    # 用生成码注册成功，且码被消费
    resp = client.post(
        "/api/auth/register",
        json={"username": "invited", "password": "secret123", "code": codes[0]},
    )
    assert resp.status_code == 200
    row = next(
        c for c in client.get("/api/admin/register-codes", headers=admin_headers).json() if c["code"] == codes[0]
    )
    assert row["used_by"] and row["used_by_name"] == "invited"

    # 同一注册码不能再用
    resp = client.post(
        "/api/auth/register",
        json={"username": "invited2", "password": "secret123", "code": codes[0]},
    )
    assert resp.status_code == 400 and "无效或已被使用" in resp.json()["detail"]


def test_me_includes_push_guide():
    cfg = Config()
    cfg.notifiers.telegram.bot_username = "dav_bot"
    cfg.notifiers.feishu.bot_name = "大V订阅机器人"
    client = make_client(config=cfg)
    headers = auth_headers(client)
    me = client.get("/api/me", headers=headers).json()
    assert me["push_guide"] == {"telegram_bot_username": "dav_bot", "feishu_bot_name": "大V订阅机器人"}


def test_empty_password_login_rejected():
    client = make_client()
    # 机器人/微信自动创建的账号没有密码
    client.app.state.db.add_user("tg_bot_user", "", telegram_chat_id="111")
    resp = client.post(
        "/api/auth/login",
        json={"username": "tg_bot_user", "password": ""},
    )
    assert resp.status_code == 401
    resp = client.post(
        "/api/auth/login",
        json={"username": "tg_bot_user", "password": "guess"},
    )
    assert resp.status_code == 401


def test_register_password_too_long_rejected():
    client = make_client()
    client.app.state.db.add_register_code("LONG1")
    resp = client.post(
        "/api/auth/register",
        json={"username": "longpw", "password": "x" * 200, "code": "LONG1"},
    )
    assert resp.status_code == 400 and "密码最长" in resp.json()["detail"]


def test_revoke_register_code():
    client = make_client()
    admin_headers = auth_headers(client)
    codes = client.post(
        "/api/admin/register-codes",
        headers=admin_headers,
        json={"count": 2, "note": "revoke"},
    ).json()["codes"]
    resp = client.delete(f"/api/admin/register-codes/{codes[0]}", headers=admin_headers)
    assert resp.status_code == 200
    remaining = client.get("/api/admin/register-codes", headers=admin_headers).json()
    assert all(c["code"] != codes[0] for c in remaining)
    assert client.delete(f"/api/admin/register-codes/{codes[0]}", headers=admin_headers).status_code == 404
    # 已使用的注册码不能作废
    register(client, "usedit", code=codes[1])
    assert client.delete(f"/api/admin/register-codes/{codes[1]}", headers=admin_headers).status_code == 400


def test_catalog_sorted_by_priority_and_activity():
    client = make_client()
    headers = auth_headers(client)
    db = client.app.state.db
    normal_id = db.add_kol("xueqiu", "普通A", "1")
    priority_id = db.add_kol("xueqiu", "优先P", "2", priority=True)
    old_post_id = db.insert_post("xueqiu", normal_id, "p1", "t", "c", "u", "")
    db._execute("UPDATE posts SET fetched_at = datetime('now', '-1 day') WHERE id = ?", (old_post_id,))
    active_id = db.add_kol("xueqiu", "活跃B", "3")
    db.insert_post("xueqiu", active_id, "p2", "t2", "c2", "u", "")

    ids = [k["id"] for k in client.get("/api/catalog", headers=headers).json()]
    assert ids[0] == priority_id
    assert ids.index(active_id) < ids.index(normal_id)


def test_stats_include_source_health():
    client = make_client()
    headers = auth_headers(client)
    db = client.app.state.db
    db.set_setting("source_ok_xueqiu", str(1785840071))
    db.set_setting("source_err_weibo", "登录失败")
    db.set_setting("source_fails_weibo", "3")
    stats = client.get("/api/stats", headers=headers).json()
    sources = {s["platform"]: s for s in stats["sources"]}
    assert sources["xueqiu"]["ok"] is True
    assert sources["weibo"]["ok"] is False and sources["weibo"]["consecutive_fails"] == 3
    assert sources["weibo"]["last_error"] == "登录失败"


def test_polling_config_get_and_update():
    client = make_client()
    headers = auth_headers(client)
    cfg = client.get("/api/admin/polling-config", headers=headers).json()
    assert cfg["interval_seconds"] > 0 and cfg["daily_report_hour"] == 20

    resp = client.put(
        "/api/admin/polling-config",
        headers=headers,
        json={"interval_seconds": 120, "digest_interval_seconds": 300, "daily_report_hour": 21},
    )
    assert resp.status_code == 200
    assert resp.json()["interval_seconds"] == 120
    assert resp.json()["digest_interval_seconds"] == 300
    assert resp.json()["daily_report_hour"] == 21
    resp = client.put(
        "/api/admin/polling-config",
        headers=headers,
        json={"translate_twitter_content": True},
    )
    assert resp.json()["translate_twitter_content"] is True
    assert client.get("/api/admin/polling-config", headers=headers).json()["translate_twitter_content"] is True

    # 超范围被拒绝
    resp = client.put(
        "/api/admin/polling-config",
        headers=headers,
        json={"daily_report_hour": 99},
    )
    assert resp.status_code == 400


def test_posts_search_and_push_log_filters():
    client = make_client()
    headers = auth_headers(client)
    db = client.app.state.db
    kid = db.add_kol("xueqiu", "大V甲", "1")
    post_id = db.insert_post("xueqiu", kid, "p1", "茅台又新高", "内容", "u", "")
    db.add_push_log(post_id, "telegram", "success", user_id=1)
    db.add_push_log(post_id, "feishu", "failed", "boom", user_id=1)

    hits = client.get("/api/posts?q=茅台", headers=headers).json()
    assert len(hits) == 1 and hits[0]["title"] == "茅台又新高"
    assert client.get("/api/posts?q=不存在", headers=headers).json() == []

    logs = client.get("/api/push-logs?channel=feishu&status=failed", headers=headers).json()
    assert len(logs) == 1 and logs[0]["channel"] == "feishu"
    logs = client.get("/api/push-logs?channel=telegram", headers=headers).json()
    assert len(logs) == 1


def test_delete_kol_cascades_posts_and_logs():
    client = make_client()
    headers = auth_headers(client)
    db = client.app.state.db
    kid = db.add_kol("xueqiu", "大V", "1")
    post_id = db.insert_post("xueqiu", kid, "p1", "t", "c", "u", "")
    db.add_push_log(post_id, "telegram", "success")
    uid = db.add_user("u1", "hash")
    db.add_subscription(uid, kid)

    assert client.delete(f"/api/kols/{kid}", headers=headers).status_code == 200
    assert db.count_posts() == 0
    assert db.list_push_logs(limit=10) == []
    assert db.list_subscriptions(uid) == []


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
    headers = user_headers(client, "admin01")
    me = client.get("/api/me", headers=headers).json()
    assert me["username"] == "admin01" and me["is_admin"] is False

    # 弱密码 / 重复用户名
    assert client.post("/api/auth/register", json={"username": "u2", "password": "123"}).status_code == 400
    assert client.post(
        "/api/auth/register", json={"username": "admin01", "password": "secret123"}
    ).status_code == 400

    # 登录失败/成功
    assert client.post("/api/auth/login", json={"username": "admin01", "password": "wrong"}).status_code == 401
    token = client.post("/api/auth/login", json={"username": "admin01", "password": "pass123456"}).json()["token"]
    assert client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    # 普通用户不能访问管理接口
    assert client.get("/api/kols", headers=headers).status_code == 403
    assert client.get("/api/posts", headers=headers).status_code == 403

    # 管理员在后台指定另一个用户为管理员
    admin_headers = auth_headers(client, "boss01", "secret123")
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
    catalog_item = client.get("/api/catalog", headers=customer_headers).json()[0]
    assert catalog_item["subscribed"] is True and catalog_item["subscribe_type"] == "post"
    assert client.get("/api/my/subscriptions", headers=customer_headers).json()[0]["id"] == kid

    # 订阅类型：切换到「回复」、再到「全部」
    assert (
        client.put(
            f"/api/subscriptions/{kid}",
            headers=customer_headers,
            json={"type": "reply"},
        ).status_code
        == 200
    )
    assert client.get("/api/catalog", headers=customer_headers).json()[0]["subscribe_type"] == "reply"
    assert (
        client.put(f"/api/subscriptions/{kid}", headers=customer_headers, json={"type": "both"}).status_code
        == 200
    )
    assert client.get("/api/my/subscriptions", headers=customer_headers).json()[0]["subscribe_type"] == "both"
    # 非法类型被拒绝
    assert (
        client.put(f"/api/subscriptions/{kid}", headers=customer_headers, json={"type": "bad"}).status_code
        == 400
    )
    # 未订阅的大V不能切类型
    other_kid = client.post(
        "/api/kols", headers=admin_headers, json={"platform": "xueqiu", "name": "另一大V", "external_id": "1"}
    ).json()["id"]
    assert (
        client.put(f"/api/subscriptions/{other_kid}", headers=customer_headers, json={"type": "both"}).status_code
        == 404
    )

    # 订阅后能看到该大V的动态
    client.app.state.db.insert_post("xueqiu", kid, "p1", "t", "c", "u", "")
    feed = client.get("/api/my/feed", headers=customer_headers).json()
    assert len(feed) == 1 and feed[0]["kol_name"] == "超级鹿鼎公"

    # images 存库为 JSON 文本，API 返回必须解析为数组（回归：网页时间线渲染崩溃）
    client.app.state.db.insert_post(
        "xueqiu", kid, "p2", "t2", "c2", "u2", "",
        images=["https://x.com/1.jpg", "https://x.com/2.jpg"],
    )
    feed = client.get("/api/my/feed", headers=customer_headers).json()
    p2 = next(p for p in feed if p["external_id"] == "p2")
    assert isinstance(p2["images"], list) and p2["images"] == [
        "https://x.com/1.jpg",
        "https://x.com/2.jpg",
    ]

    # 取消订阅后动态清空
    assert client.delete(f"/api/subscriptions/{kid}", headers=customer_headers).status_code == 200
    assert client.get("/api/my/feed", headers=customer_headers).json() == []

    # 大V详情与动态（未订阅也可查看）
    detail = client.get(f"/api/kols/{kid}", headers=customer_headers).json()
    assert detail["name"] == "超级鹿鼎公" and detail["subscribed"] is False
    posts = client.get(f"/api/kols/{kid}/posts", headers=customer_headers).json()
    assert len(posts) == 2
    p2_detail = next(p for p in posts if p["external_id"] == "p2")
    assert isinstance(p2_detail["images"], list) and p2_detail["images"] == [
        "https://x.com/1.jpg",
        "https://x.com/2.jpg",
    ]

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


def test_add_combination_kol_auto_fills_name(monkeypatch):
    client = make_client()
    admin_headers = auth_headers(client)
    monkeypatch.setattr(
        "app.api.resolve_combination_profile",
        lambda symbol, cookie="": {
            "name": "伯言-A股",
            "owner_name": "伯言2020",
            "avatar_url": "",
        },
    )
    resp = client.post(
        "/api/kols",
        headers=admin_headers,
        json={
            "platform": "combination",
            "name": "",
            "external_id": "https://xueqiu.com/P/ZH3623878",
        },
    )
    assert resp.status_code == 200, resp.text
    kol = resp.json()
    assert kol["external_id"] == "ZH3623878"
    assert kol["name"] == "伯言-A股"
    assert kol["platform"] == "combination"


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


def test_old_db_migrates_wecom_column():
    tmp = tempfile.mkdtemp()
    path = Path(tmp) / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            wechat_openid TEXT NOT NULL DEFAULT '',
            telegram_chat_id TEXT NOT NULL DEFAULT '',
            feishu_open_id TEXT NOT NULL DEFAULT '',
            feishu_chat_id TEXT NOT NULL DEFAULT '',
            notify_enabled INTEGER NOT NULL DEFAULT 1,
            daily_report INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.commit()
    conn.close()

    db = DB(path)
    uid = db.add_user("wc", "hash")
    db.update_user(uid, wecom_webhook="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=wc1")
    assert db.get_user_by_wecom_webhook("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=wc1")["id"] == uid
    db.update_user(uid, telegram_bot_token="123:custom")
    assert db.get_user_by_telegram_bot("123:custom")["id"] == uid
    db.close()


def test_healthz():
    client = make_client("api3.db")
    assert client.get("/healthz").json() == {"status": "ok"}


def test_update_kol_duplicate_external_id_rejected():
    client = make_client()
    headers = auth_headers(client)
    db = client.app.state.db
    kid = db.add_kol("xueqiu", "A", "111")
    db.add_kol("xueqiu", "B", "222")
    resp = client.put(
        f"/api/kols/{kid}",
        headers=headers,
        json={"external_id": "222"},
    )
    assert resp.status_code == 400 and "相同的外部ID" in resp.json()["detail"]
    # 改成不冲突的 ID 允许
    resp = client.put(
        f"/api/kols/{kid}",
        headers=headers,
        json={"external_id": "333"},
    )
    assert resp.status_code == 200


def test_approve_request_auto_resolves_name_and_avatar(monkeypatch):
    client = make_client()
    admin_headers = auth_headers(client)
    u1 = register(client, "user01", "pass123456")
    u_headers = {"Authorization": f"Bearer {u1.json()['token']}"}
    client.post(
        "/api/kol-requests",
        headers=u_headers,
        json={"platform": "xueqiu", "external_id": "https://xueqiu.com/u/55555"},
    )
    monkeypatch.setattr(
        "app.api.resolve_profile",
        lambda uid, cookie="": {"screen_name": "自动昵称", "avatar_url": ""},
    )
    req_id = client.get("/api/admin/kol-requests?status=pending", headers=admin_headers).json()[0]["id"]
    approved = client.post(f"/api/admin/kol-requests/{req_id}/approve", headers=admin_headers)
    assert approved.status_code == 200
    assert approved.json()["name"] == "自动昵称"
    assert approved.json()["external_id"] == "55555"


def test_batch_import_xueqiu_fetches_avatar_even_with_nickname(monkeypatch):
    client = make_client()
    headers = auth_headers(client)
    monkeypatch.setattr(
        "app.api.resolve_profile",
        lambda uid, cookie="": {
            "screen_name": "自动昵称",
            "avatar_url": "https://xueqiu.com/avatar.png",
        },
    )
    monkeypatch.setattr(
        "app.api.cache_avatar",
        lambda db, kid, url: url,
    )
    resp = client.post(
        "/api/kols/batch",
        headers=headers,
        json={"platform": "xueqiu", "lines": "段永平 https://xueqiu.com/u/12345"},
    )
    assert resp.status_code == 200 and resp.json()["ok"] == 1
    kols = client.get("/api/kols", headers=headers).json()
    target = next(k for k in kols if k["platform"] == "xueqiu")
    assert target["name"] == "段永平"
    assert target["avatar_url"] == "https://xueqiu.com/avatar.png"


def test_stats_returns_source_stability_fields():
    client = make_client()
    headers = auth_headers(client)
    db = client.app.state.db
    kid = db.add_kol("xueqiu", "A", "1")
    db.insert_post("xueqiu", kid, "p1", "t", "c", "u", "")
    db.add_source_event("xueqiu", "ok", "ok=1 fail=0")
    db.add_source_event("xueqiu", "fail", "fail=1 ok=0 err=boom")
    db.set_setting("stats_retry_pending", "2")

    data = client.get("/api/stats", headers=headers).json()
    xq = next(s for s in data["sources"] if s["platform"] == "xueqiu")
    assert xq["ok_24h"] == 1 and xq["fail_24h"] == 1
    assert xq["success_rate_24h"] == 50
    assert len(data["recent_source_events"]) == 2
    assert data["retry_pending"] == 2
    assert any(h["id"] == kid and h["last_post_at"] for h in data["kol_health"])
    assert "push_alert_last_at" in data["alerts"]


def test_login_rate_limit_blocks_after_8_failures():
    client = make_client()
    user_headers(client, "victim")
    for _ in range(8):
        assert client.post("/api/auth/login", json={"username": "victim", "password": "bad"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "victim", "password": "bad"}).status_code == 429


def test_xff_spoof_cannot_bypass_rate_limit_without_trust_proxy():
    """未显式信任反代时，伪造 X-Forwarded-For 不能绕过限流。"""
    client = make_client()
    user_headers(client, "victim")
    for i in range(8):
        r = client.post(
            "/api/auth/login",
            json={"username": "victim", "password": "bad"},
            headers={"X-Forwarded-For": f"1.1.1.{i}"},
        )
        assert r.status_code == 401
    r = client.post(
        "/api/auth/login",
        json={"username": "victim", "password": "bad"},
        headers={"X-Forwarded-For": "9.9.9.9"},
    )
    assert r.status_code == 429


def test_xff_trusted_when_trust_proxy_enabled():
    """显式信任反代后，X-Forwarded-For 才作为分桶依据。"""
    cfg = Config()
    cfg.web.trust_proxy = True
    client = make_client(config=cfg)
    user_headers(client, "victim")
    for _ in range(8):
        assert client.post(
            "/api/auth/login",
            json={"username": "victim", "password": "bad"},
            headers={"X-Forwarded-For": "1.1.1.1"},
        ).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"username": "victim", "password": "bad"},
        headers={"X-Forwarded-For": "1.1.1.1"},
    ).status_code == 429
    # 不同伪造 IP 是不同桶，不受影响
    assert client.post(
        "/api/auth/login",
        json={"username": "victim", "password": "bad"},
        headers={"X-Forwarded-For": "2.2.2.2"},
    ).status_code == 401


def test_register_failures_count_toward_limit():
    client = make_client()
    for _ in range(8):
        r = client.post(
            "/api/auth/register",
            json={"username": f"u{_}", "password": "secret123", "code": "INVALID"},
        )
        assert r.status_code == 400
    r = client.post(
        "/api/auth/register",
        json={"username": "u9", "password": "secret123", "code": "INVALID"},
    )
    assert r.status_code == 429


def test_login_success_clears_failure_count():
    client = make_client()
    user_headers(client, "victim")
    for _ in range(7):
        assert client.post("/api/auth/login", json={"username": "victim", "password": "bad"}).status_code == 401
    # 尚未锁定时输入正确密码：登录成功并清零
    assert client.post("/api/auth/login", json={"username": "victim", "password": "pass123456"}).status_code == 200
    # 清零后连续错误仍是 401；若未清零，第 8/9 次错误会是 429
    assert client.post("/api/auth/login", json={"username": "victim", "password": "bad"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "victim", "password": "bad"}).status_code == 401


def test_login_locked_ip_rejects_even_correct_password():
    client = make_client()
    user_headers(client, "victim")
    for _ in range(8):
        assert client.post("/api/auth/login", json={"username": "victim", "password": "bad"}).status_code == 401
    # 锁定时即使密码正确也 429，不泄露密码有效性
    assert client.post("/api/auth/login", json={"username": "victim", "password": "pass123456"}).status_code == 429


def test_admin_delete_user_cleans_push_logs_and_acl():
    client = make_client()
    admin_headers = auth_headers(client, "boss01")
    reg = register(client, "doomed")
    uid = reg.json()["user"]["id"]
    db = client.app.state.db
    kid = client.post(
        "/api/kols", headers=admin_headers,
        json={"platform": "xueqiu", "name": "A", "external_id": "1"},
    ).json()["id"]
    # 直接造数据：私有大V ACL + 一条推送日志
    db.set_kol_acl(kid, [uid])
    post_id = db.insert_post("xueqiu", kid, "p1", "t", "c", "u", "2026-08-06")
    db.add_push_log(post_id, "telegram", "success", user_id=uid)

    assert client.delete(f"/api/users/{uid}", headers=admin_headers).status_code == 200
    assert db.list_push_logs(user_id=uid) == []
    assert db.acl_user_ids(kid) == []


def test_db_busy_timeout_set():
    client = make_client()
    value = client.app.state.db._conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert value == 5000


def test_me_subscription_count():
    client = make_client()
    admin_headers = auth_headers(client)
    kid1 = client.post(
        "/api/kols", headers=admin_headers,
        json={"platform": "xueqiu", "name": "A", "external_id": "1"},
    ).json()["id"]
    kid2 = client.post(
        "/api/kols", headers=admin_headers,
        json={"platform": "xueqiu", "name": "B", "external_id": "2"},
    ).json()["id"]
    uh = user_headers(client, "user01")
    assert client.get("/api/me", headers=uh).json()["subscription_count"] == 0
    client.post("/api/subscriptions", headers=uh, json={"kol_id": kid1})
    client.post("/api/subscriptions", headers=uh, json={"kol_id": kid2})
    assert client.get("/api/me", headers=uh).json()["subscription_count"] == 2


def test_background_workers_flag(monkeypatch):
    """DAV_UI_ONLY=1 时关闭调度器/机器人后台任务，避免测试实例抢生产
    Telegram 机器人（getUpdates 409）或误发降级告警。"""
    from app.main import background_workers_enabled

    monkeypatch.delenv("DAV_UI_ONLY", raising=False)
    assert background_workers_enabled() is True
    monkeypatch.setenv("DAV_UI_ONLY", "1")
    assert background_workers_enabled() is False
    monkeypatch.setenv("DAV_UI_ONLY", "0")
    assert background_workers_enabled() is True


def test_passwordless_user_can_set_first_password():
    """微信/机器人自动创建的无密码账号：已持有会话即可首次设密，之后改密需旧密码。"""
    from app import auth

    client = make_client()
    db = client.app.state.db
    uid = db.add_user("wx_pwd_user", "", wechat_openid="openid_1")
    token = auth.create_token(uid, "wx_pwd_user", db.get_setting("token_secret"))
    headers = {"Authorization": f"Bearer {token}"}

    # 无密码账号无需旧密码即可首次设密
    resp = client.post(
        "/api/me/password",
        headers=headers,
        json={"old_password": "anything", "new_password": "newpass123"},
    )
    assert resp.status_code == 200

    # 设置后可用新密码登录
    assert client.post(
        "/api/auth/login", json={"username": "wx_pwd_user", "password": "newpass123"}
    ).status_code == 200

    # 已有密码后再改密必须校验旧密码
    resp = client.post(
        "/api/me/password",
        headers=headers,
        json={"old_password": "wrong", "new_password": "another456"},
    )
    assert resp.status_code == 400 and "原密码" in resp.json()["detail"]


def test_register_username_case_insensitive_unique():
    """注册时不允许与已有用户名仅大小写不同的新账号。"""
    client = make_client()
    admin_headers = auth_headers(client, "boss01")

    assert register(client, "Alice1").status_code == 200
    # 大小写变体注册被拒
    resp = register(client, "alice1", expect=400)
    assert "用户名已存在" in resp.json()["detail"]
    resp = register(client, "ALICE1", expect=400)
    assert "用户名已存在" in resp.json()["detail"]

    # 管理员改名为已有用户名的大小写变体也被拒
    client.app.state.db.add_register_code("CODE1")
    resp = client.post(
        "/api/auth/register",
        json={"username": "bob001", "password": "secret123", "code": "CODE1"},
    )
    assert resp.status_code == 200
    uid = next(
        u["id"] for u in client.get("/api/users", headers=admin_headers).json()
        if u["username"] == "bob001"
    )
    resp = client.put(
        f"/api/users/{uid}", headers=admin_headers, json={"username": "ALICE1"}
    )
    assert resp.status_code == 400 and "用户名已存在" in resp.json()["detail"]


def test_add_user_username_case_insensitive_unique():
    """机器人/微信自动建号也遵守大小写不敏感唯一约束。"""
    client = make_client()
    db = client.app.state.db
    db.add_user("TgUser", "", telegram_chat_id="1")
    try:
        db.add_user("tguser", "", telegram_chat_id="2")
        raise AssertionError("应拒绝大小写变体用户名")
    except ValueError as exc:
        assert "用户名已存在" in str(exc)


def test_security_headers():
    """基础安全响应头：防 MIME 嗅探 / 点击劫持 / Referer 泄露。"""
    client = make_client()
    resp = client.get("/healthz")
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
    assert resp.headers.get("referrer-policy") == "no-referrer"

    # 静态页面同样带安全头
    page = client.get("/")
    assert page.status_code == 200
    assert page.headers.get("x-content-type-options") == "nosniff"


# ---- 关键词提醒 API ----
def test_keywords_crud_api():
    client = make_client()
    headers = user_headers(client, "kw_user")

    # 默认空
    me = client.get("/api/me", headers=headers).json()
    assert me["keywords"] == []

    resp = client.put(
        "/api/me", headers=headers,
        json={"keywords": ["ETF", " 降息 ", "   ", "机器人"]},
    )
    assert resp.status_code == 200
    me = client.get("/api/me", headers=headers).json()
    assert me["keywords"] == ["ETF", "降息", "机器人"]  # 去空白/空项

    # 覆盖更新
    client.put("/api/me", headers=headers, json={"keywords": ["半导体"]})
    assert client.get("/api/me", headers=headers).json()["keywords"] == ["半导体"]


def test_keywords_limits_api():
    client = make_client()
    headers = user_headers(client, "kw_limit")

    too_many = [f"关键词{i}" for i in range(21)]
    resp = client.put("/api/me", headers=headers, json={"keywords": too_many})
    assert resp.status_code == 400
    assert "20" in resp.json()["detail"]

    resp = client.put(
        "/api/me", headers=headers,
        json={"keywords": ["字" * 51]},
    )
    assert resp.status_code == 400
    assert "50" in resp.json()["detail"]


# ---- Bark 绑定 API ----
def test_bark_key_bind_api():
    client = make_client()
    headers = user_headers(client, "bark_user")

    me = client.get("/api/me", headers=headers).json()
    assert me["bark_key"] == ""

    # 非法 key → 400
    resp = client.put("/api/me", headers=headers, json={"bark_key": "短"})
    assert resp.status_code == 400
    assert "Bark key 无效" in resp.json()["detail"]

    # 合法 key → 绑定成功
    resp = client.put(
        "/api/me", headers=headers,
        json={"bark_key": "AaBbCcDdEeFf1234567890"},
    )
    assert resp.status_code == 200
    assert client.get("/api/me", headers=headers).json()["bark_key"] == "AaBbCcDdEeFf1234567890"

    # 完整 URL 写法也接受
    resp = client.put(
        "/api/me", headers=headers,
        json={"bark_key": "https://api.day.app/AaBbCcDdEeFf1234567890"},
    )
    assert resp.status_code == 200
    assert client.get("/api/me", headers=headers).json()["bark_key"] == "https://api.day.app/AaBbCcDdEeFf1234567890"


def test_bark_key_duplicate_rejected():
    client = make_client()
    h1 = user_headers(client, "bark_a")
    h2 = user_headers(client, "bark_b")
    assert client.put("/api/me", headers=h1, json={"bark_key": "AaBbCcDdEeFf1234567890"}).status_code == 200
    resp = client.put("/api/me", headers=h2, json={"bark_key": "AaBbCcDdEeFf1234567890"})
    assert resp.status_code == 400
    assert "已绑定其他账号" in resp.json()["detail"]
    # 原绑定者不受影响
    assert client.get("/api/me", headers=h1).json()["bark_key"] == "AaBbCcDdEeFf1234567890"


# ---- feed token API ----
def test_feed_token_in_me():
    client = make_client()
    headers = user_headers(client, "feed_me")
    me = client.get("/api/me", headers=headers).json()
    assert me["feed_token"]  # 首次访问自动生成

    resp = client.post("/api/me/feed-token/regenerate", headers=headers)
    assert resp.status_code == 200
    new = resp.json()["feed_token"]
    assert new != me["feed_token"]
    assert client.get("/api/me", headers=headers).json()["feed_token"] == new


# ---- 账号级失败锁定（防 IP 轮换爆破）----
def test_account_lock_blocks_distributed_bruteforce():
    """轮换 IP 绕过单 IP 限流时，账号级锁定仍然生效（即使密码正确也拒绝）。"""
    cfg = Config()
    cfg.web.trust_proxy = True  # 让 X-Forwarded-For 生效，模拟多 IP 攻击
    client = make_client(config=cfg)
    user_headers(client, "victim")

    # 10 次失败各用不同 IP（单 IP 各自不足 8 次，不会触发 IP 限流）
    for i in range(10):
        r = client.post(
            "/api/auth/login",
            json={"username": "victim", "password": "bad"},
            headers={"X-Forwarded-For": f"1.1.1.{i}"},
        )
        assert r.status_code == 401, f"第 {i} 次失败应 401"
    # 账号已锁定：新 IP + 正确密码也 429，不泄露密码有效性
    r = client.post(
        "/api/auth/login",
        json={"username": "victim", "password": "pass123456"},
        headers={"X-Forwarded-For": "2.2.2.2"},
    )
    assert r.status_code == 429
    assert "锁定" in r.json()["detail"]


def test_admin_account_locks_sooner():
    """管理员账号 3 次失败即锁定（阈值更敏感）。"""
    cfg = Config()
    cfg.web.trust_proxy = True
    client = make_client(config=cfg)
    auth_headers(client, "boss01")  # 注册并提升为管理员，密码 secret123

    for i in range(3):
        r = client.post(
            "/api/auth/login",
            json={"username": "boss01", "password": "wrong"},
            headers={"X-Forwarded-For": f"3.3.3.{i}"},
        )
        assert r.status_code == 401
    r = client.post(
        "/api/auth/login",
        json={"username": "boss01", "password": "secret123"},
        headers={"X-Forwarded-For": "4.4.4.4"},
    )
    assert r.status_code == 429
    assert "锁定" in r.json()["detail"]


def test_login_locked_writes_audit_log():
    """账号锁定时写操作日志，管理员可审计（IP、角色、失败次数）。"""
    cfg = Config()
    cfg.web.trust_proxy = True
    client = make_client(config=cfg)
    user_headers(client, "victim")
    admin_headers = auth_headers(client, "boss01")

    for i in range(10):
        client.post(
            "/api/auth/login",
            json={"username": "victim", "password": "bad"},
            headers={"X-Forwarded-For": f"5.5.5.{i}"},
        )
    logs = client.get("/api/admin/logs", headers=admin_headers).json()
    locked = [l for l in logs if l["action"] == "login_locked" and l["target"] == "victim"]
    assert len(locked) == 1
    assert "role=user" in locked[0]["detail"]
    assert "ip=" in locked[0]["detail"]


def test_account_success_clears_lock_count():
    """未到锁定阈值前输入正确密码：登录成功并清零失败计数。"""
    cfg = Config()
    cfg.web.trust_proxy = True
    client = make_client(config=cfg)
    user_headers(client, "victim")

    for i in range(9):  # 阈值 10，9 次未锁
        assert client.post(
            "/api/auth/login",
            json={"username": "victim", "password": "bad"},
            headers={"X-Forwarded-For": f"6.6.6.{i}"},
        ).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"username": "victim", "password": "pass123456"},
        headers={"X-Forwarded-For": "7.7.7.7"},
    ).status_code == 200
    # 清零后重新失败仍是 401，不会因历史计数立即锁定
    assert client.post(
        "/api/auth/login",
        json={"username": "victim", "password": "bad"},
        headers={"X-Forwarded-For": "8.8.8.8"},
    ).status_code == 401


def test_account_lock_expires_after_window(monkeypatch):
    """锁定到期后允许再次尝试，正确密码可登录。"""
    import app.api as api_mod

    cfg = Config()
    cfg.web.trust_proxy = True
    client = make_client(config=cfg)
    user_headers(client, "victim")

    for i in range(10):
        client.post(
            "/api/auth/login",
            json={"username": "victim", "password": "bad"},
            headers={"X-Forwarded-For": f"9.9.9.{i}"},
        )
    assert client.post(
        "/api/auth/login",
        json={"username": "victim", "password": "pass123456"},
        headers={"X-Forwarded-For": "10.0.0.1"},
    ).status_code == 429

    # 时间前进 20 分钟（> 15 分钟锁定窗口）
    real_time = api_mod.time.time
    fake_now = {"value": real_time() + 1200}
    monkeypatch.setattr(api_mod.time, "time", lambda: fake_now["value"])
    r = client.post(
        "/api/auth/login",
        json={"username": "victim", "password": "pass123456"},
        headers={"X-Forwarded-For": "10.0.0.2"},
    )
    assert r.status_code == 200


def test_register_username_min_length_6():
    """新注册用户名最少 6 字符。"""
    client = make_client()
    db = client.app.state.db
    for i, name in enumerate(["ab", "abcde", "abcdefg"]):
        db.add_register_code(f"MINLEN{i}")
        resp = client.post(
            "/api/auth/register",
            json={"username": name, "password": "secret123", "code": f"MINLEN{i}"},
        )
        expected = 200 if len(name) >= 6 else 400
        assert resp.status_code == expected, f"{name} 应 {expected}"
        if expected == 400:
            assert "用户名至少6位" in resp.json()["detail"]


def test_admin_rename_username_min_length_6():
    """管理员改名同样要求 6-30 位。"""
    client = make_client()
    admin_headers = auth_headers(client)
    reg = register(client, "victim")
    uid = reg.json()["user"]["id"]
    assert client.put(
        f"/api/users/{uid}", headers=admin_headers, json={"username": "abcde"}
    ).status_code == 400
    assert client.put(
        f"/api/users/{uid}", headers=admin_headers, json={"username": "abcdef"}
    ).status_code == 200


def test_push_channels_accepts_bark():
    """push_channels 白名单必须包含 bark（加 Bark 通道时漏改过这里）。"""
    client = make_client()
    headers = user_headers(client, "barkchan")
    # 绑定 Bark 后，推送通道选择里勾选 bark + telegram 应可保存
    client.put("/api/me", headers=headers, json={"bark_key": "AaBbCcDdEeFf1234567890"})
    client.put(
        "/api/me", headers=headers,
        json={"telegram_chat_id": "123"},
    )
    resp = client.put(
        "/api/me", headers=headers,
        json={"push_channels": "telegram,bark"},
    )
    assert resp.status_code == 200, resp.text
    assert client.get("/api/me", headers=headers).json()["push_channels"] == "telegram,bark"
    # 非法渠道仍拒绝
    assert client.put(
        "/api/me", headers=headers, json={"push_channels": "telegram,slack"}
    ).status_code == 400
