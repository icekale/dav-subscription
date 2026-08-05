"""SQLite 持久化：KOL、帖子（去重）、推送日志。"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

_UNSET = object()


def _merge_sub_types(a: str, b: str) -> str:
    """两个订阅类型合并（并集语义）：post + reply = both。"""
    types = {a or "post", b or "post"}
    if "both" in types or {"post", "reply"} <= types:
        return "both"
    return next(iter(types))


SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS kols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    name TEXT NOT NULL,
    external_id TEXT NOT NULL,
    avatar_url TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    is_private INTEGER NOT NULL DEFAULT 0,
    original_only INTEGER NOT NULL DEFAULT 0,
    category_id INTEGER,
    priority INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS kol_acl (
    kol_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    PRIMARY KEY (kol_id, user_id)
);
CREATE TABLE IF NOT EXISTS kol_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    external_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    handled_at TEXT
);
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    kol_id INTEGER NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    post_type TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL DEFAULT '',
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (platform, external_id)
);
CREATE TABLE IF NOT EXISTS push_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL,
    channel TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    wechat_openid TEXT NOT NULL DEFAULT '',
    telegram_chat_id TEXT NOT NULL DEFAULT '',
    telegram_bot_token TEXT NOT NULL DEFAULT '',
    feishu_open_id TEXT NOT NULL DEFAULT '',
    feishu_chat_id TEXT NOT NULL DEFAULT '',
    wecom_webhook TEXT NOT NULL DEFAULT '',
    notify_enabled INTEGER NOT NULL DEFAULT 1,
    daily_report INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    kol_id INTEGER NOT NULL,
    type TEXT NOT NULL DEFAULT 'post',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, kol_id)
);
CREATE TABLE IF NOT EXISTS bind_codes (
    code TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS register_codes (
    code TEXT PRIMARY KEY,
    note TEXT NOT NULL DEFAULT '',
    used_by INTEGER,
    used_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS admin_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

ALLOWED_PLATFORMS = {"xueqiu", "combination", "weibo", "twitter"}


class DB:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        # Docker 里 /data 是 virtiofs 挂载，WAL 的共享内存映射不可靠（会出现
        # wal/shm 被删除后写入丢失的问题），统一用回滚日志模式，跨进程读写一致。
        self._conn.execute("PRAGMA journal_mode=DELETE")
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self):
        post_cols = {row["name"] for row in self._rows("PRAGMA table_info(posts)")}
        if "post_type" not in post_cols:
            self._conn.execute(
                "ALTER TABLE posts ADD COLUMN post_type TEXT NOT NULL DEFAULT ''"
            )
        if "detail" not in post_cols:
            self._conn.execute(
                "ALTER TABLE posts ADD COLUMN detail TEXT NOT NULL DEFAULT ''"
            )
        sub_cols = {row["name"] for row in self._rows("PRAGMA table_info(subscriptions)")}
        if "type" not in sub_cols:
            self._conn.execute(
                "ALTER TABLE subscriptions ADD COLUMN type TEXT NOT NULL DEFAULT 'post'"
            )
        cols = {row["name"] for row in self._rows("PRAGMA table_info(kols)")}
        if "category_id" not in cols:
            self._conn.execute("ALTER TABLE kols ADD COLUMN category_id INTEGER")
        push_cols = {row["name"] for row in self._rows("PRAGMA table_info(push_logs)")}
        if "user_id" not in push_cols:
            self._conn.execute("ALTER TABLE push_logs ADD COLUMN user_id INTEGER")
        user_cols = {row["name"] for row in self._rows("PRAGMA table_info(users)")}
        if "wechat_openid" not in user_cols:
            self._conn.execute("ALTER TABLE users ADD COLUMN wechat_openid TEXT NOT NULL DEFAULT ''")
        if "feishu_chat_id" not in user_cols:
            self._conn.execute("ALTER TABLE users ADD COLUMN feishu_chat_id TEXT NOT NULL DEFAULT ''")
        if "daily_report" not in user_cols:
            self._conn.execute("ALTER TABLE users ADD COLUMN daily_report INTEGER NOT NULL DEFAULT 0")
        if "wecom_webhook" not in user_cols:
            self._conn.execute("ALTER TABLE users ADD COLUMN wecom_webhook TEXT NOT NULL DEFAULT ''")
        if "telegram_bot_token" not in user_cols:
            self._conn.execute("ALTER TABLE users ADD COLUMN telegram_bot_token TEXT NOT NULL DEFAULT ''")
        kol_cols = {row["name"] for row in self._rows("PRAGMA table_info(kols)")}
        if "priority" not in kol_cols:
            self._conn.execute("ALTER TABLE kols ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")
        if "is_private" not in kol_cols:
            self._conn.execute("ALTER TABLE kols ADD COLUMN is_private INTEGER NOT NULL DEFAULT 0")
        if "avatar_url" not in kol_cols:
            self._conn.execute("ALTER TABLE kols ADD COLUMN avatar_url TEXT NOT NULL DEFAULT ''")
        if "original_only" not in kol_cols:
            self._conn.execute("ALTER TABLE kols ADD COLUMN original_only INTEGER NOT NULL DEFAULT 0")
        # 渠道绑定唯一化：先清理重复（保留最早注册的用户），再建唯一索引，
        # 避免两个账号绑定同一个 chat_id/open_id 导致重复推送或 /bind 合并错账号。
        for column in (
            "telegram_chat_id",
            "feishu_open_id",
            "feishu_chat_id",
            "wechat_openid",
            "wecom_webhook",
            "telegram_bot_token",
        ):
            seen = set()
            for row in self._rows(
                f"SELECT id, {column} AS v FROM users WHERE {column} != '' ORDER BY id"
            ):
                if row["v"] in seen:
                    self._conn.execute(
                        f"UPDATE users SET {column} = '' WHERE id = ?", (row["id"],)
                    )
                else:
                    seen.add(row["v"])
            self._conn.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS uq_users_{column} "
                f"ON users({column}) WHERE {column} != ''"
            )

    def close(self):
        with self._lock:
            self._conn.close()

    def _rows(self, sql, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]

    def _execute(self, sql, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur.lastrowid

    # ---- KOL ----
    def add_kol(
        self,
        platform: str,
        name: str,
        external_id: str,
        category_id: int | None = None,
        priority: bool = False,
        original_only: bool = False,
    ) -> int:
        if platform not in ALLOWED_PLATFORMS:
            raise ValueError(f"不支持的平台: {platform}")
        if self._rows(
            "SELECT id FROM kols WHERE platform = ? AND external_id = ?",
            (platform, external_id),
        ):
            raise ValueError("该大V已存在")
        return self._execute(
            "INSERT INTO kols (platform, name, external_id, category_id, priority, original_only) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (platform, name, external_id, category_id, 1 if priority else 0, 1 if original_only else 0),
        )

    def get_kol(self, kol_id: int) -> dict | None:
        rows = self._rows(
            "SELECT k.*, c.name AS category_name FROM kols k "
            "LEFT JOIN categories c ON c.id = k.category_id WHERE k.id = ?",
            (kol_id,),
        )
        return rows[0] if rows else None

    def update_kol_avatar(self, kol_id: int, avatar_url: str) -> None:
        self._execute(
            "UPDATE kols SET avatar_url = ? WHERE id = ?",
            (avatar_url or "", kol_id),
        )

    def list_kols(self, platform: str | None = None, category_id: int | None = None) -> list[dict]:
        sql = "SELECT k.*, c.name AS category_name FROM kols k LEFT JOIN categories c ON c.id = k.category_id"
        conds, params = [], []
        if platform:
            conds.append("k.platform = ?")
            params.append(platform)
        if category_id is not None:
            conds.append("k.category_id = ?")
            params.append(category_id)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY k.id"
        return self._rows(sql, params)

    def recommended_kols(self, user_id: int, limit: int = 4) -> list[dict]:
        """新用户引导推荐：启用且公开的大V，按订阅人数倒序。"""
        return self._rows(
            "SELECT k.*, c.name AS category_name, "
            "(SELECT COUNT(*) FROM subscriptions s WHERE s.kol_id = k.id) AS subscriber_count, "
            "EXISTS(SELECT 1 FROM subscriptions mine "
            "       WHERE mine.kol_id = k.id AND mine.user_id = ?) AS subscribed "
            "FROM kols k LEFT JOIN categories c ON c.id = k.category_id "
            "WHERE k.enabled = 1 AND k.is_private = 0 "
            "ORDER BY subscriber_count DESC, k.id DESC LIMIT ?",
            (user_id, limit),
        )

    def last_post_time_by_kol(self) -> dict[int, str]:
        """每个大V最近一次抓到帖子的时间（fetched_at），用于活跃度排序。"""
        rows = self._rows(
            "SELECT kol_id, MAX(fetched_at) AS last_at FROM posts GROUP BY kol_id"
        )
        return {r["kol_id"]: r["last_at"] for r in rows}

    def update_kol(
        self,
        kol_id: int,
        name=None,
        external_id=None,
        enabled=None,
        original_only=_UNSET,
        category_id=_UNSET,
        priority=_UNSET,
        is_private=_UNSET,
    ):
        sets, params = [], []
        if name is not None:
            sets.append("name = ?")
            params.append(name)
        if external_id is not None:
            sets.append("external_id = ?")
            params.append(external_id)
        if enabled is not None:
            sets.append("enabled = ?")
            params.append(1 if enabled else 0)
        if original_only is not _UNSET:
            sets.append("original_only = ?")
            params.append(1 if original_only else 0)
        if category_id is not _UNSET:
            sets.append("category_id = ?")
            params.append(category_id)
        if priority is not _UNSET:
            sets.append("priority = ?")
            params.append(1 if priority else 0)
        if is_private is not _UNSET:
            sets.append("is_private = ?")
            params.append(1 if is_private else 0)
        if not sets:
            return
        params.append(kol_id)
        self._execute(f"UPDATE kols SET {', '.join(sets)} WHERE id = ?", params)

    def delete_kol(self, kol_id: int):
        # 级联清理该大V的订阅、帖子与推送记录，避免残留
        self._execute("DELETE FROM kol_acl WHERE kol_id = ?", (kol_id,))
        self._execute("DELETE FROM subscriptions WHERE kol_id = ?", (kol_id,))
        self._execute(
            "DELETE FROM push_logs WHERE post_id IN (SELECT id FROM posts WHERE kol_id = ?)",
            (kol_id,),
        )
        self._execute("DELETE FROM posts WHERE kol_id = ?", (kol_id,))
        self._execute("DELETE FROM kols WHERE id = ?", (kol_id,))

    # ---- KOL 可见性（白名单） ----
    def set_kol_acl(self, kol_id: int, user_ids: list[int]) -> None:
        self._execute("DELETE FROM kol_acl WHERE kol_id = ?", (kol_id,))
        for uid in set(user_ids):
            self._execute(
                "INSERT OR IGNORE INTO kol_acl (kol_id, user_id) VALUES (?, ?)",
                (kol_id, uid),
            )

    def acl_user_ids(self, kol_id: int) -> list[int]:
        return [r["user_id"] for r in self._rows("SELECT user_id FROM kol_acl WHERE kol_id = ?", (kol_id,))]

    def visible_kol_ids(self, user_id: int) -> set[int]:
        """用户可见的大V：公开大V + 白名单里的私有大V。"""
        rows = self._rows(
            "SELECT id FROM kols WHERE is_private = 0 "
            "UNION SELECT kol_id FROM kol_acl WHERE user_id = ?",
            (user_id,),
        )
        return {r["id"] for r in rows}

    # ---- 求添加申请 ----
    def add_kol_request(self, platform: str, external_id: str, user_id: int, name: str = "") -> int:
        if platform not in ALLOWED_PLATFORMS:
            raise ValueError(f"不支持的平台: {platform}")
        if self._rows(
            "SELECT id FROM kol_requests WHERE platform = ? AND external_id = ? AND status = 'pending'",
            (platform, external_id),
        ):
            raise ValueError("该大V的申请已在处理中")
        if self._rows(
            "SELECT id FROM kols WHERE platform = ? AND external_id = ?",
            (platform, external_id),
        ):
            raise ValueError("该大V已在目录中，直接订阅即可")
        return self._execute(
            "INSERT INTO kol_requests (platform, name, external_id, user_id) VALUES (?, ?, ?, ?)",
            (platform, name.strip(), external_id, user_id),
        )

    def list_kol_requests(self, status: str | None = None) -> list[dict]:
        sql = (
            "SELECT r.*, u.username AS requester FROM kol_requests r "
            "LEFT JOIN users u ON u.id = r.user_id"
        )
        params: tuple = ()
        if status:
            sql += " WHERE r.status = ?"
            params = (status,)
        sql += " ORDER BY r.id DESC"
        return self._rows(sql, params)

    def get_kol_request(self, request_id: int) -> dict | None:
        rows = self._rows("SELECT * FROM kol_requests WHERE id = ?", (request_id,))
        return rows[0] if rows else None

    def set_kol_request_status(self, request_id: int, status: str) -> None:
        self._execute(
            "UPDATE kol_requests SET status = ?, handled_at = datetime('now') WHERE id = ?",
            (status, request_id),
        )

    # ---- Category ----
    def list_categories(self) -> list[dict]:
        return self._rows(
            "SELECT c.*, (SELECT COUNT(*) FROM kols k WHERE k.category_id = c.id) AS kol_count "
            "FROM categories c ORDER BY c.id"
        )

    def get_category(self, category_id: int) -> dict | None:
        rows = self._rows("SELECT * FROM categories WHERE id = ?", (category_id,))
        return rows[0] if rows else None

    def add_category(self, name: str) -> int:
        try:
            return self._execute("INSERT INTO categories (name) VALUES (?)", (name,))
        except sqlite3.IntegrityError:
            raise ValueError(f"分类已存在: {name}") from None

    def rename_category(self, category_id: int, name: str) -> None:
        try:
            self._execute("UPDATE categories SET name = ? WHERE id = ?", (name, category_id))
        except sqlite3.IntegrityError:
            raise ValueError(f"分类已存在: {name}") from None

    def delete_category(self, category_id: int) -> None:
        self._execute("UPDATE kols SET category_id = NULL WHERE category_id = ?", (category_id,))
        self._execute("DELETE FROM categories WHERE id = ?", (category_id,))

    # ---- User ----
    def get_user(self, user_id: int) -> dict | None:
        rows = self._rows("SELECT * FROM users WHERE id = ?", (user_id,))
        return rows[0] if rows else None

    def get_user_by_username(self, username: str) -> dict | None:
        rows = self._rows("SELECT * FROM users WHERE username = ?", (username,))
        return rows[0] if rows else None

    def get_user_by_telegram(self, chat_id: str) -> dict | None:
        rows = self._rows("SELECT * FROM users WHERE telegram_chat_id = ?", (chat_id,))
        return rows[0] if rows else None

    def get_user_by_telegram_bot(self, bot_token: str) -> dict | None:
        rows = self._rows("SELECT * FROM users WHERE telegram_bot_token = ?", (bot_token,))
        return rows[0] if rows else None

    def get_user_by_feishu(self, open_id: str) -> dict | None:
        rows = self._rows("SELECT * FROM users WHERE feishu_open_id = ?", (open_id,))
        return rows[0] if rows else None

    def get_user_by_feishu_chat(self, chat_id: str) -> dict | None:
        rows = self._rows("SELECT * FROM users WHERE feishu_chat_id = ?", (chat_id,))
        return rows[0] if rows else None

    def get_user_by_wecom_webhook(self, webhook: str) -> dict | None:
        rows = self._rows("SELECT * FROM users WHERE wecom_webhook = ?", (webhook,))
        return rows[0] if rows else None

    def get_user_by_openid(self, openid: str) -> dict | None:
        rows = self._rows("SELECT * FROM users WHERE wechat_openid = ?", (openid,))
        return rows[0] if rows else None

    def count_users(self) -> int:
        rows = self._rows("SELECT COUNT(*) AS n FROM users")
        return rows[0]["n"]

    def add_user(
        self,
        username: str,
        password_hash: str,
        is_admin: bool = False,
        telegram_chat_id: str = "",
        feishu_open_id: str = "",
        feishu_chat_id: str = "",
        notify_enabled: bool = True,
        wechat_openid: str = "",
    ) -> int:
        try:
            return self._execute(
                "INSERT INTO users (username, password_hash, is_admin, telegram_chat_id, "
                "feishu_open_id, feishu_chat_id, notify_enabled, wechat_openid) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (username, password_hash, 1 if is_admin else 0, telegram_chat_id, feishu_open_id,
                 feishu_chat_id, 1 if notify_enabled else 0, wechat_openid),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f"用户名已存在: {username}") from None

    def update_user(self, user_id: int, **kwargs) -> None:
        sets, params = [], []
        for key, value in kwargs.items():
            if key in ("is_admin", "notify_enabled"):
                value = 1 if value else 0
            sets.append(f"{key} = ?")
            params.append(value)
        if not sets:
            return
        params.append(user_id)
        self._execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", params)

    def list_users(self) -> list[dict]:
        return self._rows("SELECT * FROM users ORDER BY id")

    # ---- 注册码 ----
    def log_admin_action(self, user_id: int | None, action: str, target: str = "", detail: str = "") -> None:
        self._execute(
            "INSERT INTO admin_logs (user_id, action, target, detail) VALUES (?, ?, ?, ?)",
            (user_id, action, target, detail),
        )

    def list_admin_logs(self, limit: int = 100) -> list[dict]:
        return self._rows(
            "SELECT l.*, u.username FROM admin_logs l LEFT JOIN users u ON u.id = l.user_id "
            "ORDER BY l.id DESC LIMIT ?",
            (limit,),
        )

    def add_register_code(self, code: str, note: str = "") -> None:
        try:
            self._execute(
                "INSERT INTO register_codes (code, note) VALUES (?, ?)",
                (code.strip().upper(), note.strip()),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f"注册码已存在: {code}") from None

    def list_register_codes(self) -> list[dict]:
        return self._rows(
            "SELECT rc.*, u.username AS used_by_name FROM register_codes rc "
            "LEFT JOIN users u ON u.id = rc.used_by ORDER BY rc.created_at DESC"
        )

    def get_register_code(self, code: str) -> dict | None:
        rows = self._rows(
            "SELECT * FROM register_codes WHERE code = ?", (code.strip().upper(),)
        )
        return rows[0] if rows else None

    def delete_register_code(self, code: str) -> bool:
        """删除一个未使用的注册码；已使用的不可删除。"""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM register_codes WHERE code = ? AND used_by IS NULL",
                (code.strip().upper(),),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def register_with_code(self, code: str, username: str, password_hash: str) -> int:
        """凭注册码注册：原子消费注册码 + 创建用户，任一失败整体回滚。"""
        with self._lock:
            try:
                self._conn.execute("BEGIN")
                cur = self._conn.execute(
                    "UPDATE register_codes SET used_at = datetime('now') "
                    "WHERE code = ? AND used_by IS NULL",
                    (code.strip().upper(),),
                )
                if cur.rowcount == 0:
                    raise ValueError("注册码无效或已被使用")
                try:
                    insert = self._conn.execute(
                        "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 0)",
                        (username, password_hash),
                    )
                except sqlite3.IntegrityError:
                    raise ValueError(f"用户名已存在: {username}") from None
                uid = insert.lastrowid
                self._conn.execute(
                    "UPDATE register_codes SET used_by = ? WHERE code = ?",
                    (uid, code.strip().upper()),
                )
                self._conn.commit()
                return uid
            except Exception:
                self._conn.rollback()
                raise

    # ---- Subscription ----
    def add_subscription(self, user_id: int, kol_id: int, type: str = "post") -> bool:
        try:
            self._execute(
                "INSERT INTO subscriptions (user_id, kol_id, type) VALUES (?, ?, ?)",
                (user_id, kol_id, type),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def update_subscription_type(self, user_id: int, kol_id: int, type: str) -> bool:
        """切换订阅类型：post / reply / both。"""
        if type not in ("post", "reply", "both"):
            raise ValueError(f"无效的订阅类型: {type}")
        with self._lock:
            cur = self._conn.execute(
                "UPDATE subscriptions SET type = ? WHERE user_id = ? AND kol_id = ?",
                (type, user_id, kol_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def remove_subscription(self, user_id: int, kol_id: int) -> None:
        self._execute(
            "DELETE FROM subscriptions WHERE user_id = ? AND kol_id = ?",
            (user_id, kol_id),
        )

    def list_subscriptions(self, user_id: int) -> list[dict]:
        return self._rows(
            "SELECT k.*, s.type AS subscribe_type, c.name AS category_name, "
            "s.created_at AS subscribed_at "
            "FROM subscriptions s JOIN kols k ON k.id = s.kol_id "
            "LEFT JOIN categories c ON c.id = k.category_id "
            "WHERE s.user_id = ? ORDER BY s.id",
            (user_id,),
        )

    def subscribed_kol_ids(self, user_id: int) -> set[int]:
        rows = self._rows("SELECT kol_id FROM subscriptions WHERE user_id = ?", (user_id,))
        return {row["kol_id"] for row in rows}

    def subscribed_kol_types(self, user_id: int) -> dict[int, str]:
        rows = self._rows(
            "SELECT kol_id, type FROM subscriptions WHERE user_id = ?", (user_id,)
        )
        return {row["kol_id"]: row["type"] for row in rows}

    def subscribers_of_kol(self, kol_id: int) -> list[dict]:
        """该大V的订阅者（启用通知且绑定了渠道的用户）。"""
        return self._rows(
            "SELECT u.*, s.type AS subscribe_type FROM subscriptions s "
            "JOIN users u ON u.id = s.user_id "
            "JOIN kols k ON k.id = s.kol_id "
            "WHERE s.kol_id = ? AND u.notify_enabled = 1 "
            "AND (u.telegram_chat_id != '' OR u.feishu_open_id != '' OR u.feishu_chat_id != '' "
            "OR u.wecom_webhook != '') "
            "AND (k.is_private = 0 OR EXISTS "
            "(SELECT 1 FROM kol_acl a WHERE a.kol_id = k.id AND a.user_id = u.id))",
            (kol_id,),
        )

    # ---- 绑定码 ----
    def create_bind_code(self, code: str, user_id: int, expires_at: int) -> None:
        self._execute(
            "INSERT INTO bind_codes (code, user_id, expires_at) VALUES (?, ?, ?)",
            (code, user_id, expires_at),
        )

    def get_bind_code(self, code: str) -> dict | None:
        rows = self._rows("SELECT * FROM bind_codes WHERE code = ?", (code,))
        return rows[0] if rows else None

    def delete_bind_code(self, code: str) -> None:
        self._execute("DELETE FROM bind_codes WHERE code = ?", (code,))

    def delete_expired_bind_codes(self) -> None:
        self._execute("DELETE FROM bind_codes WHERE expires_at < ?", (int(time.time()),))

    # ---- 账号合并 ----
    def transfer_subscriptions(self, from_user_id: int, to_user_id: int) -> None:
        """把源账号的订阅合并到目标账号；同一大V保留更全的订阅类型。

        用于机器人账号绑定网页账号后的合并，避免「回复/帖子+回复」被降级成「帖子」。
        """
        if from_user_id == to_user_id:
            return
        with self._lock:
            try:
                self._conn.execute("BEGIN")
                rows = self._conn.execute(
                    "SELECT kol_id, type FROM subscriptions WHERE user_id = ?",
                    (from_user_id,),
                ).fetchall()
                for row in rows:
                    existing = self._conn.execute(
                        "SELECT type FROM subscriptions WHERE user_id = ? AND kol_id = ?",
                        (to_user_id, row["kol_id"]),
                    ).fetchone()
                    if existing is None:
                        self._conn.execute(
                            "INSERT INTO subscriptions (user_id, kol_id, type) VALUES (?, ?, ?)",
                            (to_user_id, row["kol_id"], row["type"] or "post"),
                        )
                    else:
                        merged = _merge_sub_types(row["type"], existing["type"])
                        self._conn.execute(
                            "UPDATE subscriptions SET type = ? WHERE user_id = ? AND kol_id = ?",
                            (merged, to_user_id, row["kol_id"]),
                        )
                self._conn.execute(
                    "DELETE FROM subscriptions WHERE user_id = ?", (from_user_id,)
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def delete_user(self, user_id: int) -> None:
        self._execute("DELETE FROM bind_codes WHERE user_id = ?", (user_id,))
        self._execute("DELETE FROM subscriptions WHERE user_id = ?", (user_id,))
        self._execute("DELETE FROM users WHERE id = ?", (user_id,))

    # ---- Post ----
    def post_exists(self, platform: str, external_id: str) -> bool:
        rows = self._rows(
            "SELECT id FROM posts WHERE platform = ? AND external_id = ?",
            (platform, external_id),
        )
        return bool(rows)

    def get_post_id(self, platform: str, external_id: str) -> int | None:
        rows = self._rows(
            "SELECT id FROM posts WHERE platform = ? AND external_id = ?",
            (platform, external_id),
        )
        return rows[0]["id"] if rows else None

    def get_post(self, post_id: int) -> dict | None:
        rows = self._rows(
            "SELECT p.*, k.name AS kol_name, k.platform AS kol_platform "
            "FROM posts p JOIN kols k ON k.id = p.kol_id WHERE p.id = ?",
            (post_id,),
        )
        return rows[0] if rows else None

    def insert_post(
        self,
        platform,
        kol_id,
        external_id,
        title,
        content,
        url,
        published_at,
        post_type: str = "",
        detail: dict | None = None,
    ) -> int | None:
        if self.post_exists(platform, external_id):
            return None
        detail_json = json.dumps(detail, ensure_ascii=False) if detail else ""
        try:
            return self._execute(
                "INSERT INTO posts (platform, kol_id, external_id, title, content, post_type, url, published_at, detail) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    platform,
                    kol_id,
                    external_id,
                    title,
                    content,
                    post_type,
                    url,
                    published_at,
                    detail_json,
                ),
            )
        except sqlite3.IntegrityError:
            return None  # 并发下重复插入，视为已存在

    def list_posts(
        self,
        limit: int = 100,
        platform: str | None = None,
        kol_id: int | None = None,
        q: str | None = None,
    ) -> list[dict]:
        sql = (
            "SELECT p.*, k.name AS kol_name, k.category_id AS category_id, "
            "k.avatar_url AS avatar_url, c.name AS category_name FROM posts p "
            "JOIN kols k ON k.id = p.kol_id "
            "LEFT JOIN categories c ON c.id = k.category_id"
        )
        conds, params = [], []
        if platform:
            conds.append("p.platform = ?")
            params.append(platform)
        if kol_id:
            conds.append("p.kol_id = ?")
            params.append(kol_id)
        if q:
            escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conds.append("(p.title LIKE ? ESCAPE '\\' OR p.content LIKE ? ESCAPE '\\')")
            like = f"%{escaped}%"
            params.extend([like, like])
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY p.id DESC LIMIT ?"
        params.append(limit)
        return self._rows(sql, params)

    def count_posts(self) -> int:
        rows = self._rows("SELECT COUNT(*) AS n FROM posts")
        return rows[0]["n"]

    def delete_push_logs_older_than(self, days: int) -> int:
        """删除超过 N 天的推送日志，返回删除条数（帖子保留期之外的独立清理）。"""
        if days <= 0:
            return 0
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM push_logs WHERE created_at < datetime('now', ?)",
                (f"-{days} days",),
            )
            self._conn.commit()
            return cur.rowcount

    def delete_posts_older_than(self, days: int) -> int:
        """删除超过 N 天的帖子及其推送记录，返回删除条数。"""
        if days <= 0:
            return 0
        rows = self._rows(
            "SELECT id FROM posts WHERE fetched_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        ids = [row["id"] for row in rows]
        if not ids:
            return 0
        placeholders = ", ".join("?" * len(ids))
        self._execute(f"DELETE FROM push_logs WHERE post_id IN ({placeholders})", ids)
        self._execute(f"DELETE FROM posts WHERE id IN ({placeholders})", ids)
        return len(ids)

    def list_feed_posts(self, kol_ids: list[int], limit: int = 100) -> list[dict]:
        if not kol_ids:
            return []
        placeholders = ", ".join("?" * len(kol_ids))
        return self._rows(
            "SELECT p.*, k.name AS kol_name, k.category_id AS category_id, "
            "k.avatar_url AS avatar_url, c.name AS category_name FROM posts p "
            "JOIN kols k ON k.id = p.kol_id "
            "LEFT JOIN categories c ON c.id = k.category_id "
            f"WHERE p.kol_id IN ({placeholders}) ORDER BY p.id DESC LIMIT ?",
            (*kol_ids, limit),
        )

    def list_daily_posts(self, kol_ids: list[int], since_ts: int, limit: int = 15) -> list[dict]:
        """用户订阅大V在 since_ts（本地零点）之后的帖子，用于每日精选。"""
        if not kol_ids:
            return []
        placeholders = ", ".join("?" * len(kol_ids))
        return self._rows(
            "SELECT p.*, k.name AS kol_name, k.avatar_url AS avatar_url, "
            "c.name AS category_name FROM posts p "
            "JOIN kols k ON k.id = p.kol_id "
            "LEFT JOIN categories c ON c.id = k.category_id "
            f"WHERE p.kol_id IN ({placeholders}) AND strftime('%s', p.fetched_at) >= ? "
            "ORDER BY p.id DESC LIMIT ?",
            (*kol_ids, since_ts, limit),
        )

    def daily_report_users(self) -> list[dict]:
        """开启每日精选、启用通知且绑定过渠道的用户。"""
        return self._rows(
            "SELECT * FROM users WHERE notify_enabled = 1 AND daily_report = 1 "
            "AND (telegram_chat_id != '' OR feishu_open_id != '' OR feishu_chat_id != '' "
            "OR wecom_webhook != '')"
        )

    # ---- Push log ----
    def add_push_log(self, post_id: int, channel: str, status: str, error: str = "", user_id: int | None = None) -> int:
        return self._execute(
            "INSERT INTO push_logs (post_id, channel, status, error, user_id) VALUES (?, ?, ?, ?, ?)",
            (post_id, channel, status, error, user_id),
        )

    def list_push_logs(
        self,
        limit: int = 100,
        user_id: int | None = None,
        channel: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        conds, params = [], []
        if user_id is not None:
            conds.append("l.user_id = ?")
            params.append(user_id)
        if channel:
            conds.append("l.channel = ?")
            params.append(channel)
        if status:
            conds.append("l.status = ?")
            params.append(status)
        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        return self._rows(
            "SELECT l.*, p.title, k.name AS kol_name, u.username AS user_name FROM push_logs l "
            "JOIN posts p ON p.id = l.post_id "
            "JOIN kols k ON k.id = p.kol_id "
            "LEFT JOIN users u ON u.id = l.user_id "
            f"{where} ORDER BY l.id DESC LIMIT ?",
            (*params, limit),
        )

    def list_failed_push_logs(self, since_hours: int = 24, limit: int = 200) -> list[dict]:
        """最近 N 小时内失败的推送记录（用于重启后恢复重推）。"""
        return self._rows(
            "SELECT post_id, channel, user_id FROM push_logs "
            "WHERE status = 'failed' AND created_at >= datetime('now', ?) "
            "ORDER BY id DESC LIMIT ?",
            (f"-{since_hours} hours", limit),
        )

    def mark_failed_push_success(self, post_id: int, channel: str, user_id: int | None) -> None:
        """把最近一条失败推送标记为成功（重试成功后）。"""
        if user_id is not None:
            self._execute(
                "UPDATE push_logs SET status = 'success', error = '' WHERE id = ("
                "SELECT id FROM push_logs WHERE post_id = ? AND channel = ? "
                "AND user_id = ? AND status = 'failed' ORDER BY id DESC LIMIT 1)",
                (post_id, channel, user_id),
            )
        else:
            self._execute(
                "UPDATE push_logs SET status = 'success', error = '' WHERE id = ("
                "SELECT id FROM push_logs WHERE post_id = ? AND channel = ? "
                "AND user_id IS NULL AND status = 'failed' ORDER BY id DESC LIMIT 1)",
                (post_id, channel),
            )

    # ---- Settings ----
    def get_setting(self, key: str) -> str | None:
        rows = self._rows("SELECT value FROM settings WHERE key = ?", (key,))
        return rows[0]["value"] if rows else None

    def set_setting(self, key: str, value: str) -> None:
        self._execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
