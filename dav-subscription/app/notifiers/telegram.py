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
    lines = [
        f"<b>{title}</b>",
        "",
        content,
        "",
        f"📌 {escape(post.kol_name)} · {platform}",
    ]
    if post.category:
        lines.append(f"🗂 {escape(post.category)}")
    lines.extend(
        [
            f"🕐 {escape(post.published_at)}",
            f'🔗 <a href="{escape(post.url)}">查看原文</a>',
        ]
    )
    return "\n".join(lines)


class TelegramNotifier(Notifier):
    channel = "telegram"

    def __init__(self, config, client: httpx.Client | None = None, chat_id: str | None = None):
        self.bot_token = config.bot_token
        self.chat_id = chat_id or config.chat_id
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
