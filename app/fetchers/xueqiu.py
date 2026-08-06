"""雪球用户原创动态抓取。"""
from __future__ import annotations

import re
import time

import httpx

from ..avatar_cache import cache_avatar
from .base import Fetcher, Post, format_published_at, strip_html

XUEQIU_COOKIE_KEY = "xueqiu_cookie"
XUEQIU_COOKIE_TIME_KEY = "xueqiu_cookie_updated_at"
XUEQIU_TIMELINE_URL = "https://xueqiu.com/statuses/user_timeline.json"


def normalize_xueqiu_id(external_id: str) -> str:
    """从雪球主页链接提取数字用户 ID；纯数字原样返回；其余原样返回（保留原有报错信息）。

    管理后台允许粘贴「主页链接/UID」（如 https://xueqiu.com/u/4514680565），
    若把完整 URL 直接当 user_id 传给接口会 400，这里统一归一化。
    """
    value = (external_id or "").strip()
    match = re.search(r"xueqiu\.com/u/(\d+)", value)
    if match:
        return match.group(1)
    if re.fullmatch(r"\d+", value):
        return value
    return value


def classify_status(status: dict) -> str | None:
    """判断动态流中的一项类型：post（发帖）/ reply（回复他人）/ None（转发等不推送项）。

    雪球 user_timeline 里回复项的特征：正文以「回复<a>@某人</a>」开头（commentId > 0），
    转发项也带 retweeted_status，不能仅凭该字段跳过（否则会把回复一起丢掉）。
    """
    desc = (status.get("description") or "").lstrip()
    if desc.startswith("回复") and status.get("commentId"):
        return "reply"
    if status.get("retweeted_status"):
        return None
    return "post"


def _is_waf_html(resp: httpx.Response) -> bool:
    """判断响应是否为阿里云 WAF 的 JS 挑战页（普通 HTTP 客户端无法通过）。"""
    content_type = resp.headers.get("content-type", "")
    return "text/html" in content_type and any(
        marker in resp.text for marker in ("renderData", "aliyun_waf", "acw_sc__v2")
    )


def merge_cookie_strings(old: str, cookies) -> str:
    """把旧 Cookie 与本次会话新下发的 cookie 合并（同名以新值为准）。

    雪球首页刷新只会回发部分 token（如 xq_a_token），直接覆盖会丢掉
    u / device_id / xqat 等其他会话字段，合并可完整保留登录态。
    """
    items: dict[str, str] = {}
    for part in (old or "").split(";"):
        if "=" in part:
            key, value = part.strip().split("=", 1)
            items[key] = value
    jar = getattr(cookies, "jar", cookies)
    for cookie in jar:
        items[cookie.name] = cookie.value
    return "; ".join(f"{k}={v}" for k, v in items.items())


def _avatar_url(user: dict) -> str:
    """从雪球 user 对象拼头像地址（photo_domain + profile_image_url 180x180 变体）。"""
    photo_domain = user.get("photo_domain") or ""
    variants = (user.get("profile_image_url") or "").split(",")
    if not variants or not variants[0]:
        return ""
    first = variants[1] if len(variants) > 1 and variants[1] else variants[0]
    if photo_domain.startswith("//"):
        return f"https:{photo_domain}{first}"
    if photo_domain.startswith("http"):
        return f"{photo_domain}{first}"
    return ""


def _extract_images(status: dict) -> list[str]:
    """雪球动态图片：original_pictures / pics / pic 字段（最多 4 张）。"""
    out: list[str] = []
    for pics_key in ("original_pictures", "pics"):
        for pic in status.get(pics_key) or []:
            url = (pic or {}).get("url") or ""
            if url.startswith("//"):
                url = f"https:{url}"
            if url and url not in out:
                out.append(url)
            if len(out) >= 4:
                return out
    # 新版接口：pic 为逗号分隔的图片列表（带 !thumb 缩略图后缀，去掉取原图）
    for url in (status.get("pic") or "").split(","):
        url = url.strip()
        if url.startswith("//"):
            url = f"https:{url}"
        if "!" in url:
            url = url.split("!")[0]
        if url and url not in out:
            out.append(url)
        if len(out) >= 4:
            break
    return out


def resolve_profile(external_id: str, cookie: str = "") -> dict:
    """查询雪球用户昵称与头像（取最新一条动态里的 user 信息），失败返回空 dict。"""
    import httpx

    uid = normalize_xueqiu_id(external_id)
    client = httpx.Client(
        timeout=15,
        follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)",
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://xueqiu.com/u/{uid}",
            **({"Cookie": cookie} if cookie else {}),
        },
    )
    try:
        resp = client.get(
            XUEQIU_TIMELINE_URL,
            params={"user_id": uid, "page": 1, "count": 1},
        )
        resp.raise_for_status()
        data = resp.json()
        statuses = (data or {}).get("statuses") or []
        if statuses:
            user = statuses[0].get("user") or {}
            screen_name = user.get("screen_name")
            avatar = _avatar_url(user)
            if screen_name:
                return {"screen_name": str(screen_name).strip(), "avatar_url": avatar}
    except Exception:  # noqa: BLE001 - 昵称解析失败不阻断导入
        return {}
    finally:
        client.close()
    return {}


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
        old = self.client.headers.get("Cookie") or ""
        cookie = merge_cookie_strings(old, self.client.cookies)
        self.db.set_setting(XUEQIU_COOKIE_KEY, cookie)
        self.db.set_setting(XUEQIU_COOKIE_TIME_KEY, str(int(time.time())))

    def fetch(self, kol: dict) -> list[Post]:
        self._apply_cookie()
        # 用户时间线 JSON 接口不受 WAF 挑战保护；original/timeline.json 反而会被 WAF 拦截
        url = XUEQIU_TIMELINE_URL
        uid = normalize_xueqiu_id(kol["external_id"])
        params = {"user_id": uid, "page": 1, "count": 20}
        self.client.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Origin": "https://xueqiu.com",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"https://xueqiu.com/u/{uid}",
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
            post_type = classify_status(s)
            if post_type is None:
                continue  # 纯转发不推送（回复项单独识别并保留）
            target = s.get("target") or ""
            url = f"https://xueqiu.com{target}" if target.startswith("/") else target
            content = strip_html(s.get("description") or "")
            if content.endswith(("…", "...")):
                # 时间线长文被截断（尾部 …）：同响应的 text 字段是完整正文，优先使用
                # （详情接口 statuses/show.json 已被雪球下线，返回 405，不再依赖）
                full = strip_html(s.get("text") or "")
                if len(full) > len(content):
                    content = full
            posts.append(
                Post(
                    platform=self.platform,
                    kol_id=kol["id"],
                    kol_name=kol["name"],
                    external_id=str(s.get("id") or ""),
                    title=s.get("title") or "",
                    content=content,
                    url=url,
                    published_at=format_published_at(str(s.get("created_at") or "")),
                    post_type=post_type,
                    images=_extract_images(s),
                )
            )
        if statuses:
            user = statuses[0].get("user") or {}
            avatar = _avatar_url(user)
            if avatar and avatar != (self.db.get_kol(kol["id"]) or {}).get("avatar_url"):
                self.db.update_kol_avatar(kol["id"], cache_avatar(self.db, kol["id"], avatar))
        return posts
