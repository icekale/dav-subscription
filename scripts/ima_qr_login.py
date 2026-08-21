"""打开 ima 网页登录窗，等扫码后捕获 x-ima-cookie。

凭证只写到 data/ima_web.env（已 gitignore），不打印完整 Cookie。
依赖本机 Google Chrome；一次性：pip install playwright
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / "data" / "ima_web.env"
DEFAULT_KB_NUMERIC_ID = "7304333330762611"

VALIDATE_URLS = (
    "https://ima.qq.com/cgi-bin/history/get_history_list",
    "https://ima.qq.com/cgi-bin/knowledge_tab_reader/get_home_page_data",
)
CGI_LIST = "https://ima.qq.com/cgi-bin/knowledge_tab_reader_nl/get_knowledge_list"


def _cookie_field(cookie: str, name: str) -> str:
    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith(f"{name}="):
            return part.split("=", 1)[1]
    return ""


def _merge_cookie_field(cookie: str, name: str, value: str) -> str:
    pattern = rf"{re.escape(name)}=[^;]+"
    replacement = f"{name}={value}"
    if re.search(pattern, cookie):
        return re.sub(pattern, replacement, cookie)
    sep = "" if cookie.endswith(";") or not cookie else "; "
    return f"{cookie}{sep}{name}={value}"


def _cookie_meta(cookie: str) -> str:
    bits = []
    for name in ("TOKEN-TYPE", "UID-TYPE"):
        value = _cookie_field(cookie, name)
        if value:
            bits.append(f"{name}={value}")
    return " ".join(bits) or "no-meta"


def _apply_auth_payload(cookie: str, body: dict) -> str:
    data = body.get("data") if isinstance(body.get("data"), dict) else body
    updated = cookie
    token = body.get("token") or data.get("token")
    refresh = body.get("refresh_token") or data.get("refresh_token") or data.get("refreshToken")
    uid = body.get("user_id") or data.get("user_id") or data.get("userId")
    if token:
        updated = _merge_cookie_field(updated, "IMA-TOKEN", token)
    if refresh:
        updated = _merge_cookie_field(updated, "IMA-REFRESH-TOKEN", refresh)
    if uid:
        updated = _merge_cookie_field(updated, "IMA-UID", uid)
    return updated


def _refresh_token(cookie: str, bkn: str = "") -> tuple[str, bool]:
    import httpx

    uid = _cookie_field(cookie, "IMA-UID")
    refresh = _cookie_field(cookie, "IMA-REFRESH-TOKEN")
    if not uid or not refresh:
        return cookie, False
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://ima.qq.com",
        "Referer": "https://ima.qq.com/",
        "x-ima-cookie": cookie,
    }
    if bkn:
        headers["x-ima-bkn"] = bkn
    body = {
        "user_id": uid,
        "refresh_token": refresh,
        "token_type": int(_cookie_field(cookie, "TOKEN-TYPE") or "14"),
    }
    with httpx.Client(timeout=15) as client:
        resp = client.post(
            "https://ima.qq.com/cgi-bin/auth_login/refresh",
            headers=headers,
            json=body,
        )
        payload = resp.json()
    if payload.get("code") != 0 or not payload.get("token"):
        return cookie, False
    return _apply_auth_payload(cookie, payload), True


def _validate_cookie(cookie: str, bkn: str = "", kb_id: str = "") -> tuple[bool, str]:
    import httpx

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://ima.qq.com",
        "Referer": "https://ima.qq.com/",
        "x-ima-cookie": cookie,
    }
    if bkn:
        headers["x-ima-bkn"] = bkn
    kb_id = kb_id or os.environ.get("IMA_KB_NUMERIC_ID") or DEFAULT_KB_NUMERIC_ID
    with httpx.Client(timeout=15) as client:
        notes: list[str] = []
        list_body = client.post(
            CGI_LIST,
            headers=headers,
            json={
                "knowledge_base_id": kb_id,
                "folder_id": "",
                "cursor": "",
                "limit": 1,
                "need_default_cover": True,
                "sort_type": 9,
            },
        ).json()
        list_code = list_body.get("code", list_body.get("retcode"))
        notes.append(f"get_knowledge_list={list_code}")
        if list_code == 0:
            count = len((list_body.get("data") or {}).get("knowledge_list") or [])
            return True, f"get_knowledge_list items={count}"
        for url in VALIDATE_URLS:
            body = client.post(url, headers=headers, json={"cursor": "", "limit": 1}).json()
            code = body.get("code", body.get("retcode"))
            notes.append(f"{url.rsplit('/', 1)[-1]}={code}")
            if code == 0:
                return True, url.rsplit("/", 1)[-1]
        return False, "; ".join(notes)


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("请先安装：.venv/bin/pip install playwright", file=sys.stderr)
        return 2

    captured: dict[str, str] = {}
    seen_paths: list[str] = []
    kb_id = os.environ.get("IMA_KB_NUMERIC_ID") or DEFAULT_KB_NUMERIC_ID
    wiki_url = f"https://ima.qq.com/wikis?knowledgeBaseId={kb_id}"

    def remember_cookie(cookie: str) -> None:
        if "IMA-TOKEN=" not in cookie:
            return
        captured.setdefault("template_cookie", cookie)
        if captured.get("logged_in"):
            captured["cookie"] = cookie

    def on_request(request) -> None:
        headers = {k.lower(): v for k, v in request.headers.items()}
        cookie = headers.get("x-ima-cookie") or ""
        remember_cookie(cookie)
        bkn = headers.get("x-ima-bkn") or ""
        if bkn:
            captured["bkn"] = bkn
        url = request.url
        if "/cgi-bin/" in url:
            path = url.split("?", 1)[0]
            if path not in seen_paths:
                seen_paths.append(path)
                print(f"见到请求 {path.rsplit('/', 2)[-2:]}")
        if captured.get("logged_in") and any(
            key in url
            for key in (
                "knowledge_tab_reader_nl/get_knowledge_list",
                "knowledge_tab_reader/get_knowledge_list",
                "knowledge_tab_reader/get_home_page_data",
                "knowledge_tab_reader/list_knowledge_bases",
            )
        ):
            captured["ready"] = url

    def on_response(response) -> None:
        url = response.url
        if "auth_login/login" not in url and "auth_login/refresh" not in url:
            return
        try:
            body = response.json()
        except Exception:
            return
        code = body.get("code", body.get("retcode"))
        endpoint = url.rsplit("/", 1)[-1]
        print(f"响应 auth/{endpoint} code={code}")
        if code != 0:
            return
        captured["logged_in"] = "1"
        base = captured.get("cookie") or captured.get("template_cookie") or ""
        if not base:
            return
        captured["cookie"] = _apply_auth_payload(base, body)
        meta = _cookie_meta(captured["cookie"])
        print(f"已从登录响应更新 cookie（{meta}）")

    print("正在打开 Chrome —— 只扫这一扇窗口里的码。")
    print("步骤：1) 扫码登录  2) 脚本会自动打开「Z哥策略」知识库页")
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(channel="chrome", headless=False)
        except Exception:
            browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        pages: list = []

        def attach_page(page) -> None:
            pages.append(page)
            page.on("request", on_request)
            page.on("response", on_response)

        context.on("page", attach_page)
        page = context.new_page()
        attach_page(page)
        page.goto("https://ima.qq.com/", wait_until="domcontentloaded")
        for i in range(180):
            if captured.get("ready"):
                break
            if i == 12:
                try:
                    page.get_by_text("登录", exact=False).first.click(timeout=2000)
                except Exception:
                    pass
            if captured.get("logged_in") and i in (12, 18, 25, 35, 50):
                target = pages[-1] if pages else page
                try:
                    print(f"打开知识库页 {wiki_url}")
                    target.goto(wiki_url, wait_until="domcontentloaded")
                except Exception:
                    pass
            if captured.get("logged_in") and i % 5 == 0 and captured.get("cookie"):
                ok, note = _validate_cookie(
                    captured["cookie"], captured.get("bkn", ""), kb_id
                )
                if ok:
                    captured["ready"] = f"validate:{note}"
                    print(f"登录校验通过（{note}）")
                    break
                refreshed, did = _refresh_token(captured["cookie"], captured.get("bkn", ""))
                if did:
                    captured["cookie"] = refreshed
                    ok, note = _validate_cookie(
                        refreshed, captured.get("bkn", ""), kb_id
                    )
                    if ok:
                        captured["ready"] = f"validate:{note}"
                        print(f"刷新后校验通过（{note}）")
                        break
            if i in (8, 20, 40, 80, 120, 160):
                hint = "正在校验登录…" if captured.get("logged_in") else "请扫码登录"
                print(f"还在等（已 {i}s）：{hint}。")
            page.wait_for_timeout(1000)
        if captured.get("ready") and captured["ready"].startswith("http"):
            print(f"触发请求：{captured['ready'].split('/cgi-bin/')[-1]}")
        context.close()
        browser.close()

    cookie = captured.get("cookie") or captured.get("template_cookie")
    if not cookie:
        print("3 分钟内没有捕获到 x-ima-cookie，请再跑一次。", file=sys.stderr)
        return 1
    if not captured.get("ready"):
        ok, note = _validate_cookie(cookie, captured.get("bkn", ""), kb_id)
        if not ok:
            refreshed, did = _refresh_token(cookie, captured.get("bkn", ""))
            if did:
                cookie = refreshed
                ok, note = _validate_cookie(cookie, captured.get("bkn", ""), kb_id)
        if not ok:
            meta = _cookie_meta(cookie)
            print(
                f"捕获到 cookie 但校验未通过（{note}；{meta}），请再跑一次。",
                file=sys.stderr,
            )
            return 1
        captured["ready"] = f"validate:{note}"
        print(f"登录校验通过（{note}）")
    captured["cookie"] = cookie

    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)

    def _quote(value: str) -> str:
        return "'" + value.replace("'", "'\"'\"'") + "'"

    lines = [f"IMA_COOKIE={_quote(captured['cookie'])}\n"]
    lines.append(f"IMA_KB_NUMERIC_ID={_quote(kb_id)}\n")
    if captured.get("bkn"):
        lines.append(f"IMA_X_IMA_BKN={_quote(captured['bkn'])}\n")
    ENV_PATH.write_text("".join(lines), encoding="utf-8")
    os.chmod(ENV_PATH, 0o600)
    print(f"已捕获登录态（cookie {len(captured['cookie'])} 字），写入 {ENV_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
