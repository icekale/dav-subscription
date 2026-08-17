"""Telegram bot 长轮询适配层：把 getUpdates 映射到通用命令核心。"""
from __future__ import annotations

import asyncio
import json
import logging
import time

import httpx
from fastapi import HTTPException

from .bot_core import SubscriptionBot
from .notifiers.telegram import _tg_rate_limiter

logger = logging.getLogger(__name__)

# 通知按钮操作（退订/设次要）的撤销窗口
UNDO_TTL_SECONDS = 30


class TelegramBot:
    def __init__(self, db, bot_token: str, secret: str, proxy: str = ""):
        self.db = db
        self.bot_token = bot_token
        self.secret = secret
        self.offset = 0
        self.client = httpx.Client(timeout=35, proxy=proxy or None)
        self._last_search: dict[str, str] = {}  # chat_id -> 最近一次 /search 关键词（用于按钮回调后重渲染）
        self._undo_windows: dict[str, tuple[float, dict]] = {}  # chat:msg -> (时间戳, 快照)
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

    def _send(self, chat_id, text: str, kind: str | None = None, page: int | None = None, pages: int | None = None, search: str | None = None) -> None:
        params = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        keyboard = None
        if kind == "start":
            keyboard = [[{"text": "📋 查看大V", "callback_data": "list:1"}]]
        elif kind == "list":
            keyboard = self._list_keyboard(page, pages)
        elif kind == "search" and search:
            self._last_search[str(chat_id)] = search
            user = self.db.get_user_by_telegram(str(chat_id))
            if user is not None:
                _, matches = self.core.search_payload(user, search)
                keyboard = self._search_keyboard(matches)
        elif kind == "mysubs":
            user = self.db.get_user_by_telegram(str(chat_id))
            if user is not None:
                keyboard = self._mysubs_keyboard(user)
        if keyboard:
            params["reply_markup"] = json.dumps({"inline_keyboard": keyboard}, ensure_ascii=False)
        self._call("sendMessage", **params)

    def _approval_category_keyboard(self, request_id: int) -> list[list[dict]]:
        """审批通过后选分类：每行两个，末尾固定「未分类」和「拒绝」。"""
        cats = self.db.list_categories()
        buttons = [{"text": c["name"], "callback_data": f"apcat:{request_id}:{c['id']}"} for c in cats]
        rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
        rows.append([
            {"text": "未分类", "callback_data": f"apcat:{request_id}:0"},
            {"text": "❌ 拒绝", "callback_data": f"reject:{request_id}"},
        ])
        return rows

    def _list_keyboard(self, page: int | None, pages: int | None) -> list[list[dict]]:
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
        return keyboard

    def _search_keyboard(self, matches: list[dict]) -> list[list[dict]]:
        """搜索结果键盘：每条大V一个订阅/退订按钮，末尾固定管理入口。"""
        keyboard = []
        for m in matches:
            if m.get("subscribed"):
                keyboard.append(
                    [{"text": f"退订 {m['name']}", "callback_data": f"unsub:{m['id']}"}]
                )
            else:
                keyboard.append(
                    [{"text": f"➕ 订阅 {m['name']}", "callback_data": f"sub:{m['id']}"}]
                )
        keyboard.append(
            [
                {"text": "📋 我的订阅", "callback_data": "mysubs"},
                {"text": "❓ 帮助", "callback_data": "help"},
            ]
        )
        return keyboard

    def _mysubs_keyboard(self, user: dict) -> list[list[dict]]:
        """我的订阅键盘：每条「改类型 / 退订」，无订阅时引导去查看大V。"""
        items = self.core.mysubs_items(user)
        if not items:
            return [[{"text": "📋 查看大V", "callback_data": "list:1"}]]
        return [
            [
                {"text": f"📮 {it['type_label']}", "callback_data": f"mysubs:type:{it['kol_id']}"},
                {"text": f"退订 {it['name']}", "callback_data": f"mysubs:unsub:{it['kol_id']}"},
            ]
            for it in items
        ]

    def _render_search(self, user: dict, keyword: str) -> tuple[str, list[list[dict]]]:
        text, matches = self.core.search_payload(user, keyword)
        return text, self._search_keyboard(matches)

    def _render_mysubs(self, user: dict) -> tuple[str, list[list[dict]]]:
        return self.core.mysubs_payload(user), self._mysubs_keyboard(user)

    def _edit(self, chat_id, message_id, text: str, page: int | None = None, pages: int | None = None, keyboard: list[list[dict]] | None = None) -> None:
        params = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if keyboard is None and page is not None and pages is not None:
            keyboard = self._list_keyboard(page, pages)
        if keyboard:
            params["reply_markup"] = json.dumps({"inline_keyboard": keyboard}, ensure_ascii=False)
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
        if not chat_id or not text or chat.get("type", "private") != "private":
            return
        from_info = msg.get("from") or {}
        self.core.handle(
            "telegram_chat_id",
            str(chat_id),
            from_info.get("username") or "",
            text,
        )

    def _remember_undo(self, chat_id, message_id, payload: dict) -> None:
        self._undo_windows[f"{chat_id}:{message_id}"] = (time.time(), payload)

    def _pop_undo(self, chat_id, message_id) -> tuple[float, dict] | None:
        return self._undo_windows.pop(f"{chat_id}:{message_id}", None)

    def _msg_keyboard(self, msg: dict) -> list[list[dict]] | None:
        """取回调消息原始 inline 键盘，用于撤销时还原。"""
        rm = msg.get("reply_markup") or {}
        return rm.get("inline_keyboard") or None

    def _handle_sub_action(self, data: str, chat_id, message_id, msg: dict, user: dict) -> None:
        """通知/搜索按钮的订阅操作：退订、设次要，均带 30 秒内撤销。"""
        action, _, rest = data.partition(":")
        try:
            kol_id = int(rest)
        except ValueError:
            kol_id = 0
        kol = self.db.get_kol(kol_id)
        if kol is None:
            return
        if action == "unsub":
            sub = self.db.get_subscription(user["id"], kol_id)
            self.db.remove_subscription(user["id"], kol_id)
            if sub is None:
                self._edit(chat_id, message_id, f"已取消订阅「{kol['name']}」")
                return
            self._remember_undo(
                chat_id, message_id,
                {
                    "kind": "unsub",
                    "kol_id": kol_id,
                    "type": sub["type"],
                    "favorite": bool(sub["favorite"]),
                    "secondary": bool(sub["secondary"]),
                    # 原始消息快照：撤销回调的 reply_markup 是撤销按钮本身，
                    # 必须用操作时的快照还原，否则还原编辑报 message not modified
                    "text": msg.get("text") or "",
                    "keyboard": self._msg_keyboard(msg),
                },
            )
            self._edit(
                chat_id, message_id,
                msg.get("text") or f"已取消订阅「{kol['name']}」",
                keyboard=[[{"text": f"↩️ 撤销退订「{kol['name']}」", "callback_data": f"unsubundo:{kol_id}"}]],
            )
            return
        if action == "sec":
            sub = self.db.get_subscription(user["id"], kol_id)
            if sub is None:
                self._edit(chat_id, message_id, f"未订阅「{kol['name']}」，无法设置次要")
                return
            was_secondary = bool(sub["secondary"])
            self.db.set_subscription_secondary(user["id"], kol_id, not was_secondary)
            self._remember_undo(
                chat_id, message_id,
                {
                    "kind": "sec",
                    "kol_id": kol_id,
                    "was_secondary": was_secondary,
                    "text": msg.get("text") or "",
                    "keyboard": self._msg_keyboard(msg),
                },
            )
            text = (
                f"已恢复实时推送：「{kol['name']}」🔔"
                if was_secondary
                else f"已设为次要：「{kol['name']}」新帖合并推送 🔕"
            )
            self._edit(
                chat_id, message_id, text,
                keyboard=[[{"text": "↩️ 撤销", "callback_data": f"secundo:{kol_id}"}]],
            )
            return
        # secundo / unsubundo
        entry = self._pop_undo(chat_id, message_id)
        if (
            entry is None
            or entry[1].get("kol_id") != kol_id
            or time.time() - entry[0] > UNDO_TTL_SECONDS
        ):
            self._edit(chat_id, message_id, "⏳ 撤销超时或操作已失效（30 秒内可撤销）")
            return
        payload = entry[1]
        if action == "unsubundo" and payload.get("kind") == "unsub":
            self.db.add_subscription(user["id"], kol_id, payload.get("type", "post"))
            self.db.set_subscription_favorite(user["id"], kol_id, bool(payload.get("favorite")))
            self.db.set_subscription_secondary(user["id"], kol_id, bool(payload.get("secondary")))
        elif action == "secundo" and payload.get("kind") == "sec":
            self.db.set_subscription_secondary(user["id"], kol_id, bool(payload.get("was_secondary")))
        else:
            return
        # 用操作时的快照还原原始消息（含原始键盘），避免拿当前撤销按钮键盘还原
        keyboard = payload.get("keyboard")
        text = payload.get("text") or msg.get("text")
        try:
            if text:
                self._edit(chat_id, message_id, text, keyboard=keyboard)
            else:
                self._edit(chat_id, message_id, "已撤销 ✅", keyboard=keyboard)
        except Exception:  # noqa: BLE001 - 界面还原失败不影响撤销已生效
            logger.warning("撤销后还原消息失败 chat=%s msg=%s", chat_id, message_id, exc_info=True)

    def _handle_callback(self, update: dict) -> None:
        cb = update.get("callback_query") or {}
        data = cb.get("data") or ""
        cq_id = cb.get("id") or ""
        msg = cb.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        message_id = msg.get("message_id")
        if not chat_id or not message_id or chat.get("type", "private") != "private":
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
        if data.startswith(("approve:", "reject:", "apcat:")):
            # 大V添加申请审批按钮：仅管理员可操作，走与后台端点相同的逻辑
            if not user.get("is_admin"):
                self._edit(chat_id, message_id, "只有管理员可以审批大V申请")
                return
            try:
                parts = data.split(":")
                request_id = int(parts[1])
            except (ValueError, IndexError):
                request_id = 0
            from .api import _do_approve_kol_request, _do_reject_kol_request

            try:
                if data.startswith("approve:"):
                    req = self.db.get_kol_request(request_id)
                    if req is None or req["status"] != "pending":
                        self._edit(chat_id, message_id, f"审批失败：申请 {request_id} 不存在或已处理")
                    else:
                        label = req.get("name") or req.get("external_id") or str(request_id)
                        self._edit(
                            chat_id, message_id,
                            f"请选择「{label}」的分类：",
                            keyboard=self._approval_category_keyboard(request_id),
                        )
                elif data.startswith("apcat:"):
                    try:
                        category_id = int(parts[2])
                    except (ValueError, IndexError):
                        category_id = 0
                    kol = _do_approve_kol_request(
                        self.db, request_id, user,
                        category_id=category_id or None,
                    )
                    if kol is None:
                        self._edit(chat_id, message_id, f"审批失败：申请 {request_id} 不存在")
                    else:
                        cat = (kol.get("category_name") or "未分类").strip() or "未分类"
                        self._edit(
                            chat_id, message_id,
                            f"✅ 已通过「{kol['name']}」的添加申请（{cat}），已上架并自动订阅申请人",
                        )
                else:
                    _do_reject_kol_request(self.db, request_id, user)
                    self._edit(chat_id, message_id, "❌ 已拒绝该添加申请")
            except HTTPException as exc:
                self._edit(chat_id, message_id, f"审批失败：{exc.detail}")
            return
        if data.startswith(("sec:", "secundo:", "unsubundo:", "unsub:")):
            self._handle_sub_action(data, chat_id, message_id, msg, user)
            return
        if data.startswith("sub:"):
            # /search 结果里的订阅按钮：私有大V只有 ACL 用户可订阅，普通用户拒绝
            try:
                kol_id = int(data.split(":", 1)[1])
            except ValueError:
                kol_id = 0
            kol = self.db.get_kol(kol_id)
            if kol is not None:
                if kol.get("is_private") and kol_id not in self.db.visible_kol_ids(user["id"]):
                    self._edit(
                        chat_id, message_id,
                        f"「{kol['name']}」为私有大V，你无权订阅（请联系管理员开通）",
                    )
                    return
                self.db.add_subscription(user["id"], kol_id)
                keyword = self._last_search.get(str(chat_id))
                if keyword:
                    text, keyboard = self._render_search(user, keyword)
                    self._edit(chat_id, message_id, text, keyboard=keyboard)
                else:
                    self._edit(chat_id, message_id, f"已订阅「{kol['name']}」✅ 发 /list 或 /mysubs 管理订阅")
            return
        if data.startswith("mysubs:type:"):
            # 我的订阅里切换订阅类型：post → reply → both → post
            try:
                kol_id = int(data.split(":", 2)[2])
            except ValueError:
                kol_id = 0
            cycle = {"post": "reply", "reply": "both", "both": "post"}
            items = {it["kol_id"]: it for it in self.core.mysubs_items(user)}
            it = items.get(kol_id)
            if it is not None:
                new_type = cycle.get(it["type"], "post")
                self.db.update_subscription_type(user["id"], kol_id, new_type)
            text, keyboard = self._render_mysubs(user)
            self._edit(chat_id, message_id, text, keyboard=keyboard)
            return
        if data.startswith("mysubs:unsub:"):
            try:
                kol_id = int(data.split(":", 2)[2])
            except ValueError:
                kol_id = 0
            kol = self.db.get_kol(kol_id)
            if kol is not None:
                self.db.remove_subscription(user["id"], kol_id)
            text, keyboard = self._render_mysubs(user)
            self._edit(chat_id, message_id, text, keyboard=keyboard)
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
            text, keyboard = self._render_mysubs(user)
            self._edit(chat_id, message_id, text, keyboard=keyboard)
        elif data == "help":
            from .bot_core import HELP_TEXT

            self._edit(chat_id, message_id, HELP_TEXT)

    def _set_commands(self) -> None:
        """注册命令菜单，用户输入框里直接看到可用命令。"""
        commands = [
            {"command": "list", "description": "查看可订阅的大V"},
            {"command": "search", "description": "搜索大V，如 /search 茅台"},
            {"command": "sub", "description": "订阅大V，如 /sub 1 both"},
            {"command": "unsub", "description": "取消订阅，如 /unsub 1"},
            {"command": "mysubs", "description": "我的订阅（退订/改类型）"},
            {"command": "ask", "description": "申请添加大V"},
            {"command": "bind", "description": "绑定网页/小程序账号"},
            {"command": "help", "description": "帮助"},
        ]
        self._call("setMyCommands", commands=json.dumps(commands))

    async def run(self):
        logger.info("Telegram bot 长轮询已启动")
        try:
            await asyncio.to_thread(self._set_commands)
            logger.info("Telegram 命令菜单已注册")
        except Exception as exc:  # noqa: BLE001 - 菜单注册失败不影响轮询
            logger.warning("setMyCommands 失败: %s", exc)
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
