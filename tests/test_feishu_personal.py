"""飞书个人机器人：注册协议、绑定码、临时监听消费、推送路由回退、API。"""
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from cryptography.fernet import Fernet

from app.channels import channel_bound
from app.config import Config, FeishuConfig
from app.db import DB
from app.feishu_personal import (
    FeishuPersonalManager,
    _parse_bind_code,
    build_personal_feishu_kwargs,
    decrypt_secret,
    encrypt_secret,
    hash_bind_code,
    is_definitive_feishu_error,
    resolve_personal_target,
)
from app.fetchers.base import Post

KEY = Fernet.generate_key().decode()


def make_db():
    return DB(Path(tempfile.mkdtemp()) / "fs.db")


def make_manager(db):
    return FeishuPersonalManager(db, FeishuConfig(app_id="a", app_secret="s", credential_key=KEY))


def begin_payload():
    return {
        "device_code": "v1:dc123",
        "user_code": "ABC-DEF",
        "verification_uri": "https://open.feishu.cn/page/launcher",
        "verification_uri_complete": "https://open.feishu.cn/page/launcher?user_code=ABC-DEF",
        "expires_in": 3600,
        "interval": 5,
    }


def poll_success_payload():
    return {
        "client_id": "cli_personal",
        "client_secret": "sec123",
        "user_info": {"open_id": "ou_p", "tenant_brand": "feishu"},
    }


def create_session(db, manager, status="pending"):
    uid = db.add_user("webuser", "hash")
    db.create_feishu_registration_session(
        session_id="sess1", user_id=uid,
        device_code_ciphertext=encrypt_secret(KEY, "v1:dc123"),
        registration_base_url="https://accounts.feishu.cn",
        verification_uri="https://open.feishu.cn/page/launcher?user_code=ABC",
        session_expires_at=int(time.time()) + 3600,
        poll_interval=5, status=status,
    )
    return uid


# ---- 加密与绑定码 ----

def test_encrypt_decrypt_secret():
    ct = encrypt_secret(KEY, "top-secret")
    assert ct != "top-secret"
    assert decrypt_secret(KEY, ct) == "top-secret"


def test_hash_bind_code_stable():
    # 解析层负责大小写归一（_parse_bind_code 已 lower），hash 对同一字符串稳定
    assert hash_bind_code("406d93") == hash_bind_code("406d93")
    assert len(hash_bind_code("406d93")) == 64
    assert hash_bind_code("406d93") != hash_bind_code("406D93")


def test_parse_bind_code():
    assert _parse_bind_code("/bind 406d93") == "406d93"
    assert _parse_bind_code("/bind 406D93") == "406d93"
    assert _parse_bind_code("  /BIND   406d93  ") == "406d93"
    assert _parse_bind_code("/bind 406d9") is None  # 长度不足
    assert _parse_bind_code("/bind zzzzzz") is None  # 非 hex
    assert _parse_bind_code("/list") is None
    assert _parse_bind_code("/bind 406d93 extra") is None  # 多余参数


# ---- 注册会话状态机 ----

def test_begin_session_creates_pending(monkeypatch):
    db = make_db()
    manager = make_manager(db)
    monkeypatch.setattr("app.feishu_personal.begin_registration", lambda base_url="https://accounts.feishu.cn": (begin_payload(), base_url))
    monkeypatch.setattr(manager, "_start_poller", lambda session_id: None)
    uid = db.add_user("u", "h")
    session = manager.begin_session(uid)
    assert session["status"] == "pending"
    assert session["verification_uri"].endswith("user_code=ABC-DEF")
    # 设备码必须加密存储，不出现明文
    assert session["device_code_ciphertext"] != "v1:dc123"
    assert "v1:dc123" not in session["device_code_ciphertext"]


def test_poll_waiting_400_is_pending(monkeypatch):
    """扫码等待：HTTP 400 + authorization_pending 是正常等待，不是异常。"""
    from app.feishu_personal import RegistrationFlowError, poll_registration

    def fake_post(url, data, timeout):
        return httpx.Response(400, json={"error": "authorization_pending", "error_description": "", "code": 20094})

    monkeypatch.setattr("app.feishu_personal.httpx.post", fake_post)
    with pytest.raises(RegistrationFlowError) as exc:
        poll_registration("v1:dc", "https://accounts.feishu.cn")
    assert exc.value.code == "authorization_pending"


def test_poll_success_issues_bind_code(monkeypatch):
    db = make_db()
    manager = make_manager(db)
    create_session(db, manager)
    monkeypatch.setattr(manager, "_ensure_listener", lambda session_id: None)
    manager._handle_poll_success("sess1", poll_success_payload(), "https://accounts.feishu.cn")
    session = db.get_feishu_registration_session("sess1")
    assert session["status"] == "awaiting_bind"
    assert session["candidate_app_id"] == "cli_personal"
    issued = manager.issue_bind_code("sess1")
    cmd = issued["bind_command"]
    assert cmd.startswith("/bind ") and len(cmd.split()[1]) == 6
    # 绑定码只存哈希
    session = db.get_feishu_registration_session("sess1")
    assert session["bind_code_hash"] == hash_bind_code(cmd.split()[1])
    assert cmd.split()[1] not in session["bind_code_hash"]


def test_poll_missing_open_id_degrades(monkeypatch):
    db = make_db()
    manager = make_manager(db)
    create_session(db, manager)
    payload = poll_success_payload()
    payload["user_info"] = {"tenant_brand": "feishu"}  # 无 open_id
    monkeypatch.setattr(manager, "_ensure_listener", lambda session_id: None)
    manager._handle_poll_success("sess1", payload, "https://accounts.feishu.cn")
    assert db.get_feishu_registration_session("sess1")["status"] == "degraded"


def test_poll_lark_switches_base_url(monkeypatch):
    db = make_db()
    manager = make_manager(db)
    create_session(db, manager)
    payload = poll_success_payload()
    payload["user_info"] = {"open_id": "ou_p", "tenant_brand": "lark"}
    monkeypatch.setattr(manager, "_ensure_listener", lambda session_id: None)
    manager._handle_poll_success("sess1", payload, "https://accounts.feishu.cn")
    session = db.get_feishu_registration_session("sess1")
    assert session["candidate_tenant_brand"] == "lark"
    assert session["registration_base_url"] == "https://accounts.larksuite.com"


# ---- 绑定消费 ----

def test_bind_command_plaintext_in_memory(monkeypatch):
    """绑定码明文只存进程内存：issue 后 get_bind_command 可读，消费后清除。"""
    db = make_db()
    manager = make_manager(db)
    create_session(db, manager)
    monkeypatch.setattr(manager, "_ensure_listener", lambda session_id: None)
    manager._handle_poll_success("sess1", poll_success_payload(), "https://accounts.feishu.cn")
    issued = manager.issue_bind_code("sess1")
    code = issued["bind_command"].split()[1]
    entry = manager.get_bind_command("sess1")
    assert entry and entry[0] == code
    # 消费后明文清除
    manager._drop_bind_command("sess1")
    assert manager.get_bind_command("sess1") is None


def test_handle_bind_message_full_flow(monkeypatch):
    db = make_db()
    manager = make_manager(db)
    uid = create_session(db, manager)
    monkeypatch.setattr(manager, "_ensure_listener", lambda session_id: None)
    manager._handle_poll_success("sess1", poll_success_payload(), "https://accounts.feishu.cn")
    issued = manager.issue_bind_code("sess1")
    code = issued["bind_command"].split()[1]

    sent = []

    class FakeNotifier:
        def __init__(self, *a, **k):
            pass

        def send_text(self, text):
            sent.append(text)

    monkeypatch.setattr("app.notifiers.feishu.FeishuNotifier", FakeNotifier)
    manager.handle_bind_message("sess1", code, "ou_p", "oc_p")

    bot = db.get_feishu_personal_bot(uid)
    assert bot["status"] == "active"
    assert bot["chat_id"] == "oc_p" and bot["open_id"] == "ou_p"
    assert bot["app_id"] == "cli_personal"
    assert db.get_feishu_registration_session("sess1")["status"] == "active"
    assert sent, "应发送测试消息"


def test_handle_bind_message_wrong_code_ignored(monkeypatch):
    db = make_db()
    manager = make_manager(db)
    create_session(db, manager)
    monkeypatch.setattr(manager, "_ensure_listener", lambda session_id: None)
    manager._handle_poll_success("sess1", poll_success_payload(), "https://accounts.feishu.cn")
    manager.issue_bind_code("sess1")
    manager.handle_bind_message("sess1", "abcdef", "ou_p", "oc_p")
    assert db.get_feishu_registration_session("sess1")["status"] == "awaiting_bind"
    assert db.get_feishu_personal_bot(db.get_feishu_registration_session("sess1")["user_id"]) is None


def test_handle_bind_message_expired_code_degrades(monkeypatch):
    db = make_db()
    manager = make_manager(db)
    create_session(db, manager)
    monkeypatch.setattr(manager, "_ensure_listener", lambda session_id: None)
    manager._handle_poll_success("sess1", poll_success_payload(), "https://accounts.feishu.cn")
    issued = manager.issue_bind_code("sess1")
    code = issued["bind_command"].split()[1]
    db.update_feishu_registration_session("sess1", bind_code_expires_at=int(time.time()) - 10)
    manager.handle_bind_message("sess1", code, "ou_p", "oc_p")
    assert db.get_feishu_registration_session("sess1")["status"] == "degraded"


def test_refresh_code_invalidates_old(monkeypatch):
    db = make_db()
    manager = make_manager(db)
    create_session(db, manager)
    monkeypatch.setattr(manager, "_ensure_listener", lambda session_id: None)
    manager._handle_poll_success("sess1", poll_success_payload(), "https://accounts.feishu.cn")
    old = manager.issue_bind_code("sess1")["bind_command"].split()[1]
    new = manager.issue_bind_code("sess1")["bind_command"].split()[1]
    assert old != new
    assert db.get_feishu_registration_session("sess1")["bind_code_hash"] == hash_bind_code(new)


def test_sender_mismatch_rejected(monkeypatch):
    db = make_db()
    manager = make_manager(db)
    uid = create_session(db, manager)
    monkeypatch.setattr(manager, "_ensure_listener", lambda session_id: None)
    manager._handle_poll_success("sess1", poll_success_payload(), "https://accounts.feishu.cn")
    code = manager.issue_bind_code("sess1")["bind_command"].split()[1]

    class FakeNotifier:
        def __init__(self, *a, **k):
            pass

        def send_text(self, text):
            raise AssertionError("发送者不匹配不应发测试消息")

    monkeypatch.setattr("app.notifiers.feishu.FeishuNotifier", FakeNotifier)
    manager.handle_bind_message("sess1", code, "ou_WRONG", "oc_p")
    assert db.get_feishu_personal_bot(uid) is None


# ---- 推送路由 ----

def make_user(**overrides):
    user = {
        "id": 1, "username": "u",
        "feishu_open_id": "ou_shared", "feishu_chat_id": "oc_shared",
    }
    user.update(overrides)
    return user


def test_channel_bound_personal_bot_without_shared_fields():
    """个人机器人 active 即视为飞书已绑定；degraded / 无 db 则否。"""
    db = make_db()
    uid = db.add_user("lili", "h")
    user = db.get_user(uid)
    cfg = FeishuConfig(credential_key=KEY)
    assert not channel_bound(user, "feishu", cfg)
    assert not channel_bound(user, "feishu", cfg, db)
    db.save_feishu_personal_bot(uid, "cli_p", encrypt_secret(KEY, "s"), "feishu", "active", chat_id="oc_p")
    user = db.get_user(uid)
    assert not channel_bound(user, "feishu", cfg)  # 无 db 看不到个人表
    assert channel_bound(user, "feishu", cfg, db)
    db.update_feishu_personal_bot(uid, status="degraded")
    assert not channel_bound(user, "feishu", cfg, db)


def test_resolve_personal_target_requires_active():
    db = make_db()
    uid = db.add_user("u", "h")
    cfg = FeishuConfig(credential_key=KEY)
    assert resolve_personal_target(db, cfg, db.get_user(uid)) is None  # 无记录
    db.save_feishu_personal_bot(uid, "cli_p", encrypt_secret(KEY, "s"), "feishu", "active", chat_id="oc_p")
    target = resolve_personal_target(db, cfg, db.get_user(uid))
    assert target and target["chat_id"] == "oc_p" and target["app_id"] == "cli_p"
    db.update_feishu_personal_bot(uid, status="degraded")
    assert resolve_personal_target(db, cfg, db.get_user(uid)) is None  # 降级走共享
    assert resolve_personal_target(db, FeishuConfig(), db.get_user(uid)) is None  # 无密钥


def test_build_personal_feishu_kwargs_fallback():
    db = make_db()
    uid = db.add_user("u", "h")
    db.update_user(uid, feishu_open_id="ou_s", feishu_chat_id="oc_s")
    cfg = FeishuConfig(credential_key=KEY)
    kw = build_personal_feishu_kwargs(db, cfg, db.get_user(uid))
    assert kw["chat_id"] == "oc_s" and kw["app_id"] is None  # 无个人 → 共享
    db.save_feishu_personal_bot(uid, "cli_p", encrypt_secret(KEY, "s"), "feishu", "active", chat_id="oc_p")
    kw = build_personal_feishu_kwargs(db, cfg, db.get_user(uid))
    assert kw["chat_id"] == "oc_p" and kw["app_id"] == "cli_p"  # 个人优先
    assert kw["open_id"] is None  # 个人路由只走 chat_id（open_id 直发被 230101 拦截）


def test_is_definitive_feishu_error():
    assert is_definitive_feishu_error(RuntimeError("飞书发送失败(code=91002): no permission"))
    assert is_definitive_feishu_error(RuntimeError("飞书发送失败(code=230101): 用户不存在"))
    assert not is_definitive_feishu_error(TimeoutError("timed out"))
    assert not is_definitive_feishu_error(RuntimeError("connection reset"))


def test_deliver_post_personal_fallback_to_shared(monkeypatch):
    """个人机器人明确错误 → 标记 degraded + 本条共享回退成功。"""
    from app.channels import deliver_post

    db = make_db()
    uid = db.add_user("u", "h")
    db.update_user(uid, feishu_open_id="ou_shared", feishu_chat_id="oc_shared")
    db.save_feishu_personal_bot(uid, "cli_p", encrypt_secret(KEY, "s"), "feishu", "active", chat_id="oc_p")

    calls = {"n": 0}

    class FakeNotifier:
        def __init__(self, config, client=None, open_id=None, chat_id=None,
                     unsub_kol_id=None, favorite=False, keyword=False,
                     secondary=False, app_id=None, app_secret=None,
                     interactive_buttons=True):
            self.chat_id = chat_id
            self.app_id = app_id

        def notify(self, post):
            calls["n"] += 1
            if calls["n"] == 1:
                assert self.app_id == "cli_p"  # 第一次走个人
                raise RuntimeError("飞书发送失败(code=91002): no permission")
            # 第二次共享回退
            assert self.app_id is None and self.chat_id == "oc_shared"

    monkeypatch.setattr("app.notifiers.feishu.FeishuNotifier", FakeNotifier)
    cfg = SimpleNamespace(feishu=FeishuConfig(app_id="a", app_secret="s", credential_key=KEY))
    post = Post(platform="xueqiu", kol_id=1, kol_name="A", external_id="p1",
                title="t", content="c", url="u", published_at="")
    kid = db.add_kol("xueqiu", "A", "ext1")
    post_id = db.insert_post("xueqiu", kid, "p1", "t", "c", "u", "")
    deliver_post(db, post_id, post, db.get_user(uid), "feishu", cfg, None)

    assert calls["n"] == 2
    bot = db.get_feishu_personal_bot(uid)
    assert bot["status"] == "degraded"
    logs = db.list_push_logs(user_id=uid, channel="feishu")
    assert len(logs) == 2  # 失败一条（个人）+ 成功一条（共享回退）
    assert logs[0]["status"] == "success"  # 最新一条（id DESC）


def test_deliver_post_personal_fuzzy_error_goes_retry(monkeypatch):
    """网络等模糊错误：不立即降级/双发，进重试队列。"""
    from app.channels import deliver_post

    db = make_db()
    uid = db.add_user("u", "h")
    db.update_user(uid, feishu_open_id="ou_shared", feishu_chat_id="oc_shared")
    db.save_feishu_personal_bot(uid, "cli_p", encrypt_secret(KEY, "s"), "feishu", "active", chat_id="oc_p")
    retried = []

    class FakeNotifier:
        def __init__(self, *a, **k):
            pass

        def notify(self, post):
            raise TimeoutError("timed out")

    monkeypatch.setattr("app.notifiers.feishu.FeishuNotifier", FakeNotifier)
    cfg = SimpleNamespace(feishu=FeishuConfig(app_id="a", app_secret="s", credential_key=KEY))
    post = Post(platform="xueqiu", kol_id=1, kol_name="A", external_id="p1",
                title="t", content="c", url="u", published_at="")
    deliver_post(db, 1, post, db.get_user(uid), "feishu", cfg, None, retry_queue=SimpleNamespace(add=lambda p, c, uid_: retried.append((p, c, uid_))))
    assert retried, "模糊错误应进重试队列"
    assert db.get_feishu_personal_bot(uid)["status"] == "active"  # 不降级


# ---- API ----

def _api_config(credential_key=""):
    cfg = Config()
    cfg.notifiers.feishu = FeishuConfig(app_id="a", app_secret="s", credential_key=credential_key)
    return cfg


def test_api_register_unavailable():
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(config=_api_config(""), db_path=Path(tempfile.mkdtemp()) / "a.db")
    client = TestClient(app)
    client.app.state.db.add_register_code("TEST0001")
    token = client.post("/api/auth/register", json={"username": "userone", "password": "secret123", "code": "TEST0001"}).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    resp = client.post("/api/me/feishu-personal/register", headers=h)
    assert resp.status_code == 400 and "未启用" in resp.json()["detail"]


def test_api_register_and_session(monkeypatch):
    from fastapi.testclient import TestClient

    from app import feishu_personal as fp
    from app.feishu_personal import FeishuPersonalManager
    from app.main import create_app

    app = create_app(config=_api_config(KEY), db_path=Path(tempfile.mkdtemp()) / "b.db")
    client = TestClient(app)
    db = client.app.state.db
    db.add_register_code("TEST0002")
    token = client.post("/api/auth/register", json={"username": "userone", "password": "secret123", "code": "TEST0002"}).json()["token"]
    h = {"Authorization": f"Bearer {token}"}

    monkeypatch.setattr(fp, "begin_registration", lambda base_url="https://accounts.feishu.cn": (begin_payload(), base_url))
    monkeypatch.setattr(FeishuPersonalManager, "_start_poller", lambda self, sid: None)
    resp = client.post("/api/me/feishu-personal/register", headers=h)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert data["verification_uri"].endswith("user_code=ABC-DEF")
    # 不返回设备码/绑定码明文
    assert "device_code" not in data and "client_secret" not in data

    sid = data["session_id"]
    # 别人的 session → 404
    db.add_register_code("TEST0003")
    token2 = client.post("/api/auth/register", json={"username": "usertwo", "password": "secret123", "code": "TEST0003"}).json()["token"]
    h2 = {"Authorization": f"Bearer {token2}"}
    assert client.get(f"/api/me/feishu-personal/register/{sid}", headers=h2).status_code == 404

    # 当前用户可查询
    assert client.get(f"/api/me/feishu-personal/register/{sid}", headers=h).status_code == 200

    # awaiting_bind 时状态接口返回内存中的绑定码明文（本人可读）
    db.update_feishu_registration_session(sid, status="awaiting_bind")
    monkeypatch.setattr(
        FeishuPersonalManager, "get_bind_command",
        lambda self, sid_: ("abc123", int(time.time()) + 60),
    )
    payload = client.get(f"/api/me/feishu-personal/register/{sid}", headers=h).json()
    assert payload["bind_command"] == "/bind abc123"
    assert payload["bind_code_expires_at"] > int(time.time())

    # 解绑个人机器人：无记录时幂等返回 ok，共享字段不受影响
    assert client.put("/api/me", headers=h, json={"feishu_open_id": "ou_s", "feishu_chat_id": "oc_s"}).status_code == 200
    assert client.delete("/api/me/feishu-personal", headers=h).status_code == 200
    me = client.get("/api/me", headers=h).json()
    assert me["feishu_personal"]["status"] == ""
    assert me["feishu_open_id"] == "ou_s" and me["feishu_chat_id"] == "oc_s"  # 共享字段保留
