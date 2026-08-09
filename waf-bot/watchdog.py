#!/usr/bin/env python3
"""waf-bot：无头浏览器定期过目标站点的 JS 执行型 WAF，维护通关 cookie 供主服务复用。

雪球 2026-08-09 起对全部 API 启用阿里云 WAF JS 挑战：裸 HTTP 客户端（httpx/curl_cffi）
一律 400（error_code 400016），必须执行挑战 JS 拿到 HttpOnly 通关 cookie 才能访问。
headless chromium 可自动执行挑战（实测 PoC），因此本进程周期访问目标站点、
把 context 里的全部 cookie（含 HttpOnly）写入共享文件，主容器 httpx 抓取时读取合并。

通用性：targets 是列表，未来其他站点（X 升级 CF managed challenge 等）加一项即可复用。
cookie 有 TTL（实测 acw_tc Max-Age=30 分钟），按 WAF_REFRESH_INTERVAL 周期刷新。
"""
from __future__ import annotations

import json
import os
import time

from playwright.sync_api import sync_playwright

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

OUTPUT = os.environ.get("WAF_COOKIE_FILE", "/data/waf_cookies.json")
INTERVAL = int(os.environ.get("WAF_REFRESH_INTERVAL", "600"))  # 10 分钟，acw_tc TTL 30 分钟
TARGETS = [
    {
        "url": "https://xueqiu.com/",
        "ok_marker": "雪球",  # 页面出现该文本即视为挑战已过
        "out": "xueqiu",
    },
]


def refresh(target: dict) -> bool:
    """无头浏览器访问目标站点，等挑战自动执行完，把 cookie 写入共享文件。"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(user_agent=UA, locale="zh-CN")
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
            path = f"{OUTPUT}.{target['out']}.tmp"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {"fetched_at": int(time.time()), "cookies": cookies},
                    f,
                    ensure_ascii=False,
                )
            os.replace(path, OUTPUT)
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
