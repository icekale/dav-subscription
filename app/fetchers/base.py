"""抓取器基础：Post 数据类与公共文本清理。"""
from __future__ import annotations

import email.utils
import html
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# 项目面向中文社交平台，发布时间统一按北京时间展示，避免依赖服务器时区
CN_TZ = timezone(timedelta(hours=8))
PLATFORM_LABELS = {
    "xueqiu": "雪球",
    "combination": "雪球组合",
    "weibo": "微博",
    "twitter": "X",
    "ima": "ima",
    "zsxq": "知识星球",
}


def show_original(platform: str, url: str | None) -> bool:
    """星球原文需登录且无稳定外链，广场/推送都不放「查看原文」。"""
    return bool(url) and platform != "zsxq"


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
    category: str = ""
    post_type: str = ""
    detail: dict | None = None
    images: list[str] = field(default_factory=list)
    favorite: bool = False
    # None = 尚未执行规则打标（pending）；空列表 = 已执行但零命中；非空 = 已打标
    tags: list[str] | None = None


def strip_html(text: str) -> str:
    """去掉 HTML 标签、还原实体（含 &#34; 等数字实体），<br> 转成换行。"""
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).replace("\xa0", " ").strip()


def truncate_text(text: str, limit: int) -> str:
    """截断长文本：优先在换行/句号处断，避免拦腰切断一句话，末尾补省略号。"""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in ("\n", "。", "！", "？", "；"):
        idx = cut.rfind(sep)
        if idx > limit * 0.6:
            return cut[: idx + 1].rstrip() + "…"
    return cut.rstrip() + "…"


def digest_body(post: Post, full: bool, max_chars: int = 120, full_limit: int = 2000) -> str:
    """合并摘要正文：单条摘要显示完整正文（保留换行）；多条截断到 max_chars 并补省略号。"""
    raw = post.content or post.title or "（无正文）"
    if full:
        return truncate_text(raw, full_limit)
    flat = raw.replace("\n", " ")
    if len(flat) <= max_chars:
        return flat
    return flat[:max_chars].rstrip() + "…"


def parse_published_at(raw: str) -> datetime | None:
    """时间戳 / RFC2822 / 常见日期串 → 北京时间；解析失败返回 None。"""
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        ts = int(raw)
        ts = ts / 1000 if ts > 1e12 else ts
        try:
            return datetime.fromtimestamp(ts, tz=CN_TZ)
        except (ValueError, OSError, OverflowError):
            return None
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        if dt is not None:
            return dt.astimezone(CN_TZ)
    except (TypeError, ValueError):
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=CN_TZ)
        except ValueError:
            continue
    return None


def attachment_lines(post: Post, note: str = "（链接可能过期）") -> list[str]:
    """从 post.detail["files"] 生成附件行：📎 文件名 + 下载链接。无附件返回空列表。"""
    files = ((post.detail or {}).get("files") or []) if post.detail else []
    lines = []
    for f in files:
        name = str(f.get("name") or "附件") if isinstance(f, dict) else "附件"
        url = str(f.get("url") or "") if isinstance(f, dict) else ""
        if url.startswith(("http://", "https://")):
            lines.append(f"📎 {name}\n   {url} {note}")
    return lines


def format_published_at(raw: str) -> str:
    """把时间戳（毫秒/秒）或 RFC2822（X/微博）格式化为可读时间，其他格式原样返回。"""
    raw = (raw or "").strip()
    dt = parse_published_at(raw)
    return dt.strftime("%Y-%m-%d %H:%M") if dt else raw


class ThreadLocalClient:
    """httpx.Client 非线程安全：poll_once 同平台最多 8 并发，每线程懒建一个。"""

    def __init__(self, factory, injected=None):
        self._factory = factory
        self._injected = injected
        self._local = threading.local()

    def get(self):
        if self._injected is not None:
            return self._injected
        client = getattr(self._local, "client", None)
        if client is None:
            client = self._factory()
            self._local.client = client
        return client

    def set(self, client) -> None:
        self._injected = client

    def reset(self) -> None:
        if self._injected is not None:
            return
        self._local.client = None


class Fetcher:
    platform = ""

    def __init__(self, source_config):
        self.source_config = source_config

    def fetch(self, kol: dict) -> list[Post]:
        raise NotImplementedError
