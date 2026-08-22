"""PWA Service Worker 静态回归测试：API 永不缓存，外壳仍可离线。"""
import re
from pathlib import Path

SW_JS = Path(__file__).parent.parent / "app" / "static" / "sw.js"


def test_fetch_handler_excludes_api_route():
    src = SW_JS.read_text()
    fetch_block = src[src.index('self.addEventListener("fetch"'):]
    assert re.search(r'pathname\.startsWith\("/api/"\)', fetch_block)
    assert '"/feed/"' not in fetch_block


def test_fetch_handler_still_guards_method_and_origin():
    src = SW_JS.read_text()
    fetch_block = src[src.index('self.addEventListener("fetch"'):]
    assert re.search(r'request\.method !== "GET"', fetch_block)
    assert re.search(r'url\.origin !== self\.location\.origin', fetch_block)


def test_shell_assets_and_registration_present():
    """离线外壳与注册入口仍存在。"""
    src = SW_JS.read_text()
    for marker in ("/manifest.webmanifest", 'caches.open(CACHE)', "networkFirst"):
        assert marker in src, f"sw.js 缺少 {marker}"
    # 前端注册 Service Worker 的入口仍在
    app_js = (SW_JS.parent / "app.js").read_text()
    assert 'navigator.serviceWorker.register("/sw.js")' in app_js


def test_sw_handles_push_and_notificationclick():
    src = SW_JS.read_text()
    assert 'self.addEventListener("push"' in src
    assert "showNotification" in src
    assert 'self.addEventListener("notificationclick"' in src
    assert "clients.openWindow" in src


STATIC = Path(__file__).parent.parent / "app" / "static"


def test_pwa_icons_have_light_and_dark_sets():
    """安装图标需同时提供亮/暗两套 PNG，并在 manifest / HTML / SW 里接上。"""
    for name in (
        "icon-mark.svg",
        "icon-mark-dark.svg",
        "icon-192.png",
        "icon-512.png",
        "icon-192-dark.png",
        "icon-512-dark.png",
    ):
        path = STATIC / name
        assert path.is_file() and path.stat().st_size > 0, f"缺少 PWA 图标 {name}"

    manifest = (STATIC / "manifest.webmanifest").read_text()
    assert '"/icon-192.png"' in manifest
    assert '"/icon-512.png"' in manifest
    assert "maskable" in manifest

    html = (STATIC / "index.html").read_text()
    assert 'href="/icon-192.png"' in html
    assert 'href="/icon-192-dark.png"' in html
    assert 'media="(prefers-color-scheme: dark)"' in html
    assert 'href="/splash-ios-dark.png"' in html

    sw = SW_JS.read_text()
    assert "/icon-192-dark.png" in sw
    assert "/icon-512-dark.png" in sw
