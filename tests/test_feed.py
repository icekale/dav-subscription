"""RSS 订阅源导出：build_rss_xml 渲染 + /api/feed/<token>.xml 路由。"""
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import DB
from app.feed import build_rss_xml
from app.main import create_app


def make_client(name="feed_test.db"):
    tmp = tempfile.mkdtemp()
    app = create_app(config=None, db_path=Path(tmp) / name)
    return TestClient(app)


def _seed_user_and_sub(client, username="feed_user", code="FEED01"):
    db: DB = client.app.state.db
    db.add_register_code(code)
    resp = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret123", "code": code},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]
    uid = resp.json()["user"]["id"]
    kid = db.add_kol("xueqiu", "雪球大V", "x1", category_id=None)
    db.add_subscription(uid, kid, type="post")
    db.insert_post(
        platform="xueqiu",
        kol_id=kid,
        external_id="p1",
        title="标题",
        content="正文内容 <b>加粗</b>\n第二行",
        url="https://xueqiu.com/1/2",
        published_at="2026-08-07 10:00:00",
        post_type="",
        images=["https://img.example.com/1.jpg"],
    )
    return {"Authorization": f"Bearer {token}"}, uid


def test_build_rss_xml_basic():
    posts = [
        {
            "platform": "xueqiu",
            "kol_id": 1,
            "kol_name": "雪球大V",
            "external_id": "p1",
            "title": "标题",
            "content": "正文内容 <b>加粗</b>\n第二行",
            "url": "https://xueqiu.com/1/2",
            "published_at": "2026-08-07 10:00:00",
            "post_type": "reply",
            "category_name": "实盘",
            "images": ["https://img.example.com/1.jpg"],
        }
    ]
    xml = build_rss_xml(posts, "alice", "https://dav.example.com")
    assert "<rss version=\"2.0\">" in xml
    assert "V Push · alice 的关注动态" in xml
    # 标题含平台标签 + 回复标记
    assert "[雪球]" in xml
    assert "回复" in xml
    # HTML 转义（正文里的 <b> 不应原样进 XML）
    assert "<b>" not in xml
    assert "加粗" in xml
    # guid 用 platform/external_id，pubDate 为 RFC 2822
    assert "xueqiu/p1" in xml
    assert "Aug 2026" in xml
    # enclosure 图床地址在
    assert "img.example.com" in xml


def test_build_rss_xml_escape_and_missing_fields():
    posts = [
        {
            "platform": "weibo",
            "kol_id": 1,
            "kol_name": "A&B",
            "external_id": "w1",
            "title": "",
            "content": "",
            "url": "",
            "published_at": "",
            "category_name": None,
            "images": [],
        }
    ]
    xml = build_rss_xml(posts, "bob", "")
    assert "A&amp;B" in xml
    assert "（无正文）" in xml
    assert "微博" in xml
    # 空发布时间的兜底（当前时间，东八区 RFC2822）
    assert "+0800" in xml


def test_feed_route_requires_token_and_renders():
    client = make_client()
    headers, _ = _seed_user_and_sub(client)
    me = client.get("/api/me", headers=headers).json()
    token = me["feed_token"]
    assert token

    resp = client.get(f"/api/feed/{token}.xml")
    assert resp.status_code == 200
    assert "application/rss+xml" in resp.headers["content-type"]
    assert "雪球大V" in resp.text
    assert "正文内容" in resp.text
    # 未登录也可访问（RSS 阅读器场景）
    assert resp.text.startswith("<?xml")


def test_feed_route_404_on_bad_token():
    client = make_client()
    resp = client.get("/api/feed/not-a-real-token.xml")
    assert resp.status_code == 404


def test_feed_token_regenerate_invalidates_old():
    client = make_client()
    headers, _ = _seed_user_and_sub(client)
    old = client.get("/api/me", headers=headers).json()["feed_token"]

    resp = client.post("/api/me/feed-token/regenerate", headers=headers)
    assert resp.status_code == 200
    new = resp.json()["feed_token"]
    assert new != old

    assert client.get(f"/api/feed/{old}.xml").status_code == 404
    assert client.get(f"/api/feed/{new}.xml").status_code == 200


def test_feed_route_empty_subscriptions():
    client = make_client()
    db: DB = client.app.state.db
    db.add_register_code("FEED02")
    resp = client.post(
        "/api/auth/register",
        json={"username": "nobody", "password": "secret123", "code": "FEED02"},
    )
    token = resp.json()["token"]
    me = client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).json()
    resp = client.get(f"/api/feed/{me['feed_token']}.xml")
    assert resp.status_code == 200
    assert "<item>" not in resp.text
