"""抓取代理：行解析、提取启发式、客户端 URL、按平台选用。"""
from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlparse, urlunparse

import httpx

logger = logging.getLogger(__name__)

from .db import ALLOWED_PLATFORMS

IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


@dataclass(frozen=True)
class ParsedProxy:
    protocol: str
    host: str
    port: int
    username: str = ""
    password: str = ""


def _norm_protocol(value: str) -> str:
    p = (value or "http").strip().lower()
    if p in ("http", "https"):
        return "http"
    if p in ("socks5", "socks5h"):
        return "socks5"
    return ""


def _valid_port(value) -> int | None:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    if 1 <= port <= 65535:
        return port
    return None


def _is_host_port(text: str) -> bool:
    if ":" not in text:
        return False
    host, port = text.rsplit(":", 1)
    return bool(host) and _valid_port(port) is not None


def _split_userpass(text: str) -> tuple[str, str]:
    if ":" in text:
        user, password = text.split(":", 1)
        return user, password
    return text, ""


def _parse_url(line: str) -> ParsedProxy | None:
    parsed = urlparse(line)
    protocol = _norm_protocol(parsed.scheme)
    if not protocol or not parsed.hostname:
        return None
    port = parsed.port or (80 if protocol == "http" else 1080)
    if _valid_port(port) is None:
        return None
    return ParsedProxy(
        protocol,
        parsed.hostname,
        port,
        unquote(parsed.username or ""),
        unquote(parsed.password or ""),
    )


def _parse_one(line: str, default: str) -> ParsedProxy | None:
    if "://" in line:
        return _parse_url(line)
    if "@" in line:
        left, right = line.rsplit("@", 1)
        left_host = left.rsplit(":", 1)[0] if ":" in left else ""
        if _is_host_port(left) and (bool(IPV4_RE.match(left_host)) or not _is_host_port(right)):
            host, port_s = left.rsplit(":", 1)
            port = _valid_port(port_s)
            user, password = _split_userpass(right)
            if host and port:
                return ParsedProxy(default, host, port, user, password)
        if _is_host_port(right):
            host, port_s = right.rsplit(":", 1)
            port = _valid_port(port_s)
            user, password = _split_userpass(left)
            if host and port:
                return ParsedProxy(default, host, port, user, password)
        return None
    parts = line.split(":")
    if len(parts) >= 2:
        port = _valid_port(parts[1])
        host = parts[0]
        user = parts[2] if len(parts) >= 3 else ""
        password = ":".join(parts[3:]) if len(parts) >= 4 else ""
        if host and port:
            return ParsedProxy(default, host, port, user, password)
    return None


def parse_proxy_lines(text: str, default_protocol: str = "http") -> list[ParsedProxy]:
    default = _norm_protocol(default_protocol) or "http"
    out: list[ParsedProxy] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parsed = _parse_one(line, default)
        if parsed:
            out.append(parsed)
    return out


def _text_lines(text: str) -> list[str]:
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _obj_line(obj: dict) -> str:
    ip = obj.get("ip") or obj.get("host") or obj.get("addr")
    port = obj.get("port")
    if ip and port is not None and str(port) != "":
        return f"{ip}:{port}"
    return ""


def _from_list(items: list) -> list[str]:
    out: list[str] = []
    for item in items:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict):
            line = _obj_line(item)
            if line:
                out.append(line)
    return out


def parse_extract_payload(text: str) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return _text_lines(text)
    if isinstance(data, list):
        return _from_list(data)
    if isinstance(data, dict):
        for key in ("data", "list", "proxies"):
            if isinstance(data.get(key), list):
                return _from_list(data[key])
        line = _obj_line(data)
        return [line] if line else []
    if isinstance(data, str):
        return _text_lines(data)
    return []


def _row_get(row, key: str, default=""):
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def proxy_url(row) -> str:
    protocol = _row_get(row, "protocol")
    host = _row_get(row, "host")
    port = int(_row_get(row, "port") or 0)
    username = _row_get(row, "username") or ""
    password = _row_get(row, "password") or ""
    scheme = "socks5h" if protocol == "socks5" else "http"
    if username or password:
        auth = f"{quote(str(username), safe='')}:{quote(str(password), safe='')}@"
    else:
        auth = ""
    return f"{scheme}://{auth}{host}:{port}"


def public_proxy(row: dict) -> dict:
    out = dict(row)
    out["has_password"] = bool(out.get("password"))
    out["password"] = "***" if out.get("password") else ""
    return out


def public_pool(row: dict, hide_extract_query: bool = True) -> dict:
    out = dict(row)
    url = out.get("extract_url") or ""
    out["extract_url_set"] = bool(url)
    if hide_extract_query:
        out["extract_url"] = mask_extract_url(url)
    return out


def import_proxies(db, pool_id: int, text: str, protocol: str | None = None) -> dict:
    pool = db.get_proxy_pool(pool_id)
    if pool is None:
        raise ValueError("代理池不存在")
    default = protocol or pool["protocol"] or "http"
    if not _norm_protocol(default):
        raise ValueError("协议须为 http 或 socks5")
    rows = parse_proxy_lines(text, default_protocol=default)
    ids: set[int] = set()
    for row in rows:
        ids.add(
            db.upsert_proxy(
                pool_id,
                row.protocol,
                row.host,
                row.port,
                row.username,
                row.password,
                source="manual",
            )
        )
    return {"imported": len(ids)}


def mask_extract_url(url: str) -> str:
    """列表展示用：去掉查询串，避免把提取密钥打到页面。"""
    if not url:
        return ""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


PROXY_ROUTES_KEY = "proxy_routes"
DEFAULT_ROUTE = {"mode": "direct"}


class ProxyUnavailable(Exception):
    """需要代理但池空、指定节点不可用或已过期。调用方不得回退直连。"""


def default_routes() -> dict:
    return {platform: dict(DEFAULT_ROUTE) for platform in sorted(ALLOWED_PLATFORMS)}


def _expired(row: dict, now: int | None) -> bool:
    exp = row.get("expires_at")
    if exp in (None, "", 0):
        return False
    ts = int(now if now is not None else time.time())
    return int(exp) <= ts


def _normalize_routes(raw) -> dict:
    out = default_routes()
    if not isinstance(raw, dict):
        return out
    for platform, route in raw.items():
        if platform not in ALLOWED_PLATFORMS or not isinstance(route, dict):
            continue
        mode = route.get("mode") or "direct"
        if mode not in ("direct", "pool", "proxy"):
            mode = "direct"
        item = {"mode": mode}
        if mode == "pool" and route.get("pool_id") is not None:
            try:
                item["pool_id"] = int(route["pool_id"])
            except (TypeError, ValueError):
                item = dict(DEFAULT_ROUTE)
        elif mode == "proxy" and route.get("proxy_id") is not None:
            try:
                item["proxy_id"] = int(route["proxy_id"])
            except (TypeError, ValueError):
                item = dict(DEFAULT_ROUTE)
        elif mode != "direct":
            item = dict(DEFAULT_ROUTE)
        out[platform] = item
    return out


class ProxyRouter:
    def __init__(self, db):
        self.db = db

    def routes(self) -> dict:
        raw = self.db.get_setting(PROXY_ROUTES_KEY)
        if not raw:
            return default_routes()
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return default_routes()
        return _normalize_routes(data)

    def set_routes(self, routes: dict) -> dict:
        normalized = _normalize_routes(routes)
        self.db.set_setting(PROXY_ROUTES_KEY, json.dumps(normalized, ensure_ascii=False))
        return normalized

    def acquire(self, platform: str, now: int | None = None) -> dict | None:
        route = self.routes().get(platform) or dict(DEFAULT_ROUTE)
        mode = route.get("mode") or "direct"
        if mode == "direct":
            return None
        if mode == "proxy":
            pid = route.get("proxy_id")
            row = self.db.get_proxy(int(pid)) if pid is not None else None
            if row is None:
                raise ProxyUnavailable("指定代理不存在")
            if _expired(row, now):
                raise ProxyUnavailable("指定代理已过期")
            return row
        pool_id = route.get("pool_id")
        if pool_id is None:
            raise ProxyUnavailable("代理池为空")
        usable = self.db.list_usable_proxies(int(pool_id), now=now)
        if not usable:
            raise ProxyUnavailable("代理池为空")
        return random.choice(usable)

    def report_ok(self, proxy_id: int) -> None:
        self.db.mark_proxy_ok(proxy_id)

    def report_fail(self, proxy_id: int, error: str = "") -> None:
        self.db.mark_proxy_fail(proxy_id, error=error)


def acquire_client_proxy(db, platform: str) -> tuple[str | None, int | None]:
    """给 HTTP 客户端选出口。(None, None) 表示直连；需要代理但不可用则抛 ProxyUnavailable。"""
    if db is None:
        return None, None
    row = ProxyRouter(db).acquire(platform)
    if row is None:
        return None, None
    return proxy_url(row), int(row["id"])


def attach_proxy(client, proxy_id: int | None) -> None:
    if client is not None:
        client._vpush_proxy_id = proxy_id


def current_fetcher_client(fetcher):
    http = getattr(fetcher, "_http", None)
    if http is not None:
        if http._injected is not None:
            return http._injected
        return getattr(http._local, "client", None)
    if getattr(fetcher, "_client", None) is not None:
        return fetcher._client
    local = getattr(fetcher, "_thread_local", None)
    if local is not None:
        return getattr(local, "session", None)
    return None


def reset_fetcher_proxy(fetcher) -> None:
    http = getattr(fetcher, "_http", None)
    if http is not None:
        http.reset()
        return
    if getattr(fetcher, "_client", None) is not None:
        return
    local = getattr(fetcher, "_thread_local", None)
    if local is not None:
        local.session = None


def note_fetch_proxy(fetcher, ok: bool, error: str = "") -> None:
    db = getattr(fetcher, "db", None)
    client = current_fetcher_client(fetcher)
    pid = getattr(client, "_vpush_proxy_id", None) if client is not None else None
    if pid and db is not None:
        router = ProxyRouter(db)
        if ok:
            router.report_ok(pid)
        else:
            router.report_fail(pid, error)
    if not ok:
        reset_fetcher_proxy(fetcher)


PROBE_URL = "https://www.gstatic.com/generate_204"


def extract_pool(db, pool_id: int, client=None, now: int | None = None) -> dict:
    pool = db.get_proxy_pool(pool_id)
    if pool is None:
        raise ValueError("代理池不存在")
    if pool["kind"] != "extract":
        raise ValueError("不是提取池")
    url = (pool.get("extract_url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("提取 URL 仅支持 http/https")
    ts = int(now if now is not None else time.time())
    owns = client is None
    client = client or httpx.Client(timeout=20)
    try:
        resp = client.get(url)
        resp.raise_for_status()
        lines = parse_extract_payload(resp.text)
        parsed_rows = parse_proxy_lines("\n".join(lines), default_protocol=pool["protocol"])
        expire = int(pool.get("expire_seconds") or 0)
        expires_at = (ts + expire) if expire > 0 else None
        imported = 0
        for row in parsed_rows:
            db.upsert_proxy(
                pool_id,
                row.protocol,
                row.host,
                row.port,
                row.username,
                row.password,
                source="extract",
                expires_at=expires_at,
            )
            imported += 1
        db.update_proxy_pool(pool_id, last_extract_at=ts, last_error="")
        return {"imported": imported, "parsed": len(lines)}
    except Exception as exc:
        db.update_proxy_pool(pool_id, last_error=str(exc)[:300])
        raise
    finally:
        if owns:
            client.close()


def probe_proxy(row, client=None, timeout: float = 8) -> dict:
    url = proxy_url(row)
    owns = client is None
    client = client or httpx.Client(timeout=timeout, proxy=url, follow_redirects=True)
    try:
        resp = client.get(PROBE_URL)
        ok = resp.status_code == 204 or 200 <= resp.status_code < 400
        return {"ok": ok, "status_code": resp.status_code}
    except Exception as exc:  # noqa: BLE001 - 探测失败只回报结果
        return {"ok": False, "error": str(exc)[:200]}
    finally:
        if owns:
            client.close()


def tick_proxy_pools(db, now: int | None = None) -> dict:
    """清过期 extract 节点；到期的提取池再拉一次。"""
    ts = int(now if now is not None else time.time())
    expired = db.delete_expired_extracted_proxies(now=ts)
    extracted = 0
    for pool in db.list_proxy_pools():
        if not pool.get("enabled") or pool.get("kind") != "extract":
            continue
        interval = int(pool.get("refresh_interval_seconds") or 0)
        if interval <= 0:
            continue
        last = pool.get("last_extract_at")
        if last not in (None, "", 0) and ts - int(last) < interval:
            continue
        try:
            extract_pool(db, pool["id"], now=ts)
            extracted += 1
        except Exception:
            logger.warning("代理池提取失败 pool_id=%s", pool["id"], exc_info=True)
    return {"expired": expired, "extracted": extracted}
