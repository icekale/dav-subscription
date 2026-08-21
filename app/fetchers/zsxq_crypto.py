"""知识星球 App 混合加密（对应逆向 `tc/a.java`，G3）。

App 用「随机 AES 密钥包裹 + RSA(服务公钥) 再包裹」对 POST/登录体加密：
  1. 生成 16 字节随机 AES 密钥 + 16 字节随机 IV（AES-128-CBC/PKCS7）
  2. 用该密钥 AES/CBC/PKCS7 加密 JSON 明文，得到 Base64 密文
  3. 用内置 RSA 公钥 RSA/ECB/PKCS1Padding 加密 AES 密钥
纯读 GET 不需要加密（探针已验证），此模块给未来含体/登录 POST 用。

实现对齐 tc/a.java：Base64 用 NO_WRAP（Java flag=2）。
"""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives import (
    hashes,  # noqa: F401  (import 对齐 tc/a，暂无用例)
)
from cryptography.hazmat.primitives import padding as _symmetric_padding
from cryptography.hazmat.primitives.asymmetric import padding as _asym_padding
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_der_public_key,
)


def new_aes_key() -> bytes:
    """16 字节随机 AES 密钥（= tc/a.java d()）。"""
    return os.urandom(16)


def new_iv() -> bytes:
    """16 字节随机 IV（= tc/a.java e()）。"""
    return os.urandom(16)


def aes_encrypt(plaintext: bytes, aes_key: bytes, iv: bytes) -> str:
    """AES/CBC/PKCS7 加密，返回 Base64(NO_WRAP) 密文（= tc/a.java b()）。"""
    padder = _symmetric_padding.PKCS7(128).padder()
    data = padder.update(plaintext) + padder.finalize()
    enc = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).encryptor()
    return base64.b64encode(enc.update(data) + enc.finalize()).decode("ascii")


def rsa_wrap_aes_key(aes_key: bytes, public_key_bytes: bytes) -> bytes:
    """用服务 RSA 公钥 PKCS1v15 加密 AES 密钥（= tc/a.java c()）。"""
    pub = load_der_public_key(public_key_bytes)
    return pub.encrypt(aes_key, _asym_padding.PKCS1v15())


def load_public_key(pem: str | bytes) -> bytes:
    """从 PEM 公钥提取 DER 原始字节（= tc/a.java f()）。"""
    if isinstance(pem, bytes):
        pem = pem.decode("utf-8", "replace")
    der = (
        pem.replace("-----BEGIN PUBLIC KEY-----", "")
        .replace("-----END PUBLIC KEY-----", "")
        .replace("\n", "")
        .replace("\r", "")
        .strip()
    )
    return base64.b64decode(der)


def _self_test() -> None:
    """往返自检：AES 密文可解回原文；RSA 包裹可用私钥解开。"""
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    der_pub = priv.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    # AES 往返
    key, iv = new_aes_key(), new_iv()
    ct = aes_encrypt(b'{"hello":"world"}', key, iv)
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    raw = dec.update(base64.b64decode(ct)) + dec.finalize()
    unpadder = _symmetric_padding.PKCS7(128).unpadder()
    assert unpadder.update(raw) + unpadder.finalize() == b'{"hello":"world"}'
    # RSA 包裹往返
    wrapped = rsa_wrap_aes_key(key, der_pub)
    assert priv.decrypt(wrapped, _asym_padding.PKCS1v15()) == key
    # 公钥解析
    pem = (
        "-----BEGIN PUBLIC KEY-----\n"
        + base64.b64encode(der_pub).decode("ascii")
        + "\n-----END PUBLIC KEY-----\n"
    )
    assert load_public_key(pem) == der_pub
    print("zsxq_crypto self-test OK")


if __name__ == "__main__":
    _self_test()
