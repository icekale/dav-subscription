# dav-subscription 自托管大V订阅服务 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个 Docker 化自托管服务，聚合订阅雪球/微博/X(Twitter) 大V公开动态，新帖实时推送至飞书和 Telegram，并提供 Web 管理界面（增删大V、浏览帖子、查看推送记录）。

**Architecture:** 单容器 Python 服务。FastAPI 提供 REST API 与静态管理页面；asyncio 调度器周期性轮询各平台抓取器；SQLite（WAL）负责 KOL、帖子去重与推送日志持久化；飞书 webhook 与 Telegram Bot API 两个通知器推送新帖。所有网络调用通过 `asyncio.to_thread` 隔离，避免阻塞事件循环。

**Tech Stack:** Python 3.12、FastAPI、uvicorn、httpx、feedparser、PyYAML、SQLite、pytest、Docker / docker-compose。

**设计文档：** `docs/superpowers/specs/2026-08-04-dav-subscription-design.md`（已获用户批准）

**约定：** 项目根为 `dav-subscription/`；所有命令在工作目录 `dav-subscription/` 下执行；每个任务结束提交一次 git。

---

## Task 0: 项目骨架与配置加载

**Files:**
- Create: `requirements.txt`
- Create: `config.example.yaml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 创建依赖与基础文件**

`requirements.txt`：

```text
fastapi==0.115.6
uvicorn[standard]==0.34.0
httpx==0.28.1
feedparser==6.0.11
PyYAML==6.0.2
pytest==8.3.4
```

`config.example.yaml`：

```yaml
notifiers:
  feishu:
    webhook_url: ""   # 飞书群机器人 webhook：群设置 → 群机器人 → 自定义机器人
  telegram:
    bot_token: ""     # @BotFather 创建 bot 获取
    chat_id: ""       # 接收推送的会话 ID（可用 @userinfobot 查询）

sources:
  xueqiu:
    cookie: ""        # 可选：浏览器登录雪球后复制 Cookie，推荐配置
  weibo:
    cookie: ""        # 推荐：浏览器登录 weibo.cn 后复制 Cookie
    token: ""         # 可选：x-xsrf-token

polling:
  interval_seconds: 180
  jitter_seconds: 30
  notify_on_start: true

web:
  password: ""        # 可选：管理界面 Basic Auth 密码
```

`.env.example`：

```bash
CONFIG_PATH=/app/config.yaml
DB_PATH=/data/dav.db
FEISHU_WEBHOOK_URL=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
XUEQIU_COOKIE=
WEIBO_COOKIE=
WEIBO_TOKEN=
POLLING_INTERVAL_SECONDS=180
POLLING_JITTER_SECONDS=30
NOTIFY_ON_START=true
WEB_PASSWORD=
```

`.gitignore`：

```gitignore
__pycache__/
.pytest_cache/
.venv/
data/
config.yaml
.env
*.pyc
```

`app/__init__.py`：空文件。

- [ ] **Step 2: 写配置加载失败/成功测试**

`tests/test_config.py`：

```python
from app.config import load_config


def test_defaults_without_file(tmp_path, monkeypatch):
    monkeypatch.delenv("CONFIG_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    config = load_config(tmp_path / "nope.yaml")
    assert config.polling.interval_seconds == 180
    assert config.notifiers.feishu.webhook_url == ""
    assert config.db_path == "/data/dav.db"


def test_yaml_and_env_overrides(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(
        "polling:\n  interval_seconds: 60\nweb:\n  password: secret\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("POLLING_INTERVAL_SECONDS", "90")
    config = load_config(tmp_path / "config.yaml")
    assert config.polling.interval_seconds == 90
    assert config.web.password == "secret"
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m pytest tests/test_config.py -q`

Expected: `ERROR` / `ModuleNotFoundError: No module named 'app.config'`（config.py 尚不存在）。

- [ ] **Step 4: 实现 `app/config.py`**

```python
"""配置加载：YAML 文件 + 环境变量覆盖。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path

import yaml


@dataclass
class FeishuConfig:
    webhook_url: str = ""


@dataclass
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""


@dataclass
class NotifiersConfig:
    feishu: FeishuConfig = field(default_factory=FeishuConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)


@dataclass
class XueqiuConfig:
    cookie: str = ""


@dataclass
class WeiboConfig:
    cookie: str = ""
    token: str = ""


@dataclass
class SourcesConfig:
    xueqiu: XueqiuConfig = field(default_factory=XueqiuConfig)
    weibo: WeiboConfig = field(default_factory=WeiboConfig)


@dataclass
class PollingConfig:
    interval_seconds: int = 180
    jitter_seconds: int = 30
    notify_on_start: bool = True


@dataclass
class WebConfig:
    password: str = ""


@dataclass
class Config:
    notifiers: NotifiersConfig = field(default_factory=NotifiersConfig)
    sources: SourcesConfig = field(default_factory=SourcesConfig)
    polling: PollingConfig = field(default_factory=PollingConfig)
    web: WebConfig = field(default_factory=WebConfig)
    db_path: str = "/data/dav.db"


# 环境变量 -> Config 属性路径（用于覆盖）
_ENV_MAP = {
    "FEISHU_WEBHOOK_URL": ("notifiers", "feishu", "webhook_url"),
    "TELEGRAM_BOT_TOKEN": ("notifiers", "telegram", "bot_token"),
    "TELEGRAM_CHAT_ID": ("notifiers", "telegram", "chat_id"),
    "XUEQIU_COOKIE": ("sources", "xueqiu", "cookie"),
    "WEIBO_COOKIE": ("sources", "weibo", "cookie"),
    "WEIBO_TOKEN": ("sources", "weibo", "token"),
    "POLLING_INTERVAL_SECONDS": ("polling", "interval_seconds"),
    "POLLING_JITTER_SECONDS": ("polling", "jitter_seconds"),
    "NOTIFY_ON_START": ("polling", "notify_on_start"),
    "WEB_PASSWORD": ("web", "password"),
    "DB_PATH": ("db_path",),
}


def _fill(dc, data: dict) -> None:
    """用嵌套 dict 就地填充 dataclass，忽略未知字段。"""
    for f in fields(dc):
        if f.name not in data:
            continue
        value = data[f.name]
        child = getattr(dc, f.name)
        if is_dataclass(child) and isinstance(value, dict):
            _fill(child, value)
        else:
            setattr(dc, f.name, value)


def _set_path(obj, path, value) -> None:
    for key in path[:-1]:
        obj = getattr(obj, key)
    setattr(obj, path[-1], value)


def load_config(path: str | Path | None = None) -> Config:
    """加载 config.yaml（如存在），再用环境变量覆盖。"""
    path = Path(path or os.environ.get("CONFIG_PATH", "config.yaml"))
    config = Config()
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        _fill(config, raw)
    for env_name, attr_path in _ENV_MAP.items():
        value = os.environ.get(env_name)
        if value is None:
            continue
        if env_name in ("POLLING_INTERVAL_SECONDS", "POLLING_JITTER_SECONDS"):
            value = int(value)
        elif env_name == "NOTIFY_ON_START":
            value = value.strip().lower() in ("1", "true", "yes")
        _set_path(config, attr_path, value)
    return config
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_config.py -q`

Expected: `2 passed`

- [ ] **Step 6: 安装依赖并提交**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
git add requirements.txt config.example.yaml .env.example .gitignore app tests
git commit -m "feat: 项目骨架与配置加载"
```

Expected: 提交成功，工作区干净。

---

## Task 1: 数据层（SQLite 去重）

**Files:**
- Create: `app/db.py`
- Test: `tests/test_dedup.py`

- [ ] **Step 1: 写去重测试**

`tests/test_dedup.py`：

```python
import tempfile
from pathlib import Path

from app.db import DB


def make_db() -> DB:
    tmp = tempfile.mkdtemp()
    return DB(Path(tmp) / "test.db")


def test_kol_crud():
    db = make_db()
    kid = db.add_kol("xueqiu", "测试大V", "123")
    assert db.get_kol(kid)["name"] == "测试大V"
    db.update_kol(kid, enabled=False)
    assert db.get_kol(kid)["enabled"] == 0
    db.delete_kol(kid)
    assert db.get_kol(kid) is None


def test_insert_post_dedup():
    db = make_db()
    kid = db.add_kol("xueqiu", "测试大V", "123")
    pid1 = db.insert_post("xueqiu", kid, "p1", "标题", "内容", "https://x", "2026-01-01")
    pid2 = db.insert_post("xueqiu", kid, "p1", "标题", "内容", "https://x", "2026-01-01")
    assert pid1 is not None
    assert pid2 is None
    assert len(db.list_posts()) == 1


def test_invalid_platform_rejected():
    db = make_db()
    try:
        db.add_kol("facebook", "x", "1")
    except ValueError:
        return
    raise AssertionError("应拒绝不支持的平台")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_dedup.py -q`

Expected: `ModuleNotFoundError: No module named 'app.db'`

- [ ] **Step 3: 实现 `app/db.py`**

```python
"""SQLite 持久化：KOL、帖子（去重）、推送日志。"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS kols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    name TEXT NOT NULL,
    external_id TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
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
"""

ALLOWED_PLATFORMS = {"xueqiu", "weibo", "twitter"}


class DB:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._lock = threading.Lock()

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
    def add_kol(self, platform: str, name: str, external_id: str) -> int:
        if platform not in ALLOWED_PLATFORMS:
            raise ValueError(f"不支持的平台: {platform}")
        return self._execute(
            "INSERT INTO kols (platform, name, external_id) VALUES (?, ?, ?)",
            (platform, name, external_id),
        )

    def get_kol(self, kol_id: int) -> dict | None:
        rows = self._rows("SELECT * FROM kols WHERE id = ?", (kol_id,))
        return rows[0] if rows else None

    def list_kols(self, platform: str | None = None) -> list[dict]:
        if platform:
            return self._rows("SELECT * FROM kols WHERE platform = ? ORDER BY id", (platform,))
        return self._rows("SELECT * FROM kols ORDER BY id")

    def update_kol(self, kol_id: int, name=None, external_id=None, enabled=None):
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
        if not sets:
            return
        params.append(kol_id)
        self._execute(f"UPDATE kols SET {', '.join(sets)} WHERE id = ?", params)

    def delete_kol(self, kol_id: int):
        self._execute("DELETE FROM kols WHERE id = ?", (kol_id,))

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
        sql = "SELECT p.*, k.name AS kol_name FROM posts p JOIN kols k ON k.id = p.kol_id"
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

    # ---- Push log ----
    def add_push_log(self, post_id: int, channel: str, status: str, error: str = "") -> int:
        return self._execute(
            "INSERT INTO push_logs (post_id, channel, status, error) VALUES (?, ?, ?, ?)",
            (post_id, channel, status, error),
        )

    def list_push_logs(self, limit: int = 100) -> list[dict]:
        return self._rows(
            "SELECT l.*, p.title, k.name AS kol_name FROM push_logs l "
            "JOIN posts p ON p.id = l.post_id "
            "JOIN kols k ON k.id = p.kol_id "
            "ORDER BY l.id DESC LIMIT ?",
            (limit,),
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_dedup.py -q`

Expected: `3 passed`

- [ ] **Step 5: 提交**

```bash
git add app/db.py tests/test_dedup.py
git commit -m "feat: SQLite 数据层与帖子去重"
```

---

## Task 2: 帖子模型与雪球抓取器

**Files:**
- Create: `app/fetchers/__init__.py`
- Create: `app/fetchers/base.py`
- Create: `app/fetchers/xueqiu.py`
- Create: `tests/fixtures/xueqiu_sample.json`
- Test: `tests/test_fetchers.py`

- [ ] **Step 1: 写雪球解析测试与夹具**

`tests/fixtures/xueqiu_sample.json`：

```json
{
  "statuses": [
    {
      "id": 101,
      "title": "看多宁德",
      "description": "今日<strong>大涨</strong>，继续持有",
      "target": "/101",
      "created_at": "2026-08-04 10:00"
    },
    {
      "id": 102,
      "title": "",
      "description": "第二条动态",
      "target": "/102",
      "created_at": "2026-08-04 11:00"
    }
  ]
}
```

`tests/test_fetchers.py`（本任务只包含雪球部分，后续任务追加）：

```python
import json
from pathlib import Path

import httpx

from app.config import XueqiuConfig
from app.fetchers.xueqiu import XueqiuFetcher

FIXTURES = Path(__file__).parent / "fixtures"


def test_xueqiu_parse_fixture():
    payload = json.loads((FIXTURES / "xueqiu_sample.json").read_text(encoding="utf-8"))

    def handler(request):
        assert request.headers.get("Cookie", "").startswith("xq_a_token=")
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = XueqiuFetcher(XueqiuConfig(cookie="xq_a_token=abc"), client=client)
    posts = fetcher.fetch({"id": 1, "name": "大V", "external_id": "123"})
    assert len(posts) == 2
    assert posts[0].external_id == "101"
    assert posts[0].url == "https://xueqiu.com/101"
    assert "大涨" in posts[0].content
    assert "<strong>" not in posts[0].content
    assert posts[0].kol_name == "大V"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_fetchers.py::test_xueqiu_parse_fixture -q`

Expected: `ModuleNotFoundError: No module named 'app.fetchers'`

- [ ] **Step 3: 实现 base、xueqiu 与包初始化**

`app/fetchers/base.py`：

```python
"""抓取器基础：Post 数据类与公共文本清理。"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Post:
    platform: str
    kol_id: int
    kol_name: str
    external_id: str
    title: str
    content: str
    url: str
    published_at: str


def strip_html(text: str) -> str:
    """去掉 HTML 标签、还原常见实体，<br> 转成换行。"""
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    for old, new in (
        ("&nbsp;", " "),
        ("&amp;", "&"),
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&quot;", '"'),
        ("&#39;", "'"),
    ):
        text = text.replace(old, new)
    return text.strip()


class Fetcher:
    platform = ""

    def __init__(self, source_config):
        self.source_config = source_config

    def fetch(self, kol: dict) -> list[Post]:
        raise NotImplementedError
```

`app/fetchers/xueqiu.py`：

```python
"""雪球用户原创动态抓取。"""
from __future__ import annotations

import httpx

from .base import Fetcher, Post, strip_html


class XueqiuFetcher(Fetcher):
    platform = "xueqiu"

    def __init__(self, source_config, client: httpx.Client | None = None):
        super().__init__(source_config)
        self.client = client or httpx.Client(
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)",
                "Referer": "https://xueqiu.com/",
            },
        )
        if self.source_config.cookie:
            self.client.headers["Cookie"] = self.source_config.cookie

    def fetch(self, kol: dict) -> list[Post]:
        resp = self.client.get(
            "https://xueqiu.com/statuses/original/timeline.json",
            params={"user_id": kol["external_id"], "page": 1},
        )
        resp.raise_for_status()
        statuses = (resp.json() or {}).get("statuses") or []
        posts = []
        for s in statuses:
            target = s.get("target") or ""
            url = f"https://xueqiu.com{target}" if target.startswith("/") else target
            posts.append(
                Post(
                    platform=self.platform,
                    kol_id=kol["id"],
                    kol_name=kol["name"],
                    external_id=str(s.get("id") or ""),
                    title=s.get("title") or "",
                    content=strip_html(s.get("description") or ""),
                    url=url,
                    published_at=str(s.get("created_at") or ""),
                )
            )
        return posts
```

`app/fetchers/__init__.py`：

```python
from __future__ import annotations

from .base import Fetcher
from .rss import RssFetcher
from .weibo import WeiboFetcher
from .xueqiu import XueqiuFetcher


def build_fetchers(config) -> dict[str, Fetcher]:
    """根据全局配置构造各平台抓取器。"""
    return {
        "xueqiu": XueqiuFetcher(config.sources.xueqiu),
        "weibo": WeiboFetcher(config.sources.weibo),
        "twitter": RssFetcher(),
    }
```

注意：`__init__.py` 引用了尚未创建的 `weibo`、`rss` 模块，Task 3/4 会创建。若此刻运行测试报 `ModuleNotFoundError`，先创建下述占位模块让 Task 2 的测试通过。

`app/fetchers/weibo.py`（占位，Task 3 完整实现）：

```python
from .base import Fetcher


class WeiboFetcher(Fetcher):
    platform = "weibo"
```

`app/fetchers/rss.py`（占位，Task 4 完整实现）：

```python
from .base import Fetcher


class RssFetcher(Fetcher):
    platform = "twitter"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_fetchers.py -q`

Expected: `1 passed`

- [ ] **Step 5: 提交**

```bash
git add app/fetchers tests/fixtures tests/test_fetchers.py
git commit -m "feat: 帖子模型与雪球抓取器"
```

---

## Task 3: 微博抓取器

**Files:**
- Modify: `app/fetchers/weibo.py`（补全实现）
- Create: `tests/fixtures/weibo_sample.json`
- Modify: `tests/test_fetchers.py`（追加微博测试）

- [ ] **Step 1: 写微博解析测试与夹具**

`tests/fixtures/weibo_sample.json`：

```json
{
  "data": {
    "cards": [
      {
        "card_type": 9,
        "mblog": {
          "id": "M1",
          "text": "今天<em>行情</em>不错，继续关注",
          "created_at": "08-04"
        }
      },
      {
        "card_type": 8,
        "mblog": null
      }
    ]
  }
}
```

在 `tests/test_fetchers.py` 末尾追加：

```python
from app.config import WeiboConfig
from app.fetchers.weibo import WeiboFetcher


def test_weibo_parse_fixture():
    payload = json.loads((FIXTURES / "weibo_sample.json").read_text(encoding="utf-8"))

    def handler(request):
        assert request.headers.get("Cookie", "").startswith("SUB=")
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = WeiboFetcher(WeiboConfig(cookie="SUB=xyz"), client=client)
    posts = fetcher.fetch({"id": 2, "name": "微博大V", "external_id": "1234567890"})
    assert len(posts) == 1
    assert posts[0].external_id == "M1"
    assert posts[0].url == "https://m.weibo.cn/detail/M1"
    assert "行情" in posts[0].content
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_fetchers.py::test_weibo_parse_fixture -q`

Expected: `AttributeError` / `NotImplementedError`（占位类无 fetch 实现）。

- [ ] **Step 3: 补全 `app/fetchers/weibo.py`**

```python
"""微博（m.weibo.cn）用户动态抓取。"""
from __future__ import annotations

import httpx

from .base import Fetcher, Post, strip_html


class WeiboFetcher(Fetcher):
    platform = "weibo"

    def __init__(self, source_config, client: httpx.Client | None = None):
        super().__init__(source_config)
        self.client = client or httpx.Client(
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                "AppleWebKit/605.1.15 Mobile/15E148",
                "Referer": "https://m.weibo.cn/",
            },
        )
        if self.source_config.cookie:
            self.client.headers["Cookie"] = self.source_config.cookie
        if self.source_config.token:
            self.client.headers["X-XSRF-TOKEN"] = self.source_config.token

    def fetch(self, kol: dict) -> list[Post]:
        uid = kol["external_id"]
        resp = self.client.get(
            "https://m.weibo.cn/api/container/getIndex",
            params={"type": "uid", "value": uid, "containerid": f"107603{uid}"},
        )
        resp.raise_for_status()
        cards = ((resp.json() or {}).get("data") or {}).get("cards") or []
        posts = []
        for card in cards:
            if card.get("card_type") != 9:
                continue
            mblog = card.get("mblog") or {}
            mid = mblog.get("id")
            if not mid:
                continue
            text = strip_html(mblog.get("text") or "")
            posts.append(
                Post(
                    platform=self.platform,
                    kol_id=kol["id"],
                    kol_name=kol["name"],
                    external_id=str(mid),
                    title=(mblog.get("raw_text") or text)[:80],
                    content=text,
                    url=f"https://m.weibo.cn/detail/{mid}",
                    published_at=str(mblog.get("created_at") or ""),
                )
            )
        return posts
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_fetchers.py -q`

Expected: `2 passed`

- [ ] **Step 5: 提交**

```bash
git add app/fetchers/weibo.py tests/fixtures/weibo_sample.json tests/test_fetchers.py
git commit -m "feat: 微博抓取器"
```

---

## Task 4: X（RSS）抓取器

**Files:**
- Modify: `app/fetchers/rss.py`（补全实现）
- Create: `tests/fixtures/rss_sample.xml`
- Modify: `tests/test_fetchers.py`（追加 RSS 测试）

- [ ] **Step 1: 写 RSS 解析测试与夹具**

`tests/fixtures/rss_sample.xml`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Hello X</title>
      <link>https://x.com/status/1</link>
      <guid>1</guid>
      <description>hello &lt;b&gt;world&lt;/b&gt;</description>
      <pubDate>Wed, 04 Aug 2026 10:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
```

在 `tests/test_fetchers.py` 末尾追加：

```python
from app.fetchers.rss import RssFetcher


def test_rss_parse_fixture():
    content = (FIXTURES / "rss_sample.xml").read_bytes()

    def handler(request):
        return httpx.Response(200, content=content)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = RssFetcher(client=client)
    posts = fetcher.fetch({"id": 3, "name": "X大V", "external_id": "https://rss.example/feed"})
    assert len(posts) == 1
    assert posts[0].external_id == "1"
    assert posts[0].url == "https://x.com/status/1"
    assert "world" in posts[0].content
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_fetchers.py::test_rss_parse_fixture -q`

Expected: `TypeError`（RssFetcher 的 fetch 无实现且占位类不允许实例化传参）。

- [ ] **Step 3: 补全 `app/fetchers/rss.py`**

```python
"""X/Twitter 等通用 RSS 抓取（RSSHub / nitter 源）。"""
from __future__ import annotations

import httpx
import feedparser

from .base import Fetcher, Post, strip_html


class RssFetcher(Fetcher):
    platform = "twitter"

    def __init__(self, source_config=None, client: httpx.Client | None = None):
        super().__init__(source_config)
        self.client = client or httpx.Client(
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0"},
        )

    def fetch(self, kol: dict) -> list[Post]:
        resp = self.client.get(kol["external_id"])
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        posts = []
        for entry in feed.entries:
            posts.append(
                Post(
                    platform=self.platform,
                    kol_id=kol["id"],
                    kol_name=kol["name"],
                    external_id=entry.get("id") or entry.get("link") or "",
                    title=entry.get("title") or "",
                    content=strip_html(entry.get("summary") or entry.get("description") or ""),
                    url=entry.get("link") or "",
                    published_at=str(entry.get("published") or entry.get("updated") or ""),
                )
            )
        return posts
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_fetchers.py -q`

Expected: `3 passed`

- [ ] **Step 5: 提交**

```bash
git add app/fetchers/rss.py tests/fixtures/rss_sample.xml tests/test_fetchers.py
git commit -m "feat: X RSS 抓取器"
```

---

## Task 5: 通知器（飞书 + Telegram）

**Files:**
- Create: `app/notifiers/__init__.py`
- Create: `app/notifiers/base.py`
- Create: `app/notifiers/feishu.py`
- Create: `app/notifiers/telegram.py`
- Test: `tests/test_format.py`
- Test: `tests/test_notifiers.py`

- [ ] **Step 1: 写格式化与通知器测试**

`tests/test_format.py`：

```python
from app.fetchers.base import Post
from app.notifiers.feishu import build_feishu_card
from app.notifiers.telegram import build_telegram_text


def make_post() -> Post:
    return Post(
        platform="xueqiu",
        kol_id=1,
        kol_name="张三",
        external_id="1",
        title="看多",
        content="今天 <b>大涨</b>",
        url="https://xueqiu.com/1",
        published_at="2026-08-04",
    )


def test_feishu_card_contains_author_and_url():
    card = build_feishu_card(make_post())
    assert card["msg_type"] == "interactive"
    assert "张三" in card["card"]["header"]["title"]["content"]
    button = card["card"]["elements"][-1]["actions"][0]
    assert button["url"] == "https://xueqiu.com/1"


def test_telegram_text_escapes_html():
    text = build_telegram_text(make_post())
    assert "<b>看多</b>" in text
    assert "&lt;b&gt;大涨&lt;/b&gt;" in text
    assert 'href="https://xueqiu.com/1"' in text
```

`tests/test_notifiers.py`：

```python
import httpx
import pytest

from app.config import FeishuConfig, TelegramConfig
from app.fetchers.base import Post
from app.notifiers.feishu import FeishuNotifier
from app.notifiers.telegram import TelegramNotifier


def make_post() -> Post:
    return Post(
        platform="weibo",
        kol_id=1,
        kol_name="李四",
        external_id="w1",
        title="t",
        content="c",
        url="https://weibo.com/1",
        published_at="",
    )


def test_feishu_success():
    def handler(request):
        assert "open.feishu.cn" in str(request.url)
        return httpx.Response(200, json={"code": 0, "msg": "success"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    notifier = FeishuNotifier(
        FeishuConfig(webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/x"),
        client=client,
    )
    notifier.notify(make_post())  # 不抛异常即成功


def test_feishu_business_error_raises():
    def handler(request):
        return httpx.Response(200, json={"code": 19001, "msg": "bad"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    notifier = FeishuNotifier(
        FeishuConfig(webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/x"),
        client=client,
    )
    with pytest.raises(RuntimeError):
        notifier.notify(make_post())


def test_telegram_success():
    def handler(request):
        assert "api.telegram.org" in str(request.url)
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    notifier = TelegramNotifier(
        TelegramConfig(bot_token="123:abc", chat_id="456"),
        client=client,
    )
    notifier.notify(make_post())


def test_telegram_unconfigured_raises():
    notifier = TelegramNotifier(TelegramConfig())
    with pytest.raises(RuntimeError):
        notifier.notify(make_post())
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_format.py tests/test_notifiers.py -q`

Expected: `ModuleNotFoundError: No module named 'app.notifiers'`

- [ ] **Step 3: 实现通知器**

`app/notifiers/base.py`：

```python
"""通知器基类。"""
from __future__ import annotations

from ..fetchers.base import Post


class Notifier:
    channel = ""

    def notify(self, post: Post) -> None:
        raise NotImplementedError

    def send_text(self, text: str) -> None:
        raise NotImplementedError
```

`app/notifiers/feishu.py`：

```python
"""飞书群机器人 webhook 通知。"""
from __future__ import annotations

import httpx

from ..fetchers.base import Post
from .base import Notifier

PLATFORM_LABELS = {"xueqiu": "雪球", "weibo": "微博", "twitter": "X/Twitter"}


def build_feishu_card(post: Post) -> dict:
    platform = PLATFORM_LABELS.get(post.platform, post.platform)
    title = post.title or "大V新动态"
    content = post.content[:200] or "（无正文）"
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"{title} · {post.kol_name}"},
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"**{post.kol_name}** · {platform}\n{content}"},
                },
                {
                    "tag": "note",
                    "elements": [{"tag": "plain_text", "content": f"发布时间：{post.published_at}"}],
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "查看原文"},
                            "type": "primary",
                            "url": post.url,
                        }
                    ],
                },
            ],
        },
    }


class FeishuNotifier(Notifier):
    channel = "feishu"

    def __init__(self, config, client: httpx.Client | None = None):
        self.webhook_url = config.webhook_url
        self.client = client or httpx.Client(timeout=15)

    def _post(self, payload: dict) -> None:
        resp = self.client.post(self.webhook_url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") not in (None, 0):
            raise RuntimeError(f"飞书返回错误: {data.get('msg', data)}")

    def notify(self, post: Post) -> None:
        if not self.webhook_url:
            raise RuntimeError("未配置飞书 webhook_url")
        self._post(build_feishu_card(post))

    def send_text(self, text: str) -> None:
        if not self.webhook_url:
            raise RuntimeError("未配置飞书 webhook_url")
        payload = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": text}}],
            },
        }
        self._post(payload)
```

`app/notifiers/telegram.py`：

```python
"""Telegram Bot API 通知。"""
from __future__ import annotations

from html import escape

import httpx

from ..fetchers.base import Post
from .base import Notifier

PLATFORM_LABELS = {"xueqiu": "雪球", "weibo": "微博", "twitter": "X/Twitter"}


def build_telegram_text(post: Post) -> str:
    platform = PLATFORM_LABELS.get(post.platform, post.platform)
    title = escape(post.title or "大V新动态")
    content = escape(post.content[:200]) or "（无正文）"
    return "\n".join(
        [
            f"<b>{title}</b>",
            "",
            content,
            "",
            f"📌 {escape(post.kol_name)} · {platform}",
            f"🕐 {escape(post.published_at)}",
            f'🔗 <a href="{escape(post.url)}">查看原文</a>',
        ]
    )


class TelegramNotifier(Notifier):
    channel = "telegram"

    def __init__(self, config, client: httpx.Client | None = None):
        self.bot_token = config.bot_token
        self.chat_id = config.chat_id
        self.client = client or httpx.Client(timeout=15)

    def _send(self, data: dict) -> None:
        if not self.bot_token or not self.chat_id:
            raise RuntimeError("未配置 telegram bot_token/chat_id")
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        resp = self.client.post(url, data={"chat_id": self.chat_id, **data})
        resp.raise_for_status()
        result = resp.json()
        if not result.get("ok"):
            raise RuntimeError(f"Telegram 返回错误: {result}")

    def notify(self, post: Post) -> None:
        self._send(
            {
                "text": build_telegram_text(post),
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
        )

    def send_text(self, text: str) -> None:
        self._send({"text": text})
```

`app/notifiers/__init__.py`：

```python
from __future__ import annotations

from .base import Notifier
from .feishu import FeishuNotifier
from .telegram import TelegramNotifier


def build_notifiers(config) -> list[Notifier]:
    """只启用已配置的通知渠道。"""
    notifiers = []
    if config.notifiers.feishu.webhook_url:
        notifiers.append(FeishuNotifier(config.notifiers.feishu))
    if config.notifiers.telegram.bot_token and config.notifiers.telegram.chat_id:
        notifiers.append(TelegramNotifier(config.notifiers.telegram))
    return notifiers
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_format.py tests/test_notifiers.py -q`

Expected: `6 passed`

- [ ] **Step 5: 提交**

```bash
git add app/notifiers tests/test_format.py tests/test_notifiers.py
git commit -m "feat: 飞书与 Telegram 通知器"
```

---

## Task 6: 调度器（轮询、去重、推送、退避）

**Files:**
- Create: `app/scheduler.py`
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: 写调度测试**

`tests/test_scheduler.py`：

```python
import tempfile
from pathlib import Path

from app.db import DB
from app.fetchers.base import Post
from app.scheduler import poll_once


class FakeFetcher:
    def __init__(self, posts):
        self.posts = posts

    def fetch(self, kol):
        return self.posts


class FakeFetcherError:
    def fetch(self, kol):
        raise RuntimeError("boom")


class FakeNotifier:
    channel = "test"

    def __init__(self):
        self.calls = []

    def notify(self, post):
        self.calls.append(post)


def make_db() -> DB:
    tmp = tempfile.mkdtemp()
    return DB(Path(tmp) / "test.db")


def make_post(kol_id):
    return Post(
        platform="xueqiu",
        kol_id=kol_id,
        kol_name="A",
        external_id="p1",
        title="t",
        content="c",
        url="u",
        published_at="",
    )


def test_new_post_pushed_once():
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    post = make_post(kid)
    notifier = FakeNotifier()

    poll_once(db, {"xueqiu": FakeFetcher([post])}, [notifier])
    assert len(notifier.calls) == 1
    assert len(db.list_posts()) == 1
    assert db.list_push_logs()[0]["status"] == "success"

    poll_once(db, {"xueqiu": FakeFetcher([post])}, [notifier])
    assert len(notifier.calls) == 1
    assert len(db.list_posts()) == 1


def test_fetch_error_does_not_crash():
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    notifier = FakeNotifier()
    poll_once(db, {"xueqiu": FakeFetcherError()}, [notifier])
    assert len(db.list_posts()) == 0
    assert len(notifier.calls) == 0


def test_push_failure_logged():
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    post = make_post(kid)

    class FailingNotifier(FakeNotifier):
        def notify(self, post):
            raise RuntimeError("down")

    notifier = FailingNotifier()
    poll_once(db, {"xueqiu": FakeFetcher([post])}, [notifier])
    logs = db.list_push_logs()
    assert logs[0]["status"] == "failed"
    assert "down" in logs[0]["error"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_scheduler.py -q`

Expected: `ModuleNotFoundError: No module named 'app.scheduler'`

- [ ] **Step 3: 实现 `app/scheduler.py`**

```python
"""调度器：轮询抓取、去重入库、推送通知、失败退避。"""
from __future__ import annotations

import asyncio
import logging
import random
import time

from .db import DB
from .fetchers.base import Fetcher, Post
from .notifiers.base import Notifier

logger = logging.getLogger(__name__)


class PlatformState:
    """每个平台连续失败次数与退避截止时间。"""

    def __init__(self):
        self.fail_count = 0
        self.skip_until = 0.0


def notify_post(db: DB, post_id: int, post: Post, notifiers: list[Notifier]) -> None:
    """向所有通知器推送，失败记录日志并重试一次。"""
    for notifier in notifiers:
        try:
            notifier.notify(post)
            db.add_push_log(post_id, notifier.channel, "success")
        except Exception as exc:  # noqa: BLE001 - 推送失败只记录
            logger.warning("推送失败 channel=%s post=%s err=%s", notifier.channel, post.external_id, exc)
            db.add_push_log(post_id, notifier.channel, "failed", str(exc))
            try:
                notifier.notify(post)
                db.add_push_log(post_id, notifier.channel, "success")
            except Exception as exc2:  # noqa: BLE001
                logger.error("推送重试失败 channel=%s post=%s err=%s", notifier.channel, post.external_id, exc2)
                db.add_push_log(post_id, notifier.channel, "failed", str(exc2))


def poll_once(
    db: DB,
    fetchers: dict[str, Fetcher],
    notifiers: list[Notifier],
    states: dict[str, PlatformState] | None = None,
) -> None:
    """执行一轮：遍历启用 KOL → 抓取 → 去重 → 推送。"""
    states = states or {}
    now = time.monotonic()
    for kol in db.list_kols():
        if not kol["enabled"]:
            continue
        fetcher = fetchers.get(kol["platform"])
        if fetcher is None:
            continue
        state = states.setdefault(kol["platform"], PlatformState())
        if now < state.skip_until:
            continue
        try:
            posts = fetcher.fetch(kol)
        except Exception as exc:  # noqa: BLE001 - 单源失败不影响其他
            state.fail_count += 1
            delay = min(30 * (2 ** (state.fail_count - 1)), 600)
            state.skip_until = time.monotonic() + delay
            logger.warning(
                "抓取失败 platform=%s kol=%s err=%s 下次尝试 %.0fs 后",
                kol["platform"],
                kol["name"],
                exc,
                delay,
            )
            continue
        state.fail_count = 0
        for post in posts:
            post_id = db.insert_post(
                post.platform,
                post.kol_id,
                post.external_id,
                post.title,
                post.content,
                post.url,
                post.published_at,
            )
            if post_id is None:
                continue
            logger.info("新帖 platform=%s kol=%s id=%s", post.platform, post.kol_name, post.external_id)
            notify_post(db, post_id, post, notifiers)


class Scheduler:
    def __init__(self, db, fetchers, notifiers, polling_config):
        self.db = db
        self.fetchers = fetchers
        self.notifiers = notifiers
        self.polling_config = polling_config
        self.states: dict[str, PlatformState] = {}
        self._stop = asyncio.Event()

    def stop(self):
        self._stop.set()

    async def _send_startup_message(self):
        for notifier in self.notifiers:
            try:
                await asyncio.to_thread(notifier.send_text, "✅ 大V订阅服务已启动")
            except Exception as exc:  # noqa: BLE001
                logger.warning("启动消息发送失败 channel=%s err=%s", notifier.channel, exc)

    async def run(self):
        if self.polling_config.notify_on_start:
            await self._send_startup_message()
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                await asyncio.to_thread(poll_once, self.db, self.fetchers, self.notifiers, self.states)
            except Exception:  # noqa: BLE001 - 任何异常都不能终止循环
                logger.exception("轮询周期异常")
            elapsed = time.monotonic() - started
            delay = self.polling_config.interval_seconds + random.uniform(
                0, self.polling_config.jitter_seconds
            )
            await asyncio.sleep(max(0.0, delay - elapsed))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_scheduler.py -q`

Expected: `3 passed`

- [ ] **Step 5: 提交**

```bash
git add app/scheduler.py tests/test_scheduler.py
git commit -m "feat: 轮询调度、去重推送与失败退避"
```

---

## Task 7: REST API 与 Web 管理界面

**Files:**
- Create: `app/api.py`
- Create: `app/static/index.html`
- Create: `app/static/app.js`
- Create: `app/static/style.css`
- Test: `tests/test_api.py`

- [ ] **Step 1: 写 API 测试**

`tests/test_api.py`：

```python
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_api_router
from app.db import DB
from app.main import create_app


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


def test_healthz():
    tmp = tempfile.mkdtemp()
    app = create_app(db_path=Path(tmp) / "api3.db")
    client = TestClient(app)
    assert client.get("/healthz").json() == {"status": "ok"}
```

注意：测试引用了 `app.main.create_app(db_path=...)`，该签名在 Task 8 实现；若本任务先跑测试会失败，因此本任务的实现顺序为 **先实现 `app/api.py` 与静态文件，再实现 `app/main.py` 中 `create_app(db_path=...)` 的最小版本**。

- [ ] **Step 2: 实现 `app/api.py`**

```python
"""REST API：KOL 增删改查、帖子列表、推送记录。"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from .db import ALLOWED_PLATFORMS, DB


class KolIn(BaseModel):
    platform: str
    name: str
    external_id: str


class KolUpdate(BaseModel):
    name: str | None = None
    external_id: str | None = None
    enabled: bool | None = None


def make_auth_dependency(password: str):
    """密码非空时启用 Basic Auth，否则返回空依赖列表。"""
    if not password:
        return []
    basic = HTTPBasic(auto_error=False)

    def check(credentials: HTTPBasicCredentials | None = Depends(basic)):
        if credentials is None or not secrets.compare_digest(credentials.password, password):
            raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})
        return credentials

    return [Depends(check)]


def create_api_router(db: DB, password: str = "") -> APIRouter:
    router = APIRouter(prefix="/api", dependencies=make_auth_dependency(password))

    @router.get("/kols")
    def list_kols(platform: str | None = None):
        return db.list_kols(platform)

    @router.post("/kols")
    def add_kol(body: KolIn):
        if body.platform not in ALLOWED_PLATFORMS:
            raise HTTPException(status_code=400, detail=f"不支持的平台: {body.platform}")
        if not body.name.strip() or not body.external_id.strip():
            raise HTTPException(status_code=400, detail="昵称与外部ID不能为空")
        kid = db.add_kol(body.platform, body.name.strip(), body.external_id.strip())
        return db.get_kol(kid)

    @router.put("/kols/{kol_id}")
    def update_kol(kol_id: int, body: KolUpdate):
        if db.get_kol(kol_id) is None:
            raise HTTPException(status_code=404, detail="KOL 不存在")
        db.update_kol(
            kol_id,
            name=body.name.strip() if body.name is not None else None,
            external_id=body.external_id.strip() if body.external_id is not None else None,
            enabled=body.enabled,
        )
        return db.get_kol(kol_id)

    @router.delete("/kols/{kol_id}")
    def delete_kol(kol_id: int):
        if db.get_kol(kol_id) is None:
            raise HTTPException(status_code=404, detail="KOL 不存在")
        db.delete_kol(kol_id)
        return {"ok": True}

    @router.get("/posts")
    def list_posts(limit: int = 100, platform: str | None = None, kol_id: int | None = None):
        return db.list_posts(limit=min(limit, 500), platform=platform, kol_id=kol_id)

    @router.get("/push-logs")
    def list_push_logs(limit: int = 100):
        return db.list_push_logs(limit=min(limit, 500))

    return router
```

- [ ] **Step 3: 实现静态前端**

`app/static/index.html`：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>大V订阅</title>
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <header>
    <h1>大V订阅</h1>
    <nav>
      <button class="tab active" data-tab="kols">订阅管理</button>
      <button class="tab" data-tab="posts">帖子</button>
      <button class="tab" data-tab="logs">推送记录</button>
    </nav>
  </header>
  <main>
    <section id="tab-kols" class="tab-panel active">
      <form id="kol-form" class="row">
        <select id="platform">
          <option value="xueqiu">雪球</option>
          <option value="weibo">微博</option>
          <option value="twitter">X (RSS)</option>
        </select>
        <input id="name" placeholder="昵称" required>
        <input id="external-id" placeholder="雪球user_id / 微博uid / RSS链接" required>
        <button type="submit">添加</button>
      </form>
      <table>
        <thead><tr><th>ID</th><th>平台</th><th>昵称</th><th>外部ID</th><th>状态</th><th>操作</th></tr></thead>
        <tbody id="kol-body"></tbody>
      </table>
    </section>
    <section id="tab-posts" class="tab-panel">
      <div class="row">
        <select id="post-platform">
          <option value="">全部平台</option>
          <option value="xueqiu">雪球</option>
          <option value="weibo">微博</option>
          <option value="twitter">X</option>
        </select>
        <button id="refresh-posts">刷新</button>
      </div>
      <ul id="post-list" class="list"></ul>
    </section>
    <section id="tab-logs" class="tab-panel">
      <div class="row"><button id="refresh-logs">刷新</button></div>
      <table>
        <thead><tr><th>时间</th><th>KOL</th><th>标题</th><th>渠道</th><th>状态</th><th>错误</th></tr></thead>
        <tbody id="log-body"></tbody>
      </table>
    </section>
  </main>
  <script src="/app.js"></script>
</body>
</html>
```

`app/static/app.js`：

```javascript
const $ = (sel) => document.querySelector(sel);

async function api(path, options = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(text || resp.statusText);
  }
  return resp.json();
}

const PLATFORM_LABELS = { xueqiu: "雪球", weibo: "微博", twitter: "X" };

async function loadKols() {
  const kols = await api("/api/kols");
  $("#kol-body").innerHTML = kols.map((k) => `
    <tr>
      <td>${k.id}</td>
      <td>${PLATFORM_LABELS[k.platform] || k.platform}</td>
      <td>${escapeHtml(k.name)}</td>
      <td>${escapeHtml(k.external_id)}</td>
      <td>${k.enabled ? "启用" : "停用"}</td>
      <td class="row">
        <button onclick="toggleKol(${k.id}, ${k.enabled ? 0 : 1})">${k.enabled ? "停用" : "启用"}</button>
        <button onclick="deleteKol(${k.id})">删除</button>
      </td>
    </tr>`).join("");
}

async function loadPosts() {
  const platform = $("#post-platform").value;
  const url = "/api/posts?limit=100" + (platform ? `&platform=${platform}` : "");
  const posts = await api(url);
  $("#post-list").innerHTML = posts.map((p) => `
    <li>
      <a href="${escapeHtml(p.url)}" target="_blank" rel="noopener">
        <strong>${escapeHtml(p.title || "（无标题）")}</strong>
      </a>
      <span>${PLATFORM_LABELS[p.platform] || p.platform} · ${escapeHtml(p.kol_name)} · ${escapeHtml(p.published_at)}</span>
      <p>${escapeHtml(p.content || "")}</p>
    </li>`).join("");
}

async function loadLogs() {
  const logs = await api("/api/push-logs?limit=100");
  $("#log-body").innerHTML = logs.map((l) => `
    <tr>
      <td>${escapeHtml(l.created_at)}</td>
      <td>${escapeHtml(l.kol_name)}</td>
      <td>${escapeHtml(l.title || "")}</td>
      <td>${l.channel}</td>
      <td class="${l.status === "success" ? "ok" : "fail"}">${l.status}</td>
      <td>${escapeHtml(l.error || "")}</td>
    </tr>`).join("");
}

async function toggleKol(id, enabled) {
  await api(`/api/kols/${id}`, { method: "PUT", body: JSON.stringify({ enabled: !!enabled }) });
  loadKols();
}

async function deleteKol(id) {
  if (!confirm("确认删除该大V？")) return;
  await api(`/api/kols/${id}`, { method: "DELETE" });
  loadKols();
}

function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $(`#tab-${btn.dataset.tab}`).classList.add("active");
  });
});

$("#kol-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/kols", {
      method: "POST",
      body: JSON.stringify({
        platform: $("#platform").value,
        name: $("#name").value,
        external_id: $("#external-id").value,
      }),
    });
    $("#name").value = "";
    $("#external-id").value = "";
    loadKols();
  } catch (err) {
    alert("添加失败: " + err.message);
  }
});

$("#refresh-posts").addEventListener("click", loadPosts);
$("#refresh-logs").addEventListener("click", loadLogs);

loadKols();
loadPosts();
loadLogs();
```

`app/static/style.css`：

```css
:root {
  --bg: #f5f6f7;
  --card: #fff;
  --border: #e2e5e9;
  --text: #1f2329;
  --muted: #6b7280;
  --accent: #3370ff;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
  background: var(--bg);
  color: var(--text);
}
header {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 12px 24px;
  background: var(--card);
  border-bottom: 1px solid var(--border);
}
header h1 { font-size: 18px; margin: 0; }
nav { display: flex; gap: 8px; }
.tab {
  border: 1px solid var(--border);
  background: var(--card);
  padding: 6px 14px;
  border-radius: 6px;
  cursor: pointer;
}
.tab.active { background: var(--accent); color: #fff; border-color: var(--accent); }
main { padding: 20px 24px; max-width: 960px; margin: 0 auto; }
.tab-panel { display: none; }
.tab-panel.active { display: block; }
.row { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; }
input, select, button {
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 14px;
}
input { flex: 1; }
button { background: var(--card); cursor: pointer; }
button:hover { border-color: var(--accent); color: var(--accent); }
table {
  width: 100%;
  border-collapse: collapse;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
}
th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border); font-size: 14px; }
th { background: #fafbfc; color: var(--muted); }
.ok { color: #16a34a; }
.fail { color: #dc2626; }
.list { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.list li {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
}
.list li span { color: var(--muted); font-size: 13px; }
.list li p { margin: 8px 0 0; white-space: pre-wrap; }
.list a { color: var(--accent); text-decoration: none; }
```

- [ ] **Step 4: 实现 `app/main.py` 最小版（支持 `create_app(db_path=...)`）**

```python
"""应用入口：FastAPI + 调度器生命周期。"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import create_api_router
from .config import load_config
from .db import DB
from .fetchers import build_fetchers
from .notifiers import build_notifiers
from .scheduler import Scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def create_app(config=None, db_path: str | Path | None = None) -> FastAPI:
    config = config or load_config()
    if db_path is not None:
        config.db_path = str(db_path)
    db = DB(config.db_path)
    fetchers = build_fetchers(config)
    notifiers = build_notifiers(config)
    scheduler = Scheduler(db, fetchers, notifiers, config.polling)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(scheduler.run())
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        db.close()

    app = FastAPI(title="大V订阅", lifespan=lifespan)
    app.state.db = db

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    app.include_router(create_api_router(db, config.web.password))
    app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
    return app


app = create_app()
```

注意：测试使用 `TestClient(app)` 时会触发 lifespan，从而启动调度器。轮询使用 `asyncio.to_thread` 且测试退出时 lifespan 会取消任务，不会卡住。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_api.py -q`

Expected: `3 passed`（`TestClient` 需要 `httpx`，已安装）

- [ ] **Step 6: 提交**

```bash
git add app/api.py app/main.py app/static tests/test_api.py
git commit -m "feat: REST API 与 Web 管理界面"
```

---

## Task 8: Docker 部署与 README

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `README.md`

- [ ] **Step 1: 创建 `Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

ENV CONFIG_PATH=/app/config.yaml
ENV DB_PATH=/data/dav.db

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: 创建 `docker-compose.yml`**

```yaml
services:
  dav-subscription:
    build: .
    container_name: dav-subscription
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      - TZ=Asia/Shanghai
      - CONFIG_PATH=/app/config.yaml
      - DB_PATH=/data/dav.db
    volumes:
      - ./config.yaml:/app/config.yaml
      - ./data:/data
```

- [ ] **Step 3: 创建 `README.md`**

````markdown
# 大V订阅（自托管版）

聚合订阅雪球 / 微博 / X(Twitter) 大V公开动态，新帖实时推送到**飞书**与**Telegram**，并带一个简单的 Web 管理界面。

> 说明：本项目为自托管替代方案，仅抓取公开可见的动态，不包含任何平台会员/付费内容；无订阅名额与推送次数限制。

## 功能

- 订阅管理：网页增删改大V、启停（雪球 user_id / 微博 uid / X RSS 地址）
- 定时轮询：默认 180s，带随机抖动与失败退避
- 消息推送：新帖去重后推送飞书（卡片）与 Telegram（HTML 消息）
- 帖子历史与推送记录：Web 页面可浏览
- Docker 一键部署，SQLite 持久化

## 快速开始

```bash
cp config.example.yaml config.yaml
# 编辑 config.yaml，填入飞书/Telegram 配置
docker compose up -d --build
```

打开 http://localhost:8000 管理订阅。数据保存在 `./data/dav.db`，重启不丢。

## 飞书机器人（申请 webhook）

1. 打开目标飞书群 → 设置 → 群机器人 → 添加机器人 → 自定义机器人
2. 复制 Webhook 地址，填入 `notifiers.feishu.webhook_url`

## Telegram 机器人（申请 token 与 chat_id）

1. 与 [@BotFather](https://t.me/BotFather) 对话：`/newbot`，按提示创建，拿到 `bot_token`
2. 把 bot 拉进目标会话，发一条消息
3. 访问 `https://api.telegram.org/bot<你的token>/getUpdates`，在返回的 JSON 里找 `chat.id`，填入 `notifiers.telegram.chat_id`

## 配置说明

| 配置项 | 说明 |
| --- | --- |
| `notifiers.feishu.webhook_url` | 飞书群机器人 webhook |
| `notifiers.telegram.bot_token` | Telegram Bot token |
| `notifiers.telegram.chat_id` | 接收消息的会话 ID |
| `sources.xueqiu.cookie` | 可选，雪球登录 Cookie，推荐配置 |
| `sources.weibo.cookie` | 微博登录 Cookie（weibo.cn），建议配置 |
| `sources.weibo.token` | 可选，x-xsrf-token |
| `polling.interval_seconds` | 轮询间隔（默认 180） |
| `polling.jitter_seconds` | 随机抖动（默认 30） |
| `polling.notify_on_start` | 启动时发上线消息（默认 true） |
| `web.password` | 管理界面访问密码（Basic Auth，留空不启用） |

所有配置项均可通过环境变量覆盖（见 `.env.example`）。

## Cookie 获取

- 雪球：浏览器登录 xueqiu.com → 开发者工具 → Network → 复制请求头里的 `Cookie` 整串
- 微博：浏览器登录 weibo.cn → 同上复制 Cookie；token 取 Cookie 中 `XSRF-TOKEN` 的值

Cookie 过期后重新复制即可，无需重启容器（改 `config.yaml` 后 `docker compose restart`）。

## X (Twitter) 订阅

X 官方 API 需付费，本项目通过 RSS 源订阅。每个 X 大V 在「订阅管理」中添加时，外部 ID 填 RSS 地址，例如：

- RSSHub 公共实例：`https://rsshub.app/twitter/user/elonmusk`
- 自建 RSSHub：`http://<你的地址>/twitter/user/elonmusk`
- 其他兼容 RSS 2.0 的源亦可

RSS 源不稳定时该平台会暂时抓不到，建议自建 RSSHub 保证可用性。

## 安全提示

默认监听所有网卡。建议：

- 仅在内网使用，或置于反向代理后
- 如暴露公网，务必设置 `web.password`

## 开发与测试

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest
```

## 常见问题

**微博抓不到内容？** 检查 `sources.weibo.cookie` 是否有效（过期需更新）。

**飞书收不到推送？** 确认 webhook 正确且机器人未被移出群。

**Telegram 收不到推送？** 确认 bot 已拉入会话、`chat_id` 正确。

**推送记录里大量 failed？** 查看该条目的错误信息，通常是渠道配置问题。
````

- [ ] **Step 4: 本地全量测试**

Run: `python -m pytest -q`

Expected: `20 passed`（Task 0~8 全部测试）

- [ ] **Step 5: 构建镜像并冒烟验证**

```bash
docker compose build
docker compose up -d
curl -s http://localhost:8000/healthz
curl -s http://localhost:8000/api/kols
docker compose down
```

Expected: healthz 返回 `{"status":"ok"}`，kols 返回 `[]`，容器正常启动与停止。

注意：`docker compose up` 会挂载 `./config.yaml`，请先 `cp config.example.yaml config.yaml`（配置为空时服务仍可启动，仅不推送）。

- [ ] **Step 6: 提交**

```bash
git add Dockerfile docker-compose.yml README.md
git commit -m "docs: Docker 部署与使用说明"
```

---

## 自检结果

**规格覆盖：** 设计文档第 3~12 节均有对应任务：架构(Task 7/8)、数据模型(Task 1)、抓取器(Task 2/3/4)、通知器(Task 5)、调度与可靠性(Task 6)、安全(Task 7 Basic Auth)、Docker(Task 8)、测试(各任务)、README(Task 8)。

**占位扫描：** 无 TBD/TODO；所有步骤含完整代码与命令。

**类型一致性：** `Post` 字段（platform/kol_id/kol_name/external_id/title/content/url/published_at）在抓取器、通知器、调度器、测试中保持一致；`poll_once` 签名在调度器与测试一致；`create_app(db_path=...)` 在 Task 7 测试与 Task 7 Step 4 实现一致。
