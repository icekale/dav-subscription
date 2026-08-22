"""Telegram Rich HTML 拼装（sendRichMessage 的 html 字段）。不发网络。"""
from __future__ import annotations

from html import escape

from ..fetchers.base import PLATFORM_LABELS, Post, attachment_lines, show_original, truncate_text
from .base import why_badges

BODY_LIMIT = 2000
DIGEST_MAX_ITEMS = 10
DND_MAX_ITEMS = 10
RICH_IMAGE_MAX = 9


def _e(text: str) -> str:
    return escape(text or "", quote=True)


def _p(text: str) -> str:
    return f"<p>{_e(text)}</p>"


def _heading(text: str, level: int = 2) -> str:
    tag = f"h{min(max(level, 1), 6)}"
    return f"<{tag}>{_e(text)}</{tag}>"


def _paragraphs(text: str) -> str:
    chunks = [c for c in (text or "").split("\n") if c.strip()]
    if not chunks:
        return _p("（无正文）")
    return "".join(_p(c) for c in chunks)


def _a(url: str, label: str) -> str:
    return f'<a href="{_e(url)}">{_e(label)}</a>'


def _table(headers: list[str], rows: list[list[str]], caption: str = "") -> str:
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in row) + "</tr>" for row in rows)
    cap = f"<caption>{_e(caption)}</caption>" if caption else ""
    return f"<table>{cap}<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _original_link(post: Post) -> str:
    if not show_original(post.platform, post.url):
        return ""
    return f"<p>{_a(post.url, '查看原文')}</p>"


def build_telegram_rich_html(post: Post, favorite: bool = False, keyword: bool = False) -> str:
    platform = PLATFORM_LABELS.get(post.platform, post.platform)
    kind = " · 回复" if post.post_type == "reply" else ""
    title = f"{post.kol_name} · {platform}{kind}"
    body = truncate_text(post.content, BODY_LIMIT) or post.title or "（无正文）"
    parts = [_heading(title, 2)]
    badges = why_badges(favorite, keyword)
    if badges:
        parts.append(_p(badges))
    body_html = _paragraphs(body)
    if post.post_type == "reply":
        body_html = f"<blockquote>{body_html}</blockquote>"
    parts.append(body_html)
    parts.append("<hr>")
    meta: list[str] = []
    if post.category:
        meta.append(post.category)
    tags = post.tags or []
    if tags:
        meta.append(" · ".join(tags))
    if post.published_at:
        meta.append(str(post.published_at))
    if meta:
        parts.append(_p(" · ".join(meta)))
    for line in attachment_lines(post):
        parts.append(_p(line))
    parts.append(_original_link(post))
    return "".join(parts)
