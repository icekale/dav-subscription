"""Telegram Rich HTML 拼装（sendRichMessage 的 html 字段）。不发网络。"""
from __future__ import annotations

from html import escape

from ..fetchers.base import PLATFORM_LABELS, Post, digest_body, truncate_text
from .base import why_badges

ACTION_MARK = {"清仓": "🗑", "新建": "🆕", "增持": "➕", "减持": "➖"}

BODY_LIMIT = 2000
DIGEST_MAX_ITEMS = 10
DND_MAX_ITEMS = 10
RICH_IMAGE_MAX = 9


def _e(text: str, *, attr: bool = False) -> str:
    return escape(text or "", quote=attr)


def _p(text: str) -> str:
    return f"<p>{_e(text)}</p>"


def _em(text: str) -> str:
    text = (text or "").strip()
    return f"<p><em>{_e(text)}</em></p>" if text else ""


def _heading(text: str, level: int = 4) -> str:
    """Telegram 客户端里 h1–h6 视觉上几乎同大，标题改成正文加粗。"""
    del level
    return f"<p><b>{_e(text)}</b></p>"


def action_label(a_type: str) -> str:
    mark = ACTION_MARK.get(a_type, "•")
    return f"{mark} {a_type}"


def _note(text: str) -> str:
    text = (text or "").strip()
    return f"<footer>{_e(text)}</footer>" if text else ""


def _paragraphs(text: str) -> str:
    """空行分段；段内换行收成 <br>，避免一行一个段落。"""
    raw = (text or "").replace("\r\n", "\n").strip()
    blocks = [b.strip() for b in raw.split("\n\n") if b.strip()]
    if not blocks:
        return ""
    parts: list[str] = []
    for block in blocks:
        lines = [_e(line.strip()) for line in block.split("\n") if line.strip()]
        if lines:
            parts.append(f"<p>{'<br>'.join(lines)}</p>")
    return "".join(parts)


def _a(url: str, label: str) -> str:
    return f'<a href="{_e(url, attr=True)}">{_e(label)}</a>'


def _table(
    headers: list[str],
    rows: list[list[str]],
    caption: str = "",
    *,
    striped: bool = False,
) -> str:
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in row) + "</tr>" for row in rows)
    cap = f"<caption>{_e(caption)}</caption>" if caption else ""
    attrs = " striped" if striped else ""
    return f"<table{attrs}>{cap}<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _footer(parts: list[str]) -> str:
    return _note(" · ".join(p for p in parts if p))


def _reason(favorite: bool, keyword: bool) -> str:
    return _em(why_badges(favorite, keyword))


def _file_block(post: Post) -> str:
    files = ((post.detail or {}).get("files") or []) if post.detail else []
    links: list[str] = []
    for item in files:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "附件")
        url = str(item.get("url") or "")
        if url.startswith(("http://", "https://")):
            links.append(_a(url, f"📎 {name}"))
    if not links:
        return ""
    return f"<p>{' · '.join(links)}</p>{_note('附件链接可能过期')}"


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


def _overflow(n: int, items_html: str) -> str:
    if n <= 0:
        return ""
    return f"<details><summary>{_e(f'还有 {n} 条')}</summary><ol>{items_html}</ol></details>"


def _when(post: Post) -> str:
    return (post.published_at or "").strip()


def _clock(when: str) -> str:
    when = (when or "").strip()
    return f"🕐 {when}" if when else ""


def _item_inner(
    post: Post, *, named: bool, full: bool, max_chars: int, mark_favorite: bool = False
) -> str:
    excerpt = digest_body(post, full=full, max_chars=max_chars)
    star = "⭐ " if mark_favorite and post.favorite else ""
    if full:
        body = _paragraphs(excerpt) or _p(excerpt)
        lead = _p(f"{star}{post.kol_name}") if named else ""
        return f"{lead}{body}{_note(_clock(_when(post)))}"
    lead = f"<b>{_e(star + post.kol_name)}</b> " if named else ""
    when = _when(post)
    tail = f" · <em>🕐 {_e(when)}</em>" if when else ""
    return f"{lead}{_e(excerpt)}{tail}"


def _item_list(
    posts: list[Post],
    *,
    named: bool,
    full: bool = False,
    max_chars: int = 100,
    mark_favorite: bool = False,
) -> str:
    if not posts:
        return ""
    if len(posts) == 1:
        inner = _item_inner(
            posts[0], named=named, full=full, max_chars=max_chars, mark_favorite=mark_favorite
        )
        return inner if full else f"<p>{inner}</p>"
    return (
        "<ol>"
        + "".join(
            f"<li>{_item_inner(p, named=named, full=False, max_chars=max_chars, mark_favorite=mark_favorite)}</li>"
            for p in posts
        )
        + "</ol>"
    )


def build_combination_rich_html(post: Post) -> str:
    detail = post.detail or {}
    stats = detail.get("stats") or []
    actions = detail.get("actions") or []
    cash = detail.get("cash") or ""
    parts = [_heading(f"📌 {post.kol_name} · 雪球组合 · 调仓")]
    if stats:
        parts.append(_p(" · ".join(f"{k} {v}" for k, v in stats)))
    if actions:
        rows = []
        for a in actions:
            stock = a.get("stock") or ""
            symbol = a.get("symbol") or ""
            name = f"{stock}（{symbol}）" if symbol else stock
            a_type = str(a.get("type") or "调整")
            rows.append(
                [
                    action_label(a_type),
                    name,
                    f"{a.get('prev') or '0.0%'} → {a.get('target') or '0.0%'}",
                ]
            )
        parts.append(_table(["操作", "标的", "仓位"], rows, striped=True))
    foot = []
    if cash:
        foot.append(f"💵 现金 {cash}")
    if post.published_at:
        foot.append(_clock(str(post.published_at)))
    parts.append(_footer(foot))
    return "".join(parts)


def build_telegram_rich_html(post: Post, favorite: bool = False, keyword: bool = False) -> str:
    platform = PLATFORM_LABELS.get(post.platform, post.platform)
    kind = " · 回复" if post.post_type == "reply" else ""
    body = truncate_text(post.content, BODY_LIMIT) or post.title or "（无正文）"
    parts = [_heading(f"📌 {post.kol_name} · {platform}{kind}"), _reason(favorite, keyword)]
    body_html = _paragraphs(body) or _p(body)
    if post.post_type == "reply":
        body_html = f"<blockquote>{body_html}</blockquote>"
    parts.append(body_html)
    parts.append(_media_block(post.images or []))
    tags = post.tags or []
    category = f"🗂 {post.category}" if post.category else ""
    parts.append(_footer([category, " · ".join(tags)]))
    parts.append(_note(_clock(_when(post))))
    parts.append(_file_block(post))
    return "".join(parts)


def build_telegram_digest_rich(posts: list[Post], kol_name: str, platform: str) -> str:
    platform_label = PLATFORM_LABELS.get(platform, platform)
    visible, extra = posts[:DIGEST_MAX_ITEMS], posts[DIGEST_MAX_ITEMS:]
    parts = [
        _heading(f"📌 {kol_name} · {platform_label}"),
        _item_list(visible, named=False, full=len(posts) == 1, max_chars=120),
        _overflow(
            len(extra),
            "".join(f"<li>{_item_inner(p, named=False, full=False, max_chars=100)}</li>" for p in extra),
        ),
    ]
    return "".join(parts)


def build_telegram_daily_rich(posts: list[Post]) -> str:
    ordered = [p for p in posts if p.favorite] + [p for p in posts if not p.favorite]
    visible, extra = ordered[:DIGEST_MAX_ITEMS], ordered[DIGEST_MAX_ITEMS:]
    parts = [
        _heading("📊 今日大V精选"),
        _item_list(visible, named=True, mark_favorite=True),
        _overflow(
            len(extra),
            "".join(
                f"<li>{_item_inner(p, named=True, full=False, max_chars=100, mark_favorite=True)}</li>"
                for p in extra
            ),
        ),
    ]
    return "".join(parts)


def build_telegram_dnd_rich(posts: list[Post], title: str | None = None) -> str:
    heading = title or "📵 免打扰时段汇总"
    visible, extra = posts[:DND_MAX_ITEMS], posts[DND_MAX_ITEMS:]
    parts = [
        _heading(heading),
        _item_list(visible, named=True),
        _overflow(
            len(extra),
            "".join(f"<li>{_item_inner(p, named=True, full=False, max_chars=100)}</li>" for p in extra),
        ),
    ]
    return "".join(parts)
