"""Telegram Bot API 通知。"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from html import escape

import httpx

from ..fetchers.base import Post
from .base import Notifier

PLATFORM_LABELS = {"xueqiu": "雪球", "combination": "雪球组合", "weibo": "微博", "twitter": "X/Twitter"}
DIGEST_MAX_ITEMS = 10
# Telegram 单 bot 全局约 30 条/秒；广播推送时留足余量，避免触发 429。
# 高水位保护：发送频率低于上限时零开销，瞬时积压时自动平滑限速。
TG_MAX_MESSAGES_PER_SECOND = 15


class _RateLimiter:
    """滑动窗口限速器：窗口内未超限时立即放行（高水位保护）。"""

    def __init__(self, max_per_second: int):
        self._max = max_per_second
        self._times: deque[float] = deque()
        self._lock = threading.Lock()

    def wait(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                cutoff = now - 1.0
                while self._times and self._times[0] <= cutoff:
                    self._times.popleft()
                if len(self._times) < self._max:
                    self._times.append(now)
                    return
                delay = self._times[0] + 1.0 - now
            time.sleep(max(delay, 0.01))


_tg_rate_limiter = _RateLimiter(TG_MAX_MESSAGES_PER_SECOND)


def build_telegram_text(post: Post) -> str:
    platform = PLATFORM_LABELS.get(post.platform, post.platform)
    body = post.content[:200] or post.title or "（无正文）"
    kind = " · 回复" if post.post_type == "reply" else ""
    lines = [
        f"<b>📌 {escape(post.kol_name)} · {platform}{kind}</b>",
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


def build_combination_text(post: Post) -> str:
    """组合调仓专用排版：收益统计 + 分组调仓明细，信息分层、留白更清晰。"""
    detail = post.detail or {}
    stats = detail.get("stats") or []
    actions = detail.get("actions") or []
    cash = detail.get("cash") or ""
    lines = [f"<b>📌 {escape(post.kol_name)} · 雪球组合 · 调仓</b>", ""]
    if stats:
        lines.append("　".join(f"<b>{escape(k)}</b> {escape(v)}" for k, v in stats))
        lines.append("")
    for a in actions:
        a_type = a.get("type") or "调整"
        icon = {"清仓": "🗑", "新建": "🆕", "增持": "➕", "减持": "➖"}.get(a_type, "•")
        head = f"{icon} <b>{escape(a_type)}</b>　{escape(a.get('stock') or '')}"
        symbol = a.get("symbol") or ""
        if symbol:
            head += f"（{escape(symbol)}）"
        lines.append(head)
        lines.append(f"　　{escape(a.get('prev') or '0.0%')} → {escape(a.get('target') or '0.0%')}")
        lines.append("")
    if cash:
        lines.append(f"💵 现金 <b>{escape(cash)}</b>")
    if post.published_at:
        lines.append(f"🕐 {escape(post.published_at)}")
    if post.url:
        lines.append(f'🔗 <a href="{escape(post.url)}">查看原文</a>')
    return "\n".join(lines).rstrip()


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
        _tg_rate_limiter.wait()
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        resp = self.client.post(url, data={"chat_id": self.chat_id, **data})
        resp.raise_for_status()
        result = resp.json()
        # 429 限流：按 Telegram 给出的 retry_after 等待后重试一次
        if not result.get("ok") and result.get("error_code") == 429:
            retry_after = int(
                (result.get("parameters") or {}).get("retry_after") or 1
            )
            time.sleep(retry_after)
            _tg_rate_limiter.wait()
            resp = self.client.post(url, data={"chat_id": self.chat_id, **data})
            resp.raise_for_status()
            result = resp.json()
        if not result.get("ok"):
            raise RuntimeError(f"Telegram 返回错误: {result}")

    def notify(self, post: Post) -> None:
        keyboard = [[{"text": "🔗 查看原文", "url": post.url}]]
        if self.unsub_kol_id is not None:
            keyboard.append([{"text": "退订", "callback_data": f"unsub:{self.unsub_kol_id}"}])
        text = (
            build_combination_text(post)
            if post.platform == "combination" and post.detail
            else build_telegram_text(post)
        )
        self._send(
            {
                "text": text,
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
        _tg_rate_limiter.wait()
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
