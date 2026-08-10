#!/usr/bin/env python3
"""waf-bot：无头浏览器定期过目标站点的 JS 执行型 WAF，维护通关 cookie 供主服务复用。

雪球 2026-08-09 起对全部 API 启用阿里云 WAF JS 挑战：裸 HTTP 客户端（httpx/curl_cffi）
一律 400（error_code 400016），必须执行挑战 JS 拿到 HttpOnly 通关 cookie 才能访问。
headless chromium 可自动执行挑战（实测 PoC），因此本进程周期访问目标站点、
把 context 里的全部 cookie（含 HttpOnly）写入共享文件，主容器 httpx 抓取时读取合并。

通用性：targets 是列表，未来其他站点（X 升级 CF managed challenge 等）加一项即可复用。
cookie 有 TTL（实测 acw_tc Max-Age=30 分钟），按 WAF_REFRESH_INTERVAL 周期刷新。

升级路径（ponytail: 当前裸 playwright 已够用，暂不引入）：若目标站点升级到检测
headless/webdriver 特征（目前雪球 acw 不看、X 的 CF 也未到），替换成 Scrapling
（github.com/d4vinci/Scrapling）StealthyFetcher——同为 Playwright Chromium + 指纹
模拟并带 stealth 补丁，waf-bot 是独立容器，替换不影响主服务。
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path


def _sync_playwright():
    """Load Playwright only in the optional Chromium image."""
    from importlib import import_module

    return import_module("playwright.sync_api").sync_playwright

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

OUTPUT = os.environ.get("WAF_COOKIE_FILE", "/data/waf_cookies.json")
try:
    INTERVAL = max(1, int(os.environ.get("WAF_REFRESH_INTERVAL", "600")))
except ValueError:
    INTERVAL = 600
SEED_COOKIE_FILE = Path(
    os.environ.get("XUEQIU_SEED_COOKIE_FILE", "/data/xueqiu_seed_cookie.txt")
)
AUTH_PROBE_URL = "https://xueqiu.com/cubes/rebalancing/history.json"
AUTH_PROBE_PARAMS = {"cube_symbol": "ZH000001", "page": 1, "count": 1}
# 可选：目标站点的登录 cookie（雪球组合等需登录态的接口要用）。
# 注入后浏览器导出的是「登录会话 + 配套 acw_tc」的整套自洽 cookie；
# 不配置则导出游客会话（公开时间线可用）。
SEED_COOKIE = os.environ.get("WAF_SEED_COOKIE", "")
TARGETS = [
    {
        "url": "https://xueqiu.com/",
        "ok_marker": "雪球",  # 页面出现该文本即视为挑战已过
        "out": "xueqiu",
        "seed_cookie": SEED_COOKIE,
    },
]


def _load_seed_cookie(target: dict) -> str:
    try:
        cookie = SEED_COOKIE_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        cookie = ""
    return cookie or (target.get("seed_cookie") or "")


def _cookie_sha256(cookie: str) -> str:
    return hashlib.sha256((cookie or "").strip().encode()).hexdigest()


def _inject_seed_cookie(ctx, cookie: str) -> None:
    """把登录 cookie 逐条注入浏览器 context（域名统一 .xueqiu.com）。"""
    for part in (cookie or "").split(";"):
        if "=" not in part:
            continue
        key, _, value = part.strip().partition("=")
        key = key.strip()
        if not key:
            continue
        ctx.add_cookies(
            [
                {
                    "name": key,
                    "value": value.strip(),
                    "domain": ".xueqiu.com",
                    "path": "/",
                }
            ]
        )


def refresh(target: dict) -> bool:
    """无头浏览器访问目标站点，等挑战自动执行完，把整套 cookie 写入共享文件。"""
    with _sync_playwright()() as p:
        browser = p.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(user_agent=UA, locale="zh-CN")
            seed_cookie = _load_seed_cookie(target)
            _inject_seed_cookie(ctx, seed_cookie)
            page = ctx.new_page()
            page.goto(target["url"], timeout=30000)
            page.wait_for_load_state("domcontentloaded")
            try:
                page.wait_for_selector(f"text={target['ok_marker']}", timeout=15000)
            except Exception:  # noqa: BLE001, S110 - 挑战已过但无该文本也可接受（照常读 cookie）
                pass
            time.sleep(2)
            cookies = [
                {"name": c["name"], "value": c["value"]} for c in ctx.cookies()
            ]
            if not cookies:
                return False
            probe_url = (
                AUTH_PROBE_URL
                if seed_cookie
                else "https://xueqiu.com/statuses/user_timeline.json"
            )
            probe_params = (
                AUTH_PROBE_PARAMS
                if seed_cookie
                else {"user_id": "1247347556", "page": 1, "count": 1}
            )
            probe = ctx.request.get(
                probe_url,
                params=probe_params,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
            if probe.status != 200:
                return False
            payload = probe.json()
            if seed_cookie:
                if not isinstance(payload, dict) or payload.get("error_code") == "10022":
                    return False
            elif not isinstance(payload, dict) or not isinstance(payload.get("statuses"), list):
                return False
            destination = os.path.abspath(OUTPUT)
            parent = os.path.dirname(destination) or "."
            fd, path = tempfile.mkstemp(
                prefix=f".{target['out']}.", suffix=".tmp", dir=parent, text=True
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "fetched_at": int(time.time()),
                            "seed_sha256": _cookie_sha256(seed_cookie),
                            "cookies": cookies,
                        },
                        f,
                        ensure_ascii=False,
                    )
                os.replace(path, destination)
            except Exception:
                try:
                    os.unlink(path)
                except OSError:
                    pass
                raise
            return True
        finally:
            browser.close()


def main() -> None:
    print(f"waf-bot 启动: {len(TARGETS)} 个目标, 刷新间隔 {INTERVAL}s, 输出 {OUTPUT}", flush=True)
    while True:
        for target in TARGETS:
            try:
                ok = refresh(target)
                print(
                    f"[{time.strftime('%H:%M:%S')}] {target['url']} cookie 刷新: "
                    f"{'成功' if ok else '失败'}",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001 - 单次失败下轮重试
                print(f"[{time.strftime('%H:%M:%S')}] {target['url']} 刷新异常: {exc}", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
