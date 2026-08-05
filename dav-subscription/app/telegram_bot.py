"""Telegram bot 长轮询适配层：把 getUpdates 映射到通用命令核心。"""
from __future__ import annotations

import asyncio
import json
import logging

import httpx

from .bot_core import SubscriptionBot
from .notifiers.telegram import _tg_rate_limiter

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, db, bot_token: str, secret: str, proxy: str = ""):
        self.db = db
        self.bot_token = bot_token
        self.secret = secret
        self.offset = 0
        self.client = httpx.Client(timeout=35, proxy=proxy or None)
        self.core = SubscriptionBot(
            db,
            lambda identity_type, identity, text, **kwargs: self._send(identity, text, **kwargs),
            lambda identity_type, identity, display_name: self._get_or_create_user(
                identity_type, identity, display_name
            ),
        )

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.bot_token}/{method}"

    def _call(self, method: str, **params):
        _tg_rate_limiter.wait()
        resp = self.client.post(self._url(method), data=params)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API 错误: {data.get('description')}")
        return data["result"]

    def _send(self, chat_id, text: str, kind: str | None = None, page: int | None = None, pages: int | None = None) -> None:
        params = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        keyboard = None
        if kind == "start":
            keyboard = [[{"text": "📋 查看大V", "callback_data": "list:1"}]]
        elif kind == "list":
            keyboard = []
            if pages and pages > 1:
                keyboard.append(
                    [
                        {"text": "◀️ 上一页", "callback_data": f"list:prev:{max(1, (page or 1) - 1)}"},
                        {"text": "下一页 ▶️", "callback_data": f"list:next:{page or 1}"},
                    ]
                )
            keyboard.append(
                [
                    {"text": "📋 我的订阅", "callback_data": "mysubs"},
                    {"text": "❓ 帮助", "callback_data": "help"},
                ]
            )
        if keyboard:
            params["reply_markup"] = json.dumps({"inline_keyboard": keyboard})
        self._call("sendMessage", **params)

    def _edit(self, chat_id, message_id, text: str, page: int | None = None, pages: int | None = None) -> None:
        params = {"chat_id": chat_id, "message_id": message_id, "text": text}
        keyboard = None
        if page is not None and pages is not None:
            keyboard = []
            if pages > 1:
                keyboard.append(
                    [
                        {"text": "◀️ 上一页", "callback_data": f"list:prev:{max(1, page - 1)}"},
                        {"text": "下一页 ▶️", "callback_data": f"list:next:{page}"},
                    ]
                )
            keyboard.append(
                [
                    {"text": "📋 我的订阅", "callback_data": "mysubs"},
                    {"text": "❓ 帮助", "callback_data": "help"},
                ]
            )
        if keyboard:
            params["reply_markup"] = json.dumps({"inline_keyboard": keyboard})
        self._call("editMessageText", **params)

    def _get_or_create_user(self, identity_type: str, identity: str, display_name: str) -> dict:
        user = self.db.get_user_by_telegram(identity)
        if user is None:
            username = (display_name or f"tg_{identity}")[:30]
            uid = self.db.add_user(username, "", telegram_chat_id=identity)
            user = self.db.get_user(uid)
        return user

    def handle_update(self, update: dict) -> None:
        if update.get("callback_query"):
            self._handle_callback(update)
            return
        msg = update.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        text = msg.get("text") or ""
        if not chat_id or not text:
            return
        from_info = msg.get("from") or {}
        self.core.handle(
            "telegram_chat_id",
            str(chat_id),
            from_info.get("username") or "",
            text,
        )

    def _handle_callback(self, update: dict) -> None:
        cb = update.get("callback_query") or {}
        data = cb.get("data") or ""
        cq_id = cb.get("id") or ""
        msg = cb.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        message_id = msg.get("message_id")
        if not chat_id or not message_id:
            return
        try:
            self._call("answerCallbackQuery", callback_query_id=cq_id)
        except Exception:  # noqa: BLE001 - 轻量回执失败不影响主流程
            logger.warning("answerCallbackQuery 失败 cq_id=%s", cq_id)
        user = self._get_or_create_user(
            "telegram_chat_id",
            str(chat_id),
            (cb.get("from") or {}).get("username") or "",
        )
        if data.startswith("unsub:"):
            try:
                kol_id = int(data.split(":", 1)[1])
            except ValueError:
                kol_id = 0
            kol = self.db.get_kol(kol_id)
            if kol is not None:
                self.db.remove_subscription(user["id"], kol_id)
                self._edit(chat_id, message_id, f"已取消订阅「{kol['name']}」")
            return
        if data.startswith("list:"):
            parts = data.split(":")
            if len(parts) == 3:
                _, direction, cur = parts
                page = max(1, int(cur))
                if direction == "prev":
                    page -= 1
                elif direction == "next":
                    page += 1
            else:
                page = max(1, int(parts[1]))
            text, page, pages = self.core.list_payload(user, str(page))
            self._edit(chat_id, message_id, text, page=page, pages=pages)
        elif data == "mysubs":
            self._edit(chat_id, message_id, self.core.mysubs_payload(user))
        elif data == "help":
            from .bot_core import HELP_TEXT

            self._edit(chat_id, message_id, HELP_TEXT)

    async def run(self):
        logger.info("Telegram bot 长轮询已启动")
        while True:
            try:
                updates = await asyncio.to_thread(
                    self._call, "getUpdates", timeout=30, offset=self.offset
                )
                for update in updates:
                    self.offset = update["update_id"] + 1
                    try:
                        await asyncio.to_thread(self.handle_update, update)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("处理 TG 命令失败: %s", exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("TG getUpdates 失败: %s", exc)
                await asyncio.sleep(5)
            await asyncio.sleep(0.3)
