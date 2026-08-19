"""微博（m.weibo.cn）用户动态抓取 + 账号密码自动登录。"""
from __future__ import annotations

import base64
import html
import json
import logging
import re
import threading
import time

import httpx
import rsa

from ..avatar_cache import cache_avatar
from .base import Fetcher, Post, ThreadLocalClient, format_published_at, strip_html

logger = logging.getLogger(__name__)

WEIBO_COOKIE_KEY = "weibo_cookie"
# 同一时刻只允许一个微博登录流程（并发 worker 触发时互斥，避免 cookie 互相覆盖）
_login_lock = threading.Lock()
# 微博对高频密码登录比高频抓取更敏感（登录失败可触发账号级验证码/风控）：
# 登录失败后冷却 30 分钟再重试，避免 cookie 失效期间每轮反复打登录接口
WEIBO_LOGIN_COOLDOWN_SECONDS = 30 * 60
WEIBO_LOGIN_ATTEMPT_KEY = "weibo_login_last_attempt_at"
PRELOGIN_URL = "https://login.sina.com.cn/sso/prelogin.php"
LOGIN_URL = "https://login.sina.com.cn/sso/login.php"
# 桌面端 AJAX 接口，配合 weibo.com 域会话 cookie（扫码登录得到的会话即可用）
TIMELINE_URL = "https://weibo.com/ajax/statuses/mymblog"


def resolve_weibo_profile(uid: str, cookie: str = "", db=None) -> dict:
    """按微博 UID 解析昵称与头像。

    优先 weibo.com 官方 AJAX（需会话 Cookie，扫码/自动登录后可用）；
    无 Cookie 或失败时退回 m.weibo.cn 公开接口（数据中心 IP 可能被 432 风控）。
    全部失败返回空 dict，调用方回退占位名。
    """
    uid = (uid or "").strip()
    if not uid.isdigit():
        return {}
    desktop_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Referer": "https://weibo.com/",
        "Cookie": cookie,
    }
    mobile_headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
        ),
        "Referer": "https://m.weibo.cn/",
    }
    from ..proxy import ProxyUnavailable, acquire_client_proxy

    try:
        proxy, _pid = acquire_client_proxy(db, "weibo")
    except ProxyUnavailable:
        return {}
    if cookie:
        try:
            with httpx.Client(timeout=15, headers=desktop_headers, proxy=proxy) as client:
                resp = client.get(
                    "https://weibo.com/ajax/profile/info",
                    params={"uid": uid},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("ok") == 1:
                    user = (data.get("data") or {}).get("user") or {}
                    name = user.get("screen_name") or ""
                    avatar = (
                        user.get("avatar_hd")
                        or user.get("avatar_large")
                        or user.get("profile_image_url")
                        or ""
                    )
                    if name or avatar:
                        return {"name": name, "avatar_url": avatar, "uid": uid}
        except Exception as exc:  # noqa: BLE001
            logger.warning("微博 AJAX 解析失败 uid=%s err=%s", uid, exc)
    try:
        with httpx.Client(timeout=15, follow_redirects=True, headers=mobile_headers, proxy=proxy) as client:
            resp = client.get(
                "https://m.weibo.cn/api/container/getIndex",
                params={"type": "uid", "value": uid},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("ok") != 1:
                return {}
            user = (data.get("data") or {}).get("userInfo") or {}
            return {
                "name": user.get("screen_name") or "",
                "avatar_url": (
                    user.get("avatar_hd")
                    or user.get("avatar_large")
                    or user.get("profile_image_url")
                    or ""
                ),
                "uid": uid,
            }
    except Exception as exc:  # noqa: BLE001 - 解析失败退回占位名
        logger.warning("微博昵称解析失败 uid=%s err=%s", uid, exc)
        return {}


def cookie_header(cookies: httpx.Cookies) -> str:
    """把会话 cookie 展平为 header；同名多域时优先取 weibo.com 域的值。"""
    preferred: dict[str, str] = {}
    for cookie in cookies.jar:
        current = preferred.get(cookie.name)
        if current is None or "weibo.com" in (cookie.domain or ""):
            preferred[cookie.name] = cookie.value
    return "; ".join(f"{k}={v}" for k, v in preferred.items())


def extract_weibo_images(mblog: dict) -> list[str]:
    """微博动态图片：pics（旧格式）与 pic_infos/pic_ids（mymblog 格式）里的原图（最多 4 张）。"""
    out: list[str] = []
    for pic in mblog.get("pics") or []:
        url = (
            (pic.get("large") or {}).get("url")
            or (pic.get("original") or {}).get("url")
            or pic.get("url")
            or ""
        )
        if url.startswith("//"):
            url = f"https:{url}"
        if url and url not in out:
            out.append(url)
        if len(out) >= 4:
            break
    infos = mblog.get("pic_infos") or {}
    for pid in mblog.get("pic_ids") or []:
        info = infos.get(pid) or {}
        url = (
            (info.get("original") or {}).get("url")
            or (info.get("large") or {}).get("url")
            or (info.get("mw690") or {}).get("url")
            or ""
        )
        if url.startswith("//"):
            url = f"https:{url}"
        if url and url not in out:
            out.append(url)
        if len(out) >= 4:
            break
    return out


class WeiboFetcher(Fetcher):
    platform = "weibo"

    def __init__(self, source_config, db, client: httpx.Client | None = None):
        super().__init__(source_config)
        self.db = db
        cookie = self.source_config.cookie
        token = self.source_config.token

        def _make_client():
            from ..proxy import acquire_client_proxy, attach_proxy

            proxy, pid = acquire_client_proxy(self.db, "weibo")
            c = httpx.Client(
                timeout=20,
                follow_redirects=True,
                proxy=proxy,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                    "Referer": "https://weibo.com/",
                },
            )
            attach_proxy(c, pid)
            if cookie:
                c.headers["Cookie"] = cookie
            if token:
                c.headers["X-XSRF-TOKEN"] = token
            return c

        self._http = ThreadLocalClient(_make_client, injected=client)

    @property
    def client(self):
        return self._http.get()

    @client.setter
    def client(self, value):
        self._http.set(value)

    def _apply_cookie(self) -> None:
        """优先使用自动登录得到的 cookie，否则用配置里的初始值。"""
        cookie = self.db.get_setting(WEIBO_COOKIE_KEY) or self.source_config.cookie
        if cookie:
            self.client.headers["Cookie"] = cookie

    @staticmethod
    def _encrypt_password(password: str, pubkey_hex: str, nonce: str) -> str:
        key = rsa.PublicKey(int(pubkey_hex, 16), 65537)
        encrypted = rsa.encrypt(f"{nonce}\n{password}".encode(), key)
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
        """weibo.cn passport 登录：拿 SUB 等 cookie 并持久化。

        登录失败进入 30 分钟冷却，避免 cookie 失效期间每轮反复打登录接口
        触发账号级风控；冷却期内报清晰错误，引导手动更新 cookie。
        """
        if not self.source_config.username or not self.source_config.password:
            raise RuntimeError("未配置 weibo.username/password，无法自动登录")
        last = self.db.get_setting(WEIBO_LOGIN_ATTEMPT_KEY)
        if last:
            try:
                elapsed = int(time.time()) - int(last)
            except (TypeError, ValueError):
                elapsed = WEIBO_LOGIN_COOLDOWN_SECONDS + 1  # 格式异常视为冷却已过
            if 0 <= elapsed < WEIBO_LOGIN_COOLDOWN_SECONDS:
                remaining_min = (WEIBO_LOGIN_COOLDOWN_SECONDS - elapsed) // 60
                raise RuntimeError(
                    f"微博登录失败冷却中（约 {remaining_min} 分钟后重试），"
                    "请先手动更新微博 cookie 恢复抓取"
                )
        with _login_lock:
            try:
                self._do_login()
            except Exception:
                self.db.set_setting(WEIBO_LOGIN_ATTEMPT_KEY, str(int(time.time())))
                raise
        self.db.set_setting(WEIBO_LOGIN_ATTEMPT_KEY, "")

    def _do_login(self) -> None:
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
        if not any(c.name == "SUB" for c in self.client.cookies.jar):
            match = re.search(r"url\s*=\s*['\"]([^'\"]+)['\"]", text)
            if match:
                redirect_url = html.unescape(match.group(1))
                try:
                    self.client.get(redirect_url)
                except Exception as exc:  # noqa: BLE001
                    raise RuntimeError(f"微博登录票据交换失败: {exc}") from None
        if not any(c.name == "SUB" for c in self.client.cookies.jar):
            raise RuntimeError("微博登录后未获取到 SUB cookie")
        cookie = cookie_header(self.client.cookies)
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

    @staticmethod
    def _html_login_redirect(resp: httpx.Response) -> bool:
        """weibo.com 接口未登录时会 302 到 passport.weibo.com 的 HTML 登录页。"""
        content_type = resp.headers.get("content-type", "")
        return "text/html" in content_type and "passport.weibo.com" in str(resp.url)

    def fetch(self, kol: dict) -> list[Post]:
        self._apply_cookie()
        uid = kol["external_id"]
        params = {"uid": uid, "feature": "1" if kol.get("original_only") else "0"}
        resp = self.client.get(TIMELINE_URL, params=params)
        if resp.status_code == 432:
            raise RuntimeError("微博反爬拦截（HTTP 432），请检查 cookie/账号配置或降低抓取频率后重试")
        if self._login_required(resp) or self._html_login_redirect(resp):
            self._login()
            self._apply_cookie()
            resp = self.client.get(TIMELINE_URL, params=params)
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError(f"微博返回非 JSON（登录态失效或反爬）: HTTP {resp.status_code}") from None
        if data.get("ok") != 1:
            raise RuntimeError(f"微博接口异常: {(data.get('msg') or data)[:200]}")
        posts = []
        mblogs = (data.get("data") or {}).get("list") or []
        for mblog in mblogs:
            mid = mblog.get("id")
            if not mid:
                continue
            text = strip_html(mblog.get("text") or "")
            title = (mblog.get("text_raw") or text)[:80]
            posts.append(
                Post(
                    platform=self.platform,
                    kol_id=kol["id"],
                    kol_name=kol["name"],
                    external_id=str(mid),
                    title=title,
                    content=text,
                    url=f"https://weibo.com/detail/{mid}",
                    published_at=format_published_at(str(mblog.get("created_at") or "")),
                    images=extract_weibo_images(mblog),
                )
            )
        if mblogs:
            user = (mblogs[0].get("user") or {})
            avatar = user.get("avatar_large") or user.get("profile_image_url") or ""
            if avatar and avatar != (self.db.get_kol(kol["id"]) or {}).get("avatar_url"):
                self.db.update_kol_avatar(kol["id"], cache_avatar(self.db, kol["id"], avatar))
        return posts
