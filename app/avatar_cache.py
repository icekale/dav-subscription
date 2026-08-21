"""头像本地缓存：把远端头像下载到数据目录并返回本地 URL。

解决第三方图床（sinaimg / pbs.twimg 等）签名链接过期、外链被拦截导致的头像显示失败。
"""
from __future__ import annotations

from pathlib import Path

import httpx

from .url_safety import safe_get

ALLOWED_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}
MAX_BYTES = 5 * 1024 * 1024
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
# 新浪图床有防盗链校验，需带 weibo.com Referer 才能下载；对 X/雪球图床无副作用
DOWNLOAD_HEADERS = {"User-Agent": UA, "Referer": "https://weibo.com/"}
ZSXQ_HEADERS = {"User-Agent": UA, "Referer": "https://wx.zsxq.com/"}


def headers_for(url: str) -> dict[str, str]:
    if "zsxq.com" in (url or ""):
        return dict(ZSXQ_HEADERS)
    return dict(DOWNLOAD_HEADERS)


def cache_image_file(db, url: str, folder: str, url_prefix: str, client: httpx.Client | None = None) -> str:
    """下载图片到数据目录 folder，返回本地 URL；内存库或失败时保留原 URL。"""
    url = (url or "").strip()
    if not url or url.startswith("/"):
        return url
    db_path = str(getattr(db, "path", "") or "")
    if not db_path or db_path == ":memory:":
        return url
    from urllib.parse import urlparse

    dest = Path(db_path).parent / folder
    dest.mkdir(parents=True, exist_ok=True)
    key = Path(urlparse(url).path).name
    if not key or any(ch in key for ch in "/\\"):
        import hashlib

        key = hashlib.sha1(url.encode()).hexdigest()[:16]
    for ext in ALLOWED_TYPES.values():
        existing = dest / f"{key}.{ext}"
        if existing.exists() and existing.stat().st_size > 2048:
            return f"{url_prefix}/{existing.name}"
    owns_client = client is None
    client = client or httpx.Client(timeout=15, follow_redirects=True, headers=headers_for(url))
    try:
        resp = safe_get(client, url, timeout=15)
        if resp.status_code != 200 or not resp.content:
            return url
        content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        ext = ALLOWED_TYPES.get(content_type)
        if not ext or len(resp.content) > MAX_BYTES or len(resp.content) <= 2048:
            return url
        target = dest / f"{key}.{ext}"
        target.write_bytes(resp.content)
        return f"{url_prefix}/{target.name}"
    except Exception:
        return url
    finally:
        if owns_client:
            client.close()


def cache_avatar(db, kol_id: int, remote_url: str, client: httpx.Client | None = None) -> str:
    """下载并缓存头像到本地，返回本地 URL；无需缓存或失败时原样返回远端 URL。"""
    url = (remote_url or "").strip()
    if not url or url.startswith("/avatars/"):
        return url
    kol = db.get_kol(kol_id)
    if (
        kol
        and kol.get("avatar_source") == url
        and (kol.get("avatar_url") or "").startswith("/avatars/")
    ):
        return kol["avatar_url"]
    owns_client = client is None
    client = client or httpx.Client(timeout=15, follow_redirects=True, headers=headers_for(url))
    try:
        resp = safe_get(client, url, timeout=15)
        if resp.status_code != 200 or not resp.content:
            return url
        content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        ext = ALLOWED_TYPES.get(content_type)
        if not ext or len(resp.content) > MAX_BYTES:
            return url
        avatars = Path(db.path).parent / "avatars"
        avatars.mkdir(parents=True, exist_ok=True)
        target = avatars / f"{kol_id}.{ext}"
        target.write_bytes(resp.content)
        local = f"/avatars/{kol_id}.{ext}"
        db.update_kol_avatar(kol_id, local)
        db.update_kol_avatar_source(kol_id, url)
        return local
    except Exception:  # noqa: BLE001 - 缓存失败退回远端 URL
        return url
    finally:
        if owns_client:
            client.close()
