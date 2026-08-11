"""企业微信群机器人 webhook 通知（官方 webhook 接口）。

文档：https://developer.work.weixin.qq.com/document/path/99110
每个群机器人有独立的 webhook URL，markdown 消息最大 4096 字节，
频率限制 20 条/分钟（超出返回 errcode=45009，会按失败重试处理）。
"""
from __future__ import annotations

import httpx

from ..fetchers.base import Post, digest_body
from .base import Notifier

PLATFORM_LABELS = {"xueqiu": "雪球", "combination": "雪球组合", "weibo": "微博", "twitter": "X/Twitter"}
DIGEST_MAX_ITEMS = 5
DND_MAX_ITEMS = 10
MAX_CONTENT_CHARS = 1800  # 保守截断，避开 4096 字节上限


def _md_escape(text: str) -> str:
    """轻量清理：正文里出现 markdown 特殊符时避免破坏排版。"""
    text = text.replace("\r", " ")
    text = text.replace("\n", " ").strip()
    # 行首 # 会触发标题语法，转义为字面量
    while text.startswith("#"):
        text = text[1:]
    return text[:MAX_CONTENT_CHARS]


def build_wecom_text(post: Post, favorite: bool = False, keyword: bool = False) -> str:
    platform = PLATFORM_LABELS.get(post.platform, post.platform)
    body = _md_escape(post.content or post.title or "（无正文）")
    kind = " · 回复" if post.post_type == "reply" else ""
    star = "⭐ " if favorite else ""
    key = "🔑 " if keyword else ""
    lines = [f"**📌 {star}{key}{post.kol_name} · {platform}{kind}**", "", body]
    if post.category:
        lines.append(f"🗂 {post.category}")
    if post.published_at:
        lines.append(f"🕐 {post.published_at}")
    if post.url:
        lines.append(f"[查看原文]({post.url})")
    return "\n".join(lines)


def build_wecom_combination_text(post: Post) -> str:
    """组合调仓专用排版：收益统计 + 分组调仓明细。"""
    detail = post.detail or {}
    stats = detail.get("stats") or []
    actions = detail.get("actions") or []
    cash = detail.get("cash") or ""
    lines = [f"**📌 {post.kol_name} · 雪球组合 · 调仓**", ""]
    if stats:
        lines.append("　".join(f"**{k}** {v}" for k, v in stats))
        lines.append("")
    for a in actions:
        a_type = a.get("type") or "调整"
        icon = {"清仓": "🗑", "新建": "🆕", "增持": "➕", "减持": "➖"}.get(a_type, "•")
        head = f"{icon} **{a_type}** {a.get('stock') or ''}"
        symbol = a.get("symbol") or ""
        if symbol:
            head += f"（{symbol}）"
        lines.append(head)
        lines.append(f"{a.get('prev') or '0.0%'} → {a.get('target') or '0.0%'}")
        lines.append("")
    if cash:
        lines.append(f"💵 现金 **{cash}**")
    if post.published_at:
        lines.append(f"🕐 {post.published_at}")
    if post.url:
        lines.append(f"[查看原文]({post.url})")
    return "\n".join(lines).rstrip()


def build_wecom_digest(posts: list[Post], kol_name: str, platform: str) -> str:
    platform_label = PLATFORM_LABELS.get(platform, platform)
    lines = [f"**📌 {kol_name} · {platform_label}**（{len(posts)} 条新动态）", ""]
    numbered = len(posts) > 1
    for i, post in enumerate(posts[:DIGEST_MAX_ITEMS], 1):
        body = _md_escape(digest_body(post, full=len(posts) == 1))
        prefix = f"{i}. " if numbered else ""
        lines.append(f"{prefix}{body}")
        meta_parts = []
        if post.published_at:
            meta_parts.append(f"🕐 {post.published_at}")
        if post.url:
            meta_parts.append(f"[查看原文]({post.url})")
        if meta_parts:
            lines.append("　" + " · ".join(meta_parts))
        lines.append("")
    if len(posts) > DIGEST_MAX_ITEMS:
        lines.append(f"… 还有 {len(posts) - DIGEST_MAX_ITEMS} 条未展示")
    return "\n".join(lines).rstrip()


def build_wecom_daily(posts: list[Post]) -> str:
    lines = ["**📊 今日大V精选**", ""]
    ordered = [p for p in posts if p.favorite] + [p for p in posts if not p.favorite]
    for i, post in enumerate(ordered[:DIGEST_MAX_ITEMS], 1):
        star = "⭐ " if post.favorite else ""
        body = _md_escape(digest_body(post, full=False, max_chars=100))
        lines.append(f"{i}. **{star}{post.kol_name}**：{body}")
        meta_parts = []
        if post.published_at:
            meta_parts.append(f"🕐 {post.published_at}")
        if post.url:
            meta_parts.append(f"[查看原文]({post.url})")
        if meta_parts:
            lines.append("　" + " · ".join(meta_parts))
        lines.append("")
    if len(posts) > DIGEST_MAX_ITEMS:
        lines.append(f"… 还有 {len(posts) - DIGEST_MAX_ITEMS} 条未展示")
    return "\n".join(lines).rstrip()


def build_wecom_dnd_summary(posts: list[Post], title: str | None = None) -> str:
    heading = title or "📵 免打扰时段汇总"
    lines = [f"**{heading}**（{len(posts)} 条新动态）", ""]
    numbered = len(posts) > 1
    for i, post in enumerate(posts[:DND_MAX_ITEMS], 1):
        body = _md_escape(digest_body(post, full=False, max_chars=100))
        prefix = f"{i}. " if numbered else ""
        line = f"{prefix}**{post.kol_name}** · {body}"
        if post.published_at:
            line += f"\n🕐 {post.published_at}"
        lines.append(line)
    if len(posts) > DND_MAX_ITEMS:
        lines.append(f"… 还有 {len(posts) - DND_MAX_ITEMS} 条未展示")
    first_url = next((p.url for p in posts if p.url), "")
    if first_url:
        lines.append(f"[查看全部]({first_url})")
    return "\n".join(lines).rstrip()


def is_valid_wecom_webhook(url: str) -> bool:
    """校验企业微信群机器人 webhook 地址格式。"""
    return url.startswith("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=")


class WeComNotifier(Notifier):
    channel = "wecom"

    def __init__(
        self,
        config,
        client: httpx.Client | None = None,
        webhook_url: str | None = None,
        favorite: bool = False,
        keyword: bool = False,
    ):
        self.webhook_url = webhook_url or config.webhook_url
        self.client = client or httpx.Client(timeout=15)
        self.favorite = favorite
        self.keyword = keyword

    def _send_markdown(self, content: str) -> None:
        if not self.webhook_url:
            raise RuntimeError("未配置企业微信 webhook_url")
        resp = self.client.post(
            self.webhook_url,
            json={"msgtype": "markdown", "markdown": {"content": content}},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode") not in (None, 0):
            raise RuntimeError(f"企业微信返回错误: {data.get('errmsg', data)}")

    def notify(self, post: Post) -> None:
        text = (
            build_wecom_combination_text(post)
            if post.platform == "combination" and post.detail
            else build_wecom_text(post, self.favorite, self.keyword)
        )
        self._send_markdown(text)

    def send_digest(self, posts: list[Post], kol_name: str, platform: str) -> None:
        self._send_markdown(build_wecom_digest(posts, kol_name, platform))

    def send_daily(self, posts: list[Post]) -> None:
        self._send_markdown(build_wecom_daily(posts))

    def send_dnd_summary(self, posts: list[Post], title: str | None = None) -> None:
        self._send_markdown(build_wecom_dnd_summary(posts, title=title))

    def send_text(self, text: str, reply_markup: list | None = None) -> None:
        self._send_markdown(text)
