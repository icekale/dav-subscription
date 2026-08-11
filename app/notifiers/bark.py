"""Bark 推送通知器（iOS 自托管通知 App）。

文档：https://github.com/Finb/Bark
- 用户在手机装 Bark App，拿到推送 key（形如 AaBbCc...50位）；
- 服务端把 key 存到用户档案，推送时 POST 到 Bark 服务器；
- 服务器地址默认为官方 https://api.day.app，管理员可用 BARK_SERVER 环境变量
  指向自建实例（如 https://bark.example.com）。
"""
from __future__ import annotations

import re
import urllib.parse

import httpx

from ..fetchers.base import Post, digest_body
from .base import Notifier

PLATFORM_LABELS = {"xueqiu": "雪球", "combination": "雪球组合", "weibo": "微博", "twitter": "X/Twitter"}
MAX_CONTENT_CHARS = 1600  # Bark 单条消息过长会被截断，正文截断到 1600 字
DIGEST_MAX_ITEMS = 8
DND_MAX_ITEMS = 10
DEFAULT_SERVER = "https://api.day.app"

_KEY_RE = re.compile(r"^[A-Za-z0-9\-_]{10,100}$")


def is_valid_bark_key(key: str) -> bool:
    """Bark App 生成的推送 key；服务器地址只能由管理员配置。"""
    return bool(_KEY_RE.fullmatch((key or "").strip()))


def _normalize_key(key: str, server: str = DEFAULT_SERVER) -> tuple[str, str]:
    """把 key 或完整地址拆成 (server, key)；非法时抛错。"""
    key = (key or "").strip()
    server = (server or DEFAULT_SERVER).rstrip("/")
    if not is_valid_bark_key(key):
        raise RuntimeError(f"Bark key 无效: {key[:20]}…")
    return server, key


def build_bark_text(post: Post, favorite: bool = False, keyword: bool = False) -> str:
    platform = PLATFORM_LABELS.get(post.platform, post.platform)
    body = (post.content or post.title or "（无正文）").strip()
    kind = " · 回复" if post.post_type == "reply" else ""
    marks = ("⭐ " if favorite else "") + ("🔑 " if keyword else "")
    lines = [f"{marks}{post.kol_name} · {platform}{kind}", "", body[:MAX_CONTENT_CHARS]]
    if post.category:
        lines.append(f"🗂 {post.category}")
    if post.published_at:
        lines.append(f"🕐 {post.published_at}")
    if post.url:
        lines.append(f"🔗 {post.url}")
    return "\n".join(lines)


def build_bark_combination_text(post: Post) -> str:
    detail = post.detail or {}
    stats = detail.get("stats") or []
    actions = detail.get("actions") or []
    lines = [f"{post.kol_name} · 雪球组合 · 调仓", ""]
    if stats:
        lines.append("　".join(f"{k} {v}" for k, v in stats))
    for a in actions[:6]:
        a_type = a.get("type") or "调整"
        icon = {"清仓": "🗑", "新建": "🆕", "增持": "➕", "减持": "➖"}.get(a_type, "•")
        head = f"{icon} {a_type} {a.get('stock') or ''}"
        symbol = a.get("symbol") or ""
        if symbol:
            head += f"（{symbol}）"
        lines.append(f"{head}: {a.get('prev') or '0.0%'} → {a.get('target') or '0.0%'}")
    if detail.get("cash"):
        lines.append(f"💵 现金 {detail['cash']}")
    if post.url:
        lines.append(f"🔗 {post.url}")
    return "\n".join(lines)


def build_bark_digest(posts: list[Post], kol_name: str, platform: str) -> str:
    platform_label = PLATFORM_LABELS.get(platform, platform)
    lines = [f"{kol_name} · {platform_label}（{len(posts)} 条新动态）", ""]
    numbered = len(posts) > 1
    for i, post in enumerate(posts[:DIGEST_MAX_ITEMS], 1):
        body = digest_body(post, full=len(posts) == 1)
        prefix = f"{i}. " if numbered else ""
        lines.append(f"{prefix}{body[:160]}")
    if len(posts) > DIGEST_MAX_ITEMS:
        lines.append(f"…等共 {len(posts)} 条")
    return "\n".join(lines)


def build_bark_dnd_summary(posts: list[Post], title: str | None = None) -> str:
    heading = title or "🌙 免打扰时段汇总"
    lines = [f"{heading}（{len(posts)} 条新动态）", ""]
    for post in posts[:DND_MAX_ITEMS]:
        platform = PLATFORM_LABELS.get(post.platform, post.platform)
        body = digest_body(post, full=False)
        lines.append(f"· {post.kol_name}（{platform}）：{body[:120]}")
    if len(posts) > DND_MAX_ITEMS:
        lines.append(f"…等共 {len(posts)} 条")
    return "\n".join(lines)


class BarkNotifier(Notifier):
    channel = "bark"

    def __init__(
        self,
        config=None,
        client: httpx.Client | None = None,
        bark_key: str = "",
        server: str = "",
        favorite: bool = False,
        keyword: bool = False,
    ):
        self.key = (bark_key or (getattr(config, "bark_key", "") if config else "") or "").strip()
        self.server = (server or (getattr(config, "bark_server", "") if config else "") or DEFAULT_SERVER).rstrip("/")
        self.client = client or httpx.Client(timeout=15)
        self.favorite = favorite
        self.keyword = keyword

    def _post(self, title: str, body: str, group: str = "dav") -> None:
        if not self.key:
            raise RuntimeError("未配置 Bark key")
        server, key = _normalize_key(self.key, self.server)
        # Bark 路径格式：/<key>/<title>/<body>?group=...；中文走 URL 编码
        url = f"{server}/{key}/{urllib.parse.quote(title)}/{urllib.parse.quote(body)}"
        resp = self.client.post(url, params={"group": group})
        resp.raise_for_status()
        result = resp.json()
        if result.get("code") != 200:
            raise RuntimeError(f"Bark 返回错误: {result.get('message', result)}")

    def notify(self, post: Post) -> None:
        title = f"{post.kol_name} · {PLATFORM_LABELS.get(post.platform, post.platform)}"
        text = (
            build_bark_combination_text(post)
            if post.platform == "combination" and post.detail
            else build_bark_text(post, self.favorite, self.keyword)
        )
        self._post(title[:50], text)

    def send_digest(self, posts: list[Post], kol_name: str, platform: str) -> None:
        self._post(
            f"{kol_name} · {len(posts)} 条新动态",
            build_bark_digest(posts, kol_name, platform),
        )

    def send_dnd_summary(self, posts: list[Post], title: str | None = None) -> None:
        self._post(title or "🌙 免打扰时段汇总", build_bark_dnd_summary(posts, title=title))

    def send_daily(self, posts: list[Post]) -> None:
        # 每日精选与免打扰汇总同构：标题 + 逐条「· 大V（平台）：摘要」
        self._post("📅 每日精选", build_bark_dnd_summary(posts))

    def send_text(self, text: str, reply_markup: list | None = None) -> None:
        # 告警等纯文本：首行做标题，其余做正文
        lines = (text or "").strip().splitlines()
        title = lines[0][:50] if lines else "V Push"
        self._post(title, "\n".join(lines[1:]) or title)
