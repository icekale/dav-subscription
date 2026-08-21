"""腾讯 ima 只读探针：验证官方 OpenAPI 能否覆盖 vpush 需要的字段。

不入库、不写入知识库、不批量下载。需要本机已申请的 OpenAPI 凭证
（登录 https://ima.qq.com/agent-interface 生成 Client ID / API Key）。

用法：
  IMA_OPENAPI_CLIENTID='...' IMA_OPENAPI_APIKEY='...' \\
    .venv/bin/python scripts/ima_probe.py
  IMA_KB_ID='知识库ID' .venv/bin/python scripts/ima_probe.py
  IMA_KB_NAME='频道名关键字' .venv/bin/python scripts/ima_probe.py
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
addable_ids = _inspect.addable_ids
classify_item = _inspect.classify_item
inventory_items = _inspect.inventory_items
knowledge_bases = _inspect.knowledge_bases
knowledge_items = _inspect.knowledge_items
list_cursor = _inspect.list_cursor
summarize_media = _inspect.summarize_media

API_BASE = "https://ima.qq.com/openapi/wiki/v1"
DEFAULT_DELAY = 1.5


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _credentials() -> tuple[str, str]:
    client_id = _env("IMA_OPENAPI_CLIENTID") or _env("IMA_CLIENT_ID")
    api_key = _env("IMA_OPENAPI_APIKEY") or _env("IMA_API_KEY")
    if not client_id or not api_key:
        raise ValueError("缺少 ima OpenAPI 凭证")
    return client_id, api_key


def _headers(client_id: str, api_key: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "ima-openapi-clientid": client_id,
        "ima-openapi-apikey": api_key,
    }


def _post(client: httpx.Client, method: str, body: dict[str, Any]) -> dict[str, Any]:
    time.sleep(float(_env("IMA_PROBE_DELAY") or DEFAULT_DELAY))
    resp = client.post(f"{API_BASE}/{method}", json=body)
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"非 JSON HTTP {resp.status_code} method={method}") from None
    return {
        "method": method,
        "http_status": resp.status_code,
        "retcode": data.get("retcode", data.get("code")),
        "errmsg": data.get("errmsg") or data.get("msg"),
        "keys": sorted(data.keys()) if isinstance(data, dict) else [],
        "data": data,
    }


def _unwrap(result: dict[str, Any]) -> dict[str, Any]:
    data = result["data"]
    if not isinstance(data, dict):
        raise RuntimeError(f"响应不是对象 method={result.get('method')}")
    retcode = data.get("retcode", data.get("code"))
    errmsg = data.get("errmsg") or data.get("msg")
    if retcode not in (0, None):
        raise RuntimeError(
            f"API 失败 method={result.get('method')} HTTP {result['http_status']} "
            f"retcode={retcode} errmsg={errmsg}"
        )
    payload = data.get("data")
    if payload is None:
        payload = {k: v for k, v in data.items() if k not in {"retcode", "errmsg"}}
    if not isinstance(payload, dict):
        raise RuntimeError(f"data 不是对象: {type(payload)}")
    return payload


def _try_post(
    client: httpx.Client, method: str, body: dict[str, Any]
) -> dict[str, Any]:
    result = _post(client, method, body)
    try:
        return {"ok": True, "payload": _unwrap(result), "meta": result}
    except RuntimeError as exc:
        return {
            "ok": False,
            "error": str(exc)[:240],
            "retcode": result.get("retcode"),
            "errmsg": result.get("errmsg"),
        }


def _page_bases(client: httpx.Client) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    pages = []
    cursor = ""
    for _ in range(int(_env("IMA_PROBE_MAX_PAGES") or 2)):
        payload = _unwrap(
            _post(
                client,
                "search_knowledge_base",
                {"query": "", "cursor": cursor, "limit": 20},
            )
        )
        batch = knowledge_bases(payload)
        seen.extend(batch)
        cursor_info = list_cursor(payload)
        pages.append({"resp_keys": sorted(payload.keys()), "cursor": cursor_info})
        if cursor_info["is_end"] or not cursor_info["next_cursor"]:
            break
        cursor = cursor_info["next_cursor"]
    return seen, {"pages": pages, "count": len(seen)}


def _pick_bases(bases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    wanted_id = _env("IMA_KB_ID")
    wanted_name = _env("IMA_KB_NAME")
    if wanted_id:
        matched = [b for b in bases if str(b.get("id")) == wanted_id]
        if not matched:
            raise RuntimeError(f"可见知识库里没有 id={wanted_id}")
        return matched
    if wanted_name:
        matched = [b for b in bases if wanted_name in str(b.get("name") or "")]
        if not matched:
            raise RuntimeError(f"可见知识库里没有名称包含 {wanted_name!r}")
        return matched
    return bases[:3]


def _list_pages(
    client: httpx.Client, kb_id: str, folder_id: str | None = None
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    pages = []
    cursor = ""
    max_pages = int(_env("IMA_PROBE_MAX_PAGES") or 2)
    for _ in range(max_pages):
        body: dict[str, Any] = {
            "cursor": cursor,
            "limit": 20,
            "knowledge_base_id": kb_id,
        }
        if folder_id:
            body["folder_id"] = folder_id
        payload = _unwrap(_post(client, "get_knowledge_list", body))
        batch = knowledge_items(payload)
        items.extend(batch)
        cursor_info = list_cursor(payload)
        pages.append(
            {
                "resp_keys": sorted(payload.keys()),
                "cursor": cursor_info,
                "path_len": len(payload.get("current_path") or [])
                if isinstance(payload.get("current_path"), list)
                else 0,
            }
        )
        if cursor_info["is_end"] or not cursor_info["next_cursor"]:
            break
        cursor = cursor_info["next_cursor"]
    return {"pages": pages, "items": items, "inventory": inventory_items(items)}


def main() -> int:
    client_id, api_key = _credentials()
    delay = float(_env("IMA_PROBE_DELAY") or DEFAULT_DELAY)
    report: dict[str, Any] = {
        "auth": "openapi",
        "delay_seconds": delay,
        "knowledge_bases": [],
    }
    with httpx.Client(timeout=20, headers=_headers(client_id, api_key)) as client:
        bases, base_meta = _page_bases(client)
        addable = _try_post(
            client, "get_addable_knowledge_base_list", {"cursor": "", "limit": 20}
        )
        writable = addable_ids(addable["payload"]) if addable["ok"] else set()
        report["visible_count"] = base_meta["count"]
        report["list_meta"] = base_meta
        report["addable"] = {
            "ok": addable["ok"],
            "count": len(writable),
            "error": addable.get("error"),
        }
        for base in _pick_bases(bases):
            kb_id = str(base.get("id") or "")
            item: dict[str, Any] = {
                "id": kb_id,
                "name": base.get("name"),
                "cover": bool(base.get("cover_url")),
                "list_keys": sorted(base.keys()),
                "writable": kb_id in writable,
            }
            detail = _try_post(client, "get_knowledge_base", {"ids": [kb_id]})
            if detail["ok"]:
                infos = knowledge_bases(detail["payload"])
                item["detail_keys"] = sorted(infos[0].keys()) if infos else []
                item["description"] = bool((infos[0] if infos else {}).get("description"))
            else:
                item["detail_error"] = detail.get("error")
            listing = _list_pages(client, kb_id)
            item["root"] = {
                "pages": listing["pages"],
                "inventory": listing["inventory"],
            }
            folders = [
                entry
                for entry in listing["items"]
                if classify_item(entry) == "folder" and entry.get("folder_id")
            ]
            if folders:
                child = _list_pages(client, kb_id, str(folders[0]["folder_id"]))
                item["subfolder"] = {
                    "folder_id": folders[0].get("folder_id"),
                    "name": folders[0].get("name"),
                    "inventory": child["inventory"],
                    "pages": child["pages"],
                }
            media = next(
                (
                    entry
                    for entry in listing["items"]
                    if entry.get("media_id") and classify_item(entry) != "folder"
                ),
                None,
            )
            if media:
                media_id = str(media["media_id"])
                sample = {
                    "media_id_prefix": media_id.split("_", 1)[0],
                    "kind": classify_item(media),
                    "item_keys": sorted(media.keys()),
                    "title_len": len(str(media.get("title") or "")),
                }
                raw = _try_post(client, "get_media_info", {"media_id": media_id})
                if raw["ok"]:
                    sample["media_info"] = summarize_media(raw["payload"])
                else:
                    sample["media_info"] = {
                        "ok": False,
                        "retcode": raw.get("retcode"),
                        "errmsg": raw.get("errmsg"),
                    }
                item["sample"] = sample
            report["knowledge_bases"].append(item)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"缺少凭证：{exc}", file=sys.stderr)
        print(
            "请打开 https://ima.qq.com/agent-interface 登录后生成 API Key，然后执行：\n"
            "  IMA_OPENAPI_CLIENTID='...' IMA_OPENAPI_APIKEY='...' \\\n"
            "    .venv/bin/python scripts/ima_probe.py",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    except RuntimeError as exc:
        print(f"探针失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
