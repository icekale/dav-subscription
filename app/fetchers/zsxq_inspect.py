"""知识星球只读探针：解析网页版 API 响应，不负责发请求。"""
from __future__ import annotations

from collections import Counter
from typing import Any


def access_token_from_cookie(raw: str) -> str:
    """接受裸 token 或完整 Cookie 头，只取出 zsxq_access_token。"""
    text = (raw or "").strip()
    if not text:
        raise ValueError("缺少知识星球登录态")
    if "=" not in text and ";" not in text:
        return text
    for part in text.split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name == "zsxq_access_token" and value:
            return value
    raise ValueError("Cookie 中没有 zsxq_access_token")


def _blocks(topic: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = []
    for key in ("talk", "question", "answer", "task", "solution"):
        block = topic.get(key)
        if isinstance(block, dict):
            blocks.append(block)
    return blocks


def classify_topic(topic: dict[str, Any]) -> str:
    """把主题分成 talk / article / forward / q&a / task / solution。"""
    if topic.get("referenced_topic"):
        return "forward"
    talk = topic.get("talk") if isinstance(topic.get("talk"), dict) else {}
    if talk.get("article"):
        return "article"
    kind = str(topic.get("type") or "talk")
    return kind


def group_profile(group: dict[str, Any] | None) -> dict[str, str]:
    """从 /groups/{id} 或 topic.group 取出星球名和主理人头像。"""
    if not isinstance(group, dict):
        return {}
    owner = group.get("owner") if isinstance(group.get("owner"), dict) else {}
    name = str(group.get("name") or "").strip()
    avatar = str(owner.get("avatar_url") or group.get("background_url") or "").strip()
    owner_name = str(owner.get("name") or "").strip()
    if not name and not avatar:
        return {}
    return {"name": name, "avatar_url": avatar, "owner_name": owner_name}


def collect_images(topic: dict[str, Any]) -> list[dict[str, Any]]:
    """收集主题各区块图片，优先 original。"""
    images: list[dict[str, Any]] = []
    for block in _blocks(topic):
        for image in block.get("images") or []:
            if not isinstance(image, dict):
                continue
            chosen = image.get("original") or image.get("large") or image.get("thumbnail") or {}
            url = chosen.get("url") if isinstance(chosen, dict) else ""
            if not url:
                continue
            images.append(
                {
                    "image_id": str(image.get("image_id") or ""),
                    "url": url,
                    "size": int(chosen.get("size") or 0) if isinstance(chosen, dict) else 0,
                }
            )
    return images


def collect_files(topic: dict[str, Any]) -> list[dict[str, Any]]:
    """收集主题各区块附件，包含问答回答里的文件。"""
    files: list[dict[str, Any]] = []
    for block in _blocks(topic):
        for item in block.get("files") or []:
            if not isinstance(item, dict):
                continue
            file_id = item.get("file_id")
            if file_id is None:
                continue
            files.append(
                {
                    "file_id": str(file_id),
                    "name": str(item.get("name") or "unknown"),
                    "size": int(item.get("size") or 0),
                }
            )
    return files


def comment_coverage(comments_count: int, payload: dict[str, Any]) -> dict[str, Any]:
    """对照 comments_count 与本页返回数，判断是否还要翻页。"""
    comments = payload.get("comments") if isinstance(payload, dict) else None
    returned = len(comments) if isinstance(comments, list) else 0
    return {
        "returned": returned,
        "incomplete": returned < max(int(comments_count or 0), 0),
        "next_index": returned,
        "has_more": bool(payload.get("has_more")) if isinstance(payload, dict) else False,
        "next_end_time": (payload.get("next_end_time") if isinstance(payload, dict) else None),
    }


def collect_comments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """归一化主题评论列表为紧凑 dict（comment_id/时间/作者/正文/点赞）。"""
    comments = payload.get("comments") if isinstance(payload, dict) else None
    out: list[dict[str, Any]] = []
    for c in comments or []:
        if not isinstance(c, dict):
            continue
        owner = c.get("owner") if isinstance(c.get("owner"), dict) else {}
        out.append(
            {
                "comment_id": str(c.get("comment_id") or ""),
                "create_time": str(c.get("create_time") or ""),
                "owner": str(owner.get("name") or ""),
                "text": str(c.get("text") or ""),
                "likes_count": int(c.get("likes_count") or 0),
            }
        )
    return out


def topics_cursor(payload: dict[str, Any]) -> dict[str, Any]:
    """读取主题列表分页字段。"""
    topics = payload.get("topics") if isinstance(payload, dict) else None
    count = len(topics) if isinstance(topics, list) else 0
    return {
        "count": count,
        "has_more": bool(payload.get("has_more")) if isinstance(payload, dict) else False,
        "next_end_time": payload.get("next_end_time") if isinstance(payload, dict) else None,
    }


def inventory_topics(topics: list[dict[str, Any]]) -> dict[str, Any]:
    """汇总一页主题的类型、附件体积和需要翻评论的帖数。"""
    kinds: Counter[str] = Counter()
    file_bytes = 0
    need_comment_pages = 0
    for topic in topics:
        kinds[classify_topic(topic)] += 1
        file_bytes += sum(item["size"] for item in collect_files(topic))
        if int(topic.get("comments_count") or 0) > 30:
            need_comment_pages += 1
    return {
        "topic_count": len(topics),
        "kinds": dict(kinds),
        "file_bytes": file_bytes,
        "need_comment_pages": need_comment_pages,
    }
