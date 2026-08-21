"""浏览器 Web Push（Chrome / Edge，关掉标签页也能弹）。

VAPID 密钥未配置时首次使用自动生成并写入 settings 表。
推送端点只允许已知推送服务主机，避免把订阅 URL 当成 SSRF。
"""
from __future__ import annotations

import base64
import json
import os
import struct
import time
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..fetchers.base import PLATFORM_LABELS, Post, digest_body
from .base import Notifier, why_badges

MAX_BODY = 180
DIGEST_MAX_ITEMS = 8
DND_MAX_ITEMS = 10
DEFAULT_MAILTO = "mailto:admin@localhost"
VAPID_PRIV_SETTING = "vapid_private_key"
VAPID_PUB_SETTING = "vapid_public_key"

_PUSH_HOSTS = frozenset({
    "fcm.googleapis.com",
    "android.googleapis.com",
    "updates.push.services.mozilla.com",
    "web.push.apple.com",
})
_PUSH_SUFFIXES = (".notify.windows.com", ".push.apple.com")


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(s: str) -> bytes:
    raw = (s or "").strip()
    pad = "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode(raw + pad)


def is_valid_push_endpoint(url: str) -> bool:
    if not url or len(url) > 2048:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return False
    host = parsed.hostname.lower().rstrip(".")
    return host in _PUSH_HOSTS or any(host.endswith(suf) for suf in _PUSH_SUFFIXES)


def is_valid_subscription_keys(p256dh: str, auth: str) -> bool:
    try:
        pub = b64url_decode(p256dh)
        secret = b64url_decode(auth)
    except (ValueError, TypeError):
        return False
    return len(pub) == 65 and pub[0] == 4 and len(secret) == 16


def _public_b64url(public_key) -> str:
    numbers = public_key.public_numbers()
    return b64url(b"\x04" + numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big"))


def _load_private_pem(pem: str):
    return serialization.load_pem_private_key(pem.encode(), password=None)


def generate_vapid_keys() -> tuple[str, str]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return pem, _public_b64url(private_key.public_key())


def public_b64url_from_pem(pem: str) -> str:
    return _public_b64url(_load_private_pem(pem).public_key())


def ensure_vapid_keys(db=None, config=None) -> tuple[str, str]:
    """返回 (private_pem, public_b64url)。配置优先，否则读/写入 settings。"""
    cfg_priv = (getattr(config, "vapid_private_key", "") or "").strip() if config else ""
    cfg_pub = (getattr(config, "vapid_public_key", "") or "").strip() if config else ""
    if cfg_priv:
        return cfg_priv, cfg_pub or public_b64url_from_pem(cfg_priv)
    if db is not None:
        stored_priv = (db.get_setting(VAPID_PRIV_SETTING) or "").strip()
        stored_pub = (db.get_setting(VAPID_PUB_SETTING) or "").strip()
        if stored_priv:
            pub = stored_pub or public_b64url_from_pem(stored_priv)
            if not stored_pub:
                db.set_setting(VAPID_PUB_SETTING, pub)
            return stored_priv, pub
        pem, pub = generate_vapid_keys()
        db.set_setting(VAPID_PRIV_SETTING, pem)
        db.set_setting(VAPID_PUB_SETTING, pub)
        return pem, pub
    return generate_vapid_keys()


def vapid_mailto(config=None) -> str:
    value = (getattr(config, "vapid_mailto", "") or "").strip() if config else ""
    return value or DEFAULT_MAILTO


def _load_uncompressed(data: bytes):
    if len(data) != 65 or data[0] != 4:
        raise ValueError("p256dh 无效")
    x = int.from_bytes(data[1:33], "big")
    y = int.from_bytes(data[33:], "big")
    return ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()


def encrypt_webpush(plaintext: bytes, p256dh: str, auth: str) -> bytes:
    """RFC 8291 aes128gcm 单记录加密。"""
    ua_public = b64url_decode(p256dh)
    auth_secret = b64url_decode(auth)
    local = ec.generate_private_key(ec.SECP256R1())
    local_public = b"\x04" + local.public_key().public_numbers().x.to_bytes(32, "big") + (
        local.public_key().public_numbers().y.to_bytes(32, "big")
    )
    shared = local.exchange(ec.ECDH(), _load_uncompressed(ua_public))
    salt = os.urandom(16)
    ikm = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=auth_secret,
        info=b"WebPush: info\x00" + ua_public + local_public,
    ).derive(shared)
    cek = HKDF(
        algorithm=hashes.SHA256(), length=16, salt=salt, info=b"Content-Encoding: aes128gcm\x00",
    ).derive(ikm)
    nonce = HKDF(
        algorithm=hashes.SHA256(), length=12, salt=salt, info=b"Content-Encoding: nonce\x00",
    ).derive(ikm)
    ciphertext = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)
    return salt + struct.pack("!L", 4096) + bytes([65]) + local_public + ciphertext


def decrypt_webpush(body: bytes, ua_private, auth: str) -> bytes:
    """测试用：解开 encrypt_webpush 的密文。"""
    salt, rs, idlen = body[:16], struct.unpack("!L", body[16:20])[0], body[20]
    if rs != 4096 or idlen != 65:
        raise ValueError("header 无效")
    local_public, ciphertext = body[21:86], body[86:]
    ua_public_bytes = (
        b"\x04"
        + ua_private.public_key().public_numbers().x.to_bytes(32, "big")
        + ua_private.public_key().public_numbers().y.to_bytes(32, "big")
    )
    shared = ua_private.exchange(ec.ECDH(), _load_uncompressed(local_public))
    auth_secret = b64url_decode(auth)
    ikm = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=auth_secret,
        info=b"WebPush: info\x00" + ua_public_bytes + local_public,
    ).derive(shared)
    cek = HKDF(
        algorithm=hashes.SHA256(), length=16, salt=salt, info=b"Content-Encoding: aes128gcm\x00",
    ).derive(ikm)
    nonce = HKDF(
        algorithm=hashes.SHA256(), length=12, salt=salt, info=b"Content-Encoding: nonce\x00",
    ).derive(ikm)
    padded = AESGCM(cek).decrypt(nonce, ciphertext, None)
    if not padded.endswith(b"\x02"):
        raise ValueError("padding 无效")
    return padded[:-1]


def vapid_authorization(endpoint: str, private_pem: str, public_b64: str, mailto: str) -> str:
    parsed = urlparse(endpoint)
    aud = f"{parsed.scheme}://{parsed.netloc}"
    header = b64url(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = b64url(json.dumps(
        {"aud": aud, "exp": int(time.time()) + 12 * 3600, "sub": mailto},
        separators=(",", ":"),
    ).encode())
    signing_input = f"{header}.{claims}".encode()
    der = _load_private_pem(private_pem).sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    jwt = f"{header}.{claims}.{b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    return f"vapid t={jwt}, k={public_b64}"


def build_webpush_payload(post: Post, favorite: bool = False, keyword: bool = False) -> dict:
    platform = PLATFORM_LABELS.get(post.platform, post.platform)
    kind = " · 回复" if post.post_type == "reply" else ""
    title = f"{post.kol_name} · {platform}{kind}"[:60]
    body = (post.content or post.title or "（无正文）").replace("\n", " ").strip()
    badges = why_badges(favorite, keyword)
    if badges:
        body = f"{badges}  {body}"
    return {
        "title": title,
        "body": body[:MAX_BODY],
        "url": "/#/timeline",
        "tag": f"post-{post.platform}-{post.external_id}"[:80],
    }


def build_webpush_digest_payload(posts: list[Post], kol_name: str, platform: str) -> dict:
    platform_label = PLATFORM_LABELS.get(platform, platform)
    lines = []
    for post in posts[:DIGEST_MAX_ITEMS]:
        lines.append(digest_body(post, full=False, max_chars=80))
    extra = f" 等共 {len(posts)} 条" if len(posts) > DIGEST_MAX_ITEMS else ""
    return {
        "title": f"{kol_name} · {platform_label}（{len(posts)} 条）"[:60],
        "body": ("；".join(lines) + extra)[:MAX_BODY],
        "url": "/#/timeline",
        "tag": f"digest-{platform}-{kol_name}"[:80],
    }


def build_webpush_summary_payload(posts: list[Post], title: str) -> dict:
    lines = []
    for post in posts[:DND_MAX_ITEMS]:
        platform = PLATFORM_LABELS.get(post.platform, post.platform)
        lines.append(f"{post.kol_name}（{platform}）：{digest_body(post, full=False, max_chars=60)}")
    extra = f" 等共 {len(posts)} 条" if len(posts) > DND_MAX_ITEMS else ""
    return {
        "title": title[:60],
        "body": ("；".join(lines) + extra)[:MAX_BODY],
        "url": "/#/timeline",
        "tag": title[:80],
    }


class WebPushNotifier(Notifier):
    channel = "webpush"

    def __init__(
        self,
        config=None,
        client: httpx.Client | None = None,
        subscriptions: list | None = None,
        vapid_private_pem: str = "",
        vapid_public_b64: str = "",
        vapid_mailto: str = "",
        db=None,
        favorite: bool = False,
        keyword: bool = False,
    ):
        self.subscriptions = list(subscriptions or [])
        self.vapid_private_pem = vapid_private_pem
        self.vapid_public_b64 = vapid_public_b64
        self.vapid_mailto = vapid_mailto or DEFAULT_MAILTO
        self.client = client or httpx.Client(timeout=15)
        self.db = db
        self.favorite = favorite
        self.keyword = keyword
        if config is not None and not self.vapid_private_pem:
            self.vapid_private_pem, self.vapid_public_b64 = ensure_vapid_keys(db, config)
            self.vapid_mailto = vapid_mailto(config)

    def _post_payload(self, payload: dict) -> None:
        if not self.subscriptions:
            raise RuntimeError("用户未绑定浏览器通知")
        if not self.vapid_private_pem:
            raise RuntimeError("未配置 VAPID 密钥")
        body = json.dumps(payload, ensure_ascii=False).encode()
        remaining = 0
        last_error = ""
        for sub in self.subscriptions:
            endpoint = (sub.get("endpoint") or "").strip()
            p256dh = (sub.get("p256dh") or "").strip()
            auth = (sub.get("auth") or "").strip()
            if not (endpoint and p256dh and auth):
                continue
            try:
                encrypted = encrypt_webpush(body, p256dh, auth)
                headers = {
                    "TTL": "86400",
                    "Urgency": "high",
                    "Content-Encoding": "aes128gcm",
                    "Content-Type": "application/octet-stream",
                    "Authorization": vapid_authorization(
                        endpoint, self.vapid_private_pem, self.vapid_public_b64, self.vapid_mailto
                    ),
                }
                resp = self.client.post(endpoint, content=encrypted, headers=headers)
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                continue
            if resp.status_code in (404, 410):
                if self.db is not None:
                    self.db.delete_webpush_subscription(endpoint)
                continue
            if resp.status_code >= 400:
                last_error = f"HTTP {resp.status_code}"
                continue
            remaining += 1
        if remaining == 0:
            raise RuntimeError(last_error or "浏览器推送订阅已全部失效")

    def notify(self, post: Post) -> None:
        self._post_payload(build_webpush_payload(post, self.favorite, self.keyword))

    def send_digest(self, posts: list[Post], kol_name: str, platform: str) -> None:
        self._post_payload(build_webpush_digest_payload(posts, kol_name, platform))

    def send_dnd_summary(self, posts: list[Post], title: str | None = None) -> None:
        self._post_payload(build_webpush_summary_payload(posts, title or "🌙 免打扰时段汇总"))

    def send_daily(self, posts: list[Post]) -> None:
        self._post_payload(build_webpush_summary_payload(posts, "📅 每日精选"))

    def send_text(self, text: str, reply_markup: list | None = None) -> None:
        lines = (text or "").strip().splitlines()
        title = lines[0][:60] if lines else "V Push"
        body = "\n".join(lines[1:]).strip() or title
        self._post_payload({"title": title, "body": body[:MAX_BODY], "url": "/", "tag": "text"})
