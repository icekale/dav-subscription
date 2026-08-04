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
    category: str = ""


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
