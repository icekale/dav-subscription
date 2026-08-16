"""SQLite 持久化：KOL、帖子（去重）、推送日志。"""
from __future__ import annotations

import json
import secrets
import shutil
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


def _to_int(value) -> int:
    """COUNT/SUM 等聚合结果转 int，None/非数字兜底为 0。"""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


# 布尔字段的显式真值集合：字符串 "false"/"0"/"" 不应被 Python 的 truthy 误判为真
_TRUE_VALUES = {"1", "true", "yes", "on"}


def _to_bool(value) -> int:
    """把任意输入归一化为 0/1：字符串按显式真值集合判断，其余按布尔语义。"""
    if isinstance(value, str):
        return 1 if value.strip().lower() in _TRUE_VALUES else 0
    return 1 if value else 0


def _user_has_channel_sql(alias: str = "") -> str:
    """用户已绑定任一推送渠道（含飞书个人机器人 active + chat_id）。"""
    p = f"{alias}." if alias else ""
    uid = f"{alias}.id" if alias else "id"
    return (
        f"({p}telegram_chat_id != '' OR {p}feishu_open_id != '' OR {p}feishu_chat_id != '' "
        f"OR {p}wecom_webhook != '' OR {p}bark_key != '' "
        f"OR EXISTS (SELECT 1 FROM feishu_personal_bots b "
        f"WHERE b.user_id = {uid} AND b.status = 'active' AND b.chat_id != ''))"
    )


def _normalize_post_images(rows: list[dict]) -> list[dict]:
    """posts 行的 images 是 JSON 文本，API 场景统一解析为数组。"""
    for row in rows:
        raw = row.get("images")
        if isinstance(raw, list):
            continue
        if isinstance(raw, str) and raw:
            try:
                parsed = json.loads(raw)
                row["images"] = parsed if isinstance(parsed, list) else []
            except (TypeError, ValueError):
                row["images"] = []
        else:
            row["images"] = []
    return rows


def _normalize_post_tags(rows: list[dict]) -> list[dict]:
    """posts 行的 tags 是 JSON 数组文本（LLM 打标结果），统一解析为列表。"""
    for row in rows:
        raw = row.get("tags")
        if isinstance(raw, list):
            continue
        if isinstance(raw, str) and raw:
            try:
                parsed = json.loads(raw)
                row["tags"] = parsed if isinstance(parsed, list) else []
            except (TypeError, ValueError):
                row["tags"] = []
        else:
            row["tags"] = []
    return rows


# 贴文规则打标的默认词表（标签 + 关键词，管理员可在后台改，存 settings 表 tag_vocabulary）。
# 关键词做子串匹配：任一命中即给该标签；英文关键词打标时统一小写比较，故此处可混用大小写。
DEFAULT_TAG_RULES = [
    {"tag": "宏观", "keywords": ["央行", "降息", "加息", "GDP", "通胀", "CPI", "PPI", "利率", "美联储", "货币政策", "汇率"]},
    {"tag": "大盘", "keywords": ["A股", "沪指", "上证", "深成指", "创业板指", "大盘", "指数", "两市", "涨停", "跌停", "成交量"]},
    {"tag": "板块", "keywords": ["板块", "概念股", "半导体", "新能源", "光伏", "锂电", "白酒", "券商", "地产", "汽车"]},
    {"tag": "个股", "keywords": ["个股", "股价", "买入", "卖出", "目标价", "重仓", "持仓", "业绩", "市盈率", "PE"]},
    {"tag": "科技", "keywords": ["AI", "人工智能", "芯片", "大模型", "OpenAI", "英伟达", "NVIDIA", "算力", "机器人", "半导体设备", "GPU"]},
    {"tag": "政策", "keywords": ["政策", "监管", "证监会", "国务院", "发改委", "央行行长", "降准", "专项债", "限购", "补贴"]},
    {"tag": "财报", "keywords": ["财报", "季报", "年报", "营收", "净利润", "EPS", "毛利率", "分红", "回购", "指引"]},
    {"tag": "公告", "keywords": ["公告", "停牌", "复牌", "减持", "增持", "重组", "要约收购", "重大合同", "诉讼", "立案"]},
    {"tag": "资讯", "keywords": ["消息", "传闻", "报道", "据悉", "知情人士", "来源", "表示", "称", "透露"]},
]
TAG_VOCABULARY_KEY = "tag_vocabulary"

# 常用股票名表：纯文字提及（无 $标记$）时按名称子串匹配打股票标签。
# 管理员可在后台增删；$股票名(代码)$ 标记会自动识别、无需在此登记。
DEFAULT_STOCK_NAMES = [
    "贵州茅台", "宁德时代", "比亚迪", "中芯国际", "英伟达", "台积电", "三星",
    "SK海力士", "长鑫", "中船特气", "神火", "云铝", "中际旭创", "药明康德",
    "恒瑞医药", "招商银行", "中国平安", "茅台", "腾讯", "阿里", "小米",
    "华为", "赛力斯", "理想", "蔚来", "小鹏", "隆基", "通威", "阳光电源",
    "京东方", "立讯精密", "海康威视", "紫光国微", "兆易创新", "寒武纪",
]
STOCK_NAMES_KEY = "stock_names"

# 黑话别名表：LLM 每日自动识别（settings 键 stock_aliases），结构为
# [{"alias": "宁王", "stock": "宁德时代"}, ...]；打标时命中别名输出正式名。
STOCK_ALIASES_KEY = "stock_aliases"


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
    avatar_source TEXT NOT NULL DEFAULT '',
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
    images TEXT NOT NULL DEFAULT '',
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
CREATE TABLE IF NOT EXISTS error_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL,
    logger TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS daily_report_deliveries (
    user_id INTEGER NOT NULL,
    report_date TEXT NOT NULL,
    channel TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, report_date, channel)
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
    push_channels TEXT NOT NULL DEFAULT '',
    dnd_start TEXT NOT NULL DEFAULT '',
    dnd_end TEXT NOT NULL DEFAULT '',
    dnd_allow_favorite INTEGER NOT NULL DEFAULT 0,
    token_version INTEGER NOT NULL DEFAULT 0,
    last_login_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    kol_id INTEGER NOT NULL,
    type TEXT NOT NULL DEFAULT 'post',
    favorite INTEGER NOT NULL DEFAULT 0,
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
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    batch_id TEXT NOT NULL DEFAULT '',
    expires_at TEXT,
    revoked_at TEXT,
    created_by INTEGER
);
CREATE TABLE IF NOT EXISTS admin_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS source_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    ok_count INTEGER NOT NULL DEFAULT 0,
    fail_count INTEGER NOT NULL DEFAULT 0
);

-- 雪球组合快照：quote（实时净值/涨跌）、holdings（当前持仓）、nav（净值序列）
-- 抓取端定时写入（TTL 内不重复请求），API 端只读，页面展示不依赖雪球在线
CREATE TABLE IF NOT EXISTS cube_snapshots (
    kol_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (kol_id, kind)
);

-- 飞书个人机器人（扫码自动创建的应用，纯推送、共享回退）
CREATE TABLE IF NOT EXISTS feishu_personal_bots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER UNIQUE NOT NULL,
    app_id TEXT UNIQUE NOT NULL,
    app_secret_ciphertext TEXT NOT NULL,
    open_id TEXT NOT NULL DEFAULT '',
    chat_id TEXT NOT NULL DEFAULT '',
    tenant_brand TEXT NOT NULL DEFAULT 'feishu',
    status TEXT NOT NULL,
    last_error TEXT NOT NULL DEFAULT '',
    verified_at TEXT,
    last_success_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_fpb_status ON feishu_personal_bots(status);
-- 飞书个人机器人扫码注册会话（同一用户同时只有一个未结束会话）
CREATE TABLE IF NOT EXISTS feishu_registration_sessions (
    session_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    device_code_ciphertext TEXT NOT NULL,
    registration_base_url TEXT NOT NULL,
    verification_uri TEXT NOT NULL,
    candidate_app_id TEXT NOT NULL DEFAULT '',
    candidate_app_secret_ciphertext TEXT NOT NULL DEFAULT '',
    candidate_tenant_brand TEXT NOT NULL DEFAULT 'feishu',
    expected_open_id TEXT NOT NULL DEFAULT '',
    bind_code_hash TEXT NOT NULL DEFAULT '',
    bind_code_expires_at INTEGER,
    session_expires_at INTEGER NOT NULL,
    poll_interval INTEGER NOT NULL,
    status TEXT NOT NULL,
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_frs_user ON feishu_registration_sessions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_frs_status ON feishu_registration_sessions(status);

-- 性能索引：帖子/日志/订阅按数据量增长后的高频查询
CREATE INDEX IF NOT EXISTS idx_posts_kol_id ON posts(kol_id);
CREATE INDEX IF NOT EXISTS idx_posts_fetched_at ON posts(fetched_at);
CREATE INDEX IF NOT EXISTS idx_push_logs_created_at ON push_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_push_logs_post_id ON push_logs(post_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_kol_id ON subscriptions(kol_id);
CREATE INDEX IF NOT EXISTS idx_source_events_platform ON source_events(platform, created_at);
"""

ALLOWED_PLATFORMS = {"xueqiu", "combination", "weibo", "twitter"}


class DB:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._open_unlocked()
        self._migrate()
        self._conn.commit()

    def _open_unlocked(self) -> None:
        """建立连接。调用方须已持有 _lock，或处于 __init__ 的单线程窗口。"""
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=0)
        if self.path != ":memory:":
            Path(self.path).chmod(0o600)
        self._conn.row_factory = sqlite3.Row
        # 并发写（多 worker/健康检查脚本）时等待而非直接报错
        self._conn.execute("PRAGMA busy_timeout = 5000")
        # Docker 里 /data 是 virtiofs 挂载，WAL 的共享内存映射不可靠（会出现
        # wal/shm 被删除后写入丢失的问题），统一用回滚日志模式，跨进程读写一致。
        self._conn.execute("PRAGMA journal_mode=DELETE")
        self._conn.executescript(SCHEMA)

    def online_backup(self, target: str | Path) -> None:
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            dst = sqlite3.connect(str(target))
            try:
                with dst:
                    self._conn.backup(dst)
            finally:
                dst.close()

    def reopen(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            self._open_unlocked()
        self._migrate()
        with self._lock:
            self._conn.commit()

    def replace_database(self, candidate: str | Path) -> None:
        """关闭连接，用 candidate 覆盖库文件后重新打开。调用方负责失败回滚。"""
        path = Path(self.path)
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            shutil.copy2(candidate, path)
            Path(str(path) + "-wal").unlink(missing_ok=True)
            Path(str(path) + "-shm").unlink(missing_ok=True)
            self._open_unlocked()
        self._migrate()
        with self._lock:
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
        if "images" not in post_cols:
            self._conn.execute(
                "ALTER TABLE posts ADD COLUMN images TEXT NOT NULL DEFAULT ''"
            )
        if "tags" not in post_cols:
            self._conn.execute(
                "ALTER TABLE posts ADD COLUMN tags TEXT NOT NULL DEFAULT ''"
            )
        sub_cols = {row["name"] for row in self._rows("PRAGMA table_info(subscriptions)")}
        if "type" not in sub_cols:
            self._conn.execute(
                "ALTER TABLE subscriptions ADD COLUMN type TEXT NOT NULL DEFAULT 'post'"
            )
        if "favorite" not in sub_cols:
            self._conn.execute(
                "ALTER TABLE subscriptions ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0"
            )
        if "secondary" not in sub_cols:
            self._conn.execute(
                "ALTER TABLE subscriptions ADD COLUMN secondary INTEGER NOT NULL DEFAULT 0"
            )
        cols = {row["name"] for row in self._rows("PRAGMA table_info(kols)")}
        if "category_id" not in cols:
            self._conn.execute("ALTER TABLE kols ADD COLUMN category_id INTEGER")
        if "secondary" not in cols:
            self._conn.execute("ALTER TABLE kols ADD COLUMN secondary INTEGER NOT NULL DEFAULT 0")
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
        if "push_channels" not in user_cols:
            self._conn.execute("ALTER TABLE users ADD COLUMN push_channels TEXT NOT NULL DEFAULT ''")
        if "dnd_start" not in user_cols:
            self._conn.execute("ALTER TABLE users ADD COLUMN dnd_start TEXT NOT NULL DEFAULT ''")
        if "dnd_end" not in user_cols:
            self._conn.execute("ALTER TABLE users ADD COLUMN dnd_end TEXT NOT NULL DEFAULT ''")
        if "dnd_allow_favorite" not in user_cols:
            self._conn.execute(
                "ALTER TABLE users ADD COLUMN dnd_allow_favorite INTEGER NOT NULL DEFAULT 0"
            )
        if "wecom_webhook" not in user_cols:
            self._conn.execute("ALTER TABLE users ADD COLUMN wecom_webhook TEXT NOT NULL DEFAULT ''")
        if "telegram_bot_token" not in user_cols:
            self._conn.execute("ALTER TABLE users ADD COLUMN telegram_bot_token TEXT NOT NULL DEFAULT ''")
        if "feed_token" not in user_cols:
            self._conn.execute("ALTER TABLE users ADD COLUMN feed_token TEXT NOT NULL DEFAULT ''")
        if "bark_key" not in user_cols:
            self._conn.execute("ALTER TABLE users ADD COLUMN bark_key TEXT NOT NULL DEFAULT ''")
        if "llm_api_base" not in user_cols:
            self._conn.execute("ALTER TABLE users ADD COLUMN llm_api_base TEXT NOT NULL DEFAULT ''")
        if "llm_api_key" not in user_cols:
            self._conn.execute("ALTER TABLE users ADD COLUMN llm_api_key TEXT NOT NULL DEFAULT ''")
        if "llm_model" not in user_cols:
            self._conn.execute("ALTER TABLE users ADD COLUMN llm_model TEXT NOT NULL DEFAULT ''")
        if "token_version" not in user_cols:
            self._conn.execute("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0")
        if "last_login_at" not in user_cols:
            self._conn.execute("ALTER TABLE users ADD COLUMN last_login_at TEXT")
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_feed_token "
            "ON users(feed_token) WHERE feed_token != ''"
        )
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_bark_key "
            "ON users(bark_key) WHERE bark_key != ''"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS user_keywords ("
            "  user_id INTEGER NOT NULL,"
            "  keyword TEXT NOT NULL,"
            "  created_at TEXT NOT NULL DEFAULT (datetime('now')),"
            "  UNIQUE (user_id, keyword)"
            ")"
        )
        kol_cols = {row["name"] for row in self._rows("PRAGMA table_info(kols)")}
        if "priority" not in kol_cols:
            self._conn.execute("ALTER TABLE kols ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")
        if "is_private" not in kol_cols:
            self._conn.execute("ALTER TABLE kols ADD COLUMN is_private INTEGER NOT NULL DEFAULT 0")
        if "avatar_url" not in kol_cols:
            self._conn.execute("ALTER TABLE kols ADD COLUMN avatar_url TEXT NOT NULL DEFAULT ''")
        if "avatar_source" not in kol_cols:
            self._conn.execute("ALTER TABLE kols ADD COLUMN avatar_source TEXT NOT NULL DEFAULT ''")
        if "original_only" not in kol_cols:
            self._conn.execute("ALTER TABLE kols ADD COLUMN original_only INTEGER NOT NULL DEFAULT 0")
        if "baseline_ready" not in kol_cols:
            # 1=已建首次抓取基线（存量默认 1，升级后新帖照常推送）；0=新大V待首轮建基线
            self._conn.execute(
                "ALTER TABLE kols ADD COLUMN baseline_ready INTEGER NOT NULL DEFAULT 1"
            )
        ev_cols = {row["name"] for row in self._rows("PRAGMA table_info(source_events)")}
        if "ok_count" not in ev_cols:
            self._conn.execute(
                "ALTER TABLE source_events ADD COLUMN ok_count INTEGER NOT NULL DEFAULT 0"
            )
        if "fail_count" not in ev_cols:
            self._conn.execute(
                "ALTER TABLE source_events ADD COLUMN fail_count INTEGER NOT NULL DEFAULT 0"
            )
        rc_cols = {row["name"] for row in self._rows("PRAGMA table_info(register_codes)")}
        if "batch_id" not in rc_cols:
            self._conn.execute(
                "ALTER TABLE register_codes ADD COLUMN batch_id TEXT NOT NULL DEFAULT ''"
            )
        if "expires_at" not in rc_cols:
            self._conn.execute("ALTER TABLE register_codes ADD COLUMN expires_at TEXT")
        if "revoked_at" not in rc_cols:
            self._conn.execute("ALTER TABLE register_codes ADD COLUMN revoked_at TEXT")
        if "created_by" not in rc_cols:
            self._conn.execute("ALTER TABLE register_codes ADD COLUMN created_by INTEGER")
        for row in self._rows("SELECT code FROM register_codes WHERE batch_id = ''"):
            self._conn.execute(
                "UPDATE register_codes SET batch_id = ? WHERE code = ?",
                (secrets.token_hex(8), row["code"]),
            )
        # 并发创建的历史重复项先合并/收口，再由数据库唯一索引兜底。
        duplicates = self._rows(
            "SELECT platform, external_id, MIN(id) AS keep_id FROM kols "
            "GROUP BY platform, external_id HAVING COUNT(*) > 1"
        )
        for group in duplicates:
            keep_id = group["keep_id"]
            duplicate_ids = [
                r["id"] for r in self._rows(
                    "SELECT id FROM kols WHERE platform = ? AND external_id = ? AND id != ?",
                    (group["platform"], group["external_id"], keep_id),
                )
            ]
            for duplicate_id in duplicate_ids:
                for subscription in self._rows(
                    "SELECT user_id, type, favorite, secondary FROM subscriptions WHERE kol_id = ?",
                    (duplicate_id,),
                ):
                    existing_rows = self._rows(
                        "SELECT type, favorite, secondary FROM subscriptions "
                        "WHERE user_id = ? AND kol_id = ?",
                        (subscription["user_id"], keep_id),
                    )
                    existing = existing_rows[0] if existing_rows else None
                    if existing:
                        subscribe_type = (
                            existing["type"]
                            if existing["type"] == subscription["type"]
                            else "both"
                        )
                        self._conn.execute(
                            "UPDATE subscriptions SET type = ?, favorite = ?, secondary = ? "
                            "WHERE user_id = ? AND kol_id = ?",
                            (
                                subscribe_type,
                                max(existing["favorite"], subscription["favorite"]),
                                max(existing["secondary"], subscription["secondary"]),
                                subscription["user_id"],
                                keep_id,
                            ),
                        )
                    else:
                        self._conn.execute(
                            "INSERT INTO subscriptions "
                            "(user_id, kol_id, type, favorite, secondary) VALUES (?, ?, ?, ?, ?)",
                            (
                                subscription["user_id"],
                                keep_id,
                                subscription["type"],
                                subscription["favorite"],
                                subscription["secondary"],
                            ),
                        )
                self._conn.execute("DELETE FROM subscriptions WHERE kol_id = ?", (duplicate_id,))
                self._conn.execute(
                    "INSERT OR IGNORE INTO kol_acl (kol_id, user_id) "
                    "SELECT ?, user_id FROM kol_acl WHERE kol_id = ?",
                    (keep_id, duplicate_id),
                )
                self._conn.execute("DELETE FROM kol_acl WHERE kol_id = ?", (duplicate_id,))
                self._conn.execute("UPDATE posts SET kol_id = ? WHERE kol_id = ?", (keep_id, duplicate_id))
                self._conn.execute(
                    "INSERT OR IGNORE INTO cube_snapshots (kol_id, kind, payload, fetched_at) "
                    "SELECT ?, kind, payload, fetched_at FROM cube_snapshots WHERE kol_id = ?",
                    (keep_id, duplicate_id),
                )
                self._conn.execute("DELETE FROM cube_snapshots WHERE kol_id = ?", (duplicate_id,))
                self._conn.execute("DELETE FROM kols WHERE id = ?", (duplicate_id,))
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_kols_platform_external "
            "ON kols(platform, external_id)"
        )
        pending_duplicates = self._rows(
            "SELECT platform, external_id, MIN(id) AS keep_id FROM kol_requests "
            "WHERE status = 'pending' GROUP BY platform, external_id HAVING COUNT(*) > 1"
        )
        for group in pending_duplicates:
            self._conn.execute(
                "UPDATE kol_requests SET status = 'rejected', handled_at = datetime('now') "
                "WHERE platform = ? AND external_id = ? AND status = 'pending' AND id != ?",
                (group["platform"], group["external_id"], group["keep_id"]),
            )
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_kol_requests_pending "
            "ON kol_requests(platform, external_id) WHERE status = 'pending'"
        )

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
        secondary: bool = False,
        original_only: bool = False,
    ) -> int:
        if platform not in ALLOWED_PLATFORMS:
            raise ValueError(f"不支持的平台: {platform}")
        if self._rows(
            "SELECT id FROM kols WHERE platform = ? AND external_id = ?",
            (platform, external_id),
        ):
            raise ValueError("该大V已存在")
        if priority and secondary:
            secondary = False  # 互斥：priority 优先（与 update_kol 行为一致）
        try:
            return self._execute(
                "INSERT INTO kols (platform, name, external_id, category_id, priority, secondary, original_only, baseline_ready) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                (
                    platform,
                    name,
                    external_id,
                    category_id,
                    1 if priority else 0,
                    1 if secondary else 0,
                    1 if original_only else 0,
                ),
            )
        except sqlite3.IntegrityError:
            raise ValueError("该大V已存在") from None

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

    def update_kol_avatar_source(self, kol_id: int, source: str) -> None:
        self._execute(
            "UPDATE kols SET avatar_source = ? WHERE id = ?",
            (source or "", kol_id),
        )

    def list_kols(
        self,
        platform: str | None = None,
        category_id: int | None = None,
        q: str | None = None,
        status: int | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        """大V列表：可选平台/分类/关键词/启用状态筛选 + 分页（管理列表用）。"""
        sql = "SELECT k.*, c.name AS category_name FROM kols k LEFT JOIN categories c ON c.id = k.category_id"
        conds, params = [], []
        if platform:
            conds.append("k.platform = ?")
            params.append(platform)
        if category_id is not None:
            conds.append("k.category_id = ?")
            params.append(category_id)
        if q:
            like = f"%{q}%"
            conds.append("(k.name LIKE ? OR k.external_id LIKE ?)")
            params.extend([like, like])
        if status is not None:
            conds.append("k.enabled = ?")
            params.append(1 if status else 0)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY k.id"
        if limit:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        return self._rows(sql, params)

    def count_kols(
        self,
        platform: str | None = None,
        category_id: int | None = None,
        q: str | None = None,
        status: int | None = None,
    ) -> int:
        """与 list_kols 同条件的大V总数（分页控件用）。"""
        conds, params = [], []
        if platform:
            conds.append("k.platform = ?")
            params.append(platform)
        if category_id is not None:
            conds.append("k.category_id = ?")
            params.append(category_id)
        if q:
            like = f"%{q}%"
            conds.append("(k.name LIKE ? OR k.external_id LIKE ?)")
            params.extend([like, like])
        if status is not None:
            conds.append("k.enabled = ?")
            params.append(1 if status else 0)
        where = f"WHERE {' AND '.join(conds)}" if conds else ""
        row = self._rows(f"SELECT COUNT(*) AS n FROM kols k {where}", params)
        return _to_int(row[0]["n"]) if row else 0

    def set_kols_enabled(self, ids: list[int], enabled: bool) -> None:
        placeholders = ",".join("?" * len(ids))
        self._execute(
            f"UPDATE kols SET enabled = ? WHERE id IN ({placeholders})",
            (1 if enabled else 0, *ids),
        )

    def set_kols_flag(self, ids: list[int], flag: str, value: bool) -> None:
        """批量设置 priority / secondary 标记。"""
        col = "priority" if flag == "priority" else "secondary"
        placeholders = ",".join("?" * len(ids))
        self._execute(
            f"UPDATE kols SET {col} = ? WHERE id IN ({placeholders})",
            (1 if value else 0, *ids),
        )

    def set_kols_category(self, ids: list[int], category_id: int | None) -> None:
        placeholders = ",".join("?" * len(ids))
        self._execute(
            f"UPDATE kols SET category_id = ? WHERE id IN ({placeholders})",
            (category_id, *ids),
        )

    def get_kol_by_external(self, platform: str, external_id: str) -> dict | None:
        """按平台 + 外部ID 查大V（更新 external_id 时的唯一性校验用）。"""
        rows = self._rows(
            "SELECT * FROM kols WHERE platform = ? AND external_id = ?",
            (platform, external_id),
        )
        return rows[0] if rows else None

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
        secondary=_UNSET,
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
            if priority:
                sets.append("secondary = 0")  # 互斥：优先大V不能同时是次要
        if secondary is not _UNSET:
            sets.append("secondary = ?")
            params.append(1 if secondary else 0)
            if secondary:
                sets.append("priority = 0")  # 互斥：次要大V不能同时是优先
        if is_private is not _UNSET:
            sets.append("is_private = ?")
            params.append(1 if is_private else 0)
        if not sets:
            return
        params.append(kol_id)
        self._execute(f"UPDATE kols SET {', '.join(sets)} WHERE id = ?", params)

    def delete_kol(self, kol_id: int):
        # 级联清理必须作为一个事务，任一步失败都保留完整原状态。
        with self._lock:
            try:
                self._conn.execute("BEGIN")
                self._conn.execute("DELETE FROM kol_acl WHERE kol_id = ?", (kol_id,))
                self._conn.execute("DELETE FROM subscriptions WHERE kol_id = ?", (kol_id,))
                self._conn.execute(
                    "DELETE FROM push_logs WHERE post_id IN (SELECT id FROM posts WHERE kol_id = ?)",
                    (kol_id,),
                )
                self._conn.execute("DELETE FROM posts WHERE kol_id = ?", (kol_id,))
                self._conn.execute("DELETE FROM kols WHERE id = ?", (kol_id,))
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

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
        try:
            return self._execute(
                "INSERT INTO kol_requests (platform, name, external_id, user_id) VALUES (?, ?, ?, ?)",
                (platform, name.strip(), external_id, user_id),
            )
        except sqlite3.IntegrityError:
            raise ValueError("该大V的申请已在处理中") from None

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

    def get_user_by_username_ci(self, username: str) -> dict | None:
        """按用户名查找（不区分大小写），用于注册/改名的唯一性校验。"""
        rows = self._rows(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        )
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

    def get_user_by_bark_key(self, bark_key: str) -> dict | None:
        rows = self._rows("SELECT * FROM users WHERE bark_key = ?", (bark_key,))
        return rows[0] if rows else None

    def get_user_by_feed_token(self, feed_token: str) -> dict | None:
        rows = self._rows("SELECT * FROM users WHERE feed_token = ?", (feed_token,))
        return rows[0] if rows else None

    def ensure_feed_token(self, user_id: int) -> str:
        """返回用户 RSS 订阅 token；没有则生成一个（长随机串，等价订阅凭证）。"""
        user = self.get_user(user_id)
        if user and user.get("feed_token"):
            return user["feed_token"]
        token = secrets.token_urlsafe(32)
        self.update_user(user_id, feed_token=token)
        return token

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
        if self.get_user_by_username_ci(username):
            raise ValueError(f"用户名已存在: {username}")
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

    def touch_last_login(self, user_id: int) -> None:
        self._execute(
            "UPDATE users SET last_login_at = datetime('now') WHERE id = ?",
            (user_id,),
        )

    # update_user 允许写入的字段白名单：拦截任意 key 拼接进 SQL（防注入脚枪）
    _UPDATE_USER_COLUMNS = frozenset({
        "username", "password_hash", "is_admin", "wechat_openid",
        "telegram_chat_id", "telegram_bot_token", "feishu_open_id",
        "feishu_chat_id", "wecom_webhook", "notify_enabled", "daily_report",
        "push_channels", "dnd_start", "dnd_end", "dnd_allow_favorite",
        "feed_token", "bark_key", "llm_api_base", "llm_api_key", "llm_model",
        "token_version", "last_login_at",
    })

    def update_user(self, user_id: int, **kwargs) -> None:
        sets, params = [], []
        for key, value in kwargs.items():
            if key not in self._UPDATE_USER_COLUMNS:
                raise ValueError(f"非法用户字段: {key}")
            # 布尔字段统一归一化为 0/1，避免字符串 "false"/"0" 误判为真
            if key in ("is_admin", "notify_enabled", "daily_report", "dnd_allow_favorite"):
                value = _to_bool(value)
            sets.append(f"{key} = ?")
            params.append(value)
        if not sets:
            return
        params.append(user_id)
        self._execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", params)

    def set_users_notify(self, ids: list[int], enabled: bool) -> int:
        ids = [int(i) for i in ids]
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE users SET notify_enabled = ? WHERE id IN ({placeholders})",
                (1 if enabled else 0, *ids),
            )
            self._conn.commit()
            return cur.rowcount

    def update_user_atomic(
        self,
        user_id: int,
        updates: dict,
        *,
        keywords=_UNSET,
        revoke_tokens: bool = False,
    ) -> None:
        """一次提交用户字段与关键词；密码变更可同时撤销既有 token。"""
        sets, params = [], []
        for key, value in updates.items():
            if key not in self._UPDATE_USER_COLUMNS:
                raise ValueError(f"非法用户字段: {key}")
            if key in ("is_admin", "notify_enabled", "daily_report", "dnd_allow_favorite"):
                value = _to_bool(value)
            sets.append(f"{key} = ?")
            params.append(value)
        if revoke_tokens:
            sets.append("token_version = token_version + 1")
        with self._lock:
            try:
                self._conn.execute("BEGIN")
                if sets:
                    self._conn.execute(
                        f"UPDATE users SET {', '.join(sets)} WHERE id = ?",
                        (*params, user_id),
                    )
                if keywords is not _UNSET:
                    self._conn.execute("DELETE FROM user_keywords WHERE user_id = ?", (user_id,))
                    for keyword in keywords:
                        self._conn.execute(
                            "INSERT INTO user_keywords (user_id, keyword) VALUES (?, ?)",
                            (user_id, keyword),
                        )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def update_user_password(self, user_id: int, password_hash: str) -> None:
        self.update_user_atomic(
            user_id, {"password_hash": password_hash}, revoke_tokens=True
        )

    def list_users(self) -> list[dict]:
        return self._rows("SELECT * FROM users ORDER BY id DESC")

    def subscription_counts(self) -> dict[int, int]:
        return {
            r["user_id"]: r["n"]
            for r in self._rows("SELECT user_id, COUNT(*) AS n FROM subscriptions GROUP BY user_id")
        }

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

    def add_register_code(
        self,
        code: str,
        note: str = "",
        batch_id: str | None = None,
        expires_at: str | None = None,
        created_by: int | None = None,
    ) -> None:
        try:
            self._execute(
                "INSERT INTO register_codes (code, note, batch_id, expires_at, created_by) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    code.strip().upper(),
                    note.strip(),
                    (batch_id or secrets.token_hex(8)).strip(),
                    expires_at or None,
                    created_by,
                ),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f"注册码已存在: {code}") from None

    def list_register_codes(self) -> list[dict]:
        return self._rows(
            "SELECT rc.*, u.username AS used_by_name, c.username AS created_by_name "
            "FROM register_codes rc "
            "LEFT JOIN users u ON u.id = rc.used_by "
            "LEFT JOIN users c ON c.id = rc.created_by "
            "ORDER BY rc.created_at DESC"
        )

    def get_register_code(self, code: str) -> dict | None:
        rows = self._rows(
            "SELECT * FROM register_codes WHERE code = ?", (code.strip().upper(),)
        )
        return rows[0] if rows else None

    def revoke_register_code(self, code: str) -> bool:
        """软作废未使用的码；已使用返回 False。"""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE register_codes SET revoked_at = datetime('now') "
                "WHERE code = ? AND used_by IS NULL AND revoked_at IS NULL",
                (code.strip().upper(),),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def delete_register_code(self, code: str) -> bool:
        """兼容旧名：软作废。"""
        return self.revoke_register_code(code)

    def revoke_unused_in_batch(self, batch_id: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE register_codes SET revoked_at = datetime('now') "
                "WHERE batch_id = ? AND used_by IS NULL AND revoked_at IS NULL",
                (batch_id,),
            )
            self._conn.commit()
            return cur.rowcount

    def purge_register_codes(self, codes: list[str]) -> int:
        codes = [str(c).strip().upper() for c in codes if str(c).strip()]
        if not codes:
            return 0
        placeholders = ",".join("?" * len(codes))
        with self._lock:
            cur = self._conn.execute(
                f"DELETE FROM register_codes WHERE code IN ({placeholders}) AND ("
                "used_by IS NOT NULL OR revoked_at IS NOT NULL OR "
                "(expires_at IS NOT NULL AND expires_at <= datetime('now')))",
                codes,
            )
            self._conn.commit()
            return cur.rowcount

    def update_register_code_note(self, code: str, note: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE register_codes SET note = ? WHERE code = ?",
                (note.strip(), code.strip().upper()),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def register_with_code(self, code: str, username: str, password_hash: str) -> int:
        """凭注册码注册：原子消费可用码 + 创建用户，任一失败整体回滚。"""
        code = code.strip().upper()
        with self._lock:
            try:
                self._conn.execute("BEGIN")
                cur = self._conn.execute(
                    "UPDATE register_codes SET used_at = datetime('now') "
                    "WHERE code = ? AND used_by IS NULL AND revoked_at IS NULL "
                    "AND (expires_at IS NULL OR expires_at > datetime('now'))",
                    (code,),
                )
                if cur.rowcount == 0:
                    row = self._conn.execute(
                        "SELECT used_by, revoked_at, expires_at FROM register_codes WHERE code = ?",
                        (code,),
                    ).fetchone()
                    if row is None or row["used_by"] is not None:
                        raise ValueError("邀请码无效或已被使用")
                    if row["revoked_at"]:
                        raise ValueError("邀请码已作废，请向管理员索取新的")
                    raise ValueError("邀请码已过期，请向管理员索取新的")
                if self._conn.execute(
                    "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
                    (username,),
                ).fetchone():
                    raise ValueError(f"用户名已存在: {username}")
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
                    (uid, code),
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
        rows = self._rows(
            "SELECT k.*, s.type AS subscribe_type, s.favorite AS favorite, "
            "s.secondary AS sub_secondary, "
            "c.name AS category_name, "
            "s.created_at AS subscribed_at "
            "FROM subscriptions s JOIN kols k ON k.id = s.kol_id "
            "LEFT JOIN categories c ON c.id = k.category_id "
            "WHERE s.user_id = ? ORDER BY s.id",
            (user_id,),
        )
        # kols 表也有 secondary（全局次要）列，k.* 会与之同名冲突且 dict(row) 取到全局值；
        # 用别名带回个人次要（覆盖全局列）
        for r in rows:
            r["secondary"] = r.pop("sub_secondary")
        return rows

    def count_subscriptions(self, user_id: int) -> int:
        rows = self._rows(
            "SELECT COUNT(*) AS n FROM subscriptions WHERE user_id = ?", (user_id,)
        )
        return rows[0]["n"]

    def dashboard_stats(self) -> dict:
        """业务数据看板聚合：用户/订阅/帖子/推送/数据源健康（近 N 天窗口用 UTC）。"""
        def scalar(sql: str, *params) -> int:
            return _to_int((self._rows(sql, params) or [{}])[0].get("v"))

        users = {
            "total": scalar("SELECT COUNT(*) AS v FROM users"),
            "admins": scalar("SELECT COUNT(*) AS v FROM users WHERE is_admin = 1"),
            "bound": scalar(
                "SELECT COUNT(*) AS v FROM users WHERE telegram_chat_id != '' OR "
                "feishu_open_id != '' OR feishu_chat_id != '' OR wecom_webhook != '' "
                "OR EXISTS (SELECT 1 FROM feishu_personal_bots b "
                "WHERE b.user_id = users.id AND b.status = 'active' AND b.chat_id != '')"
            ),
            "new_7d": scalar(
                "SELECT COUNT(*) AS v FROM users WHERE created_at >= datetime('now', '-7 days')"
            ),
        }
        subs_total = scalar("SELECT COUNT(*) AS v FROM subscriptions")
        subscriptions = {
            "total": subs_total,
            "favorite": scalar("SELECT COUNT(*) AS v FROM subscriptions WHERE favorite = 1"),
            "avg_per_user": round(subs_total / users["total"], 1) if users["total"] else 0,
        }
        posts = {
            "total": scalar("SELECT COUNT(*) AS v FROM posts"),
            "today": scalar(
                "SELECT COUNT(*) AS v FROM posts WHERE fetched_at >= datetime('now', '-24 hours')"
            ),
            "last_7d": scalar(
                "SELECT COUNT(*) AS v FROM posts WHERE fetched_at >= datetime('now', '-7 days')"
            ),
            "by_platform": {
                r["platform"]: _to_int(r["c"])
                for r in self._rows(
                    "SELECT platform, COUNT(*) AS c FROM posts GROUP BY platform ORDER BY c DESC"
                )
            },
        }
        push_ok = scalar(
            "SELECT COUNT(*) AS v FROM push_logs WHERE status = 'success' "
            "AND created_at >= datetime('now', '-7 days')"
        )
        push_total = scalar(
            "SELECT COUNT(*) AS v FROM push_logs WHERE created_at >= datetime('now', '-7 days')"
        )
        pushes = {
            "total_7d": push_total,
            "ok_7d": push_ok,
            "fail_7d": push_total - push_ok,
            # 无推送时置 None，前端显示 "—"，避免误导性的绿色 100%
            "success_rate": round(push_ok / push_total * 100, 1) if push_total else None,
            "today": scalar(
                "SELECT COUNT(*) AS v FROM push_logs WHERE created_at >= datetime('now', '-24 hours')"
            ),
            "by_channel": {
                r["channel"]: {"total": _to_int(r["c"]), "ok": _to_int(r["ok"])}
                for r in self._rows(
                    "SELECT channel, COUNT(*) AS c, "
                    "SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS ok "
                    "FROM push_logs WHERE created_at >= datetime('now', '-7 days') "
                    "GROUP BY channel ORDER BY c DESC"
                )
            },
            "trend_14d": [
                {"date": r["d"], "pushed": _to_int(r["c"]), "ok": _to_int(r["ok"])}
                for r in self._rows(
                    # 按本地时间分桶显示，与看板事件流一致；窗口边界与其他统计统一用 UTC
                    "SELECT strftime('%Y-%m-%d', created_at, 'localtime') AS d, COUNT(*) AS c, "
                    "SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS ok "
                    "FROM push_logs WHERE created_at >= datetime('now', '-13 days') "
                    "GROUP BY d ORDER BY d"
                )
            ],
        }
        sources_fail_24h = {
            r["platform"]: _to_int(r["c"])
            for r in self._rows(
                "SELECT platform, COUNT(*) AS c FROM source_events "
                "WHERE status != 'ok' AND created_at >= datetime('now', '-24 hours') "
                "GROUP BY platform"
            )
        }
        return {
            "users": users,
            "subscriptions": subscriptions,
            "posts": posts,
            "pushes": pushes,
            "sources_fail_24h": sources_fail_24h,
        }

    def subscribed_kol_ids(self, user_id: int) -> set[int]:
        rows = self._rows("SELECT kol_id FROM subscriptions WHERE user_id = ?", (user_id,))
        return {row["kol_id"] for row in rows}

    def kol_ids_with_subscribers(self) -> set[int]:
        """当前有任何订阅关系的大V id 集合（含关闭通知的订阅者）。

        抓取调度用它跳过无人订阅的大V——没有订阅者就没有推送/阅读对象，
        不值得每轮白耗抓取配额。
        """
        rows = self._rows("SELECT DISTINCT kol_id FROM subscriptions")
        return {row["kol_id"] for row in rows}

    def readable_subscribed_kol_ids(self, user_id: int, is_admin: bool = False) -> set[int]:
        """用户可读的已订阅大V集合：订阅集合 ∩ 可见集合（公开 + ACL 私有大V）。

        内容读取（动态/RSS/每日精选）统一走该集合，权限判断必须在后端完成；
        管理员保留对已订阅私有大V的管理访问语义，不做可见性过滤。
        """
        subscribed = self.subscribed_kol_ids(user_id)
        if is_admin:
            return subscribed
        return subscribed & self.visible_kol_ids(user_id)

    def subscribed_kol_types(self, user_id: int) -> dict[int, str]:
        rows = self._rows(
            "SELECT kol_id, type FROM subscriptions WHERE user_id = ?", (user_id,)
        )
        return {row["kol_id"]: row["type"] for row in rows}

    def subscribers_of_kol(self, kol_id: int) -> list[dict]:
        """该大V的订阅者（启用通知且绑定了渠道的用户）。"""
        return self._rows(
            "SELECT u.*, s.type AS subscribe_type, s.favorite AS favorite, "
            "s.secondary AS secondary FROM subscriptions s "
            "JOIN users u ON u.id = s.user_id "
            "JOIN kols k ON k.id = s.kol_id "
            "WHERE s.kol_id = ? AND u.notify_enabled = 1 "
            f"AND {_user_has_channel_sql('u')} "
            "AND (k.is_private = 0 OR EXISTS "
            "(SELECT 1 FROM kol_acl a WHERE a.kol_id = k.id AND a.user_id = u.id))",
            (kol_id,),
        )

    def get_subscription(self, user_id: int, kol_id: int) -> dict | None:
        """单个订阅记录（type/favorite/secondary），未订阅返回 None。"""
        rows = self._rows(
            "SELECT type, favorite, secondary FROM subscriptions "
            "WHERE user_id = ? AND kol_id = ?",
            (user_id, kol_id),
        )
        return rows[0] if rows else None

    def set_subscription_favorite(self, user_id: int, kol_id: int, favorite: bool) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE subscriptions SET favorite = ? WHERE user_id = ? AND kol_id = ?",
                (1 if favorite else 0, user_id, kol_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def subscribed_favorite_ids(self, user_id: int) -> set[int]:
        rows = self._rows(
            "SELECT kol_id FROM subscriptions WHERE user_id = ? AND favorite = 1",
            (user_id,),
        )
        return {row["kol_id"] for row in rows}

    def set_subscription_secondary(self, user_id: int, kol_id: int, secondary: bool) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE subscriptions SET secondary = ? WHERE user_id = ? AND kol_id = ?",
                (1 if secondary else 0, user_id, kol_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def subscribed_secondary_ids(self, user_id: int) -> set[int]:
        rows = self._rows(
            "SELECT kol_id FROM subscriptions WHERE user_id = ? AND secondary = 1",
            (user_id,),
        )
        return {row["kol_id"] for row in rows}

    def get_user_keywords(self, user_id: int) -> list[str]:
        """用户的关键词提醒规则（命中即穿透免打扰并加急推送）。"""
        rows = self._rows(
            "SELECT keyword FROM user_keywords WHERE user_id = ? ORDER BY rowid", (user_id,)
        )
        return [r["keyword"] for r in rows]

    def set_user_keywords(self, user_id: int, keywords: list[str]) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM user_keywords WHERE user_id = ?", (user_id,))
            for keyword in keywords:
                self._conn.execute(
                    "INSERT INTO user_keywords (user_id, keyword) VALUES (?, ?)",
                    (user_id, keyword),
                )
            self._conn.commit()

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
                    "SELECT kol_id, type, favorite FROM subscriptions WHERE user_id = ?",
                    (from_user_id,),
                ).fetchall()
                for row in rows:
                    existing = self._conn.execute(
                        "SELECT type, favorite FROM subscriptions WHERE user_id = ? AND kol_id = ?",
                        (to_user_id, row["kol_id"]),
                    ).fetchone()
                    if existing is None:
                        self._conn.execute(
                            "INSERT INTO subscriptions (user_id, kol_id, type, favorite) VALUES (?, ?, ?, ?)",
                            (to_user_id, row["kol_id"], row["type"] or "post", row["favorite"]),
                        )
                    else:
                        merged = _merge_sub_types(row["type"], existing["type"])
                        favorite = 1 if (row["favorite"] or existing["favorite"]) else 0
                        self._conn.execute(
                            "UPDATE subscriptions SET type = ?, favorite = ? WHERE user_id = ? AND kol_id = ?",
                            (merged, favorite, to_user_id, row["kol_id"]),
                        )
                self._conn.execute(
                    "DELETE FROM subscriptions WHERE user_id = ?", (from_user_id,)
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def delete_user(self, user_id: int) -> None:
        with self._lock:
            try:
                self._conn.execute("BEGIN")
                self._conn.execute("DELETE FROM bind_codes WHERE user_id = ?", (user_id,))
                self._conn.execute("DELETE FROM subscriptions WHERE user_id = ?", (user_id,))
                self._conn.execute("DELETE FROM push_logs WHERE user_id = ?", (user_id,))
                self._conn.execute("DELETE FROM kol_acl WHERE user_id = ?", (user_id,))
                self._conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # ---- 雪球组合快照 ----
    def set_cube_snapshot(self, kol_id: int, kind: str, payload) -> None:
        """写入/覆盖组合快照（quote/holdings/nav），刷新 fetched_at。"""
        self._execute(
            "INSERT INTO cube_snapshots (kol_id, kind, payload) VALUES (?, ?, ?) "
            "ON CONFLICT(kol_id, kind) DO UPDATE SET "
            "payload = excluded.payload, fetched_at = datetime('now')",
            (kol_id, kind, json.dumps(payload, ensure_ascii=False)),
        )

    def get_cube_snapshot(self, kol_id: int, kind: str) -> dict | None:
        """读组合快照：{"payload": 已解析 JSON, "fetched_at": "YYYY-MM-DD HH:MM:SS"}。"""
        rows = self._rows(
            "SELECT payload, fetched_at FROM cube_snapshots WHERE kol_id = ? AND kind = ?",
            (kol_id, kind),
        )
        if not rows:
            return None
        try:
            payload = json.loads(rows[0]["payload"])
        except (TypeError, ValueError):
            return None
        return {"payload": payload, "fetched_at": rows[0]["fetched_at"]}

    def cube_snapshot_fresh(self, kol_id: int, kind: str, ttl_seconds: int) -> bool:
        """快照是否在 TTL 内（fetcher 据此决定要不要重新请求雪球）。"""
        rows = self._rows(
            "SELECT 1 FROM cube_snapshots WHERE kol_id = ? AND kind = ? "
            "AND CAST(strftime('%s', fetched_at) AS INTEGER) >= strftime('%s', 'now') - ?",
            (kol_id, kind, ttl_seconds),
        )
        return bool(rows)

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

    def mark_kol_baseline(self, kol_id: int) -> None:
        """标记该大V已建立首次抓取基线（首次成功 fetch 后调用，含空列表）。"""
        self._execute("UPDATE kols SET baseline_ready = 1 WHERE id = ?", (kol_id,))

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
        images: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> int | None:
        detail_json = json.dumps(detail, ensure_ascii=False) if detail else ""
        images_json = json.dumps(images, ensure_ascii=False) if images else ""
        # None=未打标（pending，待回填）；[]=已处理但零命中（也持久化为 '[]'，避免重复回填）
        tags_json = json.dumps(tags, ensure_ascii=False) if tags is not None else ""
        try:
            with self._lock:
                cur = self._conn.execute(
                    "INSERT OR IGNORE INTO posts (platform, kol_id, external_id, title, content, post_type, images, url, published_at, detail, tags) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        platform,
                        kol_id,
                        external_id,
                        title,
                        content,
                        post_type,
                        images_json,
                        url,
                        published_at,
                        detail_json,
                        tags_json,
                    ),
                )
                # 无论是否命中唯一约束都提交：忽略插入同样会打开隐式事务，
                # 提前 return 不提交会把悬空事务留给下一个 BEGIN（事务嵌套报错）
                self._conn.commit()
                if cur.rowcount == 0:
                    return None  # 唯一约束命中，帖子已存在
                return cur.lastrowid
        except sqlite3.IntegrityError:
            # 并发下重复插入，视为已存在；回滚关闭隐式事务，避免悬空事务污染后续 BEGIN
            self._conn.rollback()
            return None

    def insert_posts_batch(self, posts) -> list[int | None]:
        """一个事务批量插入帖子，返回与入参对齐的 id 列表（已存在为 None）。"""
        if not posts:
            return []
        with self._lock:
            try:
                self._conn.execute("BEGIN")
                ids: list[int | None] = []
                for p in posts:
                    detail_json = json.dumps(p.detail, ensure_ascii=False) if p.detail else ""
                    images_json = json.dumps(p.images, ensure_ascii=False) if p.images else ""
                    tags_json = (
                        json.dumps(p.tags, ensure_ascii=False)
                        if p.tags is not None
                        else ""
                    )
                    cur = self._conn.execute(
                        "INSERT OR IGNORE INTO posts (platform, kol_id, external_id, title, content, post_type, images, url, published_at, detail, tags) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            p.platform,
                            p.kol_id,
                            p.external_id,
                            p.title,
                            p.content,
                            p.post_type,
                            images_json,
                            p.url,
                            p.published_at,
                            detail_json,
                            tags_json,
                        ),
                    )
                    ids.append(cur.lastrowid if cur.rowcount else None)
                self._conn.commit()
                return ids
            except Exception:
                self._conn.rollback()
                raise

    def list_posts(
        self,
        limit: int = 100,
        platform: str | None = None,
        kol_id: int | None = None,
        q: str | None = None,
        offset: int = 0,
        untagged_only: bool = False,
        below_id: int | None = None,
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
        if untagged_only:
            # 直接过滤未打标帖（tags 为空串），避免先取全量再在 Python 里过滤导致
            # 「最新 N 条都已打标」时回填数量恒为 0
            conds.append("(p.tags IS NULL OR p.tags = '')")
        if below_id is not None:
            # id 游标：只取该 id 之下的帖（配合 ORDER BY id DESC 实现一次扫描的分页回填）
            conds.append("p.id < ?")
            params.append(below_id)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY p.id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return _normalize_post_tags(_normalize_post_images(self._rows(sql, params)))

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

    def delete_posts_older_than(self, days: int, batch_size: int = 500) -> int:
        """删除超过 N 天的帖子及其推送记录，返回删除条数。

        分批（默认每批 500）避免过期帖子量大时 IN (...) 触达 SQLite 变量上限。
        """
        if days <= 0:
            return 0
        removed = 0
        while True:
            rows = self._rows(
                "SELECT id FROM posts WHERE fetched_at < datetime('now', ?) "
                "ORDER BY id LIMIT ?",
                (f"-{days} days", batch_size),
            )
            ids = [row["id"] for row in rows]
            if not ids:
                break
            placeholders = ", ".join("?" * len(ids))
            with self._lock:
                try:
                    self._conn.execute("BEGIN")
                    self._conn.execute(
                        f"DELETE FROM push_logs WHERE post_id IN ({placeholders})", ids
                    )
                    self._conn.execute(
                        f"DELETE FROM posts WHERE id IN ({placeholders})", ids
                    )
                    self._conn.commit()
                except Exception:
                    self._conn.rollback()
                    raise
            removed += len(ids)
        return removed

    def list_feed_posts(
        self,
        kol_ids: list[int],
        limit: int = 100,
        user_id: int | None = None,
        offset: int = 0,
        platform: str | None = None,
        category_id: int | None = None,
        q: str | None = None,
        favorite: bool = False,
        tag: str | None = None,
        include_secondary: bool = False,
        since_id: int | None = None,
    ) -> list[dict]:
        if not kol_ids:
            return []
        placeholders = ", ".join("?" * len(kol_ids))
        conds = [f"p.kol_id IN ({placeholders})"]
        params: list = [user_id, *kol_ids]
        if not include_secondary:
            # 默认隐藏次要大V的动态（全局 kols.secondary 或个人订阅 secondary）：
            # 避免连珠炮式发言刷屏时间线；特别关注（favorite）穿透始终显示
            conds.append(
                "(s.favorite = 1 OR (COALESCE(k.secondary, 0) = 0 AND COALESCE(s.secondary, 0) = 0))"
            )
        if platform:
            conds.append("p.platform = ?")
            params.append(platform)
        if category_id:
            conds.append("k.category_id = ?")
            params.append(category_id)
        if q:
            escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conds.append("(p.title LIKE ? ESCAPE '\\' OR p.content LIKE ? ESCAPE '\\')")
            like = f"%{escaped}%"
            params.extend([like, like])
        if tag:
            # tags 列存 JSON 数组文本，按 JSON 编码后的元素边界匹配（%"标签"%），
            # 避免「宏观」误中「宏观经济」；标签含引号/反斜杠时 json.dumps 保证转义一致
            escaped_tag = json.dumps(tag, ensure_ascii=False)[1:-1]
            escaped = escaped_tag.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conds.append("p.tags LIKE ? ESCAPE '\\'")
            params.append(f'%"{escaped}"%')
        if favorite:
            conds.append("s.favorite = 1")
        if since_id:
            conds.append("p.id > ?")
            params.append(since_id)
        return _normalize_post_tags(_normalize_post_images(self._rows(
            "SELECT p.*, k.name AS kol_name, k.category_id AS category_id, "
            "k.avatar_url AS avatar_url, c.name AS category_name, "
            "COALESCE(s.favorite, 0) AS favorite FROM posts p "
            "JOIN kols k ON k.id = p.kol_id "
            "LEFT JOIN categories c ON c.id = k.category_id "
            "LEFT JOIN subscriptions s ON s.kol_id = p.kol_id AND s.user_id = ? "
            f"WHERE {' AND '.join(conds)} ORDER BY p.id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )))

    def list_daily_posts(
        self, kol_ids: list[int], since_ts: int, limit: int = 15, user_id: int | None = None
    ) -> list[dict]:
        """用户订阅大V在 since_ts（本地零点）之后的帖子，用于每日精选。"""
        if not kol_ids:
            return []
        placeholders = ", ".join("?" * len(kol_ids))
        return _normalize_post_tags(_normalize_post_images(self._rows(
            "SELECT p.*, k.name AS kol_name, k.avatar_url AS avatar_url, "
            "c.name AS category_name, COALESCE(s.favorite, 0) AS favorite FROM posts p "
            "JOIN kols k ON k.id = p.kol_id "
            "LEFT JOIN categories c ON c.id = k.category_id "
            "LEFT JOIN subscriptions s ON s.kol_id = p.kol_id AND s.user_id = ? "
            f"WHERE p.kol_id IN ({placeholders}) AND strftime('%s', p.fetched_at) >= ? "
            "ORDER BY p.id DESC LIMIT ?",
            (user_id, *kol_ids, since_ts, limit),
        )))

    def daily_report_users(self) -> list[dict]:
        """开启每日精选、启用通知且绑定过渠道的用户。"""
        return self._rows(
            "SELECT * FROM users WHERE notify_enabled = 1 AND daily_report = 1 "
            f"AND {_user_has_channel_sql()}"
        )

    def active_feishu_personal_user_ids(self) -> set[int]:
        return {
            row["user_id"]
            for row in self._rows(
                "SELECT user_id FROM feishu_personal_bots "
                "WHERE status = 'active' AND chat_id != ''"
            )
        }

    # ---- Push log ----
    def add_push_log(self, post_id: int, channel: str, status: str, error: str = "", user_id: int | None = None) -> int:
        return self._execute(
            "INSERT INTO push_logs (post_id, channel, status, error, user_id) VALUES (?, ?, ?, ?, ?)",
            (post_id, channel, status, error, user_id),
        )

    # ---- 持久化错误日志（WARNING+，跨重启可查） ----
    ERROR_LOG_KEEP = 5000

    def record_error_log(self, level: str, logger: str, message: str) -> None:
        self._execute(
            "INSERT INTO error_logs (level, logger, message) VALUES (?, ?, ?)",
            (level.upper(), logger, message),
        )
        # 保留最近 N 条，防止无界增长（WARNING+ 频率低，代价可忽略）
        self._execute(
            "DELETE FROM error_logs WHERE id NOT IN "
            "(SELECT id FROM error_logs ORDER BY id DESC LIMIT ?)",
            (self.ERROR_LOG_KEEP,),
        )

    def list_error_logs(
        self, limit: int = 200, level: str | None = None, q: str | None = None
    ) -> list[dict]:
        conds, params = [], []
        if level:
            min_rank = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}[
                level.upper()
            ]
            conds.append(
                "CASE level WHEN 'DEBUG' THEN 10 WHEN 'INFO' THEN 20 WHEN 'WARNING' THEN 30 "
                "WHEN 'ERROR' THEN 40 WHEN 'CRITICAL' THEN 50 ELSE 0 END >= ?"
            )
            params.append(min_rank)
        if q:
            conds.append("(logger LIKE ? OR message LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like])
        where = f"WHERE {' AND '.join(conds)}" if conds else ""
        return self._rows(
            f"SELECT id, level, logger, message, created_at FROM error_logs "
            f"{where} ORDER BY id DESC LIMIT ?",
            (*params, limit),
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

    def get_failed_push_error(self, post_id: int, channel: str, user_id: int | None) -> str:
        """最近一条失败推送的原始错误（重试成功前取用，写入日志便于追溯）。"""
        if user_id is not None:
            cond = "user_id = ?"
            params = (post_id, channel, user_id)
        else:
            cond = "user_id IS NULL"
            params = (post_id, channel)
        rows = self._rows(
            f"SELECT error FROM push_logs WHERE post_id = ? AND channel = ? AND {cond} "
            "AND status = 'failed' ORDER BY id DESC LIMIT 1",
            params,
        )
        return rows[0]["error"] if rows else ""

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

    def update_post_tags(self, post_id: int, tags: list[str]) -> None:
        """回写单条贴文的标签（回填/纠错用），空列表持久化为 '[]'（已处理零命中）。"""
        tags_json = json.dumps(tags, ensure_ascii=False)
        self._execute("UPDATE posts SET tags = ? WHERE id = ?", (tags_json, post_id))

    def get_tag_vocabulary(self) -> list[dict]:
        """读贴文打标词表（settings 持久化），返回「标签 + 关键词」对象数组。

        兼容旧格式：settings 里若是纯字符串数组（旧 LLM 打标版本），自动迁移——
        tag 在默认规则里则补默认关键词，否则给空关键词（管理页可见可改）。
        """
        default_tags = {r["tag"]: r.get("keywords") or [] for r in DEFAULT_TAG_RULES}
        raw = self.get_setting(TAG_VOCABULARY_KEY)
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list) and parsed:
                    if isinstance(parsed[0], str):
                        # 旧格式：字符串数组 → 迁移为对象数组
                        return [
                            {"tag": t, "keywords": list(default_tags.get(t, []))}
                            for t in parsed
                        ]
                    rules = []
                    for r in parsed:
                        if not isinstance(r, dict) or not str(r.get("tag") or "").strip():
                            continue
                        rules.append(
                            {
                                "tag": str(r["tag"]).strip(),
                                "keywords": [
                                    str(k).strip() for k in (r.get("keywords") or []) if str(k).strip()
                                ],
                            }
                        )
                    if rules:
                        return rules
            except (TypeError, ValueError):
                pass
        return [dict(r) for r in DEFAULT_TAG_RULES]

    def set_tag_vocabulary(self, tags: list[dict]) -> None:
        """保存贴文打标词表（对象数组：tag + keywords）。"""
        self.set_setting(TAG_VOCABULARY_KEY, json.dumps(tags, ensure_ascii=False))

    def tag_stats(self) -> dict:
        """打标统计（管理端回填进度展示用）。

        processed = 已成功执行规则（含零命中）；tagged = 实际有标签；
        pending = 尚未执行规则（'' 或 NULL，需回填）。
        """
        rows = self._rows(
            "SELECT COUNT(*) AS n, "
            "SUM(CASE WHEN tags != '' THEN 1 ELSE 0 END) AS processed, "
            "SUM(CASE WHEN tags != '' AND tags != '[]' THEN 1 ELSE 0 END) AS tagged "
            "FROM posts"
        )
        row = rows[0] if rows else {"n": 0, "processed": 0, "tagged": 0}
        total = _to_int(row["n"])
        processed = _to_int(row["processed"])
        return {
            "total": total,
            "processed": processed,
            "tagged": _to_int(row["tagged"]),
            "pending": total - processed,
        }

    def get_stock_names(self) -> list[str]:
        """读常用股票名表（settings 持久化），缺省用内置默认名单。"""
        raw = self.get_setting(STOCK_NAMES_KEY)
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list) and parsed:
                    return [str(n) for n in parsed]
            except (TypeError, ValueError):
                pass
        return list(DEFAULT_STOCK_NAMES)

    def set_stock_names(self, names: list[str]) -> None:
        """保存常用股票名表。"""
        self.set_setting(STOCK_NAMES_KEY, json.dumps(names, ensure_ascii=False))

    def get_stock_aliases(self) -> list[dict]:
        """读黑话别名表（settings 持久化），缺省空表。

        兼容旧数据：元素若是纯字符串（早期格式），视为无对应正式名，跳过。
        """
        raw = self.get_setting(STOCK_ALIASES_KEY)
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    aliases = []
                    for a in parsed:
                        if isinstance(a, dict):
                            alias = str(a.get("alias") or "").strip()
                            stock = str(a.get("stock") or "").strip()
                            if alias and stock:
                                aliases.append({"alias": alias, "stock": stock})
                        elif isinstance(a, str) and a.strip():
                            # 旧格式纯字符串：只有别名无正式名，无法打标，忽略
                            continue
                    return aliases
            except (TypeError, ValueError):
                pass
        return []

    def set_stock_aliases(self, aliases: list[dict]) -> None:
        """保存黑话别名表。"""
        self.set_setting(STOCK_ALIASES_KEY, json.dumps(aliases, ensure_ascii=False))

    def aggregate_post_tags(self, limit: int = 50) -> list[str]:
        """聚合贴文里出现过的全部标签（去重，按出现次数降序）。

        供前端动态标签筛选下拉使用（词表标签之外的实际标签，如股票名）。
        全表扫描 tags 列；1500+ 帖量级一次扫描可接受。
        """
        counts: dict[str, int] = {}
        for row in self._rows("SELECT tags FROM posts WHERE tags != ''"):
            raw = row["tags"]
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if not isinstance(parsed, list):
                continue
            for tag in parsed:
                tag = str(tag).strip()
                if tag:
                    counts[tag] = counts.get(tag, 0) + 1
        return [tag for tag, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))][:limit]

    # ---- 每日精选投递状态（按渠道幂等） ----
    def daily_report_delivered(self, user_id: int, report_date: str, channel: str) -> bool:
        """该用户当日该渠道是否已成功投递。"""
        rows = self._rows(
            "SELECT 1 FROM daily_report_deliveries "
            "WHERE user_id = ? AND report_date = ? AND channel = ? AND status = 'success'",
            (user_id, report_date, channel),
        )
        return bool(rows)

    def mark_daily_report_delivered(self, user_id: int, report_date: str, channel: str) -> None:
        """标记渠道当日投递成功；重复标记覆盖为成功（幂等）。"""
        self._execute(
            "INSERT INTO daily_report_deliveries (user_id, report_date, channel, status) "
            "VALUES (?, ?, ?, 'success') "
            "ON CONFLICT(user_id, report_date, channel) "
            "DO UPDATE SET status = 'success', updated_at = datetime('now')",
            (user_id, report_date, channel),
        )

    def mark_daily_report_failed(self, user_id: int, report_date: str, channel: str) -> None:
        """标记渠道当日投递失败（用于重试时区分，成功标记覆盖失败标记）。"""
        self._execute(
            "INSERT INTO daily_report_deliveries (user_id, report_date, channel, status) "
            "VALUES (?, ?, ?, 'failed') "
            "ON CONFLICT(user_id, report_date, channel) "
            "DO UPDATE SET status = 'failed', updated_at = datetime('now')",
            (user_id, report_date, channel),
        )

    def delete_daily_report_deliveries_older_than(self, days: int) -> int:
        """清理超过 N 天的每日精选投递状态，避免表无限增长。"""
        if days <= 0:
            return 0
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM daily_report_deliveries WHERE report_date < date('now', ?)",
                (f"-{days} days",),
            )
            self._conn.commit()
            return cur.rowcount

    # ---- 数据源稳定性事件 ----
    def add_source_event(
        self, platform: str, status: str, detail: str = "", ok_count: int = 0, fail_count: int = 0
    ) -> None:
        """记录一次数据源事件：ok（本轮有抓取成功）/ fail（本轮有失败）/ warn（降级）。

        ok_count/fail_count 是本轮该平台成功/失败的大V抓取次数，用于按
        「尝试次数」统计真实成功率，避免单个大V失败被同平台多数成功掩盖。
        """
        self._execute(
            "INSERT INTO source_events (platform, status, detail, ok_count, fail_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (platform, status, detail[:300], int(ok_count), int(fail_count)),
        )

    def source_event_stats(self, platform: str, hours: int = 24) -> dict[str, int]:
        """最近 N 小时内的抓取成功/失败次数与降级事件数。

        ok/fail 按「尝试次数」求和；旧版事件行（迁移前 ok_count=0）按 1 次
        计，避免升级后 24h 内成功率瞬时归零。
        """
        rows = self._rows(
            "SELECT status, "
            "SUM(CASE WHEN ok_count > 0 THEN ok_count ELSE 1 END) AS ok, "
            "SUM(CASE WHEN fail_count > 0 THEN fail_count ELSE 1 END) AS fail, "
            "COUNT(*) AS n "
            "FROM source_events "
            "WHERE platform = ? AND created_at >= datetime('now', ?) "
            "GROUP BY status",
            (platform, f"-{hours} hours"),
        )
        out = {"ok": 0, "fail": 0, "warn": 0}
        for row in rows:
            status = row["status"]
            if status == "warn":
                out["warn"] = row["n"]
            elif status == "ok":
                out["ok"] = int(row["ok"] or 0)
            elif status == "fail":
                out["fail"] = int(row["fail"] or 0)
        return out

    def recent_source_events(self, limit: int = 30) -> list[dict]:
        return self._rows(
            "SELECT * FROM source_events ORDER BY id DESC LIMIT ?",
            (min(max(limit, 1), 200),),
        )

    def delete_source_events_older_than(self, days: int) -> int:
        if days <= 0:
            return 0
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM source_events WHERE created_at < datetime('now', ?)",
                (f"-{days} days",),
            )
            self._conn.commit()
            return cur.rowcount

    def delete_admin_logs_older_than(self, days: int) -> int:
        """删除超过 N 天的管理员操作日志，返回删除条数。"""
        if days <= 0:
            return 0
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM admin_logs WHERE created_at < datetime('now', ?)",
                (f"-{days} days",),
            )
            self._conn.commit()
            return cur.rowcount

    # ---- 飞书个人机器人 ----
    _PERSONAL_BOT_COLUMNS = frozenset({
        "app_id", "app_secret_ciphertext", "open_id", "chat_id",
        "tenant_brand", "status", "last_error", "verified_at", "last_success_at",
    })

    def get_feishu_personal_bot(self, user_id: int) -> dict | None:
        rows = self._rows(
            "SELECT * FROM feishu_personal_bots WHERE user_id = ?", (user_id,)
        )
        return rows[0] if rows else None

    def get_feishu_personal_bot_by_app(self, app_id: str) -> dict | None:
        rows = self._rows(
            "SELECT * FROM feishu_personal_bots WHERE app_id = ?", (app_id,)
        )
        return rows[0] if rows else None

    def save_feishu_personal_bot(self, user_id: int, app_id: str,
                                 app_secret_ciphertext: str, tenant_brand: str,
                                 status: str, *, open_id: str = "", chat_id: str = "",
                                 last_error: str = "") -> None:
        """按 user_id upsert 个人机器人记录（唯一约束：每用户一条）。"""
        self._execute(
            "INSERT INTO feishu_personal_bots "
            "(user_id, app_id, app_secret_ciphertext, tenant_brand, status, open_id, chat_id, last_error, verified_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, CASE WHEN ? = 'active' THEN datetime('now') ELSE NULL END, datetime('now')) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "app_id=excluded.app_id, app_secret_ciphertext=excluded.app_secret_ciphertext, "
            "tenant_brand=excluded.tenant_brand, status=excluded.status, open_id=excluded.open_id, "
            "chat_id=excluded.chat_id, last_error=excluded.last_error, "
            "verified_at=CASE WHEN excluded.status = 'active' THEN datetime('now') ELSE verified_at END, "
            "updated_at=datetime('now')",
            (user_id, app_id, app_secret_ciphertext, tenant_brand, status, open_id, chat_id, last_error, status),
        )

    def update_feishu_personal_bot(self, user_id: int, **kwargs) -> None:
        sets, params = [], []
        for key, value in kwargs.items():
            if key not in self._PERSONAL_BOT_COLUMNS:
                raise ValueError(f"非法个人机器人字段: {key}")
            sets.append(f"{key} = ?")
            params.append(value)
        if not sets:
            return
        sets.append("updated_at = datetime('now')")
        params.append(user_id)
        self._execute(
            f"UPDATE feishu_personal_bots SET {', '.join(sets)} WHERE user_id = ?", params
        )

    def delete_feishu_personal_bot(self, user_id: int) -> None:
        self._execute("DELETE FROM feishu_personal_bots WHERE user_id = ?", (user_id,))

    # ---- 飞书个人机器人注册会话 ----
    _REG_SESSION_COLUMNS = frozenset({
        "device_code_ciphertext", "registration_base_url", "verification_uri",
        "candidate_app_id", "candidate_app_secret_ciphertext", "candidate_tenant_brand",
        "expected_open_id", "bind_code_hash", "bind_code_expires_at",
        "session_expires_at", "poll_interval", "status", "last_error",
    })

    def create_feishu_registration_session(self, **kwargs) -> None:
        keys = [k for k in kwargs if k in self._REG_SESSION_COLUMNS or k == "session_id" or k == "user_id"]
        missing = {"session_id", "user_id", "device_code_ciphertext", "registration_base_url",
                   "verification_uri", "session_expires_at", "poll_interval", "status"} - set(keys)
        if missing:
            raise ValueError(f"注册会话缺少必填字段: {', '.join(sorted(missing))}")
        cols = ", ".join(keys)
        marks = ", ".join("?" for _ in keys)
        self._execute(
            f"INSERT INTO feishu_registration_sessions ({cols}) VALUES ({marks})",
            tuple(kwargs[k] for k in keys),
        )

    def get_feishu_registration_session(self, session_id: str) -> dict | None:
        rows = self._rows(
            "SELECT * FROM feishu_registration_sessions WHERE session_id = ?", (session_id,)
        )
        return rows[0] if rows else None

    def get_active_feishu_registration_session(self, user_id: int) -> dict | None:
        rows = self._rows(
            "SELECT * FROM feishu_registration_sessions WHERE user_id = ? "
            "AND status NOT IN ('expired', 'cancelled') ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        )
        return rows[0] if rows else None

    def update_feishu_registration_session(self, session_id: str, **kwargs) -> None:
        sets, params = [], []
        for key, value in kwargs.items():
            if key not in self._REG_SESSION_COLUMNS:
                raise ValueError(f"非法注册会话字段: {key}")
            sets.append(f"{key} = ?")
            params.append(value)
        if not sets:
            return
        sets.append("updated_at = datetime('now')")
        params.append(session_id)
        self._execute(
            f"UPDATE feishu_registration_sessions SET {', '.join(sets)} WHERE session_id = ?",
            params,
        )

    def cancel_feishu_registration_sessions_by_user(self, user_id: int) -> None:
        """取消某用户所有未结束的注册会话（开始新会话前调用）。"""
        self._execute(
            "UPDATE feishu_registration_sessions SET status = 'cancelled', "
            "updated_at = datetime('now') WHERE user_id = ? AND status NOT IN ('expired', 'cancelled')",
            (user_id,),
        )

    def expire_stale_feishu_registration_sessions(self, now: int | None = None) -> int:
        """把已过期的非终态会话置为 expired（启动清理），返回处理条数。"""
        now = int(now if now is not None else time.time())
        stale = self._rows(
            "SELECT session_id FROM feishu_registration_sessions "
            "WHERE status NOT IN ('expired', 'cancelled', 'active') AND session_expires_at < ?",
            (now,),
        )
        for row in stale:
            self._execute(
                "UPDATE feishu_registration_sessions SET status = 'expired', "
                "updated_at = datetime('now') WHERE session_id = ?",
                (row["session_id"],),
            )
        return len(stale)
