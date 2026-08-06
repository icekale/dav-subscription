import httpx
import pytest

from app.url_safety import is_safe_http_url, safe_get


def test_rejects_non_http_and_empty():
    assert is_safe_http_url("") is False
    assert is_safe_http_url("ftp://example.com/x") is False
    assert is_safe_http_url("file:///etc/passwd") is False
    assert is_safe_http_url("javascript:alert(1)") is False


def test_rejects_internal_bare_ips():
    for url in (
        "http://127.0.0.1/",
        "http://127.0.0.1:8000/admin",
        "http://10.0.0.5/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[fc00::1]/",
    ):
        assert is_safe_http_url(url) is False, url


def test_allows_public_bare_ips():
    assert is_safe_http_url("http://93.184.216.34/") is True
    assert is_safe_http_url("https://8.8.8.8/") is True


def test_resolves_hostname_and_blocks_internal(monkeypatch):
    monkeypatch.setattr(
        "app.url_safety._resolve_host_ips",
        lambda host: ["10.0.0.6"] if host == "evil.example" else ["93.184.216.34"],
    )
    assert is_safe_http_url("http://evil.example/x") is False
    assert is_safe_http_url("http://ok.example/x") is True


def test_resolve_failure_is_unsafe(monkeypatch):
    monkeypatch.setattr("app.url_safety._resolve_host_ips", lambda host: [])
    assert is_safe_http_url("http://nope.invalid/") is False


def test_safe_get_follows_redirect_revalidating(monkeypatch):
    requested = []

    def handler(request):
        requested.append(request.url.host)
        if request.url.host == "safe.example":
            return httpx.Response(302, headers={"location": "https://target.example/img"})
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=b"x")

    monkeypatch.setattr(
        "app.url_safety._resolve_host_ips",
        lambda host: ["93.184.216.34"],
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    resp = safe_get(client, "https://safe.example/a")
    assert resp.status_code == 200
    assert requested == ["safe.example", "target.example"]


def test_safe_get_blocks_redirect_to_internal(monkeypatch):
    def handler(request):
        if request.url.host == "safe.example":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
        raise AssertionError("internal URL should never be requested")

    monkeypatch.setattr(
        "app.url_safety._resolve_host_ips",
        lambda host: ["93.184.216.34"],
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError):
        safe_get(client, "https://safe.example/a")


def test_safe_get_blocks_too_many_redirects(monkeypatch):
    def handler(request):
        return httpx.Response(302, headers={"location": "https://safe.example/loop"})

    monkeypatch.setattr(
        "app.url_safety._resolve_host_ips",
        lambda host: ["93.184.216.34"],
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError):
        safe_get(client, "https://safe.example/a")
