"""浏览器 Web Push：端点校验、VAPID、加密往返、通知器 MockTransport。"""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.fetchers.base import Post
from app.main import create_app
from app.notifiers.webpush import (
    WebPushNotifier,
    b64url,
    build_webpush_payload,
    decrypt_webpush,
    encrypt_webpush,
    generate_vapid_keys,
    is_valid_push_endpoint,
    is_valid_subscription_keys,
    vapid_authorization,
)


def make_post() -> Post:
    return Post(
        platform="xueqiu",
        kol_id=1,
        kol_name="张三",
        external_id="p1",
        title="标题",
        content="正文内容",
        url="https://xueqiu.com/1/2",
        published_at="2026-08-07 10:00:00",
    )


def make_subscriber():
    private = ec.generate_private_key(ec.SECP256R1())
    pub = private.public_key().public_numbers()
    p256dh = b64url(b"\x04" + pub.x.to_bytes(32, "big") + pub.y.to_bytes(32, "big"))
    auth = b64url(b"a" * 16)
    return private, p256dh, auth


def test_is_valid_push_endpoint():
    assert is_valid_push_endpoint("https://fcm.googleapis.com/fcm/send/abc")
    assert is_valid_push_endpoint("https://updates.push.services.mozilla.com/wpush/v2/xxx")
    assert is_valid_push_endpoint("https://web.push.apple.com/xxx")
    assert is_valid_push_endpoint("https://wns2-par02p.notify.windows.com/w/?token=1")
    assert not is_valid_push_endpoint("http://fcm.googleapis.com/fcm/send/abc")
    assert not is_valid_push_endpoint("https://evil.example.com/push")
    assert not is_valid_push_endpoint("https://127.0.0.1/push")
    assert not is_valid_push_endpoint("https://user:pass@fcm.googleapis.com/fcm/send/x")
    assert not is_valid_push_endpoint("")


def test_is_valid_subscription_keys():
    _, p256dh, auth = make_subscriber()
    assert is_valid_subscription_keys(p256dh, auth)
    assert not is_valid_subscription_keys("short", auth)
    assert not is_valid_subscription_keys(p256dh, "nope")
    assert not is_valid_subscription_keys("", "")


def test_encrypt_decrypt_roundtrip():
    ua_private, p256dh, auth = make_subscriber()
    plaintext = json.dumps({"title": "t", "body": "b"}, ensure_ascii=False).encode()
    body = encrypt_webpush(plaintext, p256dh, auth)
    assert body[20] == 65
    assert decrypt_webpush(body, ua_private, auth) == plaintext


def test_vapid_authorization_shape():
    pem, pub = generate_vapid_keys()
    header = vapid_authorization(
        "https://fcm.googleapis.com/fcm/send/x", pem, pub, "mailto:admin@localhost"
    )
    assert header.startswith("vapid t=")
    assert f"k={pub}" in header
    jwt = header.split("t=", 1)[1].split(",", 1)[0]
    parts = jwt.split(".")
    assert len(parts) == 3


def test_build_webpush_payload_truncates_and_marks():
    post = make_post()
    post.content = "x" * 500
    payload = build_webpush_payload(post, favorite=True, keyword=True)
    assert payload["title"].startswith("张三")
    assert "特别关注" in payload["body"]
    assert "命中关键词" in payload["body"]
    assert len(payload["body"]) <= 180
    assert payload["url"] == "/#/timeline"


def test_notifier_posts_encrypted_body_and_drops_gone(monkeypatch):
    pem, pub = generate_vapid_keys()
    _, p256dh, auth = make_subscriber()
    gone = "https://fcm.googleapis.com/fcm/send/gone"
    ok = "https://fcm.googleapis.com/fcm/send/ok"
    deleted = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == gone:
            return httpx.Response(410)
        assert request.headers["Content-Encoding"] == "aes128gcm"
        assert request.headers["Authorization"].startswith("vapid t=")
        assert request.content and request.content[20] == 65
        return httpx.Response(201)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    db = SimpleNamespace(delete_webpush_subscription=lambda endpoint: deleted.append(endpoint))
    notifier = WebPushNotifier(
        client=client,
        subscriptions=[
            {"endpoint": gone, "p256dh": p256dh, "auth": auth},
            {"endpoint": ok, "p256dh": p256dh, "auth": auth},
        ],
        vapid_private_pem=pem,
        vapid_public_b64=pub,
        db=db,
    )
    notifier.notify(make_post())
    assert deleted == [gone]


def test_webpush_subscribe_and_disable_api():
    tmp = tempfile.mkdtemp()
    client = TestClient(create_app(db_path=Path(tmp) / "webpush.db"))
    db = client.app.state.db
    db.add_register_code("WPUSH01")
    token = client.post(
        "/api/auth/register",
        json={"username": "webpusher", "password": "pass123456", "code": "WPUSH01"},
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/me", headers=headers).json()
    assert me["webpush_bound"] is False
    assert me["vapid_public_key"]

    _, p256dh, auth = make_subscriber()
    bad = client.post(
        "/api/me/webpush",
        headers=headers,
        json={"endpoint": "https://evil.example.com/push", "keys": {"p256dh": p256dh, "auth": auth}},
    )
    assert bad.status_code == 400

    ok = client.post(
        "/api/me/webpush",
        headers=headers,
        json={
            "endpoint": "https://fcm.googleapis.com/fcm/send/abc",
            "keys": {"p256dh": p256dh, "auth": auth},
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["webpush_bound"] is True
    me = client.get("/api/me", headers=headers).json()
    assert me["webpush_bound"] is True
    assert me["webpush_count"] == 1

    saved = client.put(
        "/api/me", headers=headers, json={"push_channels": "webpush"}
    )
    assert saved.status_code == 200, saved.text

    off = client.delete("/api/me/webpush", headers=headers)
    assert off.status_code == 200
    me = client.get("/api/me", headers=headers).json()
    assert me["webpush_bound"] is False
    assert me["webpush_count"] == 0


def test_notifier_all_gone_raises():
    pem, pub = generate_vapid_keys()
    _, p256dh, auth = make_subscriber()
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(410)))
    notifier = WebPushNotifier(
        client=client,
        subscriptions=[{"endpoint": "https://fcm.googleapis.com/fcm/send/x", "p256dh": p256dh, "auth": auth}],
        vapid_private_pem=pem,
        vapid_public_b64=pub,
    )
    with pytest.raises(RuntimeError, match="失效"):
        notifier.notify(make_post())
