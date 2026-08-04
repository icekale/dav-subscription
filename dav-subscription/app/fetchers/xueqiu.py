"""雪球用户原创动态抓取。"""
from __future__ import annotations

import time

import httpx

from .base import Fetcher, Post, strip_html

XUEQIU_COOKIE_KEY = "xueqiu_cookie"
XUEQIU_COOKIE_TIME_KEY = "xueqiu_cookie_updated_at"


class XueqiuFetcher(Fetcher):
    platform = "xueqiu"

    def __init__(self, source_config, db, client: httpx.Client | None = None):
        super().__init__(source_config)
        self.db = db
        self.client = client or httpx.Client(
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)",
                "Referer": "https://xueqiu.com/",
            },
        )
        if self.source_config.cookie:
            self.client.headers["Cookie"] = self.source_config.cookie

    def _apply_cookie(self) -> None:
        """优先使用数据库里续期后的 cookie，否则用配置里的初始值。"""
        cookie = self.db.get_setting(XUEQIU_COOKIE_KEY) or self.source_config.cookie
        if cookie:
            self.client.headers["Cookie"] = cookie

    def _refresh_cookie(self) -> None:
        """访问雪球首页拿新 token（匿名访问也会下发 xq_a_token），持久化到 DB。"""
        resp = self.client.get("https://xueqiu.com/")
        resp.raise_for_status()
        if not self.client.cookies.get("xq_a_token"):
            raise RuntimeError("雪球首页未返回 xq_a_token，cookie 续期失败")
        cookie = "; ".join(f"{k}={v}" for k, v in self.client.cookies.items())
        self.db.set_setting(XUEQIU_COOKIE_KEY, cookie)
        self.db.set_setting(XUEQIU_COOKIE_TIME_KEY, str(int(time.time())))

    def fetch(self, kol: dict) -> list[Post]:
        self._apply_cookie()
        url = "https://xueqiu.com/statuses/original/timeline.json"
        params = {"user_id": kol["external_id"], "page": 1}
        resp = self.client.get(
            url,
            params=params,
        )
        if resp.status_code in (401, 403):
            self._refresh_cookie()
            self._apply_cookie()
            resp = self.client.get(url, params=params)
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError(
                "雪球接口返回异常（可能被反爬拦截），请检查 xueqiu cookie 配置后重试"
            ) from None
        statuses = (data or {}).get("statuses") or []
        posts = []
        for s in statuses:
            target = s.get("target") or ""
            url = f"https://xueqiu.com{target}" if target.startswith("/") else target
            posts.append(
                Post(
                    platform=self.platform,
                    kol_id=kol["id"],
                    kol_name=kol["name"],
                    external_id=str(s.get("id") or ""),
                    title=s.get("title") or "",
                    content=strip_html(s.get("description") or ""),
                    url=url,
                    published_at=str(s.get("created_at") or ""),
                )
            )
        return posts
