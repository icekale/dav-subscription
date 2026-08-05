"""飞书群机器人 webhook 通知。"""
from __future__ import annotations

import json
import logging
import threading
import time

import httpx

from ..fetchers.base import Post, truncate_text
from .base import Notifier

PLATFORM_LABELS = {"xueqiu": "雪球", "combination": "雪球组合", "weibo": "微博", "twitter": "X/Twitter"}
DIGEST_MAX_ITEMS = 5
logger = logging.getLogger(__name__)

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
    content = truncate_text(post.content, 2000) or post.title or "（无正文）"
    title = f"📌 {post.kol_name} · {platform}"
    if post.post_type == "reply":
        title += " · 回复"
    category = post.category or ""
    meta_lines = []
    if category:
        meta_lines.append(f"🗂 {category}")
    meta_lines.append(f"🕐 {post.published_at}")
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": content},
                },
                {"tag": "hr"},
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": "\n".join(meta_lines)},
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


def build_feishu_combination_card(post: Post) -> dict:
    """组合调仓专用卡片：收益统计一行、每次操作独立卡片块，层次更清楚。"""
    detail = post.detail or {}
    stats = detail.get("stats") or []
    actions = detail.get("actions") or []
    cash = detail.get("cash") or ""
    elements: list[dict] = []
    if stats:
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "　".join(f"**{k}** {v}" for k, v in stats),
                },
            }
        )
        elements.append({"tag": "hr"})
    for a in actions:
        a_type = a.get("type") or "调整"
        icon = {"清仓": "🗑", "新建": "🆕", "增持": "➕", "减持": "➖"}.get(a_type, "•")
        stock = a.get("stock") or ""
        symbol = a.get("symbol") or ""
        stock_text = f"{stock}（{symbol}）" if symbol else stock
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"{icon} **{a_type}** {stock_text}\n"
                        f"{a.get('prev') or '0.0%'} → {a.get('target') or '0.0%'}"
                    ),
                },
            }
        )
    if cash:
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"💵 现金 **{cash}**"}})
    elements.append({"tag": "hr"})
    elements.append(
        {
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"🕐 {post.published_at}"},
        }
    )
    elements.append(
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
        }
    )
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"📌 {post.kol_name} · 雪球组合 · 调仓"},
                "template": "blue",
            },
            "elements": elements,
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


def build_feishu_daily_card(posts: list[Post]) -> dict:
    elements = []
    for i, post in enumerate(posts[:DIGEST_MAX_ITEMS], 1):
        body = (post.content[:100] or post.title or "（无正文）").replace("\n", " ")
        text = f"{i}. **{post.kol_name}**：{body}"
        if post.published_at:
            text += f"\n🕐 {post.published_at}"
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": text}})
        if post.url:
            elements.append(
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "查看原文"},
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
            "title": {"tag": "plain_text", "content": "📊 今日大V精选"},
            "template": "orange",
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
        if post.platform == "combination" and post.detail:
            card = build_feishu_combination_card(post)["card"]
        else:
            card = build_feishu_card(post)["card"]
        # 帖子图片：上传后插入 img 元素（最多 2 张），失败不影响文本卡片
        if post.images and self.app_id and self.app_secret:
            try:
                keys = self._upload_images(post.images[:2])
                if keys:
                    img_elements = [
                        {
                            "tag": "img",
                            "img_key": key,
                            "alt": {"tag": "plain_text", "content": ""},
                        }
                        for key in keys
                    ]
                    card["elements"] = (
                        [card["elements"][0]] + img_elements + card["elements"][1:]
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("飞书图片上传失败 err=%s", exc)
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

    def _upload_images(self, image_urls: list[str]) -> list[str]:
        """下载远端图片并上传到飞书，返回 image_key 列表（失败项跳过）。"""
        token = self._tenant_access_token()
        keys: list[str] = []
        headers = {"Authorization": f"Bearer {token}"}
        for url in image_urls:
            try:
                img_resp = self.client.get(url, timeout=12)
                if img_resp.status_code != 200 or not img_resp.content:
                    continue
                resp = self.client.post(
                    "https://open.feishu.cn/open-apis/im/v1/images",
                    headers=headers,
                    data={"image_type": "message"},
                    files={"image": ("img.jpg", img_resp.content, "image/jpeg")},
                )
                data = resp.json()
                key = ((data or {}).get("data") or {}).get("image_key") or ""
                if key:
                    keys.append(key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("飞书图片上传失败 url=%s err=%s", url, exc)
        return keys

    def send_digest(self, posts: list[Post], kol_name: str, platform: str) -> None:
        self._send_card(build_feishu_digest_card(posts, kol_name, platform))

    def send_daily(self, posts: list[Post]) -> None:
        self._send_card(build_feishu_daily_card(posts))

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
