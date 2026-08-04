"""Telegram bot 命令订阅层：长轮询 getUpdates，支持 /list /sub /unsub /mysubs。"""
from __future__ import annotations

import asyncio
import logging
import re

import httpx

from . import auth

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "📌 大V订阅机器人\n"
    "/list — 查看可订阅的大V\n"
    "/sub 1 / 雪球主页链接 / 雪球UID — 订阅大V\n"
    "/unsub 1 / 雪球主页链接 / 雪球UID — 取消订阅\n"
    "/mysubs — 我的订阅\n"
    "/help — 帮助"
)


class TelegramBot:
    def __init__(self, db, bot_token: str, secret: str):
        self.db = db
        self.bot_token = bot_token
        self.secret = secret
        self.offset = 0
        self.client = httpx.Client(timeout=35)

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

    def _get_user(self, chat_id, from_info: dict) -> dict:
        chat_id = str(chat_id)
        user = self.db.get_user_by_telegram(chat_id)
        if user is None:
            username = (from_info.get("username") or f"tg_{chat_id}")[:30]
            uid = self.db.add_user(
                username,
                auth.hash_password(""),
                telegram_chat_id=chat_id,
            )
            user = self.db.get_user(uid)
        return user

    def _resolve_kol(self, arg: str):
        arg = arg.strip()
        if not arg:
            return None
        # 雪球主页链接：https://xueqiu.com/8790885129 或 https://xueqiu.com/u/8790885129
        if "xueqiu.com" in arg:
            match = re.search(r"xueqiu\.com/(?:u/)?(\d+)", arg)
            if not match:
                return None
            uid = match.group(1)
            for kol in self.db.list_kols():
                if kol["platform"] == "xueqiu" and kol["external_id"] == uid:
                    return kol
            return None
        # 纯数字：先按内部 ID，再按雪球 UID
        if arg.isdigit():
            kol = self.db.get_kol(int(arg))
            if kol:
                return kol
        for kol in self.db.list_kols():
            if kol["platform"] == "xueqiu" and kol["external_id"] == arg:
                return kol
        return None

    def handle_update(self, update: dict) -> None:
        msg = update.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        text = (msg.get("text") or "").strip()
        if not chat_id or not text or not text.startswith("/"):
            return
        user = self._get_user(chat_id, msg.get("from") or {})
        cmd, _, arg = text.partition(" ")
        cmd = cmd.lower()

        if cmd in ("/start", "/help"):
            self._send(chat_id, HELP_TEXT)
            return

        if cmd == "/list":
            kols = self.db.list_kols()[:30]
            subscribed = self.db.subscribed_kol_ids(user["id"])
            lines = ["📋 可订阅的大V："]
            lines.extend(
                f"{'✅' if k['id'] in subscribed else '⬜'} {k['id']}. {k['name']}（{k['platform']}）{'🔥' if k.get('priority') else ''}"
                for k in kols
            )
            if any(k.get("priority") for k in kols):
                lines.append("（🔥 优先大V，抓取更及时）")
            self._send(chat_id, "\n".join(lines) if kols else "暂无大V")
            return

        if cmd == "/sub":
            kol = self._resolve_kol(arg)
            if kol is None:
                self._send(chat_id, "没找到该大V，试试 /list 查看 ID")
            else:
                self.db.add_subscription(user["id"], kol["id"])
                self._send(chat_id, f"已订阅 {kol['name']} ✅")
            return

        if cmd == "/unsub":
            kol = self._resolve_kol(arg)
            if kol is None:
                self._send(chat_id, "没找到该大V，试试 /mysubs 查看已订阅")
            else:
                self.db.remove_subscription(user["id"], kol["id"])
                self._send(chat_id, f"已取消订阅 {kol['name']}")
            return

        if cmd == "/mysubs":
            subs = self.db.list_subscriptions(user["id"])
            if subs:
                lines = ["📌 我的订阅："]
                lines.extend(f"{s['id']}. {s['name']}" for s in subs)
                self._send(chat_id, "\n".join(lines))
            else:
                self._send(chat_id, "还没有订阅任何大V，试试 /list")
            return

        self._send(chat_id, "未知命令，发 /help 查看帮助")

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
