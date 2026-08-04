"""Telegram bot 长轮询适配层：把 getUpdates 映射到通用命令核心。"""
from __future__ import annotations

import asyncio
import logging

import httpx

from . import auth
from .bot_core import SubscriptionBot

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, db, bot_token: str, secret: str):
        self.db = db
        self.bot_token = bot_token
        self.secret = secret
        self.offset = 0
        self.client = httpx.Client(timeout=35)
        self.core = SubscriptionBot(
            db,
            lambda identity_type, identity, text: self._send(identity, text),
            lambda identity_type, identity, display_name: self._get_or_create_user(
                identity_type, identity, display_name
            ),
        )

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.bot_token}/{method}"

    def _call(self, method: str, **params):
        resp = self.client.post(self._url(method), data=params)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API 错误: {data.get('description')}")
        return data["result"]

    def _send(self, chat_id, text: str) -> None:
        self._call("sendMessage", chat_id=chat_id, text=text, disable_web_page_preview=True)

    def _get_or_create_user(self, identity_type: str, identity: str, display_name: str) -> dict:
        user = self.db.get_user_by_telegram(identity)
        if user is None:
            username = (display_name or f"tg_{identity}")[:30]
            uid = self.db.add_user(username, auth.hash_password(""), telegram_chat_id=identity)
            user = self.db.get_user(uid)
        return user

    def handle_update(self, update: dict) -> None:
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
