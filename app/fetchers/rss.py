"""X/Twitter 等通用 RSS 抓取（RSSHub / nitter 源）。"""
from __future__ import annotations

import re

import feedparser
import httpx

from ..avatar_cache import cache_avatar
from .base import Fetcher, Post, strip_html


class RssFetcher(Fetcher):
    platform = "twitter"

    def __init__(self, source_config=None, db=None, client: httpx.Client | None = None):
        super().__init__(source_config)
        self.db = db
        self.rsshub_base = (getattr(source_config, "rsshub_base", "") or "https://rsshub.app").rstrip("/")
        self.client = client or httpx.Client(
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0"},
        )

    def _resolve_feed_url(self, external_id: str) -> str:
        """x.com / twitter.com 主页链接或纯用户名（含 @前缀）转成 RSSHub 用户 RSS。"""
        value = (external_id or "").strip()
        match = re.search(
            r"(?:x\.com|twitter\.com)/(?:@?)([A-Za-z0-9_]+)",
            value,
        )
        if match:
            username = match.group(1)
            return f"{self.rsshub_base}/twitter/user/{username}"
        if re.fullmatch(r"@?[A-Za-z0-9_]{1,15}", value):
            return f"{self.rsshub_base}/twitter/user/{value.lstrip('@')}"
        return external_id

    @staticmethod
    def _extract_avatar(feed) -> str:
        """从 RSS 里提取账号头像：feed image → 首条 media_thumbnail/media_content/作者头像。"""
        feed_image = (feed.get("feed") or {}).get("image") or {}
        if feed_image.get("url"):
            return feed_image["url"]
        entries = feed.get("entries") or []
        for entry in entries:
            thumbnails = entry.get("media_thumbnail") or []
            if thumbnails and thumbnails[0].get("url"):
                return thumbnails[0]["url"]
            media = entry.get("media_content") or []
            if media and media[0].get("url"):
                return media[0]["url"]
            author = (entry.get("author_detail") or {}).get("avatar")
            if author:
                return author
        return ""

    def fetch(self, kol: dict) -> list[Post]:
        url = self._resolve_feed_url(kol["external_id"])
        resp = self.client.get(url)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        posts = []
        for entry in feed.entries:
            images: list[str] = []
            for media in entry.get("media_content") or []:
                if media.get("url") and media["url"] not in images:
                    images.append(media["url"])
            for thumb in entry.get("media_thumbnail") or []:
                if thumb.get("url") and thumb["url"] not in images:
                    images.append(thumb["url"])
            posts.append(
                Post(
                    platform=self.platform,
                    kol_id=kol["id"],
                    kol_name=kol["name"],
                    external_id=entry.get("id") or entry.get("link") or "",
                    title=entry.get("title") or "",
                    content=strip_html(entry.get("summary") or entry.get("description") or ""),
                    url=entry.get("link") or "",
                    published_at=str(entry.get("published") or entry.get("updated") or ""),
                    images=images[:4],
                )
            )
        if self.db is not None:
            avatar = self._extract_avatar(feed)
            if avatar and avatar != (self.db.get_kol(kol["id"]) or {}).get("avatar_url"):
                self.db.update_kol_avatar(kol["id"], cache_avatar(self.db, kol["id"], avatar))
        return posts
