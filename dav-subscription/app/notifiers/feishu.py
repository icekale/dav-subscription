"""飞书群机器人 webhook 通知。"""
from __future__ import annotations

import json

import httpx

from ..fetchers.base import Post
from .base import Notifier

PLATFORM_LABELS = {"xueqiu": "雪球", "weibo": "微博", "twitter": "X/Twitter"}


def build_feishu_card(post: Post) -> dict:
    platform = PLATFORM_LABELS.get(post.platform, post.platform)
    title = post.title or "大V新动态"
    content = post.content[:200] or "（无正文）"
    category = post.category or ""
    meta = f"**{post.kol_name}** · {platform}"
    if category:
        meta += f" · 🗂 {category}"
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"{title} · {post.kol_name}"},
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"{meta}\n{content}"},
                },
                {
                    "tag": "note",
                    "elements": [{"tag": "plain_text", "content": f"发布时间：{post.published_at}"}],
                },
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


class FeishuNotifier(Notifier):
    channel = "feishu"

    def __init__(self, config, client: httpx.Client | None = None, open_id: str | None = None, chat_id: str | None = None):
        self.webhook_url = config.webhook_url
        self.app_id = config.app_id
        self.app_secret = config.app_secret
        self.open_id = open_id
        self.chat_id = chat_id
        self.client = client or httpx.Client(timeout=15)

    def _tenant_access_token(self) -> str:
        if not self.app_id or not self.app_secret:
            raise RuntimeError("未配置飞书应用凭据（feishu.app_id / app_secret）")
        resp = self.client.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"飞书获取 token 失败: {data.get('msg', data)}")
        return data["tenant_access_token"]

    def _post(self, payload: dict) -> None:
        resp = self.client.post(self.webhook_url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") not in (None, 0):
            raise RuntimeError(f"飞书返回错误: {data.get('msg', data)}")

    def notify(self, post: Post) -> None:
        if self.open_id or self.chat_id:
            token = self._tenant_access_token()
            receive_id_type = "open_id" if self.open_id else "chat_id"
            receive_id = self.open_id or self.chat_id
            # 应用消息 API 的 content 只需要 card 本体（不含 msg_type/card 外层）
            card = build_feishu_card(post)["card"]
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
        self._post(build_feishu_card(post))

    def send_text(self, text: str) -> None:
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
