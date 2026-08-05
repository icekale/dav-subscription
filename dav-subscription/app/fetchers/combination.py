"""雪球组合调仓抓取：订阅组合后推送每次调仓（持仓比例变化）。"""
from __future__ import annotations

import re
import time

import httpx

from .base import Fetcher, Post, format_published_at
from .xueqiu import XUEQIU_COOKIE_KEY, XUEQIU_COOKIE_TIME_KEY, _is_waf_html

REBALANCING_URL = "https://xueqiu.com/cubes/rebalancing/history.json"
CUBE_SEARCH_URL = "https://xueqiu.com/query/v1/cube/search.json"


def extract_cube_symbol(external_id: str) -> str:
    """从组合主页链接或纯 symbol 里提取组合编码（ZHxxxxxx）。"""
    match = re.search(r"(?:xueqiu\.com/P/)?(ZH\d+)", external_id or "")
    return match.group(1) if match else (external_id or "").strip()


def _cube_client(cookie: str) -> httpx.Client:
    return httpx.Client(
        timeout=20,
        follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)",
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://xueqiu.com/P/",
            **({"Cookie": cookie} if cookie else {}),
        },
    )


def resolve_combination_profile(symbol: str, cookie: str = "") -> dict:
    """查组合名称/主理人/头像/年化（添加组合大V时自动填名用），失败返回空 dict。"""
    client = _cube_client(cookie)
    try:
        resp = client.get(
            CUBE_SEARCH_URL,
            params={"q": symbol, "count": 5},
        )
        resp.raise_for_status()
        data = resp.json()
        for item in (data or {}).get("list") or []:
            if item.get("symbol") == symbol:
                owner = item.get("owner") or {}
                avatar = ""
                photo_domain = owner.get("photo_domain") or ""
                purl = (owner.get("profile_image_url") or "").split(",")[0]
                if purl:
                    if photo_domain.startswith("//"):
                        avatar = f"https:{photo_domain}{purl}"
                    elif photo_domain.startswith("http"):
                        avatar = f"{photo_domain}{purl}"
                return {
                    "name": item.get("name") or "",
                    "owner_name": owner.get("screen_name") or "",
                    "avatar_url": avatar,
                    "annualized_gain": item.get("annualized_gain_rate") or 0,
                }
    except Exception:  # noqa: BLE001 - 名称解析失败不阻断添加
        return {}
    finally:
        client.close()
    return {}


class CombinationFetcher(Fetcher):
    platform = "combination"

    def __init__(self, source_config, db, client: httpx.Client | None = None):
        super().__init__(source_config)
        self.db = db
        self.client = client or _cube_client(getattr(source_config, "cookie", ""))

    def _apply_cookie(self) -> None:
        cookie = self.db.get_setting(XUEQIU_COOKIE_KEY) or self.source_config.cookie
        if cookie:
            self.client.headers["Cookie"] = cookie

    def _refresh_cookie(self) -> None:
        """访问雪球首页刷新会话，持久化最新 cookie（与雪球帖抓取共用）。"""
        resp = self.client.get("https://xueqiu.com/")
        resp.raise_for_status()
        if _is_waf_html(resp):
            raise RuntimeError("雪球 cookie 续期被反爬拦截，请到后台更新雪球 cookie")
        cookie = "; ".join(f"{k}={v}" for k, v in self.client.cookies.items())
        if cookie:
            self.db.set_setting(XUEQIU_COOKIE_KEY, cookie)
            self.db.set_setting(XUEQIU_COOKIE_TIME_KEY, str(int(time.time())))

    def fetch(self, kol: dict) -> list[Post]:
        symbol = extract_cube_symbol(kol["external_id"])
        if not symbol:
            raise RuntimeError(f"无效的组合编码: {kol['external_id']}")
        self._apply_cookie()
        resp = self.client.get(
            REBALANCING_URL,
            params={"cube_symbol": symbol, "page": 1, "count": 20},
        )
        if resp.status_code in (401, 403):
            self._refresh_cookie()
            self._apply_cookie()
            resp = self.client.get(
                REBALANCING_URL,
                params={"cube_symbol": symbol, "page": 1, "count": 20},
            )
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError("雪球组合接口返回异常（可能被反爬拦截）") from None
        name = kol["name"]
        posts = []
        for item in (data or {}).get("list") or []:
            histories = item.get("rebalancing_histories") or []
            if item.get("status") != "success" or not histories:
                continue
            lines = []
            for h in histories:
                prev_w = h.get("prev_weight")
                target_w = h.get("target_weight")
                prev_s = f"{prev_w:.1f}%" if isinstance(prev_w, (int, float)) else "-"
                target_s = f"{target_w:.1f}%" if isinstance(target_w, (int, float)) else "-"
                action = "→"
                if isinstance(prev_w, (int, float)) and isinstance(target_w, (int, float)):
                    if target_w > prev_w:
                        action = "➕"
                    elif target_w < prev_w:
                        action = "➖"
                lines.append(f"{h.get('stock_name') or ''} {prev_s} {action} {target_s}")
            cash = item.get("cash")
            cash_line = f"现金 {cash:.1f}%" if isinstance(cash, (int, float)) else ""
            content = "\n".join(lines)
            if cash_line:
                content = f"{content}\n{cash_line}" if content else cash_line
            posts.append(
                Post(
                    platform=self.platform,
                    kol_id=kol["id"],
                    kol_name=name,
                    external_id=str(item.get("id") or ""),
                    title=f"{name} 调仓",
                    content=content,
                    url=f"https://xueqiu.com/P/{symbol}",
                    published_at=format_published_at(str(item.get("updated_at") or "")),
                    post_type="",
                )
            )
        return posts
