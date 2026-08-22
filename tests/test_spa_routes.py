"""History API 前端路径：白名单回退 index.html，真实资源与 API 不被劫持。"""
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def make_client(name="test.db"):
    tmp = tempfile.mkdtemp()
    app = create_app(db_path=Path(tmp) / name)
    return TestClient(app)


def test_spa_prefixes_serve_index_html():
    client = make_client("spa.db")
    for path in ("/timeline", "/home", "/admin/kols", "/kol/123", "/search", "/zsxq"):
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert "text/html" in resp.headers.get("content-type", "")
        assert "/app.js" in resp.text


def test_real_assets_and_api_not_hijacked():
    client = make_client("spa2.db")
    js = client.get("/app.js")
    assert js.status_code == 200
    assert "APP_VERSION" in js.text
    assert "text/html" not in js.headers.get("content-type", "")
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/api/me").status_code in {401, 403}
    assert client.get("/not-a-spa-page").status_code == 404
