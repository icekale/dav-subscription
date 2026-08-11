"""URL 下载安全校验：防止服务端抓取/下载时被引导访问内网地址（SSRF）。

头像缓存与飞书图片上传会下载抓取内容里携带的 URL（帖子图片、头像来自
第三方平台/RSSHub），这些地址不可信。统一经 is_safe_http_url / safe_get
校验：仅允许 http/https、拒绝环回/私网/链路本地/云元数据等保留网段，
跟随重定向时逐跳重新校验。
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

ALLOWED_SCHEMES = ("http", "https")
MAX_REDIRECTS = 3
USER_LLM_HOSTS = frozenset({
    "api.openai.com",
    "api.deepseek.com",
    "api.x.ai",
    "generativelanguage.googleapis.com",
})

# 直接拒绝的目标网段：环回/私网/链路本地/运营商级 NAT/云元数据/多播/保留段
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
]


def _blocked_ip(ip: str) -> bool:
    """单个 IP（含 IPv6 作用域后缀）是否命中拒绝网段；非法 IP 一律拒绝。"""
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return True
    return any(addr in net for net in _BLOCKED_NETWORKS)


def _resolve_host_ips(host: str) -> list[str]:
    """解析主机名到 IP（IPv4/IPv6 去重）；解析失败返回空列表。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return []
    return list({info[4][0] for info in infos})


def is_safe_http_url(url: str) -> bool:
    """判断 URL 是否允许服务端下载：http/https 且不指向内网/保留地址。

    裸 IP 直接判定；域名解析后任一地址命中内网即拒绝（覆盖多 IP / IPv6）。
    解析失败视为不安全（宁可不下，避免 DNS 重绑定类绕过）。
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.hostname:
        return False
    host = parsed.hostname
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return not _blocked_ip(host)
    ips = _resolve_host_ips(host)
    if not ips:
        return False
    return not any(_blocked_ip(ip) for ip in ips)


def is_allowed_user_llm_base(url: str) -> bool:
    """用户级 LLM 只允许明确的官方公网 HTTPS 端点。"""
    try:
        parsed = urlparse((url or "").strip())
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname in USER_LLM_HOSTS
        and port in (None, 443)
        and not parsed.username
        and not parsed.password
    )


def _pinned_request(url: str) -> tuple[str, str]:
    """返回连接到已验证 IP 的 URL 与原始 Host，消除校验后再次 DNS 解析窗口。"""
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        raise ValueError(f"不安全的下载地址: {url[:80]}") from None
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.hostname:
        raise ValueError(f"不安全的下载地址: {url[:80]}")
    host = parsed.hostname
    try:
        ipaddress.ip_address(host)
        ips = [host]
    except ValueError:
        ips = sorted(_resolve_host_ips(host))
    if not ips or any(_blocked_ip(ip) for ip in ips):
        raise ValueError(f"不安全的下载地址: {url[:80]}")
    ip = ips[0]
    ip_host = f"[{ip}]" if ":" in ip else ip
    netloc = f"{ip_host}:{port}" if port else ip_host
    host_header = parsed.netloc.rsplit("@", 1)[-1]
    pinned = urlunparse(parsed._replace(netloc=netloc))
    return pinned, host_header


def safe_get(client: httpx.Client, url: str, timeout: float = 15) -> httpx.Response:
    """逐跳校验并连接到已验证 IP，保留原 Host/SNI。"""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        pinned, host_header = _pinned_request(current)
        hostname = urlparse(current).hostname or ""
        resp = client.get(
            pinned,
            timeout=timeout,
            follow_redirects=False,
            headers={"Host": host_header},
            extensions={"sni_hostname": hostname},
        )
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location")
            if not location:
                return resp
            current = urljoin(current, location)
            continue
        return resp
    raise ValueError(f"重定向次数过多: {url[:80]}")
