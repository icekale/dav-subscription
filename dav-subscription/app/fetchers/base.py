"""抓取器基础：Post 数据类与公共文本清理。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime


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


def format_published_at(raw: str) -> str:
    """把时间戳（毫秒/秒）格式化为可读时间，其他格式原样返回。"""
    raw = (raw or "").strip()
    if raw.isdigit():
        ts = int(raw)
        ts = ts / 1000 if ts > 1e12 else ts
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        except (ValueError, OSError):
            return raw
    return raw


class Fetcher:
    platform = ""

    def __init__(self, source_config):
        self.source_config = source_config

    def fetch(self, kol: dict) -> list[Post]:
        raise NotImplementedError
