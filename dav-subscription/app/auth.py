"""认证：PBKDF2 密码哈希 + HMAC 签名 token（无第三方依赖）。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

TOKEN_TTL_SECONDS = 30 * 24 * 3600

def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), 200_000
    ).hex()
    return f"{salt}${digest}"


# 用户不存在时也执行一次同样的哈希校验，避免通过响应时间探测用户名是否存在
DUMMY_HASH = hash_password("__dummy__")


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, salt), stored)


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def create_token(user_id: int, username: str, secret: str) -> str:
    payload = {
        "uid": user_id,
        "name": username,
        "exp": int(time.time()) + TOKEN_TTL_SECONDS,
    }
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_token(token: str, secret: str) -> dict | None:
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        payload = json.loads(_b64d(body))
    except Exception:
        return None
    if not isinstance(payload, dict) or payload.get("exp", 0) < time.time():
        return None
    return payload


def get_or_create_secret(db, configured: str = "") -> str:
    """token 密钥：优先用配置，否则在 DB 里持久化一个随机密钥。"""
    if configured:
        return configured
    key = "token_secret"
    secret = db.get_setting(key)
    if not secret:
        secret = os.urandom(32).hex()
        db.set_setting(key, secret)
    return secret
