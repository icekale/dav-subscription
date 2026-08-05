"""头像本地缓存：把远端头像下载到数据目录并返回本地 URL。

解决第三方图床（sinaimg / pbs.twimg 等）签名链接过期、外链被拦截导致的头像显示失败。
"""
from __future__ import annotations

from pathlib import Path

import httpx

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
    client = client or httpx.Client(timeout=15, follow_redirects=True, headers=DOWNLOAD_HEADERS)
    try:
        resp = client.get(url)
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
