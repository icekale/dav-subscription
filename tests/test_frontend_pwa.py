"""PWA Service Worker 静态回归测试：保护私有 RSS 不被缓存。

背景：/api/feed/{token}.xml 是私有 RSS 源，token 即凭证（无需登录）。
Service Worker 的 network-first 策略会把 GET 响应写入缓存；若把 /feed/ 也纳入，
等于把订阅内容连同 token 一起留在用户本机缓存里。本测试只做静态断言，
不跑浏览器，防止安全边界被后续改动无意移除。
"""
import re
from pathlib import Path

SW_JS = Path(__file__).parent.parent / "app" / "static" / "sw.js"


def test_fetch_handler_excludes_feed_route():
    """fetch handler 必须显式排除 /feed/（私有 RSS token 永不入缓存）。"""
    src = SW_JS.read_text()
    fetch_block = src[src.index('self.addEventListener("fetch"'):]
    assert re.search(r'pathname\.startsWith\("/feed/"\)', fetch_block), (
        "Service Worker fetch 逻辑缺少 /feed/ 排除，私有 RSS 可能被缓存"
    )
    # 已有的 /api/ 排除不能丢
    assert re.search(r'pathname\.startsWith\("/api/"\)', fetch_block)


def test_fetch_handler_still_guards_method_and_origin():
    """fetch 排除必须保留 method/origin 守卫，且排除逻辑是短路 return（不拦截才走缓存）。"""
    src = SW_JS.read_text()
    fetch_block = src[src.index('self.addEventListener("fetch"'):]
    assert re.search(r'request\.method !== "GET"', fetch_block)
    assert re.search(r'url\.origin !== self\.location\.origin', fetch_block)
    # 排除分支应直接 return，不调用 e.respondWith（否则仍可能被缓存策略兜住）
    feed_line = next(l for l in fetch_block.splitlines() if '"/feed/"' in l)
    assert "return" in feed_line


def test_shell_assets_and_registration_present():
    """离线外壳与注册入口仍存在，确认排除 /feed/ 没有破坏 PWA 本身。"""
    src = SW_JS.read_text()
    for marker in ("/manifest.webmanifest", 'caches.open(CACHE)', "networkFirst"):
        assert marker in src, f"sw.js 缺少 {marker}"
    # 前端注册 Service Worker 的入口仍在
    app_js = (SW_JS.parent / "app.js").read_text()
    assert 'navigator.serviceWorker.register("/sw.js")' in app_js
