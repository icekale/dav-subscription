"""雪球用户原创动态抓取。"""
from __future__ import annotations

import time

import httpx

from .base import Fetcher, Post, strip_html

XUEQIU_COOKIE_KEY = "xueqiu_cookie"
XUEQIU_COOKIE_TIME_KEY = "xueqiu_cookie_updated_at"
XUEQIU_TIMELINE_URL = "https://xueqiu.com/statuses/user_timeline.json"


def _is_waf_html(resp: httpx.Response) -> bool:
    """判断响应是否为阿里云 WAF 的 JS 挑战页（普通 HTTP 客户端无法通过）。"""
    content_type = resp.headers.get("content-type", "")
    return "text/html" in content_type and any(
        marker in resp.text for marker in ("renderData", "aliyun_waf", "acw_sc__v2")
    )


class XueqiuFetcher(Fetcher):
    platform = "xueqiu"

    def __init__(self, source_config, db, client: httpx.Client | None = None):
        super().__init__(source_config)
        self.db = db
        self.client = client or httpx.Client(
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Origin": "https://xueqiu.com",
                "X-Requested-With": "XMLHttpRequest",
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
        if _is_waf_html(resp):
            raise RuntimeError(
                "雪球 cookie 自动续期被反爬拦截（首页需要浏览器执行 JS 验证），"
                "请手动更新 sources.xueqiu.cookie 后重试"
            )
        if not self.client.cookies.get("xq_a_token"):
            raise RuntimeError("雪球首页未返回 xq_a_token，cookie 续期失败")
        cookie = "; ".join(f"{k}={v}" for k, v in self.client.cookies.items())
        self.db.set_setting(XUEQIU_COOKIE_KEY, cookie)
        self.db.set_setting(XUEQIU_COOKIE_TIME_KEY, str(int(time.time())))

    def fetch(self, kol: dict) -> list[Post]:
        self._apply_cookie()
        # 用户时间线 JSON 接口不受 WAF 挑战保护；original/timeline.json 反而会被 WAF 拦截
        url = XUEQIU_TIMELINE_URL
        params = {"user_id": kol["external_id"], "page": 1, "count": 20}
        self.client.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Origin": "https://xueqiu.com",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"https://xueqiu.com/u/{kol['external_id']}",
            }
        )
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
            if s.get("retweeted_status"):
                continue  # 只保留原创动态，转发不推送
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
