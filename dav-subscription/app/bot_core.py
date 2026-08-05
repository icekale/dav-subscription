"""订阅命令核心：Telegram / 飞书通用（/list /sub /unsub /mysubs /bind）。"""
from __future__ import annotations

import re
import time
from math import ceil

HELP_TEXT = (
    "📌 大V订阅机器人\n"
    "/list — 查看可订阅的大V（/list 2 翻页）\n"
    "/sub 1 / 雪球/微博主页链接 / UID — 订阅大V\n"
    "　可选：/sub 1 reply（只订回复）/ /sub 1 both（帖子+回复）\n"
    "/unsub 1 / 雪球/微博主页链接 / UID — 取消订阅\n"
    "/ask 主页链接/UID — 申请添加大V，管理员审批\n"
    "/mysubs — 我的订阅\n"
    "/bind 6位绑定码 — 绑定网页/小程序账号\n"
    "📌 飞书用户请在本机器人的「私聊」会话使用，群聊不会推送新帖\n"
    "/help — 帮助"
)

WELCOME_TEXT = (
    "👋 欢迎使用大V订阅机器人！\n\n"
    "✅ 当前聊天已自动绑定为你的推送渠道，订阅大V后，新帖会直接发到这里。\n\n"
    "接下来只需 3 步：\n"
    "1️⃣ 发 /list 查看可订阅的大V\n"
    "2️⃣ 发 /sub 大VID 订阅，例如 /sub 1\n"
    "3️⃣ 已订阅大V发新帖时，会自动推送到这里\n\n"
    "💡 想和网页/小程序订阅同步？\n"
    "1. 网页「推送设置」点生成绑定码\n"
    "2. 把 /bind 6位码 发给我，账号即合并，一处订阅处处同步\n\n"
    "📌 飞书用户：请在本机器人的「私聊」会话里使用，群聊不会推送新帖"
)

BIND_CODE_TTL = 600
LIST_PAGE_SIZE = 20
SUB_TYPE_LABELS = {"post": "帖子", "reply": "回复", "both": "帖子+回复"}
PLATFORM_LABELS = {"xueqiu": "雪球", "combination": "雪球组合", "weibo": "微博", "twitter": "X"}


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

        if cmd == "/start":
            self.send(reply_type or identity_type, reply_id or identity, WELCOME_TEXT, kind="start")
        elif cmd == "/help":
            self.send(reply_type or identity_type, reply_id or identity, HELP_TEXT)
        elif cmd == "/list":
            text, page, pages = self.list_payload(user, arg)
            self.send(
                reply_type or identity_type,
                reply_id or identity,
                text,
                kind="list",
                page=page,
                pages=pages,
            )
        elif cmd == "/sub":
            self._sub(user, reply_type or identity_type, reply_id or identity, arg)
        elif cmd == "/unsub":
            self._unsub(user, reply_type or identity_type, reply_id or identity, arg)
        elif cmd == "/mysubs":
            self._mysubs(user, reply_type or identity_type, reply_id or identity)
        elif cmd == "/ask":
            self._ask(user, reply_type or identity_type, reply_id or identity, arg)
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

    def list_payload(self, user: dict, arg: str = "") -> tuple[str, int, int]:
        """构造 /list 文案与分页信息，供文本/键盘/卡片复用。"""
        kols = self.db.list_kols()
        if not user.get("is_admin"):
            visible = self.db.visible_kol_ids(user["id"])
            kols = [k for k in kols if k["id"] in visible]
        subscribed = self.db.subscribed_kol_ids(user["id"])
        page = int(arg.strip()) if arg.strip().isdigit() else 1
        total = len(kols)
        pages = max(1, ceil(total / LIST_PAGE_SIZE))
        page = min(max(1, page), pages)
        start = (page - 1) * LIST_PAGE_SIZE
        page_kols = kols[start : start + LIST_PAGE_SIZE]
        lines = ["📋 可订阅的大V："]
        lines.extend(
            f"{'✅' if k['id'] in subscribed else '⬜'} {k['id']}. {k['name']}"
            f"（{PLATFORM_LABELS.get(k['platform'], k['platform'])}）"
            f"{'🔥' if k.get('priority') else ''}"
            for k in page_kols
        )
        if any(k.get("priority") for k in page_kols):
            lines.append("（🔥 优先大V，抓取更及时）")
        if pages > 1:
            lines.append(f"第 {page}/{pages} 页，共 {total} 个（发 /list {page + 1} 看下一页）")
        return ("\n".join(lines) if page_kols else "暂无大V", page, pages)

    def _sub(self, user, identity_type: str, identity: str, arg: str) -> None:
        parts = arg.split(None, 1)
        ref = parts[0].strip() if parts else ""
        sub_type = parts[1].strip().lower() if len(parts) > 1 else "post"
        if sub_type not in ("post", "reply", "both"):
            self.send(identity_type, identity, "订阅类型需为 post / reply / both，例如 /sub 1 both")
            return
        kol = self._resolve_kol(user, ref)
        if kol is None:
            self.send(identity_type, identity, "没找到该大V，试试 /list 查看 ID")
        else:
            self.db.add_subscription(user["id"], kol["id"], type=sub_type)
            label = SUB_TYPE_LABELS.get(sub_type, "帖子")
            self.send(identity_type, identity, f"已订阅 {kol['name']}（{label}）✅")

    def _unsub(self, user, identity_type: str, identity: str, arg: str) -> None:
        kol = self._resolve_kol(user, arg)
        if kol is None:
            self.send(identity_type, identity, "没找到该大V，试试 /mysubs 查看已订阅")
        else:
            self.db.remove_subscription(user["id"], kol["id"])
            self.send(identity_type, identity, f"已取消订阅 {kol['name']}")

    def _ask(self, user, identity_type: str, identity: str, arg: str) -> None:
        arg = arg.strip()
        if not arg:
            self.send(identity_type, identity, "用法：/ask 大V主页链接或UID\n管理员审批通过后即可在 /list 中订阅")
            return
        platform, external_id = "xueqiu", arg
        xueqiu_match = re.search(r"xueqiu\.com/(?:u/)?(\d+)", arg)
        combination_match = re.search(r"xueqiu\.com/P/(ZH\d+)|(?:^|\s)(ZH\d+)", arg)
        weibo_match = re.search(r"weibo\.com/u/(\d+)", arg)
        if xueqiu_match:
            platform, external_id = "xueqiu", xueqiu_match.group(1)
        elif combination_match:
            platform, external_id = "combination", (combination_match.group(1) or combination_match.group(2))
        elif weibo_match:
            platform, external_id = "weibo", weibo_match.group(1)
        elif not arg.isdigit():
            self.send(identity_type, identity, "未识别到有效链接，请发大V主页链接或UID")
            return
        try:
            self.db.add_kol_request(platform, external_id, user["id"])
        except ValueError as exc:
            self.send(identity_type, identity, str(exc))
            return
        self.send(identity_type, identity, "已提交申请 ✅ 管理员审批通过后即可在 /list 中订阅")

    def _mysubs(self, user, identity_type: str, identity: str) -> None:
        self.send(identity_type, identity, self.mysubs_payload(user))

    def mysubs_payload(self, user: dict) -> str:
        subs = self.db.list_subscriptions(user["id"])
        if subs:
            lines = ["📌 我的订阅："]
            lines.extend(
                f"{s['id']}. {s['name']}（{SUB_TYPE_LABELS.get(s.get('subscribe_type') or 'post', '帖子')}）"
                for s in subs
            )
            return "\n".join(lines)
        return "还没有订阅任何大V，试试 /list"

    def _resolve_kol(self, user: dict, arg: str):
        arg = arg.strip()
        if not arg:
            return None
        if "xueqiu.com" in arg:
            match = re.search(r"xueqiu\.com/(?:u/)?(\d+)", arg)
            combo = re.search(r"xueqiu\.com/P/(ZH\d+)", arg)
            if combo:
                symbol = combo.group(1)
                for kol in self.db.list_kols():
                    if kol["platform"] == "combination" and kol["external_id"] == symbol:
                        return kol if self._visible_to(user, kol["id"]) else None
                return None
            if match:
                uid = match.group(1)
                for kol in self.db.list_kols():
                    if kol["platform"] == "xueqiu" and kol["external_id"] == uid:
                        return kol if self._visible_to(user, kol["id"]) else None
                return None
        if re.fullmatch(r"ZH\d+", arg):
            for kol in self.db.list_kols():
                if kol["platform"] == "combination" and kol["external_id"] == arg:
                    return kol if self._visible_to(user, kol["id"]) else None
            return None
        weibo_match = re.search(r"weibo\.com/u/(\d+)", arg)
        if weibo_match:
            uid = weibo_match.group(1)
            for kol in self.db.list_kols():
                if kol["platform"] == "weibo" and kol["external_id"] == uid:
                    return kol if self._visible_to(user, kol["id"]) else None
            return None
        if arg.isdigit():
            kol = self.db.get_kol(int(arg))
            if kol and self._visible_to(user, kol["id"]):
                return kol
        for kol in self.db.list_kols():
            if kol["platform"] == "xueqiu" and kol["external_id"] == arg:
                return kol if self._visible_to(user, kol["id"]) else None
        return None

    def _visible_to(self, user: dict, kol_id: int) -> bool:
        return bool(user.get("is_admin")) or kol_id in self.db.visible_kol_ids(user["id"])
