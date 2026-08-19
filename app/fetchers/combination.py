"""雪球组合调仓抓取：订阅组合后推送每次调仓（持仓比例变化）。

同时抓取组合快照（quote 实时净值/今日涨跌/年化、current 当前持仓、nav 净值序列）
写入 cube_snapshots 表，供详情页展示；快照失败不阻断调仓推送。
"""
from __future__ import annotations

import logging
import re
import time

import httpx

from .base import Fetcher, Post, ThreadLocalClient, format_published_at
from .xueqiu import (
    XUEQIU_COOKIE_KEY,
    XUEQIU_COOKIE_TIME_KEY,
    _is_waf_html,
    merge_cookie_strings,
    merge_waf_cookie,
)

logger = logging.getLogger(__name__)

REBALANCING_URL = "https://xueqiu.com/cubes/rebalancing/history.json"
CUBE_QUOTE_URL = "https://xueqiu.com/cubes/quote.json"
CUBE_CURRENT_URL = "https://xueqiu.com/cubes/rebalancing/current.json"
CUBE_NAV_URL = "https://xueqiu.com/cubes/nav_daily/all.json"
CUBE_SEARCH_URL = "https://xueqiu.com/query/v1/cube/search.json"
PROFILE_CACHE_TTL = 300
# 快照 TTL：quote 随轮次刷新（30s 级），持仓 5 分钟，净值序列 1 小时
SNAPSHOT_TTL = {"quote": 60, "holdings": 300, "nav": 3600}
_profile_cache: dict[str, tuple[float, dict]] = {}


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


def resolve_combination_profile(
    symbol: str, cookie: str = "", client: httpx.Client | None = None
) -> dict:
    """查组合名称/主理人/头像/年化（添加组合大V时自动填名用），失败返回空 dict。"""
    now = time.time()
    cached = _profile_cache.get(symbol)
    if cached and now - cached[0] < PROFILE_CACHE_TTL:
        return cached[1]
    owns_client = client is None
    client = client or _cube_client(cookie)
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
                profile = {
                    "name": item.get("name") or "",
                    "owner_name": owner.get("screen_name") or "",
                    "avatar_url": avatar,
                    "annualized_gain": item.get("annualized_gain_rate") or 0,
                    "net_value": item.get("net_value") or 0,
                }
                _profile_cache[symbol] = (now, profile)
                return profile
    except Exception:  # noqa: BLE001 - 名称解析失败不阻断添加
        return {}
    finally:
        if owns_client:
            client.close()
    return {}


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def parse_quote(data) -> dict:
    """解析 cubes/quote.json 响应。

    真实结构（实测 2026-08）：顶层 {symbol: {net_value, daily_gain, annualized_gain}}，值为字符串；
    兼容 {"data": {...}} 与 day_percent_gain/percent、annualized_gain_rate 旧猜测。
    """
    empty = {"net_value": None, "day_percent_gain": None, "annualized_gain": None}
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    # 顶层 {symbol: {...}} 字典：取第一个非空元素
    if isinstance(data, dict) and "net_value" not in data and "daily_gain" not in data:
        for v in data.values():
            if isinstance(v, dict):
                data = v
                break
    if not isinstance(data, dict):
        return empty
    day = None
    for key in ("daily_gain", "day_percent_gain", "percent"):
        day = _num(data.get(key))
        if day is not None:
            break
    annual = None
    for key in ("annualized_gain", "annualized_gain_rate"):
        annual = _num(data.get(key))
        if annual is not None:
            break
    return {
        "net_value": _num(data.get("net_value")),
        "day_percent_gain": day,
        "annualized_gain": annual,
    }


def parse_holdings(data) -> list[dict]:
    """解析 rebalancing/current.json 响应为 [{name, symbol, weight}]。

    真实结构（实测 2026-08）：{"last_rb": {"holdings": [...]}}；
    兼容顶层数组 / {"data": [...]} / {"data": {"holdings": [...]}}。
    """
    rows = []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        inner = data.get("data")
        if isinstance(inner, list):
            rows = inner
        elif isinstance(inner, dict) and isinstance(inner.get("holdings"), list):
            rows = inner["holdings"]
        elif isinstance(data.get("holdings"), list):
            rows = data["holdings"]
        elif isinstance(data.get("last_rb"), dict):
            rows = data["last_rb"].get("holdings") or []
    else:
        rows = []
    holdings = []
    for h in rows:
        if not isinstance(h, dict):
            continue
        w = h.get("weight")
        if not isinstance(w, (int, float)):
            w = h.get("target_weight")
        if not isinstance(w, (int, float)):
            continue
        row = {
            "name": h.get("stock_name") or "",
            "symbol": h.get("stock_symbol") or "",
            "weight": round(w, 2),
        }
        prev = _num(h.get("prev_weight"))
        if prev is not None:
            row["prev"] = round(prev, 2)
        holdings.append(row)
    return holdings


def parse_cash(data) -> float | None:
    """从 current.json 取现金占比。只信 last_rb.cash，不读调仓历史顶层伪 cash。"""
    if not isinstance(data, dict):
        return None
    inner = data.get("data") if isinstance(data.get("data"), dict) else None
    for obj in (data.get("last_rb"), (inner or {}).get("last_rb")):
        if not isinstance(obj, dict):
            continue
        n = _num(obj.get("cash"))
        if n is not None:
            return round(n, 2)
    return None


def _xueqiu_error(data) -> bool:
    if not isinstance(data, dict):
        return False
    return data.get("error_code") not in (None, 0, "0")


def _looks_like_holdings(data) -> bool:
    if isinstance(data, list):
        return True
    if not isinstance(data, dict):
        return False
    if isinstance(data.get("holdings"), list) or isinstance(data.get("last_rb"), dict):
        return True
    inner = data.get("data")
    if isinstance(inner, list):
        return True
    return isinstance(inner, dict) and (
        isinstance(inner.get("holdings"), list) or isinstance(inner.get("last_rb"), dict)
    )


def _nav_series(obj) -> list[dict]:
    if not isinstance(obj, dict):
        return []
    items = obj.get("list")
    if not isinstance(items, list):
        return []
    series = []
    for it in items:
        if not isinstance(it, dict):
            continue
        v = it.get("value")
        if not isinstance(v, (int, float)):
            continue
        series.append({"date": str(it.get("date") or ""), "value": round(v, 4)})
    return series


def parse_nav(data) -> list[dict]:
    """解析 nav_daily/all.json 的组合自身序列 [{date, value}]。"""
    if not isinstance(data, list) or not data:
        return []
    return _nav_series(data[0])


def parse_benchmark(data) -> list[dict]:
    """解析 nav_daily/all.json 的沪深300基准（通常是第 2 项）。"""
    if not isinstance(data, list) or len(data) < 2:
        return []
    return _nav_series(data[1])


class CombinationFetcher(Fetcher):
    platform = "combination"

    def __init__(self, source_config, db, client: httpx.Client | None = None):
        super().__init__(source_config)
        self.db = db
        cookie = getattr(source_config, "cookie", "")
        self._http = ThreadLocalClient(
            lambda: _cube_client(cookie),
            injected=client,
        )

    @property
    def client(self):
        return self._http.get()

    @client.setter
    def client(self, value):
        self._http.set(value)

    def _apply_cookie(self) -> None:
        cookie = self.db.get_setting(XUEQIU_COOKIE_KEY) or self.source_config.cookie
        self.client.headers["Cookie"] = merge_waf_cookie(cookie)

    def _refresh_cookie(self) -> None:
        """访问雪球首页刷新会话，持久化最新 cookie（与雪球帖抓取共用）。"""
        resp = self.client.get("https://xueqiu.com/")
        resp.raise_for_status()
        if _is_waf_html(resp):
            raise RuntimeError("雪球 cookie 续期被反爬拦截，请到后台更新雪球 cookie")
        old = self.client.headers.get("Cookie") or ""
        cookie = merge_cookie_strings(old, self.client.cookies)
        if cookie:
            self.db.set_setting(XUEQIU_COOKIE_KEY, cookie)
            self.db.set_setting(XUEQIU_COOKIE_TIME_KEY, str(int(time.time())))

    def _snapshot(self, kol_id: int, cube_symbol: str, kind: str, url: str, params: dict) -> None:
        """抓取并写入一种组合快照；TTL 内跳过，失败仅记日志（不阻断调仓推送）。"""
        ttl = SNAPSHOT_TTL.get(kind, 300)
        if self.db.cube_snapshot_fresh(kol_id, kind, ttl):
            return
        self._apply_cookie()
        try:
            resp = self.client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001 - 快照失败不影响主流程
            logger.warning("组合 %s %s 快照抓取失败: %s", cube_symbol, kind, exc)
            return
        if _xueqiu_error(data):
            logger.warning("组合 %s %s 快照接口返回 error_code=%s", cube_symbol, kind, data.get("error_code"))
            return
        try:
            if kind == "quote":
                payload = parse_quote(data)
                if payload.get("net_value") is None and payload.get("day_percent_gain") is None:
                    return
            elif kind == "holdings":
                if not _looks_like_holdings(data):
                    return
                payload = {"holdings": parse_holdings(data), "cash": parse_cash(data)}
            else:
                series = parse_nav(data)
                if not series:
                    return
                payload = {"series": series, "benchmark": parse_benchmark(data)}
        except Exception as exc:  # noqa: BLE001
            logger.warning("组合 %s %s 快照解析失败: %s", cube_symbol, kind, exc)
            return
        self.db.set_cube_snapshot(kol_id, kind, payload)

    def _refresh_snapshots(self, kol_id: int, cube_symbol: str) -> None:
        """刷新三种组合快照（各带 TTL，独立失败互不影响）。"""
        self._snapshot(kol_id, cube_symbol, "quote", CUBE_QUOTE_URL, {"code": cube_symbol, "cube_symbol": cube_symbol})
        self._snapshot(kol_id, cube_symbol, "holdings", CUBE_CURRENT_URL, {"cube_symbol": cube_symbol})
        self._snapshot(kol_id, cube_symbol, "nav", CUBE_NAV_URL, {"cube_symbol": cube_symbol})

    def fetch(self, kol: dict) -> list[Post]:
        cube_symbol = extract_cube_symbol(kol["external_id"])
        if not cube_symbol:
            raise RuntimeError(f"无效的组合编码: {kol['external_id']}")
        self._apply_cookie()
        resp = self.client.get(
            REBALANCING_URL,
            params={"cube_symbol": cube_symbol, "page": 1, "count": 20},
        )
        if resp.status_code in (401, 403):
            self._refresh_cookie()
            self._apply_cookie()
            resp = self.client.get(
                REBALANCING_URL,
                params={"cube_symbol": cube_symbol, "page": 1, "count": 20},
            )
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError("雪球组合接口返回异常（可能被反爬拦截）") from None
        # 先刷新快照（TTL 内跳过），调仓卡与详情页引用本次的 quote/持仓/净值数据
        self._refresh_snapshots(kol["id"], cube_symbol)
        name = kol["name"]
        posts = []
        # 今日/年化/净值只信 quote.json；搜索接口盘中会滞后，不能用来填调仓卡
        quote = parse_quote(
            (self.db.get_cube_snapshot(kol["id"], "quote") or {}).get("payload") or {}
        )
        stats_line = ""
        parts = []
        if quote.get("day_percent_gain") is not None:
            d = quote["day_percent_gain"]
            sign = "+" if d >= 0 else ""
            parts.append(f"今日 {sign}{d:.2f}%")
        if quote.get("annualized_gain") is not None:
            parts.append(f"年化 {quote['annualized_gain']:.1f}%")
        if quote.get("net_value") is not None:
            parts.append(f"净值 {quote['net_value']:.3f}")
        if parts:
            stats_line = " · ".join(parts)
        for item in (data or {}).get("list") or []:
            histories = item.get("rebalancing_histories") or []
            if item.get("status") != "success" or not histories:
                continue
            lines = []
            actions = []
            for h in histories:
                prev_w = h.get("prev_weight")
                target_w = h.get("target_weight")
                prev_ok = isinstance(prev_w, (int, float))
                target_ok = isinstance(target_w, (int, float))
                stock = h.get("stock_name") or ""
                stock_symbol = h.get("stock_symbol") or ""
                # 全量快照记录会把未变动持仓也列出来（prev==target），调仓卡只报变化，跳过
                if prev_ok and target_ok and abs(target_w - prev_w) < 1e-9:
                    continue
                action = ""
                prev_s = f"{prev_w:.1f}%" if prev_ok else ""
                target_s = f"{target_w:.1f}%" if target_ok else ""
                if not prev_ok and target_ok:
                    action = "新建"
                    lines.append(f"🆕 {stock} 新建 {target_s}")
                elif prev_ok and (not target_ok or target_w <= 0):
                    action = "清仓"
                    lines.append(f"🗑 {stock} 清仓 {prev_s}")
                elif prev_ok and target_ok:
                    action = "增持" if target_w > prev_w else "减持"
                    icon = "➕" if target_w > prev_w else "➖"
                    lines.append(f"{icon} {stock} {prev_s} → {target_s}")
                actions.append(
                    {
                        "type": action,
                        "stock": stock,
                        "symbol": stock_symbol,
                        "prev": prev_s or "0.0%",
                        "target": target_s or "0.0%",
                    }
                )
            # 接口的 cash 字段对「只列变动」的记录是伪值（100 − Σ变动targets，如新建后显示
            # 现金 81%，实际 0%）；cash_value 才是组合内真实现金（按净值计），现金占比 = cash_value / 净值。
            cash_value = item.get("cash_value")
            cube_net = quote.get("net_value")
            cash_pct = (
                f"{cash_value / cube_net * 100:.1f}%"
                if isinstance(cash_value, (int, float)) and cube_net
                else ""
            )
            cash_line = f"现金 {cash_pct}" if cash_pct else ""
            content = "\n".join(lines)
            if cash_line:
                content = f"{content}\n{cash_line}" if content else cash_line
            if stats_line:
                content = f"{stats_line}\n{content}" if content else stats_line
            posts.append(
                Post(
                    platform=self.platform,
                    kol_id=kol["id"],
                    kol_name=name,
                    external_id=str(item.get("id") or ""),
                    title=f"{name} 调仓",
                    content=content,
                    url=f"https://xueqiu.com/P/{cube_symbol}",
                    published_at=format_published_at(str(item.get("updated_at") or "")),
                    post_type="",
                    detail={
                        "stats": [
                            (k, v)
                            for k, v in (
                                ("今日", f"{quote['day_percent_gain']:+.2f}%" if quote.get("day_percent_gain") is not None else ""),
                                ("年化", f"{quote['annualized_gain']:.1f}%" if quote.get("annualized_gain") is not None else ""),
                                ("净值", f"{quote['net_value']:.3f}" if quote.get("net_value") is not None else ""),
                            )
                            if v
                        ],
                        "actions": actions,
                        "cash": cash_pct,
                    },
                )
            )
        return posts
