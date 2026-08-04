"""微博（m.weibo.cn）用户动态抓取 + 账号密码自动登录。"""
from __future__ import annotations

import base64
import html
import json
import re
import time

import httpx
import rsa

from .base import Fetcher, Post, strip_html

WEIBO_COOKIE_KEY = "weibo_cookie"
PRELOGIN_URL = "https://login.sina.com.cn/sso/prelogin.php"
LOGIN_URL = "https://login.sina.com.cn/sso/login.php"
TIMELINE_URL = "https://m.weibo.cn/api/container/getIndex"


class WeiboFetcher(Fetcher):
    platform = "weibo"

    def __init__(self, source_config, db, client: httpx.Client | None = None):
        super().__init__(source_config)
        self.db = db
        self.client = client or httpx.Client(
            timeout=20,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                "AppleWebKit/605.1.15 Mobile/15E148",
                "Referer": "https://m.weibo.cn/",
            },
        )
        if self.source_config.cookie:
            self.client.headers["Cookie"] = self.source_config.cookie
        if self.source_config.token:
            self.client.headers["X-XSRF-TOKEN"] = self.source_config.token

    def _apply_cookie(self) -> None:
        """优先使用自动登录得到的 cookie，否则用配置里的初始值。"""
        cookie = self.db.get_setting(WEIBO_COOKIE_KEY) or self.source_config.cookie
        if cookie:
            self.client.headers["Cookie"] = cookie

    @staticmethod
    def _encrypt_password(password: str, pubkey_hex: str, nonce: str) -> str:
        key = rsa.PublicKey(int(pubkey_hex, 16), 65537)
        encrypted = rsa.encrypt(f"{nonce}\n{password}".encode("utf-8"), key)
        return base64.b64encode(encrypted).decode()

    def _prelogin(self) -> dict:
        resp = self.client.get(
            PRELOGIN_URL,
            params={
                "entry": "weibo",
                "callback": "sinaSSOController.preloginCallBack",
                "rsakt": "mod",
                "client": "ssologin.js(v1.4.19)",
                "_": int(time.time() * 1000),
            },
        )
        resp.raise_for_status()
        text = resp.text
        start, end = text.find("("), text.rfind(")")
        if start == -1 or end <= start:
            raise RuntimeError(f"微博预登录响应异常: {text[:200]}")
        data = json.loads(text[start + 1 : end])
        if data.get("retcode") != 0 or not data.get("pubkey") or not data.get("nonce"):
            raise RuntimeError(f"微博预登录失败（可能被限流）: {data}")
        return data

    def _login(self) -> None:
        """weibo.cn passport 登录：拿 SUB 等 cookie 并持久化。"""
        if not self.source_config.username or not self.source_config.password:
            raise RuntimeError("未配置 weibo.username/password，无法自动登录")
        pre = self._prelogin()
        data = {
            "entry": "weibo",
            "gateway": "1",
            "from": "",
            "savestate": "7",
            "qrcode_flag": "false",
            "useticket": "1",
            "pagerefer": "https://weibo.cn/",
            "door": "",
            "pcid": pre.get("pcid", ""),
            "pwencode": "rsa2",
            "rsakv": pre.get("rsakv", ""),
            "servertime": pre.get("servertime", ""),
            "nonce": pre.get("nonce", ""),
            "pubkey": pre.get("pubkey", ""),
            "encoding": "UTF-8",
            "prelt": "30",
            "url": "https://weibo.cn/",
            "returntype": "META",
            "service": "miniblog",
            "su": base64.b64encode(self.source_config.username.encode()).decode(),
            "sp": self._encrypt_password(self.source_config.password, pre["pubkey"], pre["nonce"]),
        }
        resp = self.client.post(
            LOGIN_URL,
            params={"client": "ssologin.js(v1.4.19)", "_": int(time.time() * 1000)},
            data=data,
        )
        resp.raise_for_status()
        text = resp.text
        if "retcode=0" not in text:
            raise RuntimeError(f"微博登录失败（可能需要验证码或凭据错误）: {text[:200]}")
        # returntype=META 的响应里带 meta refresh 跳转（ticket 交换），
        # httpx 不会自动跟随 meta refresh，需手动 GET 才能拿到 SUB 等会话 cookie。
        if not self.client.cookies.get("SUB"):
            match = re.search(r"url\s*=\s*['\"]([^'\"]+)['\"]", text)
            if match:
                redirect_url = html.unescape(match.group(1))
                try:
                    self.client.get(redirect_url)
                except Exception as exc:  # noqa: BLE001
                    raise RuntimeError(f"微博登录票据交换失败: {exc}") from None
        if not self.client.cookies.get("SUB"):
            raise RuntimeError("微博登录后未获取到 SUB cookie")
        cookie = "; ".join(f"{k}={v}" for k, v in self.client.cookies.items())
        self.db.set_setting(WEIBO_COOKIE_KEY, cookie)

    @staticmethod
    def _login_required(resp: httpx.Response) -> bool:
        if resp.status_code in (401, 403, 302):
            return True
        try:
            data = resp.json()
        except ValueError:
            return False
        msg = str(((data or {}).get("msg")) or "").lower()
        return data.get("ok") == 0 and ("login" in msg or "登录" in msg)

    def fetch(self, kol: dict) -> list[Post]:
        self._apply_cookie()
        uid = kol["external_id"]
        params = {"type": "uid", "value": uid, "containerid": f"107603{uid}"}
        resp = self.client.get(TIMELINE_URL, params=params)
        if resp.status_code == 432:
            raise RuntimeError("微博反爬拦截（HTTP 432），请检查 cookie/账号配置或降低抓取频率后重试")
        if self._login_required(resp):
            self._login()
            self._apply_cookie()
            resp = self.client.get(TIMELINE_URL, params=params)
        resp.raise_for_status()
        cards = ((resp.json() or {}).get("data") or {}).get("cards") or []
        posts = []
        for card in cards:
            if card.get("card_type") != 9:
                continue
            mblog = card.get("mblog") or {}
            mid = mblog.get("id")
            if not mid:
                continue
            text = strip_html(mblog.get("text") or "")
            posts.append(
                Post(
                    platform=self.platform,
                    kol_id=kol["id"],
                    kol_name=kol["name"],
                    external_id=str(mid),
                    title=(mblog.get("raw_text") or text)[:80],
                    content=text,
                    url=f"https://m.weibo.cn/detail/{mid}",
                    published_at=str(mblog.get("created_at") or ""),
                )
            )
        return posts
