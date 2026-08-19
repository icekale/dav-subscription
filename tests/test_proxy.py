"""代理行解析、提取启发式与池/节点 CRUD。"""
from types import SimpleNamespace

import pytest

from app.db import DB
from app.fetchers.base import ThreadLocalClient
from app.proxy import (
    ParsedProxy,
    ProxyRouter,
    ProxyUnavailable,
    acquire_client_proxy,
    extract_pool,
    note_fetch_proxy,
    parse_extract_payload,
    parse_proxy_lines,
    probe_proxy,
    proxy_url,
    tick_proxy_pools,
)


def test_parse_host_port_uses_default_protocol():
    rows = parse_proxy_lines("1.2.3.4:8080", default_protocol="socks5")
    assert len(rows) == 1
    assert rows[0].protocol == "socks5"
    assert rows[0].host == "1.2.3.4"
    assert rows[0].port == 8080
    assert rows[0].username == ""
    assert rows[0].password == ""


def test_parse_host_port_user_pass():
    rows = parse_proxy_lines("1.2.3.4:8080:alice:s3cret")
    assert rows[0].username == "alice"
    assert rows[0].password == "s3cret"
    assert rows[0].protocol == "http"


def test_parse_user_pass_at_host():
    rows = parse_proxy_lines("alice:s3cret@1.2.3.4:8080")
    assert rows[0].host == "1.2.3.4"
    assert rows[0].port == 8080
    assert rows[0].username == "alice"
    assert rows[0].password == "s3cret"


def test_parse_host_port_at_user_pass():
    rows = parse_proxy_lines("1.2.3.4:8080@alice:s3cret")
    assert rows[0].host == "1.2.3.4"
    assert rows[0].username == "alice"
    assert rows[0].password == "s3cret"


def test_parse_scheme_overrides_default_protocol():
    rows = parse_proxy_lines(
        "socks5://alice:s3cret@1.2.3.4:1080\nhttp://9.9.9.9:80",
        default_protocol="http",
    )
    assert rows[0].protocol == "socks5"
    assert rows[0].username == "alice"
    assert rows[1].protocol == "http"
    assert rows[1].host == "9.9.9.9"


def test_parse_skips_comments_blanks_and_bad_lines():
    text = """
# comment
1.2.3.4:8080

not-a-proxy
1.2.3.4:99999
"""
    rows = parse_proxy_lines(text)
    assert len(rows) == 1
    assert rows[0].port == 8080


def test_proxy_url_uses_socks5h_and_http():
    rows = parse_proxy_lines(
        "socks5://u:p@1.2.3.4:1080\nhttp://u:p@5.6.7.8:8080"
    )
    assert proxy_url(rows[0]) == "socks5h://u:p@1.2.3.4:1080"
    assert proxy_url(rows[1]) == "http://u:p@5.6.7.8:8080"


def test_extract_payload_plain_lines():
    lines = parse_extract_payload("1.2.3.4:8080\n5.6.7.8:9090\n")
    assert lines == ["1.2.3.4:8080", "5.6.7.8:9090"]


def test_extract_payload_json_string_list():
    assert parse_extract_payload('["1.2.3.4:8080", "5.6.7.8:9090"]') == [
        "1.2.3.4:8080",
        "5.6.7.8:9090",
    ]


def test_extract_payload_json_wrapped_data():
    payload = '{"code":0,"data":["1.2.3.4:8080","5.6.7.8:9090"]}'
    assert parse_extract_payload(payload) == ["1.2.3.4:8080", "5.6.7.8:9090"]


def test_extract_payload_json_ip_port_objects():
    payload = '{"data":[{"ip":"1.2.3.4","port":8080},{"ip":"5.6.7.8","port":"9090"}]}'
    assert parse_extract_payload(payload) == ["1.2.3.4:8080", "5.6.7.8:9090"]


def test_create_static_pool_and_upsert_proxy(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    pool_id = db.create_proxy_pool("海外S5", kind="static", protocol="socks5")
    pid = db.upsert_proxy(pool_id, "socks5", "1.2.3.4", 1080, "u", "p", source="manual")
    row = db.get_proxy(pid)
    assert row["host"] == "1.2.3.4"
    assert row["username"] == "u"
    assert row["status"] == "unknown"
    pools = db.list_proxy_pools()
    assert pools[0]["name"] == "海外S5"
    assert pools[0]["proxy_count"] == 1


def test_upsert_same_proxy_updates_expiry_not_duplicate(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    pool_id = db.create_proxy_pool("提取", kind="extract", protocol="http")
    first = db.upsert_proxy(
        pool_id, "http", "1.2.3.4", 8080, source="extract", expires_at=100
    )
    again = db.upsert_proxy(
        pool_id, "http", "1.2.3.4", 8080, source="extract", expires_at=200
    )
    assert first == again
    assert len(db.list_proxies(pool_id)) == 1
    assert db.get_proxy(first)["expires_at"] == 200


def test_delete_expired_extracted_keeps_manual(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    pool_id = db.create_proxy_pool("混合")
    db.upsert_proxy(pool_id, "http", "1.1.1.1", 80, source="manual", expires_at=1)
    db.upsert_proxy(pool_id, "http", "2.2.2.2", 80, source="extract", expires_at=1)
    db.upsert_proxy(pool_id, "http", "3.3.3.3", 80, source="extract", expires_at=9999999999)
    deleted = db.delete_expired_extracted_proxies(now=10)
    assert deleted == 1
    hosts = {r["host"] for r in db.list_proxies(pool_id)}
    assert hosts == {"1.1.1.1", "3.3.3.3"}


def test_router_default_is_direct(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    assert ProxyRouter(db).acquire("twitter") is None


def test_router_pool_picks_usable_and_skips_dead(tmp_path, monkeypatch):
    db = DB(str(tmp_path / "t.db"))
    pool_id = db.create_proxy_pool("池")
    dead_id = db.upsert_proxy(pool_id, "http", "1.1.1.1", 80)
    ok_id = db.upsert_proxy(pool_id, "http", "2.2.2.2", 80)
    router = ProxyRouter(db)
    router.set_routes({"twitter": {"mode": "pool", "pool_id": pool_id}})
    for _ in range(3):
        router.report_fail(dead_id, "timeout")
    picked = []
    monkeypatch.setattr("app.proxy.random.choice", lambda seq: seq[0])
    for _ in range(3):
        row = router.acquire("twitter")
        picked.append(row["id"])
    assert picked == [ok_id, ok_id, ok_id]
    assert db.get_proxy(dead_id)["status"] == "dead"


def test_router_empty_pool_raises(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    pool_id = db.create_proxy_pool("空")
    router = ProxyRouter(db)
    router.set_routes({"xueqiu": {"mode": "pool", "pool_id": pool_id}})
    with pytest.raises(ProxyUnavailable, match="代理池为空"):
        router.acquire("xueqiu")


def test_router_specified_proxy_rejects_expired(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    pool_id = db.create_proxy_pool("单")
    pid = db.upsert_proxy(pool_id, "http", "1.1.1.1", 80, expires_at=1)
    router = ProxyRouter(db)
    router.set_routes({"weibo": {"mode": "proxy", "proxy_id": pid}})
    with pytest.raises(ProxyUnavailable, match="已过期"):
        router.acquire("weibo", now=10)


def test_router_report_ok_clears_fails(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    pool_id = db.create_proxy_pool("池")
    pid = db.upsert_proxy(pool_id, "http", "1.1.1.1", 80)
    router = ProxyRouter(db)
    router.report_fail(pid, "x")
    router.report_ok(pid)
    row = db.get_proxy(pid)
    assert row["status"] == "ok"
    assert row["fail_count"] == 0


def test_extract_pool_parses_json_and_sets_expiry(tmp_path, monkeypatch):
    db = DB(str(tmp_path / "t.db"))
    pool_id = db.create_proxy_pool(
        "芝麻",
        kind="extract",
        extract_url="https://api.example.com/get?key=SECRET",
        protocol="http",
        expire_seconds=60,
    )

    class FakeResp:
        text = '{"data":["1.2.3.4:8080"]}'

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, url):
            assert url.startswith("https://api.example.com/get")
            return FakeResp()

        def close(self):
            return None

    monkeypatch.setattr("app.proxy.httpx.Client", FakeClient)
    result = extract_pool(db, pool_id, now=1000)
    assert result["imported"] == 1
    row = db.list_proxies(pool_id)[0]
    assert row["host"] == "1.2.3.4"
    assert row["source"] == "extract"
    assert row["expires_at"] == 1060
    assert db.get_proxy_pool(pool_id)["last_error"] == ""


def test_extract_pool_records_error(tmp_path, monkeypatch):
    db = DB(str(tmp_path / "t.db"))
    pool_id = db.create_proxy_pool(
        "芝麻", kind="extract", extract_url="https://api.example.com/get"
    )

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, url):
            raise RuntimeError("timeout")

        def close(self):
            return None

    monkeypatch.setattr("app.proxy.httpx.Client", FakeClient)
    with pytest.raises(RuntimeError, match="timeout"):
        extract_pool(db, pool_id)
    assert "timeout" in db.get_proxy_pool(pool_id)["last_error"]


def test_probe_proxy_ok(monkeypatch):
    class FakeResp:
        status_code = 204

    class FakeClient:
        def __init__(self, *args, **kwargs):
            assert "1.2.3.4" in (kwargs.get("proxy") or "")

        def get(self, url):
            return FakeResp()

        def close(self):
            return None

    monkeypatch.setattr("app.proxy.httpx.Client", FakeClient)
    result = probe_proxy(ParsedProxy("http", "1.2.3.4", 8080, "u", "p"))
    assert result["ok"] is True
    assert result["status_code"] == 204


def test_tick_deletes_expired_and_refreshes_due_pool(tmp_path, monkeypatch):
    db = DB(str(tmp_path / "t.db"))
    pool_id = db.create_proxy_pool(
        "提取",
        kind="extract",
        extract_url="https://api.example.com/get",
        expire_seconds=60,
        refresh_interval_seconds=30,
    )
    db.upsert_proxy(pool_id, "http", "1.1.1.1", 80, source="extract", expires_at=5)
    db.update_proxy_pool(pool_id, last_extract_at=10)
    calls = []

    class FakeResp:
        text = "8.8.8.8:8080"

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, url):
            calls.append(url)
            return FakeResp()

        def close(self):
            return None

    monkeypatch.setattr("app.proxy.httpx.Client", FakeClient)
    result = tick_proxy_pools(db, now=50)
    assert result["expired"] == 1
    assert result["extracted"] == 1
    assert calls
    hosts = {r["host"] for r in db.list_proxies(pool_id)}
    assert hosts == {"8.8.8.8"}
    assert db.get_proxy_pool(pool_id)["last_extract_at"] == 50


def test_tick_skips_extract_when_not_due(tmp_path, monkeypatch):
    db = DB(str(tmp_path / "t.db"))
    db.create_proxy_pool(
        "提取",
        kind="extract",
        extract_url="https://api.example.com/get",
        refresh_interval_seconds=30,
    )
    db.update_proxy_pool(1, last_extract_at=40)
    monkeypatch.setattr(
        "app.proxy.httpx.Client",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not extract")),
    )
    result = tick_proxy_pools(db, now=50)
    assert result["extracted"] == 0


def test_acquire_client_proxy_direct_and_pool(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    assert acquire_client_proxy(None, "xueqiu") == (None, None)
    assert acquire_client_proxy(db, "xueqiu") == (None, None)
    pool_id = db.create_proxy_pool("池")
    pid = db.upsert_proxy(pool_id, "http", "1.2.3.4", 8080, "u", "p")
    ProxyRouter(db).set_routes({"xueqiu": {"mode": "pool", "pool_id": pool_id}})
    url, got = acquire_client_proxy(db, "xueqiu")
    assert got == pid
    assert url == "http://u:p@1.2.3.4:8080"


def test_thread_local_client_reset():
    n = {"i": 0}

    def factory():
        n["i"] += 1
        return n["i"]

    tl = ThreadLocalClient(factory)
    assert tl.get() == 1
    assert tl.get() == 1
    tl.reset()
    assert tl.get() == 2


def test_note_fetch_proxy_fail_then_ok(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    pool_id = db.create_proxy_pool("池")
    pid = db.upsert_proxy(pool_id, "http", "1.2.3.4", 80)
    client = SimpleNamespace(_vpush_proxy_id=pid)
    fetcher = SimpleNamespace(db=db, _http=ThreadLocalClient(lambda: client, injected=client))
    note_fetch_proxy(fetcher, False, "timeout")
    assert db.get_proxy(pid)["fail_count"] == 1
    note_fetch_proxy(fetcher, True)
    assert db.get_proxy(pid)["status"] == "ok"
