"""知识星球只读探针：验证网页版 API 能否覆盖 vpush 需要的字段。

不入库、不批量下载附件。需要本机已登录网页版的 zsxq_access_token。

用法：
  ZSXQ_ACCESS_TOKEN='...' .venv/bin/python scripts/zsxq_probe.py
  ZSXQ_COOKIE='zsxq_access_token=...' .venv/bin/python scripts/zsxq_probe.py
  ZSXQ_GROUP_ID=123 .venv/bin/python scripts/zsxq_probe.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

ROOT = Path(__file__).resolve().parents[1]


def _load_inspect():
    path = ROOT / "app" / "fetchers" / "zsxq_inspect.py"
    spec = importlib.util.spec_from_file_location("zsxq_inspect", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_inspect = _load_inspect()
access_token_from_cookie = _inspect.access_token_from_cookie
classify_topic = _inspect.classify_topic
collect_files = _inspect.collect_files
collect_images = _inspect.collect_images
comment_coverage = _inspect.comment_coverage
inventory_topics = _inspect.inventory_topics
topics_cursor = _inspect.topics_cursor

API_BASE = "https://api.zsxq.com/v2"
DEFAULT_DELAY = 3.0


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _token() -> str:
    raw = _env("ZSXQ_ACCESS_TOKEN") or _env("ZSXQ_COOKIE")
    return access_token_from_cookie(raw)


def _cookie_header() -> str:
    raw = _env("ZSXQ_COOKIE")
    if "zsxq_access_token=" in raw:
        return raw
    return f"zsxq_access_token={_token()}"


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Origin": "https://wx.zsxq.com",
        "Referer": "https://wx.zsxq.com/",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
        "Cookie": _cookie_header(),
    }


def _get(client: httpx.Client, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    time.sleep(float(_env("ZSXQ_PROBE_DELAY") or DEFAULT_DELAY))
    url = f"{API_BASE}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    resp = client.get(url)
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"非 JSON HTTP {resp.status_code} path={path}") from None
    return {
        "path": path,
        "http_status": resp.status_code,
        "succeeded": bool(data.get("succeeded")),
        "code": data.get("code"),
        "info": data.get("info") or data.get("error"),
        "keys": sorted(data.keys()),
        "resp_keys": sorted((data.get("resp_data") or {}).keys())
        if isinstance(data.get("resp_data"), dict)
        else [],
        "data": data,
    }


def _unwrap(result: dict[str, Any]) -> dict[str, Any]:
    data = result["data"]
    if not data.get("succeeded"):
        raise RuntimeError(
            f"API 失败 path={result.get('path')} HTTP {result['http_status']} "
            f"code={data.get('code')} info={data.get('info') or data.get('error') or data}"
        )
    payload = data.get("resp_data") or {}
    if not isinstance(payload, dict):
        raise RuntimeError(f"resp_data 不是对象: {type(payload)}")
    return payload


def _pick_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    wanted = _env("ZSXQ_GROUP_ID")
    if wanted:
        matched = [g for g in groups if str(g.get("group_id")) == wanted]
        if not matched:
            raise RuntimeError(f"星球列表里没有 group_id={wanted}")
        return matched
    return groups[:3]


def _probe_comments(client: httpx.Client, topic: dict[str, Any]) -> dict[str, Any]:
    topic_id = topic.get("topic_id")
    count = int(topic.get("comments_count") or 0)
    if not topic_id:
        return {"skipped": True}
    first = _get(client, f"/topics/{topic_id}/comments", {"sort": "asc", "count": 30})
    payload = _unwrap(first)
    coverage = comment_coverage(count, payload)
    extra: dict[str, Any] = {}
    if coverage["incomplete"]:
        for label, params in (
            ("index", {"sort": "asc", "count": 30, "index": coverage["next_index"]}),
            (
                "end_time",
                {
                    "sort": "asc",
                    "count": 30,
                    "end_time": (payload.get("comments") or [{}])[-1].get("create_time"),
                },
            ),
        ):
            if not params.get("end_time") and label == "end_time":
                continue
            try:
                page = _unwrap(_get(client, f"/topics/{topic_id}/comments", params))
                extra[label] = {
                    "returned": len(page.get("comments") or []),
                    "resp_keys": sorted(page.keys()),
                    "first_id": str((page.get("comments") or [{}])[0].get("comment_id") or ""),
                }
            except RuntimeError as exc:
                extra[label] = {"error": str(exc)[:200]}
    return {
        "topic_id": str(topic_id),
        "comments_count": count,
        "resp_keys": sorted(payload.keys()),
        "coverage": coverage,
        "page2": extra,
    }


def _probe_file(client: httpx.Client, file_id: str) -> dict[str, Any]:
    try:
        payload = _unwrap(_get(client, f"/files/{file_id}/download_url"))
    except RuntimeError as exc:
        return {"file_id": file_id, "error": str(exc)[:200]}
    url = str(payload.get("download_url") or "")
    return {
        "file_id": file_id,
        "has_url": bool(url),
        "host": httpx.URL(url).host if url else "",
        "resp_keys": sorted(payload.keys()),
    }


def main() -> int:
    _token()
    delay = float(_env("ZSXQ_PROBE_DELAY") or DEFAULT_DELAY)
    max_pages = int(_env("ZSXQ_PROBE_MAX_PAGES") or 2)
    report: dict[str, Any] = {
        "auth": "cookie-only",
        "cookie_mode": "full-header" if "zsxq_access_token=" in _env("ZSXQ_COOKIE") else "token",
        "delay_seconds": delay,
        "groups": [],
    }
    with httpx.Client(timeout=20, headers=_headers(), follow_redirects=True) as client:
        groups_payload = _unwrap(_get(client, "/groups"))
        groups = groups_payload.get("groups") or []
        report["group_count"] = len(groups)
        report["group_resp_keys"] = sorted(groups_payload.keys())
        for group in _pick_groups(groups):
            group_id = str(group.get("group_id") or "")
            item: dict[str, Any] = {
                "group_id": group_id,
                "name": group.get("name"),
                "pages": [],
                "samples": [],
            }
            end_time = None
            seen: list[dict[str, Any]] = []
            for _ in range(max_pages):
                params = {"scope": "all", "count": 20}
                if end_time:
                    params["end_time"] = end_time
                page = _unwrap(_get(client, f"/groups/{group_id}/topics", params))
                cursor = topics_cursor(page)
                topics = page.get("topics") or []
                seen.extend(topics)
                item["pages"].append({"resp_keys": sorted(page.keys()), "cursor": cursor})
                if not cursor["has_more"] and not cursor["next_end_time"]:
                    break
                end_time = cursor["next_end_time"]
                if not end_time:
                    break
            item["inventory"] = inventory_topics(seen)
            interesting = []
            for topic in seen:
                kind = classify_topic(topic)
                if kind in {"article", "forward", "q&a"} or collect_files(topic):
                    interesting.append(topic)
            if not interesting and seen:
                interesting = seen[:1]
            for topic in interesting[:4]:
                detail = None
                try:
                    detail = _unwrap(_get(client, f"/topics/{topic.get('topic_id')}"))
                    raw = detail.get("topic") or detail
                except RuntimeError as exc:
                    raw = topic
                    detail = {"error": str(exc)[:200]}
                sample = {
                    "topic_id": str(topic.get("topic_id") or ""),
                    "kind": classify_topic(raw if isinstance(raw, dict) else topic),
                    "list_keys": sorted(topic.keys()),
                    "detail_keys": sorted(raw.keys()) if isinstance(raw, dict) else [],
                    "images": len(collect_images(raw if isinstance(raw, dict) else topic)),
                    "files": collect_files(raw if isinstance(raw, dict) else topic),
                    "has_article": bool(
                        (raw.get("talk") or {}).get("article")
                        if isinstance(raw, dict)
                        else False
                    ),
                    "has_referenced": bool(
                        raw.get("referenced_topic") if isinstance(raw, dict) else False
                    ),
                    "comments_count": int(
                        (raw.get("comments_count") if isinstance(raw, dict) else 0) or 0
                    ),
                }
                if sample["comments_count"]:
                    sample["comments"] = _probe_comments(
                        client, raw if isinstance(raw, dict) else topic
                    )
                if sample["files"]:
                    sample["download"] = _probe_file(client, sample["files"][0]["file_id"])
                item["samples"].append(sample)
            report["groups"].append(item)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"缺少登录态：{exc}", file=sys.stderr)
        print(
            "请先登录 https://wx.zsxq.com ，从任意 api.zsxq.com 请求复制 "
            "zsxq_access_token，然后执行：\n"
            "  ZSXQ_ACCESS_TOKEN='...' .venv/bin/python scripts/zsxq_probe.py",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    except RuntimeError as exc:
        print(f"探针失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
