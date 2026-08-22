"""Telegram Rich HTML 拼装（sendRichMessage 的 html 字段）。不发网络。"""
from __future__ import annotations

from html import escape

from ..fetchers.base import PLATFORM_LABELS, Post, attachment_lines, digest_body, show_original, truncate_text
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


def _https_images(images: list[str]) -> list[str]:
    urls = [u for u in images if isinstance(u, str) and u.startswith(("http://", "https://"))]
    return urls[:RICH_IMAGE_MAX]


def build_rich_message_media(images: list[str]) -> list[dict]:
    """Bot API 10.2：html 里的 tg://photo?id= 必须对应 rich_message.media。"""
    return [
        {"id": f"p{i}", "media": {"type": "photo", "media": url}}
        for i, url in enumerate(_https_images(images))
    ]


def _media_block(images: list[str]) -> str:
    urls = _https_images(images)
    if not urls:
        return ""
    imgs = "".join(f'<img src="tg://photo?id=p{i}">' for i in range(len(urls)))
    if len(urls) == 1:
        return f"<figure>{imgs}</figure>"
    return f"<tg-collage>{imgs}</tg-collage>"


def build_combination_rich_html(post: Post) -> str:
    detail = post.detail or {}
    stats = detail.get("stats") or []
    actions = detail.get("actions") or []
    cash = detail.get("cash") or ""
    parts = [_heading(f"{post.kol_name} · 雪球组合 · 调仓", 2)]
    if stats:
        rows = [[str(k), str(v)] for k, v in stats]
        parts.append(_table(["指标", "数值"], rows))
    if actions:
        rows = []
        for a in actions:
            stock = a.get("stock") or ""
            symbol = a.get("symbol") or ""
            name = f"{stock}（{symbol}）" if symbol else stock
            rows.append(
                [
                    str(a.get("type") or "调整"),
                    name,
                    str(a.get("prev") or "0.0%"),
                    str(a.get("target") or "0.0%"),
                ]
            )
        parts.append(_table(["操作", "标的", "原仓位", "目标仓位"], rows))
    if cash:
        parts.append(_p(f"现金 {cash}"))
    if post.published_at:
        parts.append(_p(str(post.published_at)))
    parts.append(_original_link(post))
    return "".join(parts)


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
    parts.append(_media_block(post.images or []))
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


def build_telegram_digest_rich(posts: list[Post], kol_name: str, platform: str) -> str:
    platform_label = PLATFORM_LABELS.get(platform, platform)
    parts = [_heading(f"{kol_name} · {platform_label}（{len(posts)} 条新动态）", 2)]
    visible, extra = posts[:DIGEST_MAX_ITEMS], posts[DIGEST_MAX_ITEMS:]
    full = len(posts) == 1
    lis = "".join(f"<li>{_e(digest_body(p, full=full))}</li>" for p in visible)
    parts.append(f"<ol>{lis}</ol>")
    if extra:
        more = "".join(f"<li>{_e(digest_body(p, full=False))}</li>" for p in extra)
        parts.append(
            f"<details><summary>{_e(f'还有 {len(extra)} 条未展示')}</summary><ol>{more}</ol></details>"
        )
    return "".join(parts)


def build_telegram_daily_rich(posts: list[Post]) -> str:
    ordered = [p for p in posts if p.favorite] + [p for p in posts if not p.favorite]
    visible, extra = ordered[:DIGEST_MAX_ITEMS], ordered[DIGEST_MAX_ITEMS:]
    rows = []
    for post in visible:
        rows.append(
            [
                "是" if post.favorite else "",
                post.kol_name,
                digest_body(post, full=False, max_chars=100),
                post.published_at or "",
            ]
        )
    parts = [_heading("今日大V精选", 2), _table(["关注", "大V", "摘要", "时间"], rows)]
    if extra:
        more = "".join(
            f"<li><b>{_e(p.kol_name)}</b> {_e(digest_body(p, full=False, max_chars=100))}</li>"
            for p in extra
        )
        parts.append(
            f"<details><summary>{_e(f'还有 {len(extra)} 条未展示')}</summary><ol>{more}</ol></details>"
        )
    return "".join(parts)


def build_telegram_dnd_rich(posts: list[Post], title: str | None = None) -> str:
    heading = title or "免打扰时段汇总"
    parts = [_heading(f"{heading}（{len(posts)} 条新动态）", 2)]
    visible, extra = posts[:DND_MAX_ITEMS], posts[DND_MAX_ITEMS:]
    lis = "".join(
        f"<li><b>{_e(p.kol_name)}</b> {_e(digest_body(p, full=False, max_chars=100))}</li>"
        for p in visible
    )
    parts.append(f"<ol>{lis}</ol>")
    if extra:
        more = "".join(
            f"<li><b>{_e(p.kol_name)}</b> {_e(digest_body(p, full=False, max_chars=100))}</li>"
            for p in extra
        )
        parts.append(
            f"<details><summary>{_e(f'还有 {len(extra)} 条未展示')}</summary><ol>{more}</ol></details>"
        )
    return "".join(parts)
