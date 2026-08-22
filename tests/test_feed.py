"""私有 RSS 已下线：路由、token、前端入口都不应再出现。"""
from pathlib import Path

from test_api import make_client, user_headers

ROOT = Path(__file__).parent.parent


def test_rss_feed_route_and_token_are_gone():
    client = make_client()
    headers = user_headers(client, "norss1")
    me = client.get("/api/me", headers=headers).json()
    assert "feed_token" not in me
    assert client.get("/api/feed/anything.xml").status_code == 404
    assert client.post("/api/me/feed-token/regenerate", headers=headers).status_code in (404, 405)


def test_rss_module_and_ui_removed():
    assert not (ROOT / "app" / "feed.py").exists()
    app_js = (ROOT / "app" / "static" / "app.js").read_text()
    assert "copyFeedUrl" not in app_js
    assert "RSS 订阅源" not in app_js
    assert "set-feed-url" not in app_js
    wxml = (ROOT / "miniprogram" / "pages" / "settings" / "settings.wxml").read_text()
    assert "RSS" not in wxml
    js = (ROOT / "miniprogram" / "pages" / "settings" / "settings.js").read_text()
    assert "copyFeed" not in js
    assert "feed-token" not in js
