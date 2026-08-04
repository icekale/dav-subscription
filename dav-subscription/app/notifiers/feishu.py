"""飞书群机器人 webhook 通知。"""
from __future__ import annotations

import json
import threading
import time

import httpx

from ..fetchers.base import Post
from .base import Notifier

PLATFORM_LABELS = {"xueqiu": "雪球", "weibo": "微博", "twitter": "X/Twitter"}
DIGEST_MAX_ITEMS = 5

_token_cache: dict[tuple[str, str], tuple[str, float]] = {}
_token_lock = threading.Lock()


def _tenant_access_token(app_id: str, app_secret: str, client: httpx.Client) -> str:
    """获取并缓存 tenant_access_token（2 小时有效，提前 60 秒过期）。"""
    key = (app_id, app_secret)
    with _token_lock:
        cached = _token_cache.get(key)
        if cached and cached[1] > time.time() + 60:
            return cached[0]
    if not app_id or not app_secret:
        raise RuntimeError("未配置飞书应用凭据（feishu.app_id / app_secret）")
    resp = client.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"飞书获取 token 失败: {data.get('msg', data)}")
    token = data["tenant_access_token"]
    expire_in = int(data.get("expire", 7200))
    with _token_lock:
        _token_cache[key] = (token, time.time() + expire_in)
    return token


def build_feishu_card(post: Post) -> dict:
    platform = PLATFORM_LABELS.get(post.platform, post.platform)
    content = post.content[:200] or post.title or "（无正文）"
    category = post.category or ""
    note_elements = [{"tag": "plain_text", "content": f"发布时间：{post.published_at}"}]
    if category:
        note_elements.append({"tag": "plain_text", "content": f"🗂 {category}"})
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"📌 {post.kol_name} · {platform}"},
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": content},
                },
                {"tag": "note", "elements": note_elements},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "查看原文"},
                            "type": "primary",
                            "url": post.url,
                        }
                    ],
                },
            ],
        },
    }


def build_feishu_digest_card(posts: list[Post], kol_name: str, platform: str) -> dict:
    platform_label = PLATFORM_LABELS.get(platform, platform)
    elements = []
    for i, post in enumerate(posts[:DIGEST_MAX_ITEMS], 1):
        body = (post.content[:120] or post.title or "（无正文）").replace("\n", " ")
        time_line = f"🕐 {post.published_at}" if post.published_at else ""
        text = f"{i}. {body}"
        if time_line:
            text += f"\n{time_line}"
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": text}})
        if post.url:
            elements.append(
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": f"查看原文 {i}"},
                            "type": "default",
                            "url": post.url,
                        }
                    ],
                }
            )
    if len(posts) > DIGEST_MAX_ITEMS:
        elements.append(
            {
                "tag": "note",
                "elements": [
                    {"tag": "plain_text", "content": f"… 还有 {len(posts) - DIGEST_MAX_ITEMS} 条未展示"}
                ],
            }
        )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"📌 {kol_name} · {platform_label}（{len(posts)} 条新动态）",
            },
            "template": "blue",
        },
        "elements": elements,
    }


class FeishuNotifier(Notifier):
    channel = "feishu"

    def __init__(
        self,
        config,
        client: httpx.Client | None = None,
        open_id: str | None = None,
        chat_id: str | None = None,
        unsub_kol_id: int | None = None,
    ):
        self.webhook_url = config.webhook_url
        self.app_id = config.app_id
        self.app_secret = config.app_secret
        self.open_id = open_id
        self.chat_id = chat_id
        self.unsub_kol_id = unsub_kol_id
        self.client = client or httpx.Client(timeout=15)

    def _tenant_access_token(self) -> str:
        return _tenant_access_token(self.app_id, self.app_secret, self.client)

    def _post(self, payload: dict) -> None:
        resp = self.client.post(self.webhook_url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") not in (None, 0):
            raise RuntimeError(f"飞书返回错误: {data.get('msg', data)}")

    def _send_card(self, card: dict) -> None:
        if self.open_id or self.chat_id:
            token = self._tenant_access_token()
            receive_id_type = "open_id" if self.open_id else "chat_id"
            receive_id = self.open_id or self.chat_id
            # 应用消息 API 的 content 只需要 card 本体（不含 msg_type/card 外层）
            resp = self.client.post(
                f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "receive_id": receive_id,
                    "msg_type": "interactive",
                    "content": json.dumps(card, ensure_ascii=False),
                },
            )
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"飞书发送失败: {data.get('msg', data)}")
            return
        if not self.webhook_url:
            raise RuntimeError("未配置飞书 webhook_url 或应用凭据")
        self._post({"msg_type": "interactive", "card": card})

    def notify(self, post: Post) -> None:
        card = build_feishu_card(post)["card"]
        if self.unsub_kol_id is not None:
            card["elements"].append(
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "退订"},
                            "type": "default",
                            "value": {"action": "unsub", "kol_id": self.unsub_kol_id},
                        }
                    ],
                }
            )
        self._send_card(card)

    def send_digest(self, posts: list[Post], kol_name: str, platform: str) -> None:
        self._send_card(build_feishu_digest_card(posts, kol_name, platform))

    def send_text(self, text: str) -> None:
        if self.open_id or self.chat_id:
            token = self._tenant_access_token()
            receive_id_type = "open_id" if self.open_id else "chat_id"
            receive_id = self.open_id or self.chat_id
            resp = self.client.post(
                f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "receive_id": receive_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": text}, ensure_ascii=False),
                },
            )
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"飞书发送失败: {data.get('msg', data)}")
            return
        if not self.webhook_url:
            raise RuntimeError("未配置飞书 webhook_url")
        payload = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": text}}],
            },
        }
        self._post(payload)
