"""微博扫码登录公共逻辑：后台网页与 TG 保活续期共用。"""
from __future__ import annotations

import json
import time

import httpx

from .fetchers.weibo import cookie_header

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def _parse_sina_jsonp(text: str) -> dict:
    body = text.strip()
    start = body.index("(")
    end = body.rindex(")")
    return json.loads(body[start + 1 : end])


def create_qr(client: httpx.Client | None = None, db=None) -> tuple[httpx.Client, str, str]:
    """创建微博扫码会话，返回 (client, qrid, 二维码图片地址)。"""
    if client is None:
        from .proxy import acquire_client_proxy

        proxy, _pid = acquire_client_proxy(db, "weibo")
        client = httpx.Client(
            timeout=15,
            follow_redirects=True,
            proxy=proxy,
            headers={"User-Agent": UA, "Referer": "https://weibo.com/"},
        )
    resp = client.get(
        "https://login.sina.com.cn/sso/qrcode/image",
        params={"entry": "weibo", "size": "180", "callback": str(int(time.time() * 1000))},
    )
    data = (_parse_sina_jsonp(resp.text) or {}).get("data") or {}
    qrid = data.get("qrid")
    image = data.get("image")
    if not qrid:
        client.close()
        raise RuntimeError("获取微博二维码失败")
    return client, qrid, f"https:{image}"


def poll_qr(client: httpx.Client, qrid: str) -> dict:
    """轮询扫码状态；确认后完成登录并返回 cookie。"""
    resp = client.get(
        "https://login.sina.com.cn/sso/qrcode/check",
        params={
            "entry": "weibo",
            "qrid": qrid,
            "callback": f"STK_{int(time.time() * 10000)}",
        },
    )
    data = _parse_sina_jsonp(resp.text)
    code = data.get("retcode")
    if code == 50114001:
        return {"status": "pending"}
    if code == 50114002:
        return {"status": "scanned"}
    if code == 50114004:
        return {"status": "expired"}
    if code == 20000000:
        alt = (data.get("data") or {}).get("alt") or ""
        if not alt:
            return {"status": "error", "detail": "登录确认缺少票据"}
        login_resp = client.get(
            "https://login.sina.com.cn/sso/login.php",
            params={
                "entry": "weibo",
                "returntype": "TEXT",
                "crossdomain": "1",
                "cdult": "3",
                "domain": "weibo.com",
                "alt": alt,
                "savestate": "30",
                "callback": f"STK_{int(time.time() * 1000)}",
            },
        )
        login_data = _parse_sina_jsonp(login_resp.text)
        cross_domains = list(login_data.get("crossDomainUrlList", []))
        if cross_domains:
            cross_domains[0] = f"{cross_domains[0]}&action=login"
        for url in cross_domains:
            client.get(url)
        if not any(c.name == "SUB" for c in client.cookies.jar):
            return {"status": "error", "detail": "登录后未获取到微博会话"}
        return {"status": "ok", "cookie": cookie_header(client.cookies)}
    return {"status": "error", "detail": str(data)[:200]}
