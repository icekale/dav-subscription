#!/usr/bin/env python3
"""Refresh Xueqiu WAF cookies with curl_cffi and the sibling jsdom solver."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urljoin

from curl_cffi import requests

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

OUTPUT = os.environ.get("WAF_COOKIE_FILE", "/data/waf_cookies.json")
INTERVAL = int(os.environ.get("WAF_REFRESH_INTERVAL", "600"))
SEED_COOKIE = os.environ.get("WAF_SEED_COOKIE", "")
SOLVER = Path(__file__).with_name("solver.js")
PROBE_URL = "https://xueqiu.com/statuses/user_timeline.json"
PROBE_PARAMS = {"user_id": "1247347556", "page": 1, "count": 1}
# 登录态探测：组合调仓接口未登录必返回 error_code 10022（实测确认），
# 配置了 WAF_SEED_COOKIE 时用它验证登录会话有效后才允许覆盖 Cookie。
AUTH_PROBE_URL = "https://xueqiu.com/cubes/rebalancing/history.json"
AUTH_PROBE_PARAMS = {"cube_symbol": "ZH000001", "page": 1, "count": 1}
AUTH_ERROR_CODE = "10022"

TARGETS = [
    {
        "url": "https://xueqiu.com/",
        "out": "xueqiu",
        "seed_cookie": SEED_COOKIE,
    },
]

_NAVIGATION_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Upgrade-Insecure-Requests": "1",
}
_XHR_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
}


def _is_challenge(response) -> bool:
    content_type = response.headers.get("content-type", "").lower()
    return content_type.startswith("text/html") and "renderData" in response.text


def _solve_challenge(html: str, url: str) -> str:
    result = subprocess.run(
        [
            "node",
            "--permission",
            "--allow-fs-read=.",
            "--allow-fs-read=./node_modules",
            "./solver.js",
        ],
        cwd=str(SOLVER.parent),
        input=json.dumps({"html": html, "url": url, "user_agent": UA}),
        text=True,
        capture_output=True,
        timeout=10,
        check=True,
    )
    payload = json.loads(result.stdout)
    signed_url = payload.get("signed_url") if isinstance(payload, dict) else None
    if not isinstance(signed_url, str):
        raise RuntimeError("solver returned no signed URL")
    signed_url = signed_url.strip()
    if not signed_url:
        raise RuntimeError("solver returned no signed URL")
    return signed_url


def _inject_seed_cookie(session, cookie: str) -> None:
    for part in (cookie or "").split(";"):
        if "=" not in part:
            continue
        name, _, value = part.strip().partition("=")
        name = name.strip()
        if name:
            session.cookies.set(
                name,
                value.strip(),
                domain=".xueqiu.com",
                path="/",
            )


def refresh(
    target: dict,
    *,
    session=None,
    solve=_solve_challenge,
    output=None,
) -> bool:
    """Refresh one target and publish cookies only after a valid API probe."""
    owned_session = session is None
    temp_path = None
    stage = "session"
    if owned_session:
        try:
            session = requests.Session(impersonate="chrome124")
        except Exception as exc:  # noqa: BLE001 - keep refresh failures isolated
            print(f"waf refresh failed at {stage}: {type(exc).__name__}", flush=True)
            return False

    try:
        target_url = target["url"]
        stage = "seed"
        _inject_seed_cookie(session, target.get("seed_cookie") or "")

        stage = "homepage"
        response = session.get(target_url, headers=_NAVIGATION_HEADERS, timeout=30)
        if _is_challenge(response):
            stage = "solve"
            signed = solve(response.text, target_url)
            if not isinstance(signed, str) or not signed:
                return False
            signed_url = urljoin(target_url, signed)
            stage = "signed"
            signed_response = session.get(
                signed_url,
                headers={**_NAVIGATION_HEADERS, "Referer": target_url},
                timeout=30,
            )
            if _is_challenge(signed_response):
                return False

        stage = "probe"
        seed = target.get("seed_cookie") or ""
        if seed:
            # 登录态会话：必须通过需要登录的组合调仓接口验证，
            # 登录失效（10022）时保留旧 Cookie，不覆盖成游客会话。
            probe_url, probe_params = AUTH_PROBE_URL, AUTH_PROBE_PARAMS
        else:
            probe_url, probe_params = PROBE_URL, PROBE_PARAMS
        probe = session.get(
            probe_url,
            headers={**_XHR_HEADERS, "Referer": target_url},
            params=probe_params,
            timeout=30,
        )
        if probe.status_code != 200:
            return False
        payload = probe.json()
        if seed:
            if not isinstance(payload, dict) or payload.get("error_code") == AUTH_ERROR_CODE:
                return False
        elif not isinstance(payload, dict) or not isinstance(payload.get("statuses"), list):
            return False

        cookies = list(session.cookies.jar)
        if not cookies:
            return False
        cookie_list = [{"name": cookie.name, "value": cookie.value} for cookie in cookies]
        destination = Path(output if output is not None else OUTPUT)
        stage = "write"
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.{target['out']}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temp_path = Path(file.name)
            json.dump(
                {"fetched_at": int(time.time()), "cookies": cookie_list},
                file,
                ensure_ascii=False,
            )
        stage = "replace"
        os.replace(temp_path, destination)
        temp_path = None
        return True
    except Exception as exc:  # noqa: BLE001 - one failed refresh must not stop the loop
        print(f"waf refresh failed at {stage}: {type(exc).__name__}", flush=True)
        return False
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        if owned_session:
            try:
                session.close()
            except Exception as exc:  # noqa: BLE001 - cleanup must not mask refresh result
                print(f"waf refresh cleanup failed: {type(exc).__name__}", flush=True)


def main() -> None:
    print(
        f"waf-bot started: {len(TARGETS)} targets, interval {INTERVAL}s, output {OUTPUT}",
        flush=True,
    )
    while True:
        for target in TARGETS:
            try:
                ok = refresh(target)
                print(
                    f"[{time.strftime('%H:%M:%S')}] {target['url']} cookie refresh: "
                    f"{'success' if ok else 'failed'}",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001 - retry on the next interval
                print(
                    f"[{time.strftime('%H:%M:%S')}] {target['url']} refresh error: "
                    f"{type(exc).__name__}",
                    flush=True,
                )
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
