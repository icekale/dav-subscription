"""订阅命令核心：Telegram / 飞书通用（/list /sub /unsub /mysubs /bind）。"""
from __future__ import annotations

import re
import time

from . import auth

HELP_TEXT = (
    "📌 大V订阅机器人\n"
    "/list — 查看可订阅的大V\n"
    "/sub 1 / 雪球主页链接 / 雪球UID — 订阅大V\n"
    "/unsub 1 / 雪球主页链接 / 雪球UID — 取消订阅\n"
    "/mysubs — 我的订阅\n"
    "/bind 6位绑定码 — 绑定网页/小程序账号\n"
    "/help — 帮助"
)

BIND_CODE_TTL = 600


class SubscriptionBot:
    """渠道无关的命令处理。send 与 get_or_create_user 由渠道适配层提供。"""

    def __init__(self, db, send, get_or_create_user):
        self.db = db
        self.send = send  # send(identity_type, identity, text)
        self.get_or_create_user = get_or_create_user  # (identity_type, identity, display_name) -> user dict

    def handle(
        self,
        identity_type: str,
        identity: str,
        display_name: str,
        text: str,
        reply_type: str | None = None,
        reply_id: str | None = None,
    ) -> None:
        """处理一条命令。

        identity 用于用户识别（TG chat_id / 飞书 open_id）；reply 用于回复目标，
        缺省时回复到 identity 本身（飞书群聊里回复目标是群 chat_id，需单独传）。
        """
        text = (text or "").strip()
        if not text.startswith("/"):
            return
        cmd, _, arg = text.partition(" ")
        cmd = cmd.lower()

        if cmd == "/bind":
            self._bind(identity_type, identity, arg, reply_type, reply_id)
            return

        user = self.get_or_create_user(identity_type, identity, display_name)

        if cmd in ("/start", "/help"):
            self.send(reply_type or identity_type, reply_id or identity, HELP_TEXT)
        elif cmd == "/list":
            self._list(user, reply_type or identity_type, reply_id or identity)
        elif cmd == "/sub":
            self._sub(user, reply_type or identity_type, reply_id or identity, arg)
        elif cmd == "/unsub":
            self._unsub(user, reply_type or identity_type, reply_id or identity, arg)
        elif cmd == "/mysubs":
            self._mysubs(user, reply_type or identity_type, reply_id or identity)
        else:
            self.send(reply_type or identity_type, reply_id or identity, "未知命令，发 /help 查看帮助")

    def _bind(self, identity_type: str, identity: str, code: str, reply_type=None, reply_id=None) -> None:
        reply_type = reply_type or identity_type
        reply_id = reply_id or identity
        code = code.strip().upper()
        if len(code) != 6:
            self.send(reply_type, reply_id, "绑定码无效，请在网页/小程序「推送设置」里生成")
            return
        row = self.db.get_bind_code(code)
        if row is None or row["expires_at"] < int(time.time()):
            self.send(reply_type, reply_id, "绑定码无效或已过期，请重新生成")
            return
        target = self.db.get_user(row["user_id"])
        if target is None:
            self.send(reply_type, reply_id, "绑定码无效，请重新生成")
            return
        # 若该渠道已有自动创建的账号，合并订阅后删除
        if identity_type == "telegram_chat_id":
            existing = self.db.get_user_by_telegram(identity)
            update = {"telegram_chat_id": identity}
        else:
            existing = self.db.get_user_by_feishu(identity)
            update = {"feishu_open_id": identity}
        if existing and existing["id"] != target["id"]:
            self.db.transfer_subscriptions(existing["id"], target["id"])
            self.db.delete_user(existing["id"])
        self.db.update_user(target["id"], **update)
        self.db.delete_bind_code(code)
        self.send(
            reply_type,
            reply_id,
            f"已绑定到账号 {target['username']} ✅ 之后新帖会推送到这里",
        )

    def _list(self, user, identity_type: str, identity: str) -> None:
        kols = self.db.list_kols()[:30]
        subscribed = self.db.subscribed_kol_ids(user["id"])
        lines = ["📋 可订阅的大V："]
        lines.extend(
            f"{'✅' if k['id'] in subscribed else '⬜'} {k['id']}. {k['name']}（{k['platform']}）{'🔥' if k.get('priority') else ''}"
            for k in kols
        )
        if any(k.get("priority") for k in kols):
            lines.append("（🔥 优先大V，抓取更及时）")
        self.send(identity_type, identity, "\n".join(lines) if kols else "暂无大V")

    def _sub(self, user, identity_type: str, identity: str, arg: str) -> None:
        kol = self._resolve_kol(arg)
        if kol is None:
            self.send(identity_type, identity, "没找到该大V，试试 /list 查看 ID")
        else:
            self.db.add_subscription(user["id"], kol["id"])
            self.send(identity_type, identity, f"已订阅 {kol['name']} ✅")

    def _unsub(self, user, identity_type: str, identity: str, arg: str) -> None:
        kol = self._resolve_kol(arg)
        if kol is None:
            self.send(identity_type, identity, "没找到该大V，试试 /mysubs 查看已订阅")
        else:
            self.db.remove_subscription(user["id"], kol["id"])
            self.send(identity_type, identity, f"已取消订阅 {kol['name']}")

    def _mysubs(self, user, identity_type: str, identity: str) -> None:
        subs = self.db.list_subscriptions(user["id"])
        if subs:
            lines = ["📌 我的订阅："]
            lines.extend(f"{s['id']}. {s['name']}" for s in subs)
            self.send(identity_type, identity, "\n".join(lines))
        else:
            self.send(identity_type, identity, "还没有订阅任何大V，试试 /list")

    def _resolve_kol(self, arg: str):
        arg = arg.strip()
        if not arg:
            return None
        if "xueqiu.com" in arg:
            match = re.search(r"xueqiu\.com/(?:u/)?(\d+)", arg)
            if not match:
                return None
            uid = match.group(1)
            for kol in self.db.list_kols():
                if kol["platform"] == "xueqiu" and kol["external_id"] == uid:
                    return kol
            return None
        if arg.isdigit():
            kol = self.db.get_kol(int(arg))
            if kol:
                return kol
        for kol in self.db.list_kols():
            if kol["platform"] == "xueqiu" and kol["external_id"] == arg:
                return kol
        return None
