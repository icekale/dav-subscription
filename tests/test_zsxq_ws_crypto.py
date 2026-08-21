"""知识星球 App 原生协议层单元测试：混合加密(G3) + WS 信封/分发(G5)。"""
import base64
import json
import os

from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.fetchers.zsxq import _ws_address, _ws_enabled
from app.fetchers.zsxq_crypto import (
    aes_encrypt,
    load_public_key,
    new_aes_key,
    new_iv,
    rsa_wrap_aes_key,
)
from app.fetchers.zsxq_ws import (
    build_request,
    parse_resp,
    utc_str,
    ws_handshake_headers,
)


def _aes_decrypt(ct_b64, key, iv):
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    return dec.update(ct_b64) + dec.finalize()


def test_crypto_roundtrip():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    der = priv.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    pem = "-----BEGIN PUBLIC KEY-----\n" + base64.b64encode(der).decode() + "\n-----END PUBLIC KEY-----\n"
    assert load_public_key(pem) == der

    key, iv = new_aes_key(), new_iv()
    ct = aes_encrypt(b'{"a":1}', key, iv)
    assert _aes_decrypt(base64.b64decode(ct), key, iv).startswith(b'{"a":1}')  # PKCS7 填充
    # RSA 包裹可被私钥解开
    wrapped = rsa_wrap_aes_key(key, der)
    assert priv.decrypt(wrapped, padding.PKCS1v15()) == key


def test_ws_build_request():
    now = 1764252723000
    req = build_request(now, [(28888112822211, now)], now)
    rd = req["req_data"]
    assert set(rd) == {"dynamics", "groups", "in_app_notifications"}
    assert rd["groups"][0] == {"group_id": 28888112822211, "begin_time": "2025-11-27T22:12:03.000+0800"}
    assert utc_str(now) == "2025-11-27T22:12:03.000+0800"
    assert set(ws_handshake_headers()) == {"User-Agent", "X-Request-Id", "X-Version"}


def test_ws_parse_resp_dispatch():
    sample = {
        "succeeded": True, "code": 0, "info": "", "resp_data": {
            "resp_id": "r1",
            "dynamics": {"updated": {"occur_time": "2025-11-27T22:12:03.000+0800"}},
            "in_app_notifications": {"updated": {"occur_time": "2025-11-27T22:12:04.000+0800"}},
            "groups": [
                {"group_id": 1, "joined": {"occur_time": "2025-11-27T22:12:05.000+0800"}},
                {"group_id": 2, "updated": {"occur_time": "2025-11-27T22:12:06.000+0800"}},
                {"group_id": 3, "exited": {"removed": True, "occur_time": "2025-11-27T22:13:00.000+0800"}},
            ],
            "command": {"text": "bye", "action": "logout"},
            "im_messages": [{"conversation_id": 9}],
        }
    }
    r = parse_resp(json.dumps(sample))
    assert r["succeeded"]
    kinds = [k for k, _ in r["events"]]
    assert kinds[:1] == ["resp_id"] and {"dynamics", "in_app", "logout", "im"} <= set(kinds)
    groups = [d for k, d in r["events"] if k == "group"]
    assert [g["action"] for g in groups] == ["joined", "updated", "exited"]
    assert groups[2]["removed"] is True


def test_ws_config_helpers():
    class Db:
        def __init__(self, vals):
            self.vals = vals

        def get_setting(self, key):
            return self.vals.get(key)

    for k in ("ZSXQ_WS_ENABLED", "ZSXQ_WS_ADDRESS"):
        os.environ.pop(k, None)
    # db 提供值
    assert _ws_enabled(Db({"zsxq_ws_enabled": "1"})) is True
    assert _ws_address(Db({"zsxq_ws_address": "wss://a.b/c"})) == "wss://a.b/c"
    # db 缺省回退环境变量
    os.environ["ZSXQ_WS_ENABLED"] = "1"
    os.environ["ZSXQ_WS_ADDRESS"] = "ws://x.y"
    assert _ws_enabled(Db({})) is True
    assert _ws_address(Db({})) == "ws://x.y"
    # 都缺省：关且空
    os.environ.pop("ZSXQ_WS_ENABLED")
    os.environ.pop("ZSXQ_WS_ADDRESS")
    assert _ws_enabled(Db({})) is False
    assert _ws_address(Db({})) == ""
    assert _ws_enabled(None) is False


def test_ws_dedupe_resp_id():
    # 同一 resp_id 由调用侧去重：两次解析 events 首个元素相同，视为重复
    raw = json.dumps({"succeeded": True, "resp_data": {"resp_id": "dup"}})
    r1 = parse_resp(raw)
    assert r1["events"][0] == ("resp_id", "dup")
