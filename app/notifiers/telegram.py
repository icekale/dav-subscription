"""Telegram Bot API 通知。"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from html import escape

import httpx

from ..fetchers.base import (
    PLATFORM_LABELS,
    Post,
    attachment_lines,
    digest_body,
    show_original,
    truncate_text,
)
from ..url_safety import safe_get
from .base import Notifier, why_badges
from .telegram_rich import (
    DND_MAX_ITEMS,
    DIGEST_MAX_ITEMS,
    build_telegram_daily_rich,
    build_telegram_digest_rich,
    build_telegram_dnd_rich,
)

logger = logging.getLogger(__name__)
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


def build_telegram_text(post: Post, favorite: bool = False, keyword: bool = False) -> str:
    platform = PLATFORM_LABELS.get(post.platform, post.platform)
    body = truncate_text(post.content, 2000) or post.title or "（无正文）"
    kind = " · 回复" if post.post_type == "reply" else ""
    badges = why_badges(favorite, keyword)
    lines = [f"<b>📌 {escape(post.kol_name)} · {platform}{kind}</b>"]
    if badges:
        lines.append(badges)
    lines.extend(["", escape(body)])
    if post.category:
        lines.append(f"🗂 {escape(post.category)}")
    lines.extend(
        [
            f"🕐 {escape(post.published_at)}",
        ]
    )
    lines.extend(attachment_lines(post))
    if show_original(post.platform, post.url):
        lines.append(f'🔗 <a href="{escape(post.url)}">查看原文</a>')
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


def _numbered_url_rows(posts: list[Post], max_items: int) -> list[list[dict]]:
    """摘要/汇总的逐条查看按钮：编号 + 原文链接，每行最多 5 个。"""
    rows: list[list[dict]] = []
    row: list[dict] = []
    for i, post in enumerate(posts[:max_items], 1):
        if not show_original(post.platform, post.url):
            continue
        row.append({"text": f"{i} 🔗", "url": post.url})
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def build_telegram_digest(posts: list[Post], kol_name: str, platform: str) -> str:
    """合并摘要：同一大V多条新动态合并成一条消息。"""
    platform_label = PLATFORM_LABELS.get(platform, platform)
    lines = [
        f"<b>📌 {escape(kol_name)} · {platform_label}</b>（{len(posts)} 条新动态）",
        "",
    ]
    numbered = len(posts) > 1
    for i, post in enumerate(posts[:DIGEST_MAX_ITEMS], 1):
        body = digest_body(post, full=len(posts) == 1)
        prefix = f"{i}. " if numbered else ""
        lines.append(f"{prefix}{escape(body)}")
        time_line = f"🕐 {escape(post.published_at)}" if post.published_at else ""
        link = (
            f'🔗 <a href="{escape(post.url)}">查看原文</a>'
            if show_original(post.platform, post.url)
            else ""
        )
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
    ordered = [p for p in posts if p.favorite] + [p for p in posts if not p.favorite]
    for i, post in enumerate(ordered[:DIGEST_MAX_ITEMS], 1):
        star = "⭐ " if post.favorite else ""
        body = digest_body(post, full=False, max_chars=100)
        lines.append(f"{i}. <b>{star}{escape(post.kol_name)}</b>：{escape(body)}")
        meta_parts = []
        if post.published_at:
            meta_parts.append(f"🕐 {escape(post.published_at)}")
        if show_original(post.platform, post.url):
            meta_parts.append(f'🔗 <a href="{escape(post.url)}">查看原文</a>')
        if meta_parts:
            lines.append(f"　{' · '.join(meta_parts)}")
        lines.append("")
    if len(posts) > DIGEST_MAX_ITEMS:
        lines.append(f"… 还有 {len(posts) - DIGEST_MAX_ITEMS} 条未展示")
    return "\n".join(lines).rstrip()


def build_telegram_dnd_summary(posts: list[Post], title: str | None = None) -> str:
    """免打扰/次要大V汇总：一次列出缓冲的新动态（最多 10 条）。"""
    heading = title or "📵 免打扰时段汇总"
    lines = [f"<b>{escape(heading)}</b>（{len(posts)} 条新动态）", ""]
    numbered = len(posts) > 1
    for i, post in enumerate(posts[:DND_MAX_ITEMS], 1):
        body = digest_body(post, full=False, max_chars=100)
        prefix = f"{i}. " if numbered else ""
        lines.append(f"{prefix}<b>{escape(post.kol_name)}</b> · {escape(body)}")
        time_line = f"🕐 {escape(post.published_at)}" if post.published_at else ""
        link = f'🔗 <a href="{escape(post.url)}">原文</a>' if show_original(post.platform, post.url) else ""
        meta = " · ".join(x for x in (time_line, link) if x)
        if meta:
            lines.append(f"　{meta}")
        lines.append("")
    if len(posts) > DND_MAX_ITEMS:
        lines.append(f"… 还有 {len(posts) - DND_MAX_ITEMS} 条未展示")
    return "\n".join(lines).rstrip()


class TelegramNotifier(Notifier):
    channel = "telegram"

    def __init__(
        self,
        config,
        client: httpx.Client | None = None,
        chat_id: str | None = None,
        bot_token: str | None = None,
        favorite: bool = False,
        keyword: bool = False,
    ):
        # 用户自建 bot 时用用户自己的 token；否则用全局共享 bot
        self.bot_token = bot_token or config.bot_token
        self.chat_id = chat_id or config.chat_id
        self.client = client or httpx.Client(timeout=15, proxy=config.proxy or None)
        self.favorite = favorite
        self.keyword = keyword
        self.rich_messages = bool(getattr(config, "rich_messages", True))

    def _post(self, url: str, **kw) -> httpx.Response:
        """POST 并容忍瞬时网络故障：TLS 握手超时等 TransportError 立即重试一次。

        新请求会重新解析 DNS 并建立新连接，大概率避开被黑洞的 IP；
        仍失败则抛给外层（deliver_post 会记录失败并入重试队列兜底）。
        """
        try:
            return self.client.post(url, **kw)
        except httpx.TransportError:
            logger.warning("Telegram 网络瞬时故障，立即重试")
            return self.client.post(url, **kw)

    def _send_api(self, method: str, data: dict) -> None:
        if not self.bot_token or not self.chat_id:
            raise RuntimeError("未配置 telegram bot_token/chat_id")
        _tg_rate_limiter.wait()
        url = f"https://api.telegram.org/bot{self.bot_token}/{method}"
        resp = self._post(url, data=data)
        resp.raise_for_status()
        result = resp.json()
        # 429 限流：按 Telegram 给出的 retry_after 等待后重试一次
        if not result.get("ok") and result.get("error_code") == 429:
            retry_after = int(
                (result.get("parameters") or {}).get("retry_after") or 1
            )
            time.sleep(retry_after)
            _tg_rate_limiter.wait()
            resp = self._post(url, data=data)
            resp.raise_for_status()
            result = resp.json()
        if not result.get("ok"):
            raise RuntimeError(f"Telegram 返回错误: {result}")

    def _send(self, data: dict) -> None:
        self._send_api("sendMessage", {"chat_id": self.chat_id, **data})

    def _send_rich(self, html: str, reply_markup: list | None = None) -> None:
        payload: dict = {
            "chat_id": self.chat_id,
            "rich_message": json.dumps(
                {"html": html, "skip_entity_detection": True},
                ensure_ascii=False,
            ),
        }
        if reply_markup:
            payload["reply_markup"] = json.dumps(
                {"inline_keyboard": reply_markup},
                ensure_ascii=False,
            )
        self._send_api("sendRichMessage", payload)

    def _deliver(
        self,
        html: str,
        fallback_text: str,
        reply_markup: list | None = None,
    ) -> None:
        keyboard = reply_markup or []
        if self.rich_messages:
            try:
                self._send_rich(html, keyboard)
                return
            except Exception as exc:  # noqa: BLE001 — 任意失败都回退，保证送达
                if isinstance(exc, httpx.HTTPStatusError):
                    detail = f"{type(exc).__name__} {exc.response.status_code}"
                else:
                    detail = type(exc).__name__
                logger.warning("Telegram Rich Message 失败，回退 HTML: %s", detail)
        self._send(
            {
                "text": fallback_text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "reply_markup": json.dumps(
                    {"inline_keyboard": keyboard}, ensure_ascii=False
                ),
            }
        )

    def notify(self, post: Post) -> None:
        if post.platform == "combination" and post.detail:
            self._send_text_message(post)
            return
        if post.images:
            self._send_rich_with_images(post)
            return
        self._send_text_message(post)

    def _send_text_message(self, post: Post) -> None:
        from .telegram_rich import build_combination_rich_html, build_telegram_rich_html

        keyboard = (
            [[{"text": "🔗 查看原文", "url": post.url}]]
            if show_original(post.platform, post.url)
            else []
        )
        if post.platform == "combination" and post.detail:
            html = build_combination_rich_html(post)
            fallback = build_combination_text(post)
            self._deliver(html, fallback_text=fallback, reply_markup=keyboard)
            return
        html = build_telegram_rich_html(post, self.favorite, self.keyword)
        fallback = build_telegram_text(post, self.favorite, self.keyword)
        self._deliver(html, fallback_text=fallback, reply_markup=keyboard)

    def _send_rich_with_images(self, post: Post) -> None:
        from .telegram_rich import build_telegram_rich_html

        keyboard = (
            [[{"text": "🔗 查看原文", "url": post.url}]]
            if show_original(post.platform, post.url)
            else []
        )
        html = build_telegram_rich_html(post, self.favorite, self.keyword)
        if self.rich_messages:
            try:
                self._send_rich(html, keyboard)
                return
            except Exception as exc:  # noqa: BLE001
                # token-free log (do not stringify HTTPStatusError)
                detail = type(exc).__name__
                if isinstance(exc, httpx.HTTPStatusError):
                    detail = f"{detail} {exc.response.status_code}"
                logger.warning("Telegram Rich 配图失败，回退相册: %s", detail)
        fallback = build_telegram_text(post, self.favorite, self.keyword)
        self._send(
            {
                "text": fallback,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "reply_markup": json.dumps({"inline_keyboard": keyboard}, ensure_ascii=False),
            }
        )
        try:
            self._send_media_group(post)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Telegram 相册发送失败，降级为逐张发送: %s", type(exc).__name__)
            for image_url in post.images[:4]:
                try:
                    self._send_photo_url(image_url)
                except Exception as inner:  # noqa: BLE001
                    logger.warning("Telegram 图片发送失败 err=%s", type(inner).__name__)

    def _download_images(self, urls: list[str]) -> list[bytes]:
        blobs: list[bytes] = []
        for url in urls:
            try:
                resp = safe_get(self.client, url, timeout=12)
                if resp.status_code == 200 and resp.content:
                    blobs.append(resp.content)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Telegram 图片下载失败 url=%s err=%s", url, exc)
        return blobs

    def _send_media_group(self, post: Post) -> None:
        if not self.bot_token or not self.chat_id:
            raise RuntimeError("未配置 telegram bot_token/chat_id")
        urls = post.images[:4]
        blobs = self._download_images(urls)
        if len(blobs) == 1:
            self.send_photo(blobs[0])
            return
        if len(blobs) >= 2:
            media = [{"type": "photo", "media": f"attach://p{i}"} for i in range(len(blobs))]
            files = {f"p{i}": (f"p{i}.jpg", blob, "image/jpeg") for i, blob in enumerate(blobs)}
            self._post_media_group(media, files=files)
            return
        if len(urls) == 1:
            self._send_photo_url(urls[0])
            return
        media = [{"type": "photo", "media": url} for url in urls]
        self._post_media_group(media)

    def _post_media_group(self, media: list[dict], files: dict | None = None) -> None:
        _tg_rate_limiter.wait()
        kw: dict = {"data": {"chat_id": self.chat_id, "media": json.dumps(media, ensure_ascii=False)}}
        if files:
            kw["files"] = files
        resp = self._post(f"https://api.telegram.org/bot{self.bot_token}/sendMediaGroup", **kw)
        resp.raise_for_status()
        result = resp.json()
        if not result.get("ok"):
            raise RuntimeError(f"Telegram 返回错误: {result}")

    def _send_photo_url(self, photo_url: str, caption: str = "") -> None:
        if not self.bot_token or not self.chat_id:
            raise RuntimeError("未配置 telegram bot_token/chat_id")
        _tg_rate_limiter.wait()
        data = {"chat_id": self.chat_id, "photo": photo_url}
        if caption:
            data["caption"] = caption
        resp = self._post(
            f"https://api.telegram.org/bot{self.bot_token}/sendPhoto",
            data=data,
        )
        resp.raise_for_status()
        result = resp.json()
        if not result.get("ok"):
            raise RuntimeError(f"Telegram 返回错误: {result}")

    def send_digest(self, posts: list[Post], kol_name: str, platform: str) -> None:
        self._deliver(
            build_telegram_digest_rich(posts, kol_name, platform),
            fallback_text=build_telegram_digest(posts, kol_name, platform),
            reply_markup=_numbered_url_rows(posts, DIGEST_MAX_ITEMS),
        )

    def send_daily(self, posts: list[Post]) -> None:
        self._deliver(
            build_telegram_daily_rich(posts),
            fallback_text=build_telegram_daily(posts),
        )

    def send_dnd_summary(self, posts: list[Post], title: str | None = None) -> None:
        self._deliver(
            build_telegram_dnd_rich(posts, title),
            fallback_text=build_telegram_dnd_summary(posts, title=title),
            reply_markup=_numbered_url_rows(posts, DND_MAX_ITEMS),
        )

    def send_text(self, text: str, reply_markup: list | None = None) -> None:
        data: dict = {"text": text}
        if reply_markup:
            data["reply_markup"] = json.dumps({"inline_keyboard": reply_markup}, ensure_ascii=False)
        self._send(data)

    def send_photo(self, photo: bytes, caption: str = "") -> None:
        if not self.bot_token or not self.chat_id:
            raise RuntimeError("未配置 telegram bot_token/chat_id")
        _tg_rate_limiter.wait()
        url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
        resp = self._post(
            url,
            data={"chat_id": self.chat_id, "caption": caption},
            files={"photo": ("qr.png", photo, "image/png")},
        )
        resp.raise_for_status()
        result = resp.json()
        if not result.get("ok"):
            raise RuntimeError(f"Telegram 返回错误: {result}")
