"""Telegram Bot API 通知。"""
from __future__ import annotations

import json
from html import escape

import httpx

from ..fetchers.base import Post
from .base import Notifier

PLATFORM_LABELS = {"xueqiu": "雪球", "weibo": "微博", "twitter": "X/Twitter"}
DIGEST_MAX_ITEMS = 10


def build_telegram_text(post: Post) -> str:
    platform = PLATFORM_LABELS.get(post.platform, post.platform)
    body = post.content[:200] or post.title or "（无正文）"
    lines = [
        f"<b>📌 {escape(post.kol_name)} · {platform}</b>",
        "",
        escape(body),
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


def build_telegram_digest(posts: list[Post], kol_name: str, platform: str) -> str:
    """合并摘要：同一大V多条新动态合并成一条消息。"""
    platform_label = PLATFORM_LABELS.get(platform, platform)
    lines = [
        f"<b>📌 {escape(kol_name)} · {platform_label}</b>（{len(posts)} 条新动态）",
        "",
    ]
    for i, post in enumerate(posts[:DIGEST_MAX_ITEMS], 1):
        body = (post.content[:120] or post.title or "（无正文）").replace("\n", " ")
        lines.append(f"{i}. {escape(body)}")
        time_line = f"🕐 {escape(post.published_at)}" if post.published_at else ""
        link = f'🔗 <a href="{escape(post.url)}">查看原文</a>' if post.url else ""
        meta = " · ".join(x for x in (time_line, link) if x)
        if meta:
            lines.append(f"　{meta}")
        lines.append("")
    if len(posts) > DIGEST_MAX_ITEMS:
        lines.append(f"… 还有 {len(posts) - DIGEST_MAX_ITEMS} 条未展示")
    return "\n".join(lines).rstrip()


def build_telegram_daily(posts: list[Post]) -> str:
    """每日精选：把用户订阅的所有大V今日动态汇总成一条。"""
    lines = ["<b>📊 今日大V精选</b>", ""]
    for i, post in enumerate(posts[:DIGEST_MAX_ITEMS], 1):
        body = (post.content[:100] or post.title or "（无正文）").replace("\n", " ")
        lines.append(f"{i}. <b>{escape(post.kol_name)}</b>：{escape(body)}")
        meta_parts = []
        if post.published_at:
            meta_parts.append(f"🕐 {escape(post.published_at)}")
        if post.url:
            meta_parts.append(f'🔗 <a href="{escape(post.url)}">查看原文</a>')
        if meta_parts:
            lines.append(f"　{' · '.join(meta_parts)}")
        lines.append("")
    if len(posts) > DIGEST_MAX_ITEMS:
        lines.append(f"… 还有 {len(posts) - DIGEST_MAX_ITEMS} 条未展示")
    return "\n".join(lines).rstrip()


class TelegramNotifier(Notifier):
    channel = "telegram"

    def __init__(
        self,
        config,
        client: httpx.Client | None = None,
        chat_id: str | None = None,
        unsub_kol_id: int | None = None,
    ):
        self.bot_token = config.bot_token
        self.chat_id = chat_id or config.chat_id
        self.client = client or httpx.Client(timeout=15, proxy=config.proxy or None)
        self.unsub_kol_id = unsub_kol_id

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
        keyboard = [[{"text": "🔗 查看原文", "url": post.url}]]
        if self.unsub_kol_id is not None:
            keyboard.append([{"text": "退订", "callback_data": f"unsub:{self.unsub_kol_id}"}])
        self._send(
            {
                "text": build_telegram_text(post),
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "reply_markup": json.dumps({"inline_keyboard": keyboard}, ensure_ascii=False),
            }
        )

    def send_digest(self, posts: list[Post], kol_name: str, platform: str) -> None:
        keyboard = None
        first_url = next((p.url for p in posts if p.url), "")
        if first_url:
            keyboard = json.dumps(
                {
                    "inline_keyboard": [
                        [{"text": "🔗 查看全部", "url": first_url}]
                    ]
                },
                ensure_ascii=False,
            )
        data = {
            "text": build_telegram_digest(posts, kol_name, platform),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if keyboard:
            data["reply_markup"] = keyboard
        self._send(data)

    def send_daily(self, posts: list[Post]) -> None:
        self._send(
            {
                "text": build_telegram_daily(posts),
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
        )

    def send_text(self, text: str) -> None:
        self._send({"text": text})

    def send_photo(self, photo: bytes, caption: str = "") -> None:
        if not self.bot_token or not self.chat_id:
            raise RuntimeError("未配置 telegram bot_token/chat_id")
        url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
        resp = self.client.post(
            url,
            data={"chat_id": self.chat_id, "caption": caption},
            files={"photo": ("qr.png", photo, "image/png")},
        )
        resp.raise_for_status()
        result = resp.json()
        if not result.get("ok"):
            raise RuntimeError(f"Telegram 返回错误: {result}")
