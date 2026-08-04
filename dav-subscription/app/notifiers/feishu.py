"""飞书群机器人 webhook 通知。"""
from __future__ import annotations

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

    def __init__(self, config, client: httpx.Client | None = None):
        self.webhook_url = config.webhook_url
        self.client = client or httpx.Client(timeout=15)

    def _post(self, payload: dict) -> None:
        resp = self.client.post(self.webhook_url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") not in (None, 0):
            raise RuntimeError(f"飞书返回错误: {data.get('msg', data)}")

    def notify(self, post: Post) -> None:
        if not self.webhook_url:
            raise RuntimeError("未配置飞书 webhook_url")
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
