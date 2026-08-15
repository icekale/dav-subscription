"""管理员备份：在线快照、假 WebDAV、下载/恢复 API。"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from app.db import DB
from app.main import create_app

_reg_code_seq = 0


def make_client(name="test.db"):
    tmp = tempfile.mkdtemp()
    os.environ["DAV_UI_ONLY"] = "1"
    app = create_app(config=None, db_path=Path(tmp) / name)
    return TestClient(app)


def register(client, username="testadmin", password="secret123"):
    global _reg_code_seq
    _reg_code_seq += 1
    code = f"BKP{_reg_code_seq:04d}"
    client.app.state.db.add_register_code(code)
    resp = client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "code": code},
    )
    assert resp.status_code == 200, resp.text
    return resp


def auth_headers(client, username="testadmin", password="secret123"):
    data = register(client, username, password).json()
    client.app.state.db.update_user(data["user"]["id"], is_admin=True)
    return {"Authorization": f"Bearer {data['token']}"}


def user_headers(client, username, password="pass123456"):
    token = register(client, username, password).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _quick_check(path: Path) -> str:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        conn.close()


class FakeDAV:
    """内存 WebDAV：PROPFIND/MKCOL/PUT/GET/DELETE。"""

    def __init__(self, user="u", password="p"):
        self.user = user
        self.password = password
        self.fs: dict[str, bytes] = {}
        self.dirs = {"/vpush-backups"}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        import base64

        expected = "Basic " + base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
        if request.headers.get("authorization") != expected:
            return httpx.Response(401)
        path = urlparse(str(request.url)).path.rstrip("/") or "/"
        name = path.rsplit("/", 1)[-1]
        if request.method == "PROPFIND":
            if path not in self.dirs:
                return httpx.Response(404)
            hrefs = [path + "/"] + [f"{path}/{fn}" for fn in self.fs]
            body = '<?xml version="1.0"?><D:multistatus xmlns:D="DAV:">'
            body += "".join(f"<D:response><D:href>{h}</D:href></D:response>" for h in hrefs)
            body += "</D:multistatus>"
            return httpx.Response(207, text=body)
        if request.method == "MKCOL":
            self.dirs.add(path)
            return httpx.Response(201)
        if request.method == "PUT":
            self.fs[name] = request.content
            return httpx.Response(201)
        if request.method == "GET":
            if name not in self.fs:
                return httpx.Response(404)
            return httpx.Response(200, content=self.fs[name])
        if request.method == "DELETE":
            self.fs.pop(name, None)
            return httpx.Response(204)
        return httpx.Response(405)


def test_join_webdav_strips_duplicate_slashes():
    from app.backup import join_webdav

    assert join_webdav("https://a.com/", "/vpush-backups", "dav-1.db") == (
        "https://a.com/vpush-backups/dav-1.db"
    )
    assert join_webdav("https://a.com/dav/", "vpush-backups/") == (
        "https://a.com/dav/vpush-backups"
    )


def test_snapshot_quick_check_ok_and_keeps_three(tmp_path):
    from app.backup import snapshot

    db = DB(tmp_path / "dav.db")
    db.set_setting("probe", "1")
    paths = [snapshot(db) for _ in range(4)]
    assert all(p.name.startswith("dav-") and p.suffix == ".db" for p in paths)
    remaining = sorted((tmp_path / "backups").glob("dav-*.db"))
    assert len(remaining) == 3
    assert _quick_check(remaining[-1]) == "ok"


def test_webdav_put_latest_and_keep(tmp_path):
    from app.backup import WebDAV

    fake = FakeDAV()
    client = httpx.Client(transport=httpx.MockTransport(fake))
    dav = WebDAV("https://dav.test", "u", "p", "/vpush-backups", client=client)
    dav.test_connection()
    dav.put("dav-20260801-030000.db", b"one")
    dav.put("dav-20260802-030000.db", b"two")
    dav.put("dav-20260803-030000.db", b"three")
    dav.prune(2)
    assert sorted(fake.fs) == ["dav-20260802-030000.db", "dav-20260803-030000.db"]
    assert dav.latest_name() == "dav-20260803-030000.db"
    assert dav.get("dav-20260803-030000.db") == b"three"


def test_is_due_retries_same_day_until_success(tmp_path):
    from app.backup import is_due

    db = DB(tmp_path / "dav.db")
    now = datetime.now().replace(year=2026, month=8, day=15, hour=4, minute=0, second=0, microsecond=0)
    assert is_due(db, now=now) is False  # 未配置
    db.set_setting("backup_webdav_url", "https://dav.example/webdav")
    db.set_setting("backup_webdav_password", "secret")
    db.set_setting("backup_webdav_hour", "3")
    assert is_due(db, now=now.replace(hour=2)) is False
    assert is_due(db, now=now) is True
    db.set_setting("backup_last_error", "上次失败")
    assert is_due(db, now=now) is True
    db.set_setting("backup_last_ok_at", "2026-08-15T03:01:00")
    assert is_due(db, now=now) is False


def test_download_returns_quick_check_ok_file():
    from app.backup import MSG_BUSY, _op_lock

    client = make_client()
    headers = auth_headers(client)
    resp = client.get("/api/admin/backup/download", headers=headers)
    assert resp.status_code == 200, resp.text
    assert "dav-" in resp.headers.get("content-disposition", "")
    tmp = Path(tempfile.mkdtemp()) / "got.db"
    tmp.write_bytes(resp.content)
    assert _quick_check(tmp) == "ok"

    _op_lock.acquire()
    try:
        busy = client.get("/api/admin/backup/download", headers=headers)
        assert busy.status_code == 409
        assert busy.json()["detail"] == MSG_BUSY
    finally:
        _op_lock.release()


def test_unconfigured_webdav_test_and_restore():
    from app.backup import MSG_NOT_CONFIGURED

    client = make_client()
    headers = auth_headers(client)
    test = client.post("/api/admin/backup/webdav/test", headers=headers, json={})
    assert test.status_code == 400
    assert test.json()["detail"] == MSG_NOT_CONFIGURED
    restore = client.post("/api/admin/backup/restore/webdav", headers=headers)
    assert restore.status_code == 400
    assert restore.json()["detail"] == MSG_NOT_CONFIGURED


def test_corrupt_restore_does_not_clobber_users():
    from app.backup import MSG_BAD_UPLOAD, MSG_CORRUPT

    client = make_client()
    headers = auth_headers(client)
    db = client.app.state.db
    before = len(db.list_users())
    resp = client.post(
        "/api/admin/backup/restore/upload",
        headers=headers,
        files={"file": ("broken.db", b"not a sqlite database", "application/octet-stream")},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == MSG_CORRUPT
    assert len(db.list_users()) == before

    bad_ext = client.post(
        "/api/admin/backup/restore/upload",
        headers=headers,
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert bad_ext.status_code == 400
    assert bad_ext.json()["detail"] == MSG_BAD_UPLOAD


def test_restore_upload_valid_db_replaces_and_rollback_on_reopen_fail(monkeypatch):
    from app.backup import MSG_ROLLBACK, restore_from_bytes, snapshot

    client = make_client()
    headers = auth_headers(client)
    db = client.app.state.db
    snap = snapshot(db)
    db.add_register_code("KEEPME01")
    assert db.get_register_code("KEEPME01")

    restore = client.post(
        "/api/admin/backup/restore/upload",
        headers=headers,
        files={"file": (snap.name, snap.read_bytes(), "application/octet-stream")},
    )
    assert restore.status_code == 200, restore.text
    assert db.get_register_code("KEEPME01") is None

    db.add_register_code("STAY01")
    orig = db.replace_database

    def boom(candidate):
        orig(candidate)
        raise RuntimeError("reopen ping fail")

    monkeypatch.setattr(db, "replace_database", boom)
    with pytest.raises(Exception) as exc:
        restore_from_bytes(db, snap.read_bytes())
    assert MSG_ROLLBACK in str(exc.value)
    assert db.get_register_code("STAY01") is not None


def test_scheduled_upload_and_restore_webdav(monkeypatch):
    from app import backup as backup_mod

    store: dict[str, bytes] = {}

    class MemDAV:
        def __init__(self, cfg):
            self.cfg = cfg

        def test_connection(self):
            return None

        def put(self, name, data):
            store[name] = data

        def prune(self, keep):
            names = sorted(n for n in store if n.startswith("dav-") and n.endswith(".db"))
            for name in names[:-keep]:
                del store[name]

        def latest_name(self):
            names = sorted(n for n in store if n.startswith("dav-") and n.endswith(".db"))
            if not names:
                raise backup_mod.BackupError(backup_mod.MSG_NO_REMOTE)
            return names[-1]

        def get(self, name):
            return store[name]

        def close(self):
            return None

    monkeypatch.setattr(backup_mod, "webdav_client", MemDAV)

    client = make_client()
    headers = auth_headers(client)
    db = client.app.state.db
    saved = client.put(
        "/api/admin/backup/webdav",
        headers=headers,
        json={
            "url": "https://dav.example/webdav",
            "username": "u",
            "password": "secret",
            "path": "/vpush-backups",
            "hour": 0,
            "keep": 2,
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert "password" not in body
    assert body["password_set"] is True
    assert body["url"] == "https://dav.example/webdav"

    got = client.get("/api/admin/backup", headers=headers).json()
    assert got["password_set"] is True
    assert "password" not in got

    db.add_register_code("BEFORE01")
    assert backup_mod.run_scheduled(db) is True
    assert len(store) == 1
    remote_name = next(iter(store))
    assert db.get_setting("backup_last_remote_name") == remote_name
    assert (db.get_setting("backup_last_ok_at") or "").startswith(datetime.now().strftime("%Y-%m-%d"))

    # keep=2：第三份之后只留 2
    db.set_setting("backup_last_ok_at", "2000-01-01T00:00:00")
    assert backup_mod.run_scheduled(db) is True
    db.set_setting("backup_last_ok_at", "2000-01-01T00:00:00")
    assert backup_mod.run_scheduled(db) is True
    assert len(store) == 2

    db.add_register_code("AFTER01")
    restored = client.post("/api/admin/backup/restore/webdav", headers=headers)
    assert restored.status_code == 200, restored.text
    assert db.get_register_code("AFTER01") is None
    assert db.get_register_code("BEFORE01") is not None


def test_non_admin_backup_routes_403():
    client = make_client()
    headers = user_headers(client, "normaluser")
    assert client.get("/api/admin/backup", headers=headers).status_code == 403
    assert client.put("/api/admin/backup/webdav", headers=headers, json={}).status_code == 403
    assert client.post("/api/admin/backup/webdav/test", headers=headers, json={}).status_code == 403
    assert client.get("/api/admin/backup/download", headers=headers).status_code == 403
    assert client.post("/api/admin/backup/restore/webdav", headers=headers).status_code == 403
    assert client.post(
        "/api/admin/backup/restore/upload",
        headers=headers,
        files={"file": ("x.db", b"abc", "application/octet-stream")},
    ).status_code == 403
