"""腾讯 ima 只读探针：解析官方 OpenAPI 响应，不负责发请求。"""
from __future__ import annotations

from collections import Counter
from typing import Any
from urllib.parse import urlparse


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def classify_item(item: dict[str, Any]) -> str:
    """区分文件夹与知识条目；条目再按 media_id 前缀或 media_type 细分。"""
    media_id = str(item.get("media_id") or "")
    if media_id.startswith("folder_"):
        return "folder"
    if not media_id and (
        item.get("folder_id") or "file_number" in item or "folder_number" in item
    ):
        return "folder"
    prefix, sep, _ = media_id.partition("_")
    if sep:
        return {
            "note": "note",
            "markdown": "markdown",
            "weburl": "web",
            "file": "file",
        }.get(prefix, prefix or "media")
    media_type = item.get("media_type")
    return {
        1: "pdf",
        2: "web",
        3: "word",
        4: "ppt",
        5: "excel",
        6: "wechat",
        7: "markdown",
        9: "image",
        11: "note",
        12: "session",
        13: "txt",
        14: "xmind",
        15: "audio",
        16: "video",
    }.get(media_type, "media")


def list_cursor(payload: dict[str, Any]) -> dict[str, Any]:
    """读取官方游标分页字段。"""
    return {
        "is_end": bool(payload.get("is_end")),
        "next_cursor": str(payload.get("next_cursor") or ""),
        "count": len(knowledge_items(payload)),
    }


def _normalize_base(item: dict[str, Any]) -> dict[str, Any]:
    """官方列表用 kb_id/kb_name，详情用 id/name，统一成 id/name。"""
    out = dict(item)
    out["id"] = str(out.get("id") or out.get("kb_id") or "")
    out["name"] = out.get("name") or out.get("kb_name")
    return out


def knowledge_bases(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """search_knowledge_base 的 info_list，或 get_knowledge_base 的 infos。"""
    raw = payload.get("info_list")
    if raw is None:
        raw = payload.get("infos")
    if isinstance(raw, dict):
        items = []
        for key, value in raw.items():
            item = dict(_as_dict(value))
            item.setdefault("kb_id", key)
            items.append(_normalize_base(item))
        return items
    return [_normalize_base(item) for item in _as_list(raw) if isinstance(item, dict)]


def addable_ids(payload: dict[str, Any]) -> set[str]:
    items = payload.get("addable_knowledge_base_list")
    ids: set[str] = set()
    for item in _as_list(items):
        if not isinstance(item, dict):
            continue
        kb_id = item.get("id") or item.get("kb_id")
        if kb_id:
            ids.add(str(kb_id))
    return ids


def knowledge_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """get_knowledge_list / search_knowledge 里的条目列表。"""
    for key in ("knowledge_list", "info_list"):
        items = payload.get(key)
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def inventory_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    kinds: Counter[str] = Counter()
    extra_keys: set[str] = set()
    for item in items:
        kinds[classify_item(item)] += 1
        extra_keys.update(item.keys())
    return {
        "item_count": len(items),
        "kinds": dict(kinds),
        "field_names": sorted(extra_keys),
        "has_time": bool(
            extra_keys & {"create_time", "update_time", "created_at", "updated_at"}
        ),
    }


def first_url(payload: dict[str, Any]) -> str:
    """从 get_media_info 一类响应里取出第一条 http(s) 链接，只用于看 host。"""
    stack: list[Any] = [payload]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
        elif isinstance(cur, str) and cur.startswith(("http://", "https://")):
            return cur
    return ""


def summarize_media(payload: dict[str, Any]) -> dict[str, Any]:
    url = first_url(payload)
    host = urlparse(url).netloc if url else ""
    return {
        "keys": sorted(payload.keys()),
        "has_url": bool(url),
        "host": host,
        "signed": bool(url) and ("sign=" in url or "q-sign" in url or "Expires=" in url),
    }


def public_numeric_id(payload: dict[str, Any]) -> str:
    """订阅库 openapi 列表的 current_path[0].folder_id，给网页阅读接口用。"""
    path = payload.get("current_path")
    if not isinstance(path, list) or not path:
        return ""
    first = path[0] if isinstance(path[0], dict) else {}
    return str(first.get("folder_id") or "")


# 可尝试抓取全文的媒体类型：纯文本/网页/公众号等；Office/PDF/音视频只返回文件链接，跳过
TEXT_LIKE_TYPES = {2, 6, 7, 11, 13, 14}


def item_time_ms(item: dict[str, Any]) -> int | None:
    """条目展示时间（毫秒），取 create_time，缺省回退 update_time。"""
    for key in ("create_time", "update_time", "last_modify_time", "last_open_time"):
        raw = item.get(key)
        if raw:
            try:
                return int(raw)
            except (TypeError, ValueError):
                continue
    return None


def item_text(item: dict[str, Any]) -> str:
    """无全文时的正文：优先 AI 摘要，否则引言/开头片段；都空则空串。"""
    abstract = str(item.get("abstract") or "").strip()
    if abstract:
        return abstract
    intro = str(item.get("introduction") or "").strip()
    if intro:
        return intro
    return ""


def item_cover(item: dict[str, Any]) -> str:
    covers = item.get("cover_urls")
    if isinstance(covers, list):
        for cover in covers:
            if isinstance(cover, str) and cover.startswith("http"):
                return cover
    return ""


def item_detail(item: dict[str, Any]) -> dict[str, Any]:
    """入库 detail：保留排障/排序用的轻量字段，不重复存正文。"""
    out: dict[str, Any] = {}
    for key in (
        "media_id",
        "media_type",
        "sub_media_type",
        "file_size",
        "md5_sum",
        "raw_file_url",
        "parsed_file_url",
        "access_status",
        "media_state",
        "summary_state",
        "parse_progress",
        "parent_folder_id",
        "create_time",
        "update_time",
        "last_modify_time",
    ):
        value = item.get(key)
        if value in (None, "", {}, []):
            continue
        out[key] = value
    return out


def media_info_target(payload: dict[str, Any]) -> tuple[str, dict[str, str]]:
    """从 get_media_info 响应里取可访问的原文链接与请求头。

    返回 (url, headers)；取不到原文链接返回 ("", {})。
    """
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    url_info = data.get("url_info") if isinstance(data, dict) else None
    if isinstance(url_info, dict):
        url = str(url_info.get("url") or "").strip()
        if url:
            headers = url_info.get("headers") if isinstance(url_info.get("headers"), dict) else {}
            return url, {str(k): str(v) for k, v in headers.items()}
    return "", {}


def summarize_public_item(item: dict[str, Any]) -> dict[str, Any]:
    """网页阅读接口条目：只报告字段是否可用，不带出正文。"""
    raw = str(item.get("raw_file_url") or "")
    source = str(item.get("source_path") or "")
    parsed = str(item.get("parsed_file_url") or item.get("file_url") or "")
    jump = str(item.get("jump_url") or "")
    content = item.get("content") or item.get("text") or ""
    return {
        "kind": classify_item(item),
        "keys": sorted(item.keys()),
        "title_len": len(str(item.get("title") or "")),
        "intro_len": len(str(item.get("introduction") or "")),
        "abstract_len": len(str(item.get("abstract") or "")),
        "content_len": len(str(content)),
        "has_time": any(
            item.get(key) for key in ("create_time", "update_time", "last_modify_time")
        ),
        "raw_host": urlparse(raw).netloc if raw.startswith("http") else ("relative" if raw else ""),
        "parsed_host": (
            urlparse(parsed).netloc if parsed.startswith("http") else ("relative" if parsed else "")
        ),
        "has_jump_url": bool(jump),
        "source_host": urlparse(source).netloc if source.startswith("http") else "",
        "file_size": item.get("file_size"),
    }
