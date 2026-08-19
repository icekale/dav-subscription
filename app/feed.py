"""RSS 订阅源导出：把用户订阅大V的动态渲染成标准 RSS 2.0。

设计要点：
- 每个用户一个长随机 feed_token（等价订阅凭证），RSS 阅读器无需登录即可拉取；
- 只导出该用户订阅大V的公开动态，不含任何渠道/账号信息；
- 时间统一转 RFC 2822（RSS 规范），解析失败回退抓取时间。
"""
from __future__ import annotations

import html
from datetime import datetime
from email.utils import format_datetime
from xml.etree import ElementTree

from .fetchers.base import CN_TZ, PLATFORM_LABELS, parse_published_at


def _pub_date(post: dict) -> str:
    dt = parse_published_at(post.get("published_at") or "") or parse_published_at(
        post.get("fetched_at") or ""
    )
    if dt is None:
        return format_datetime(datetime.now(CN_TZ))
    return format_datetime(dt)


def _item_title(post: dict) -> str:
    platform = PLATFORM_LABELS.get(post.get("platform") or "", post.get("platform") or "")
    kol = post.get("kol_name") or ""
    kind = " · 回复" if post.get("post_type") == "reply" else ""
    body = (post.get("content") or post.get("title") or "").strip().replace("\n", " ")
    snippet = (body or "（无正文）")[:60]
    return f"[{platform}] {kol}{kind}：{snippet}"


def _item_description(post: dict) -> str:
    """正文 + 分类 + 原文链接；换行转 <br> 方便阅读器显示。"""
    body = html.escape((post.get("content") or post.get("title") or "").strip())
    parts = []
    if post.get("category_name"):
        parts.append(f"<p>🗂 {html.escape(str(post['category_name']))}</p>")
    if body:
        parts.append(f"<p>{body.replace(chr(10), '<br>')}</p>")
    if post.get("url"):
        parts.append(f'<p><a href="{html.escape(str(post["url"]))}">查看原文</a></p>')
    return "".join(parts)


def build_rss_xml(posts: list[dict], username: str, site_url: str) -> str:
    """渲染 RSS 2.0 XML（posts 为 db.list_feed_posts 的行 dict）。"""
    rss = ElementTree.Element("rss", {"version": "2.0"})
    channel = ElementTree.SubElement(rss, "channel")
    ElementTree.SubElement(channel, "title").text = f"V Push · {username} 的关注动态"
    ElementTree.SubElement(channel, "link").text = site_url or "https://localhost"
    ElementTree.SubElement(channel, "description").text = (
        f"{username} 在自托管V Push上关注的大V动态（雪球/微博/X）。"
    )
    ElementTree.SubElement(channel, "language").text = "zh-cn"
    ElementTree.SubElement(channel, "generator").text = "vpush"
    for post in posts:
        item = ElementTree.SubElement(channel, "item")
        ElementTree.SubElement(item, "title").text = _item_title(post)
        ElementTree.SubElement(item, "link").text = post.get("url") or site_url or ""
        ElementTree.SubElement(
            item, "guid", {"isPermaLink": "false"}
        ).text = f"{post.get('platform')}/{post.get('external_id')}"
        ElementTree.SubElement(item, "pubDate").text = _pub_date(post)
        ElementTree.SubElement(item, "description").text = _item_description(post)
        images = post.get("images") or []
        if images:
            ElementTree.SubElement(
                item, "enclosure",
                {
                    "url": images[0],
                    "type": "image/jpeg",
                    "length": "0",
                },
            )
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ElementTree.tostring(
        rss, encoding="unicode", short_empty_elements=True
    )
