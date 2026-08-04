"""SQLite 持久化：KOL、帖子（去重）、推送日志。"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

_UNSET = object()


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
    enabled INTEGER NOT NULL DEFAULT 1,
    category_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS posts (
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
    telegram_chat_id TEXT NOT NULL DEFAULT '',
    feishu_open_id TEXT NOT NULL DEFAULT '',
    notify_enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    kol_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, kol_id)
);
"""

ALLOWED_PLATFORMS = {"xueqiu", "weibo", "twitter"}


class DB:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self):
        cols = {row["name"] for row in self._rows("PRAGMA table_info(kols)")}
        if "category_id" not in cols:
            self._conn.execute("ALTER TABLE kols ADD COLUMN category_id INTEGER")
        push_cols = {row["name"] for row in self._rows("PRAGMA table_info(push_logs)")}
        if "user_id" not in push_cols:
            self._conn.execute("ALTER TABLE push_logs ADD COLUMN user_id INTEGER")

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
    def add_kol(self, platform: str, name: str, external_id: str, category_id: int | None = None) -> int:
        if platform not in ALLOWED_PLATFORMS:
            raise ValueError(f"不支持的平台: {platform}")
        return self._execute(
            "INSERT INTO kols (platform, name, external_id, category_id) VALUES (?, ?, ?, ?)",
            (platform, name, external_id, category_id),
        )

    def get_kol(self, kol_id: int) -> dict | None:
        rows = self._rows(
            "SELECT k.*, c.name AS category_name FROM kols k "
            "LEFT JOIN categories c ON c.id = k.category_id WHERE k.id = ?",
            (kol_id,),
        )
        return rows[0] if rows else None

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

    def update_kol(self, kol_id: int, name=None, external_id=None, enabled=None, category_id=_UNSET):
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
        if category_id is not _UNSET:
            sets.append("category_id = ?")
            params.append(category_id)
        if not sets:
            return
        params.append(kol_id)
        self._execute(f"UPDATE kols SET {', '.join(sets)} WHERE id = ?", params)

    def delete_kol(self, kol_id: int):
        self._execute("DELETE FROM kols WHERE id = ?", (kol_id,))

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
        notify_enabled: bool = True,
    ) -> int:
        try:
            return self._execute(
                "INSERT INTO users (username, password_hash, is_admin, telegram_chat_id, "
                "feishu_open_id, notify_enabled) VALUES (?, ?, ?, ?, ?, ?)",
                (username, password_hash, 1 if is_admin else 0, telegram_chat_id, feishu_open_id,
                 1 if notify_enabled else 0),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f"用户名已存在: {username}") from None

    def update_user(self, user_id: int, **kwargs) -> None:
        sets, params = [], []
        for key, value in kwargs.items():
            if key == "is_admin":
                value = 1 if value else 0
            elif key == "notify_enabled":
                value = 1 if value else 0
            sets.append(f"{key} = ?")
            params.append(value)
        if not sets:
            return
        params.append(user_id)
        self._execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", params)

    def list_users(self) -> list[dict]:
        return self._rows("SELECT * FROM users ORDER BY id")

    # ---- Subscription ----
    def add_subscription(self, user_id: int, kol_id: int) -> bool:
        try:
            self._execute(
                "INSERT INTO subscriptions (user_id, kol_id) VALUES (?, ?)",
                (user_id, kol_id),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def remove_subscription(self, user_id: int, kol_id: int) -> None:
        self._execute(
            "DELETE FROM subscriptions WHERE user_id = ? AND kol_id = ?",
            (user_id, kol_id),
        )

    def list_subscriptions(self, user_id: int) -> list[dict]:
        return self._rows(
            "SELECT k.*, c.name AS category_name, s.created_at AS subscribed_at "
            "FROM subscriptions s JOIN kols k ON k.id = s.kol_id "
            "LEFT JOIN categories c ON c.id = k.category_id "
            "WHERE s.user_id = ? ORDER BY s.id",
            (user_id,),
        )

    def subscribed_kol_ids(self, user_id: int) -> set[int]:
        rows = self._rows("SELECT kol_id FROM subscriptions WHERE user_id = ?", (user_id,))
        return {row["kol_id"] for row in rows}

    def subscribers_of_kol(self, kol_id: int) -> list[dict]:
        """该大V的订阅者（启用通知且绑定了渠道的用户）。"""
        return self._rows(
            "SELECT u.* FROM subscriptions s JOIN users u ON u.id = s.user_id "
            "WHERE s.kol_id = ? AND u.notify_enabled = 1 "
            "AND (u.telegram_chat_id != '' OR u.feishu_open_id != '')",
            (kol_id,),
        )

    # ---- Post ----
    def post_exists(self, platform: str, external_id: str) -> bool:
        rows = self._rows(
            "SELECT id FROM posts WHERE platform = ? AND external_id = ?",
            (platform, external_id),
        )
        return bool(rows)

    def insert_post(self, platform, kol_id, external_id, title, content, url, published_at) -> int | None:
        if self.post_exists(platform, external_id):
            return None
        return self._execute(
            "INSERT INTO posts (platform, kol_id, external_id, title, content, url, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (platform, kol_id, external_id, title, content, url, published_at),
        )

    def list_posts(self, limit: int = 100, platform: str | None = None, kol_id: int | None = None) -> list[dict]:
        sql = (
            "SELECT p.*, k.name AS kol_name, k.category_id AS category_id, "
            "c.name AS category_name FROM posts p "
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
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY p.id DESC LIMIT ?"
        params.append(limit)
        return self._rows(sql, params)

    def list_feed_posts(self, kol_ids: list[int], limit: int = 100) -> list[dict]:
        if not kol_ids:
            return []
        placeholders = ", ".join("?" * len(kol_ids))
        return self._rows(
            "SELECT p.*, k.name AS kol_name, k.category_id AS category_id, "
            "c.name AS category_name FROM posts p "
            "JOIN kols k ON k.id = p.kol_id "
            "LEFT JOIN categories c ON c.id = k.category_id "
            f"WHERE p.kol_id IN ({placeholders}) ORDER BY p.id DESC LIMIT ?",
            (*kol_ids, limit),
        )

    # ---- Push log ----
    def add_push_log(self, post_id: int, channel: str, status: str, error: str = "", user_id: int | None = None) -> int:
        return self._execute(
            "INSERT INTO push_logs (post_id, channel, status, error, user_id) VALUES (?, ?, ?, ?, ?)",
            (post_id, channel, status, error, user_id),
        )

    def list_push_logs(self, limit: int = 100) -> list[dict]:
        return self._rows(
            "SELECT l.*, p.title, k.name AS kol_name, u.username AS user_name FROM push_logs l "
            "JOIN posts p ON p.id = l.post_id "
            "JOIN kols k ON k.id = p.kol_id "
            "LEFT JOIN users u ON u.id = l.user_id "
            "ORDER BY l.id DESC LIMIT ?",
            (limit,),
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
