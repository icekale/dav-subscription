"""腾讯 ima 网页阅读接口只读探针。

订阅知识库的官方 OpenAPI 不能取原文（220030）。本脚本只测网页端
`/cgi-bin/knowledge_tab_reader_nl/get_knowledge_list`：列目录、看字段，
不下载文件、不打印正文。

可选 IMA_COOKIE / IMA_X_IMA_COOKIE：带上浏览器的 x-ima-cookie，对比是否
比无 Cookie 多权限。不要把 Cookie 贴进聊天。

用法：
  IMA_OPENAPI_CLIENTID='...' IMA_OPENAPI_APIKEY='...' \\
    IMA_KB_NAME='Z哥策略' .venv/bin/python scripts/ima_web_probe.py
  IMA_COOKIE='...' IMA_KB_ID='数字或加密ID' \\
    .venv/bin/python scripts/ima_web_probe.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]


def _load_inspect():
    path = ROOT / "app" / "fetchers" / "ima_inspect.py"
    spec = importlib.util.spec_from_file_location("ima_inspect", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_inspect = _load_inspect()
classify_item = _inspect.classify_item
knowledge_bases = _inspect.knowledge_bases
public_numeric_id = _inspect.public_numeric_id
summarize_public_item = _inspect.summarize_public_item

OPENAPI_BASE = "https://ima.qq.com/openapi/wiki/v1"
CGI_LIST = "https://ima.qq.com/cgi-bin/knowledge_tab_reader_nl/get_knowledge_list"
CGI_BASES = "https://ima.qq.com/cgi-bin/knowledge_tab_reader/list_knowledge_bases"
DEFAULT_DELAY = 1.5


def _load_local_env() -> None:
    path = ROOT / "data" / "ima_web.env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if value.startswith(("'", '"')) and value.endswith(value[0]) and len(value) >= 2:
            value = value[1:-1]
        os.environ[key] = value


_load_local_env()


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _cookie() -> str:
    return _env("IMA_COOKIE") or _env("IMA_X_IMA_COOKIE")


def _openapi_headers() -> dict[str, str] | None:
    client_id = _env("IMA_OPENAPI_CLIENTID") or _env("IMA_CLIENT_ID")
    api_key = _env("IMA_OPENAPI_APIKEY") or _env("IMA_API_KEY")
    if not client_id or not api_key:
        return None
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "ima-openapi-clientid": client_id,
        "ima-openapi-apikey": api_key,
    }


def _web_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://ima.qq.com",
        "Referer": "https://ima.qq.com/",
    }
    cookie = _cookie()
    if cookie:
        headers["x-ima-cookie"] = cookie
        if _env("IMA_X_IMA_BKN"):
            headers["x-ima-bkn"] = _env("IMA_X_IMA_BKN")
    return headers


def _sleep() -> None:
    time.sleep(float(_env("IMA_PROBE_DELAY") or DEFAULT_DELAY))


def _safe_json(resp: httpx.Response) -> dict[str, Any] | None:
    try:
        body = resp.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _list_payload(numeric_id: str, headers: dict[str, str], client: httpx.Client) -> dict[str, Any]:
    _sleep()
    web = client.post(
        CGI_LIST,
        headers=headers,
        json={
            "knowledge_base_id": numeric_id,
            "folder_id": "",
            "cursor": "",
            "limit": 5,
            "need_default_cover": True,
            "sort_type": 9,
        },
    )
    body = _safe_json(web)
    if body is None:
        return {
            "http_status": web.status_code,
            "http_envelope": {"code": None, "msg": "non-json", "top_keys": []},
            "item_count": 0,
            "sample": None,
        }
    return {"http_status": web.status_code, **_summarize_web_list(body)}


def _resolve_numeric_id(client: httpx.Client) -> tuple[str, dict[str, Any]]:
    wanted_id = _env("IMA_KB_ID") or _env("IMA_KB_NUMERIC_ID")
    wanted_name = _env("IMA_KB_NAME") or "Z哥策略"
    headers = _openapi_headers()
    if headers is None:
        if wanted_id and wanted_id.isdigit():
            return wanted_id, {"source": "IMA_KB_ID"}
        raise ValueError("需要 OpenAPI 凭证来把订阅库换成网页端数字 ID，或直接设 IMA_KB_ID")
    _sleep()
    listed_resp = client.post(
        f"{OPENAPI_BASE}/search_knowledge_base",
        headers=headers,
        json={"query": "", "cursor": "", "limit": 20},
    )
    try:
        listed = listed_resp.json()
    except ValueError as exc:
        raise RuntimeError(
            f"OpenAPI 列库非 JSON HTTP {listed_resp.status_code} body={listed_resp.text[:80]!r}"
        ) from exc
    if listed.get("retcode", listed.get("code")) not in (0, None):
        raise RuntimeError(f"列库失败 retcode={listed.get('retcode')} {listed.get('errmsg')}")
    bases = knowledge_bases(listed.get("data") or {})
    if wanted_id:
        match = next((b for b in bases if b.get("id") == wanted_id), None)
    else:
        match = next((b for b in bases if wanted_name in str(b.get("name") or "")), None)
    if not match:
        raise RuntimeError("OpenAPI 可见库里没有目标知识库")
    _sleep()
    page = client.post(
        f"{OPENAPI_BASE}/get_knowledge_list",
        headers=headers,
        json={"cursor": "", "limit": 1, "knowledge_base_id": match["id"]},
    ).json()
    payload = page.get("data") or {}
    numeric = public_numeric_id(payload)
    if not numeric:
        raise RuntimeError("openapi 响应没有 current_path[0].folder_id，无法转网页端 ID")
    return numeric, {
        "source": "openapi-current_path",
        "name": match.get("name"),
        "base_type": match.get("base_type"),
        "openapi_list_count": len(payload.get("knowledge_list") or []),
    }


def _summarize_web_list(body: dict[str, Any]) -> dict[str, Any]:
    data = body.get("data") if isinstance(body.get("data"), dict) else body
    items = data.get("knowledge_list") if isinstance(data, dict) else None
    items = items if isinstance(items, list) else []
    sample = next(
        (
            summarize_public_item(item)
            for item in items
            if isinstance(item, dict) and classify_item(item) != "folder"
        ),
        None,
    )
    info = (data.get("knowledge_base_info") or {}) if isinstance(data, dict) else {}
    basic = info.get("basic_info") if isinstance(info, dict) else {}
    return {
        "http_envelope": {
            "code": body.get("code", body.get("retcode")),
            "msg": body.get("msg") or body.get("errmsg"),
            "top_keys": sorted(body.keys()),
        },
        "kb_name": (basic or {}).get("name") if isinstance(basic, dict) else None,
        "has_update_ts": bool(isinstance(basic, dict) and basic.get("update_timestamp_sec")),
        "item_count": len(items),
        "is_end": bool(data.get("is_end")) if isinstance(data, dict) else None,
        "sample": sample,
    }


def main() -> int:
    report: dict[str, Any] = {
        "auth": "x-ima-cookie" if _cookie() else "cgi-bin-no-cookie",
        "cookie_present": bool(_cookie()),
    }
    with httpx.Client(timeout=20) as client:
        numeric_id, meta = _resolve_numeric_id(client)
        url_id = _env("IMA_KB_NUMERIC_ID")
        report["resolve"] = {
            **meta,
            "numeric_id_len": len(numeric_id),
            "matches_wiki_url_id": bool(url_id) and url_id == numeric_id,
        }
        no_cookie_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://ima.qq.com",
            "Referer": "https://ima.qq.com/",
        }
        report["web_list_no_cookie"] = _list_payload(numeric_id, no_cookie_headers, client)
        if _cookie():
            _sleep()
            bases_resp = client.post(CGI_BASES, headers=_web_headers(), json={})
            bases = _safe_json(bases_resp)
            report["cookie_list_bases"] = {
                "http_status": bases_resp.status_code,
                "code": None if bases is None else bases.get("code", bases.get("retcode")),
                "msg": None if bases is None else (bases.get("msg") or bases.get("errmsg")),
                "top_keys": [] if bases is None else sorted(bases.keys()),
            }
            report["web_list"] = _list_payload(numeric_id, _web_headers(), client)
        else:
            report["web_list"] = report["web_list_no_cookie"]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except json.JSONDecodeError as exc:
        print(f"探针失败：响应不是 JSON：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except ValueError as exc:
        print(f"缺少凭证：{exc}", file=sys.stderr)
        print(
            "本机导出 x-ima-cookie 后执行（不要把 Cookie 发到聊天）：\n"
            "  IMA_COOKIE='...' IMA_KB_NAME='Z哥策略' \\\n"
            "    .venv/bin/python scripts/ima_web_probe.py",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    except RuntimeError as exc:
        print(f"探针失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
