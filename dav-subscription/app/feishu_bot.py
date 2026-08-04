"""飞书命令订阅：事件订阅长连接（WebSocket），用户在飞书里可发 /list /sub 等。"""
from __future__ import annotations

import json
import logging
import threading

from . import auth
from .bot_core import SubscriptionBot

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
            lambda identity_type, identity, text: self._send(identity_type, identity, text),
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
            uid = self.db.add_user(username, auth.hash_password(""), feishu_open_id=identity)
            user = self.db.get_user(uid)
        return user

    def handle_message(self, chat_id: str, chat_type: str, open_id: str, sender_name: str, text: str) -> None:
        is_group = chat_type == "group"
        reply_type = "feishu_chat_id" if is_group else "feishu_open_id"
        reply_id = chat_id if is_group else open_id
        self.core.handle(
            "feishu_open_id",
            open_id,
            sender_name,
            text,
            reply_type=reply_type,
            reply_id=reply_id,
        )

    def _on_message(self, event):
        try:
            message = event.event.message
            content = json.loads(message.content or "{}")
            text = content.get("text") or ""
            chat_id = message.chat_id or ""
            chat_type = message.chat_type or "p2p"
            sender = event.event.sender
            open_id = (sender.sender_id or {}).open_id or ""
            self.handle_message(chat_id, chat_type, open_id, open_id, text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("处理飞书消息失败: %s", exc)

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
            .build()
        )
        self._ws_client = lark_oapi.ws.Client(
            self.app_id,
            self.app_secret,
            event_handler=handler,
            log_level=lark_oapi.LogLevel.INFO,
        )
        self._ws_client.start()
