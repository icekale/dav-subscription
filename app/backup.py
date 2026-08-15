"""管理员 SQLite 备份：本机下载、WebDAV 定时上传、从最新一份或本地文件恢复。"""
from __future__ import annotations

import logging
import re
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote

import httpx

from .db import DB

logger = logging.getLogger(__name__)

MSG_NOT_CONFIGURED = "先保存 WebDAV 配置"
MSG_CONNECT = "WebDAV 连不上，请检查地址和账号"
MSG_NO_REMOTE = "网盘上还没有备份文件"
MSG_CORRUPT = "备份文件损坏，已取消恢复，当前数据未改"
MSG_ROLLBACK = "恢复失败，已保持恢复前的数据库"
MSG_BAD_UPLOAD = "请上传有效的 .db 备份文件"
MSG_BUSY = "已有备份或恢复在进行"
MSG_HTTPS = "WebDAV 地址需要 https"

KEY_URL = "backup_webdav_url"
KEY_USER = "backup_webdav_username"
KEY_PASSWORD = "backup_webdav_password"
KEY_PATH = "backup_webdav_path"
KEY_HOUR = "backup_webdav_hour"
KEY_KEEP = "backup_webdav_keep"
KEY_LAST_OK = "backup_last_ok_at"
KEY_LAST_ERR = "backup_last_error"
KEY_LAST_NAME = "backup_last_remote_name"

DEFAULT_PATH = "/vpush-backups"
DEFAULT_HOUR = 3
DEFAULT_KEEP = 14
LOCAL_KEEP = 3
UPLOAD_MAX = 200 * 1024 * 1024

_op_lock = threading.Lock()
_HREF_RE = re.compile(r"href>([^<]+)", re.IGNORECASE)


class BackupError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class BackupBusy(BackupError):
    def __init__(self):
        super().__init__(MSG_BUSY, 409)


def with_lock(fn):
    if not _op_lock.acquire(blocking=False):
        raise BackupBusy()
    try:
        return fn()
    finally:
        _op_lock.release()


def join_webdav(base: str, *parts: str) -> str:
    url = (base or "").strip().rstrip("/")
    for part in parts:
        piece = str(part or "").strip().strip("/")
        if piece:
            url = f"{url}/{piece}"
    return url


def backups_dir(db: DB) -> Path:
    return Path(db.path).resolve().parent / "backups"


def quick_check(path: Path) -> bool:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = conn.execute("PRAGMA quick_check").fetchone()
            return bool(row) and row[0] == "ok"
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def _new_snapshot_path(folder: Path) -> Path:
    base = time.strftime("%Y%m%d-%H%M%S")
    target = folder / f"dav-{base}.db"
    n = 1
    while target.exists():
        target = folder / f"dav-{base}-{n}.db"
        n += 1
    return target


def _prune_local(folder: Path, keep: int = LOCAL_KEEP) -> None:
    files = sorted(folder.glob("dav-*.db"))
    for old in files[:-keep]:
        old.unlink(missing_ok=True)


def snapshot(db: DB) -> Path:
    folder = backups_dir(db)
    folder.mkdir(parents=True, exist_ok=True)
    target = _new_snapshot_path(folder)
    db.online_backup(target)
    if not quick_check(target):
        target.unlink(missing_ok=True)
        raise BackupError("备份校验失败，请稍后重试")
    try:
        target.chmod(0o600)
    except OSError:
        pass
    _prune_local(folder)
    return target


def load_config(db: DB) -> dict:
    hour_raw = db.get_setting(KEY_HOUR)
    keep_raw = db.get_setting(KEY_KEEP)
    try:
        hour = int(hour_raw) if hour_raw not in (None, "") else DEFAULT_HOUR
    except (TypeError, ValueError):
        hour = DEFAULT_HOUR
    try:
        keep = int(keep_raw) if keep_raw not in (None, "") else DEFAULT_KEEP
    except (TypeError, ValueError):
        keep = DEFAULT_KEEP
    return {
        "url": db.get_setting(KEY_URL) or "",
        "username": db.get_setting(KEY_USER) or "",
        "password": db.get_setting(KEY_PASSWORD) or "",
        "path": db.get_setting(KEY_PATH) or DEFAULT_PATH,
        "hour": hour,
        "keep": keep,
    }


def is_configured(cfg: dict) -> bool:
    return bool(cfg.get("url") and cfg.get("password"))


def save_config(db: DB, body: dict) -> None:
    if body.get("url") is not None:
        url = str(body["url"]).strip()
        if url and not url.lower().startswith("https://"):
            raise BackupError(MSG_HTTPS)
        db.set_setting(KEY_URL, url)
    if body.get("username") is not None:
        db.set_setting(KEY_USER, str(body["username"]).strip())
    if body.get("password"):
        db.set_setting(KEY_PASSWORD, str(body["password"]))
    if body.get("path") is not None:
        path = str(body["path"]).strip() or DEFAULT_PATH
        if not path.startswith("/"):
            path = "/" + path
        db.set_setting(KEY_PATH, path)
    if body.get("hour") is not None:
        try:
            hour = int(body["hour"])
        except (TypeError, ValueError) as exc:
            raise BackupError("每天几点需在 0-23 之间") from exc
        if not 0 <= hour <= 23:
            raise BackupError("每天几点需在 0-23 之间")
        db.set_setting(KEY_HOUR, str(hour))
    if body.get("keep") is not None:
        try:
            keep = int(body["keep"])
        except (TypeError, ValueError) as exc:
            raise BackupError("保留份数需在 1-90 之间") from exc
        if not 1 <= keep <= 90:
            raise BackupError("保留份数需在 1-90 之间")
        db.set_setting(KEY_KEEP, str(keep))


def next_run_at(cfg: dict, last_ok_at: str = "", now: datetime | None = None) -> str:
    now = now or datetime.now()
    today_slot = now.replace(hour=int(cfg["hour"]), minute=0, second=0, microsecond=0)
    last_date = (last_ok_at or "")[:10]
    if last_date == now.strftime("%Y-%m-%d"):
        today_slot = today_slot + timedelta(days=1)
    return today_slot.strftime("%Y-%m-%d %H:00")


def public_status(db: DB) -> dict:
    cfg = load_config(db)
    last_ok = db.get_setting(KEY_LAST_OK) or ""
    return {
        "url": cfg["url"],
        "username": cfg["username"],
        "path": cfg["path"],
        "hour": cfg["hour"],
        "keep": cfg["keep"],
        "password_set": bool(cfg["password"]),
        "last_ok_at": last_ok,
        "last_error": db.get_setting(KEY_LAST_ERR) or "",
        "last_remote_name": db.get_setting(KEY_LAST_NAME) or "",
        "next_run_at": next_run_at(cfg, last_ok),
    }


def is_due(db: DB, now: datetime | None = None) -> bool:
    cfg = load_config(db)
    if not is_configured(cfg):
        return False
    now = now or datetime.now()
    if now.hour < cfg["hour"]:
        return False
    last = db.get_setting(KEY_LAST_OK) or ""
    return not last.startswith(now.strftime("%Y-%m-%d"))


def _merge_cfg(db: DB, overrides: dict | None) -> dict:
    cfg = load_config(db)
    if not overrides:
        return cfg
    for key in ("url", "username", "path"):
        if overrides.get(key) is not None:
            cfg[key] = str(overrides[key]).strip()
    if overrides.get("password"):
        cfg["password"] = str(overrides["password"])
    if overrides.get("path") is not None:
        path = str(overrides["path"]).strip() or DEFAULT_PATH
        if not path.startswith("/"):
            path = "/" + path
        cfg["path"] = path
    return cfg


class WebDAV:
    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        path: str,
        client: httpx.Client | None = None,
    ):
        self.folder = join_webdav(url, path or DEFAULT_PATH)
        self.auth = (username or "", password or "")
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=60.0, follow_redirects=True)

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            resp = self.client.request(method, url, auth=self.auth, **kwargs)
        except httpx.RequestError as exc:
            raise BackupError(MSG_CONNECT) from exc
        if resp.status_code in (401, 403):
            raise BackupError(MSG_CONNECT)
        return resp

    def test_connection(self) -> None:
        resp = self._request("PROPFIND", self.folder, headers={"Depth": "0"})
        if resp.status_code == 404:
            resp = self._request("MKCOL", self.folder)
            if resp.status_code not in (201, 204, 405) and resp.status_code >= 400:
                raise BackupError(MSG_CONNECT)
            resp = self._request("PROPFIND", self.folder, headers={"Depth": "0"})
        if resp.status_code >= 400:
            raise BackupError(MSG_CONNECT)

    def list_names(self) -> list[str]:
        resp = self._request("PROPFIND", self.folder, headers={"Depth": "1"})
        if resp.status_code >= 400:
            raise BackupError(MSG_CONNECT)
        names = []
        for href in _HREF_RE.findall(resp.text or ""):
            name = unquote(href.rstrip("/").rsplit("/", 1)[-1])
            if name.startswith("dav-") and name.endswith(".db"):
                names.append(name)
        return sorted(set(names))

    def put(self, name: str, data: bytes) -> None:
        resp = self._request(
            "PUT",
            join_webdav(self.folder, name),
            content=data,
            headers={"Content-Type": "application/octet-stream"},
        )
        if resp.status_code >= 400:
            raise BackupError(MSG_CONNECT)

    def get(self, name: str) -> bytes:
        resp = self._request("GET", join_webdav(self.folder, name))
        if resp.status_code == 404:
            raise BackupError(MSG_NO_REMOTE)
        if resp.status_code >= 400:
            raise BackupError(MSG_CONNECT)
        return resp.content

    def delete(self, name: str) -> None:
        resp = self._request("DELETE", join_webdav(self.folder, name))
        if resp.status_code >= 400 and resp.status_code != 404:
            raise BackupError(MSG_CONNECT)

    def prune(self, keep: int) -> None:
        names = self.list_names()
        for name in names[:-keep] if keep > 0 else names:
            self.delete(name)

    def latest_name(self) -> str:
        names = self.list_names()
        if not names:
            raise BackupError(MSG_NO_REMOTE)
        return names[-1]


def webdav_client(cfg: dict) -> WebDAV:
    return WebDAV(cfg["url"], cfg["username"], cfg["password"], cfg["path"])


def test_connection(db: DB, overrides: dict | None = None) -> None:
    cfg = _merge_cfg(db, overrides)
    if not is_configured(cfg):
        raise BackupError(MSG_NOT_CONFIGURED)
    dav = webdav_client(cfg)
    try:
        dav.test_connection()
    finally:
        dav.close()


def restore_from_bytes(db: DB, data: bytes) -> None:
    if not data or len(data) > UPLOAD_MAX:
        raise BackupError(MSG_BAD_UPLOAD)
    folder = backups_dir(db)
    folder.mkdir(parents=True, exist_ok=True)
    candidate = folder / f"restore-{time.time_ns()}.db"
    candidate.write_bytes(data)
    try:
        if not quick_check(candidate):
            raise BackupError(MSG_CORRUPT)
        snap = snapshot(db)
        try:
            db.replace_database(candidate)
            db._rows("SELECT 1")
        except BackupError:
            raise
        except Exception:
            logger.exception("恢复后无法打开数据库")
            try:
                shutil.copy2(snap, db.path)
                Path(str(db.path) + "-wal").unlink(missing_ok=True)
                Path(str(db.path) + "-shm").unlink(missing_ok=True)
                db.reopen()
            except Exception:
                logger.exception("恢复回滚失败")
            raise BackupError(MSG_ROLLBACK) from None
    finally:
        candidate.unlink(missing_ok=True)


def restore_from_webdav(db: DB) -> None:
    cfg = load_config(db)
    if not is_configured(cfg):
        raise BackupError(MSG_NOT_CONFIGURED)
    dav = webdav_client(cfg)
    try:
        name = dav.latest_name()
        data = dav.get(name)
    finally:
        dav.close()
    restore_from_bytes(db, data)


def run_scheduled(db: DB) -> bool:
    if not is_due(db):
        return True
    cfg = load_config(db)

    def _do() -> None:
        path = snapshot(db)
        dav = webdav_client(cfg)
        try:
            dav.test_connection()
            dav.put(path.name, path.read_bytes())
            dav.prune(cfg["keep"])
        finally:
            dav.close()
        db.set_setting(KEY_LAST_OK, datetime.now().isoformat(timespec="seconds"))
        db.set_setting(KEY_LAST_ERR, "")
        db.set_setting(KEY_LAST_NAME, path.name)

    try:
        with_lock(_do)
        return True
    except BackupBusy:
        return True
    except BackupError as exc:
        db.set_setting(KEY_LAST_ERR, exc.message)
        logger.warning("定时备份失败: %s", exc.message)
        return False
    except Exception:
        db.set_setting(KEY_LAST_ERR, MSG_CONNECT)
        logger.exception("定时备份失败")
        return False
