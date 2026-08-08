"""抓取器基础：Post 数据类与公共文本清理。"""
from __future__ import annotations

import email.utils
import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# 项目面向中文社交平台，发布时间统一按北京时间展示，避免依赖服务器时区
CN_TZ = timezone(timedelta(hours=8))


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
    tags: list[str] = field(default_factory=list)


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


def format_published_at(raw: str) -> str:
    """把时间戳（毫秒/秒）或 RFC2822（X/微博）格式化为可读时间，其他格式原样返回。"""
    raw = (raw or "").strip()
    if raw.isdigit():
        ts = int(raw)
        ts = ts / 1000 if ts > 1e12 else ts
        try:
            return datetime.fromtimestamp(ts, tz=CN_TZ).strftime("%Y-%m-%d %H:%M")
        except (ValueError, OSError):
            return raw
    try:
        dt = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return raw
    if dt is None:
        return raw
    return dt.astimezone(CN_TZ).strftime("%Y-%m-%d %H:%M")


class Fetcher:
    platform = ""

    def __init__(self, source_config):
        self.source_config = source_config

    def fetch(self, kol: dict) -> list[Post]:
        raise NotImplementedError
