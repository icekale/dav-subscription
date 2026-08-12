"""飞书命令订阅：事件订阅长连接（WebSocket），用户在飞书里可发 /list /sub 等。"""
from __future__ import annotations

import json
import logging
import threading

from .bot_core import LIST_PAGE_SIZE, SubscriptionBot

logger = logging.getLogger(__name__)


class FeishuBot:
    def __init__(self, db, app_id: str, app_secret: str):
        self.db = db
        self.app_id = app_id
        self.app_secret = app_secret
        self._ws_client = None
        self._api_client = None
        self._thread = None
        self.core = SubscriptionBot(
            db,
            lambda identity_type, identity, text, **kwargs: self._send(identity_type, identity, text),
            lambda identity_type, identity, display_name: self._get_or_create_user(
                identity_type, identity, display_name
            ),
        )

    def _get_api_client(self):
        if self._api_client is None:
            import lark_oapi

            self._api_client = (
                lark_oapi.Client.builder()
                .app_id(self.app_id)
                .app_secret(self.app_secret)
                .build()
            )
        return self._api_client

    def _send(self, identity_type: str, identity: str, text: str) -> None:
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

        receive_id_type = "chat_id" if identity_type == "feishu_chat_id" else "open_id"
        request = (
            CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(identity)
                .msg_type("text")
                .content(json.dumps({"text": text}, ensure_ascii=False))
                .build()
            )
            .build()
        )
        resp = self._get_api_client().im.v1.message.create(request)
        if not resp.success():
            raise RuntimeError(f"飞书发送失败: {resp.code} {resp.msg}")

    def _get_or_create_user(self, identity_type: str, identity: str, display_name: str) -> dict:
        user = self.db.get_user_by_feishu(identity)
        if user is None:
            username = (display_name or f"fs_{identity[:8]}")[:30]
            uid = self.db.add_user(username, "", feishu_open_id=identity)
            user = self.db.get_user(uid)
        return user

    def handle_message(self, chat_id: str, chat_type: str, open_id: str, sender_name: str, text: str) -> None:
        is_new = self.db.get_user_by_feishu(open_id) is None
        # 单聊里记录用户的 p2p 会话 chat_id：飞书 open_id 直发可能被 230101 拦截，
        # 用 chat_id 发单聊消息是稳定可用的路径（群聊/单聊回复都走 chat_id）。
        if chat_type != "group":
            user = self._get_or_create_user("feishu_open_id", open_id, sender_name)
            if user.get("feishu_chat_id") != chat_id:
                self.db.update_user(user["id"], feishu_chat_id=chat_id)
        if chat_type != "group" and (text or "").strip().lower().startswith("/list"):
            # 单聊里的 /list 用卡片交互（带订阅/翻页按钮），群聊保持文本
            self._send_list_card(chat_id, open_id, sender_name, (text or "").partition(" ")[2])
            return
        self.core.handle(
            "feishu_open_id",
            open_id,
            sender_name,
            text,
            reply_type="feishu_chat_id",
            reply_id=chat_id,
        )
        # /bind 合并账号后会自动账号被删掉，这里再补一次，确保目标账号也带上 p2p 会话
        if chat_type != "group":
            user = self.db.get_user_by_feishu(open_id)
            if user is not None and user.get("feishu_chat_id") != chat_id:
                self.db.update_user(user["id"], feishu_chat_id=chat_id)
        if is_new:
            if chat_type == "group":
                self._send(
                    "feishu_chat_id",
                    chat_id,
                    "💡 提示：群聊不会推送新帖。请在飞书里「私聊」本机器人并发送任意消息，之后新帖会发到私聊会话。",
                )
            elif not (text or "").strip().startswith("/"):
                self._send(
                    "feishu_chat_id",
                    chat_id,
                    "✅ 会话已建立：订阅大V后，新帖会直接发到这个私聊会话。发 /list 可查看大V。\n\n"
                    "💡 如果你同时使用网页/小程序，请到网页「推送设置」生成绑定码，"
                    "然后把 /bind 6位码 发给我，两个渠道的订阅与推送会合并。",
                )

    def _send_card(self, chat_id: str, card: dict) -> None:
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("interactive")
                .content(json.dumps(card, ensure_ascii=False))
                .build()
            )
            .build()
        )
        resp = self._get_api_client().im.v1.message.create(request)
        if not resp.success():
            raise RuntimeError(f"飞书卡片发送失败: {resp.code} {resp.msg}")

    def _send_list_card(self, chat_id: str, open_id: str, sender_name: str, arg: str) -> None:
        user = self._get_or_create_user("feishu_open_id", open_id, sender_name)
        _, page, pages = self.core.list_payload(user, arg)
        self._send_card(chat_id, self._build_list_card(user, page, pages))

    def _build_list_card(self, user: dict, page: int, pages: int) -> dict:
        kols = self.db.list_kols()
        if not user.get("is_admin"):
            visible = self.db.visible_kol_ids(user["id"])
            kols = [k for k in kols if k["id"] in visible]
        subscribed = self.db.subscribed_kol_ids(user["id"])
        text, _, _ = self.core.list_payload(user, str(page))
        start = (page - 1) * LIST_PAGE_SIZE
        page_kols = kols[start : start + LIST_PAGE_SIZE]
        elements = [{"tag": "div", "text": {"tag": "lark_md", "content": text}}]
        actions = []
        for k in page_kols[:4]:
            is_sub = k["id"] in subscribed
            actions.append(
                [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": f"{'取消订阅' if is_sub else '订阅'} {k['name']}"},
                        "type": "default" if is_sub else "primary",
                        "value": {"action": "unsub" if is_sub else "sub", "kol_id": k["id"]},
                    }
                ]
            )
        if pages > 1:
            actions.append(
                [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "◀️ 上一页"},
                        "type": "default",
                        "value": {"action": "page", "page": max(1, page - 1)},
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "下一页 ▶️"},
                        "type": "default",
                        "value": {"action": "page", "page": min(pages, page + 1)},
                    },
                ]
            )
        if actions:
            elements.extend(actions)
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"大V列表（第 {page}/{pages} 页）"},
                "template": "blue",
            },
            "elements": elements,
        }
        return card

    def _on_card_action(self, event):
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            CallBackCard,
            CallBackToast,
            P2CardActionTriggerResponse,
        )

        resp = P2CardActionTriggerResponse()
        try:
            action = event.event.action
            value = action.value or {}
            operator = event.event.operator
            open_id = (operator or {}).open_id or ""
            act = value.get("action")
            if not open_id or not act:
                return resp
            if act == "page":
                user = self._get_or_create_user("feishu_open_id", open_id, open_id)
                _, page, pages = self.core.list_payload(user, str(value.get("page", 1)))
                resp.card = CallBackCard({"type": "raw", "data": self._build_list_card(user, page, pages)})
                resp.toast = CallBackToast({"type": "info", "content": f"第 {page}/{pages} 页"})
                return resp
            if act == "sec":
                kol = self.db.get_kol(int(value.get("kol_id", 0) or 0))
                user = self._get_or_create_user("feishu_open_id", open_id, open_id)
                if kol is None:
                    resp.toast = CallBackToast({"type": "error", "content": "大V不存在"})
                    return resp
                sub_row = self.db.get_subscription(user["id"], kol["id"])
                if sub_row is None:
                    resp.toast = CallBackToast({"type": "error", "content": "未订阅该大V"})
                    return resp
                was = bool(sub_row["secondary"])
                self.db.set_subscription_secondary(user["id"], kol["id"], not was)
                resp.toast = CallBackToast(
                    {
                        "type": "info",
                        "content": "已恢复实时推送" if was else "已设为次要（合并推送）",
                    }
                )
                return resp
            if act in ("sub", "unsub"):
                kol = self.db.get_kol(int(value.get("kol_id", 0) or 0))
                user = self._get_or_create_user("feishu_open_id", open_id, open_id)
                if kol is None:
                    resp.toast = CallBackToast({"type": "error", "content": "大V不存在"})
                    return resp
                if act == "sub":
                    if not user.get("is_admin") and kol["id"] not in self.db.visible_kol_ids(user["id"]):
                        resp.toast = CallBackToast({"type": "error", "content": "无权订阅该大V"})
                        return resp
                    self.db.add_subscription(user["id"], kol["id"])
                    content = f"已订阅 {kol['name']} ✅"
                else:
                    self.db.remove_subscription(user["id"], kol["id"])
                    content = f"已取消订阅 {kol['name']}"
                resp.toast = CallBackToast({"type": "info", "content": content})
                return resp
        except Exception as exc:  # noqa: BLE001
            logger.warning("卡片回调处理失败: %s", exc, exc_info=True)
        return resp

    def _on_message(self, event):
        try:
            message = event.event.message
            content = json.loads(message.content or "{}")
            text = content.get("text") or ""
            chat_id = message.chat_id or ""
            chat_type = message.chat_type or "p2p"
            sender = event.event.sender
            open_id = (sender.sender_id or {}).open_id or ""
            logger.info(
                "收到飞书消息 chat_type=%s chat_id=%s sender=%s text=%r",
                chat_type,
                chat_id,
                open_id,
                text[:50],
            )
            self.handle_message(chat_id, chat_type, open_id, open_id, text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("处理飞书消息失败: %s", exc, exc_info=True)

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("飞书 bot 长连接线程已启动")

    def _run(self):
        # lark-oapi 必须在无运行中事件循环的线程里导入/创建（否则 SDK 会绑定到主循环）
        import lark_oapi
        from lark_oapi.event.dispatcher_handler import EventDispatcherHandler

        handler = (
            EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_message)
            .register_p2_card_action_trigger(self._on_card_action)
            .build()
        )
        self._ws_client = lark_oapi.ws.Client(
            self.app_id,
            self.app_secret,
            event_handler=handler,
            log_level=lark_oapi.LogLevel.INFO,
        )
        self._ws_client.start()
