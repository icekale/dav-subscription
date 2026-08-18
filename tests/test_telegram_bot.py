import json
import tempfile
import time
from pathlib import Path

from app.db import DB
from app.telegram_bot import TelegramBot


def make_env():
    db = DB(Path(tempfile.mkdtemp()) / "bot.db")
    kid = db.add_kol("xueqiu", "超级鹿鼎公", "8790885129")
    bot = TelegramBot(db, "test_token", "secret")
    sent = []
    bot._send = lambda chat_id, text, **kw: sent.append((chat_id, text, kw))
    return db, bot, kid, sent


def update(chat_id, text, *, chat_type="private", sender_id=None):
    return {
        "message": {
            "chat": {"id": chat_id, "type": chat_type},
            "from": {"id": sender_id or chat_id, "username": "icekale"},
            "text": text,
        }
    }


def test_bot_ignores_group_commands():
    db, bot, _, sent = make_env()
    bot.handle_update(update(-1001, "/start", chat_type="group", sender_id=999))
    assert sent == []
    assert db.get_user_by_telegram("-1001") is None


def test_bot_group_callback_cannot_use_bound_admin_identity():
    db = DB(Path(tempfile.mkdtemp()) / "bot.db")
    admin_id = db.add_user("admin01", "hash", is_admin=True, telegram_chat_id="-1001")
    requester_id = db.add_user("requester", "hash")
    cid = db.add_category("宏观")
    request_id = db.add_kol_request("xueqiu", "123", requester_id, "待审批", category_id=cid)
    bot = TelegramBot(db, "test_token", "secret")
    calls = []
    bot._call = lambda method, **params: calls.append((method, params))

    bot.handle_update({
        "callback_query": {
            "id": "cq-group",
            "from": {"id": 999, "username": "attacker"},
            "data": f"approve:{request_id}",
            "message": {
                "chat": {"id": -1001, "type": "group"},
                "message_id": 9,
            },
        }
    })

    assert db.get_kol_by_external("xueqiu", "123") is None
    assert db.get_user(admin_id)["is_admin"] == 1


def test_bot_command_flow():
    db, bot, kid, sent = make_env()

    bot.handle_update(update(111, "/start"))
    assert "欢迎" in sent[-1][1]
    # 首次命令自动建号并绑定 chat_id
    user = db.get_user_by_telegram("111")
    assert user is not None and user["username"] == "icekale"

    bot.handle_update(update(111, "/list"))
    assert "超级鹿鼎公" in sent[-1][1]
    assert "⬜" in sent[-1][1]
    assert sent[-1][2].get("kind") == "list"

    bot.handle_update(update(111, f"/sub {kid}"))
    assert db.subscribed_kol_ids(user["id"]) == {kid}
    bot.handle_update(update(111, "/list"))
    assert "✅" in sent[-1][1]

    bot.handle_update(update(111, "/mysubs"))
    assert "超级鹿鼎公" in sent[-1][1]

    # 按雪球 UID 取消
    bot.handle_update(update(111, "/unsub 8790885129"))
    assert db.subscribed_kol_ids(user["id"]) == set()

    bot.handle_update(update(111, "/unknown"))
    assert "未知命令" in sent[-1][1]


def test_bot_list_marks_priority_kol():
    db = DB(Path(tempfile.mkdtemp()) / "bot.db")
    db.add_kol("xueqiu", "普通大V", "1")
    db.add_kol("xueqiu", "重点大V", "2", priority=True)
    bot = TelegramBot(db, "test_token", "secret")
    sent = []
    bot._send = lambda chat_id, text, **kw: sent.append((chat_id, text, kw))
    bot.handle_update(update(777, "/list"))
    assert "🔥" in sent[-1][1]
    assert "优先大V" in sent[-1][1]


def test_bot_sub_resolve_by_external_id():
    db, bot, kid, _ = make_env()
    bot.handle_update(update(222, "/sub 8790885129"))
    user = db.get_user_by_telegram("222")
    assert db.subscribed_kol_ids(user["id"]) == {kid}


def test_bot_sub_resolve_by_homepage_link():
    for link in ("https://xueqiu.com/8790885129", "https://xueqiu.com/u/8790885129"):
        db, bot, kid, _ = make_env()
        bot.handle_update(update(999, f"/sub {link}"))
        user = db.get_user_by_telegram("999")
        assert db.subscribed_kol_ids(user["id"]) == {kid}, link


def test_bot_sub_ignores_nickname():
    _, bot, _, sent = make_env()
    bot.handle_update(update(555, "/sub 超级鹿鼎公"))
    assert "没找到" in sent[-1][1]


def test_bot_unknown_sub():
    _, bot, _, sent = make_env()
    bot.handle_update(update(333, "/sub 不存在的大V"))
    assert "没找到" in sent[-1][1]


def test_bot_bind_merges_subscriptions():
    db = DB(Path(tempfile.mkdtemp()) / "bot.db")
    kid = db.add_kol("xueqiu", "大V", "1")
    target_id = db.add_user("kale", "hash")
    bot = TelegramBot(db, "t", "s")
    sent = []
    bot._send = lambda chat_id, text, **kw: sent.append((chat_id, text, kw))

    # bot 用户先订阅大V
    bot.handle_update(update(111, f"/sub {kid}"))
    bot_user = db.get_user_by_telegram("111")
    assert bot_user is not None
    assert db.subscribed_kol_ids(bot_user["id"]) == {kid}

    # 生成绑定码后 /bind，订阅合并到网页账号，自动账号删除
    db.create_bind_code("654321", target_id, int(time.time()) + 600)
    bot.handle_update(update(111, "/bind 654321"))
    assert "已绑定" in sent[-1][1]
    assert db.subscribed_kol_ids(target_id) == {kid}
    assert db.get_user_by_telegram("111")["id"] == target_id
    assert db.get_user(target_id)["telegram_chat_id"] == "111"


def test_bot_bind_invalid_code():
    db = DB(Path(tempfile.mkdtemp()) / "bot.db")
    bot = TelegramBot(db, "t", "s")
    sent = []
    bot._send = lambda chat_id, text, **kw: sent.append((chat_id, text, kw))
    bot.handle_update(update(222, "/bind 000000"))
    assert "无效" in sent[-1][1]


def test_bot_list_keyboard_and_callback():
    db = DB(Path(tempfile.mkdtemp()) / "bot.db")
    db.add_kol("xueqiu", "超级鹿鼎公", "8790885129")
    bot = TelegramBot(db, "test_token", "secret")
    calls = []
    bot._call = lambda method, **params: calls.append((method, params))
    bot.handle_update(update(111, "/list"))
    method, params = calls[-1]
    assert method == "sendMessage"
    kb = json.loads(params["reply_markup"])
    assert kb["inline_keyboard"][0][0]["text"] == "📋 我的订阅"

    # 模拟点击「我的订阅」回调：应答 + 编辑原消息
    bot.handle_update(
        {
            "callback_query": {
                "id": "cq1",
                "from": {"username": "icekale"},
                "data": "mysubs",
                "message": {"chat": {"id": 111}, "message_id": 9},
            }
        }
    )
    methods = [c[0] for c in calls]
    assert "answerCallbackQuery" in methods
    edit_call = calls[-1]
    assert edit_call[0] == "editMessageText"
    assert edit_call[1]["message_id"] == 9


def test_bot_list_next_page():
    db = DB(Path(tempfile.mkdtemp()) / "bot.db")
    for i in range(2, 23):
        db.add_kol("xueqiu", f"大V{i}", str(i))
    bot = TelegramBot(db, "test_token", "secret")
    calls = []
    bot._call = lambda method, **params: calls.append((method, params))
    bot.handle_update(update(111, "/list"))
    send_call = calls[-1]
    kb = json.loads(send_call[1]["reply_markup"])
    next_data = kb["inline_keyboard"][0][1]["callback_data"]
    assert next_data.startswith("list:next:")

    # 点击「下一页」应翻到第 2 页
    bot.handle_update(
        {
            "callback_query": {
                "id": "cq2",
                "from": {"username": "icekale"},
                "data": next_data,
                "message": {"chat": {"id": 111}, "message_id": 9},
            }
        }
    )
    edit_call = calls[-1]
    assert edit_call[0] == "editMessageText"
    assert "第 2/2 页" in edit_call[1]["text"]


def test_bot_search_keyboard_and_sub_button():
    db = DB(Path(tempfile.mkdtemp()) / "bot.db")
    kid = db.add_kol("xueqiu", "茅台一哥", "111")
    bot = TelegramBot(db, "test_token", "secret")
    calls = []
    bot._call = lambda method, **params: calls.append((method, params))
    bot.handle_update(update(111, "/search 茅台"))
    method, params = calls[-1]
    assert method == "sendMessage"
    assert "茅台一哥" in params["text"]
    kb = json.loads(params["reply_markup"])
    assert kb["inline_keyboard"][0][0]["callback_data"] == f"sub:{kid}"

    # 点击「➕ 订阅」按钮：订阅并重渲染（按钮变退订）
    bot.handle_update(
        {
            "callback_query": {
                "id": "cq1",
                "from": {"username": "icekale"},
                "data": f"sub:{kid}",
                "message": {"chat": {"id": 111}, "message_id": 9},
            }
        }
    )
    edit_call = calls[-1]
    assert edit_call[0] == "editMessageText"
    kb = json.loads(edit_call[1]["reply_markup"])
    assert kb["inline_keyboard"][0][0]["callback_data"] == f"unsub:{kid}"
    user = db.get_user_by_telegram("111")
    assert db.subscribed_kol_ids(user["id"]) == {kid}


def test_bot_mysubs_type_cycle_and_unsub_buttons():
    db = DB(Path(tempfile.mkdtemp()) / "bot.db")
    kid = db.add_kol("xueqiu", "茅台一哥", "111")
    bot = TelegramBot(db, "test_token", "secret")
    calls = []
    bot._call = lambda method, **params: calls.append((method, params))
    bot.handle_update(update(111, "/sub 111"))
    bot.handle_update(update(111, "/mysubs"))
    method, params = calls[-1]
    assert method == "sendMessage"
    kb = json.loads(params["reply_markup"])
    # 订阅条目：改类型 + 退订两个按钮
    assert kb["inline_keyboard"][0][0]["callback_data"] == f"mysubs:type:{kid}"
    assert kb["inline_keyboard"][0][1]["callback_data"] == f"mysubs:unsub:{kid}"

    # 点击「📮 帖子」→ 类型切到 reply，重渲染后按钮文案变化
    bot.handle_update(
        {
            "callback_query": {
                "id": "cq2",
                "from": {"username": "icekale"},
                "data": f"mysubs:type:{kid}",
                "message": {"chat": {"id": 111}, "message_id": 9},
            }
        }
    )
    edit_call = calls[-1]
    assert edit_call[0] == "editMessageText"
    user = db.get_user_by_telegram("111")
    subs = db.list_subscriptions(user["id"])
    assert subs[0]["subscribe_type"] == "reply"

    # 点击「退订」→ 订阅被删除，重渲染后按钮只剩「查看大V」
    bot.handle_update(
        {
            "callback_query": {
                "id": "cq3",
                "from": {"username": "icekale"},
                "data": f"mysubs:unsub:{kid}",
                "message": {"chat": {"id": 111}, "message_id": 9},
            }
        }
    )
    edit_call = calls[-1]
    assert db.subscribed_kol_ids(user["id"]) == set()
    kb = json.loads(edit_call[1]["reply_markup"])
    assert kb["inline_keyboard"][0][0]["callback_data"] == "list:1"


def test_bot_sub_private_kol_denied_without_acl():
    """私有大V且不在 ACL：sub: 回调拒绝订阅并提示不可见。"""
    db = DB(Path(tempfile.mkdtemp()) / "bot.db")
    kid = db.add_kol("xueqiu", "私有大V", "222")
    db.update_kol(kid, is_private=True)
    bot = TelegramBot(db, "test_token", "secret")
    calls = []
    bot._call = lambda method, **params: calls.append((method, params))
    bot.handle_update(update(111, "/search 私有"))
    bot.handle_update(
        {
            "callback_query": {
                "id": "cq2",
                "from": {"username": "icekale"},
                "data": f"sub:{kid}",
                "message": {"chat": {"id": 111}, "message_id": 9},
            }
        }
    )
    edit_call = calls[-1]
    assert edit_call[0] == "editMessageText"
    assert "无权订阅" in edit_call[1]["text"]
    user = db.get_user_by_telegram("111")
    assert db.subscribed_kol_ids(user["id"]) == set()


def test_bot_sub_private_kol_allowed_with_acl():
    """私有大V但在 ACL：sub: 回调正常订阅。"""
    db = DB(Path(tempfile.mkdtemp()) / "bot.db")
    kid = db.add_kol("xueqiu", "私有大V", "333")
    db.update_kol(kid, is_private=True)
    bot = TelegramBot(db, "test_token", "secret")
    calls = []
    bot._call = lambda method, **params: calls.append((method, params))
    bot.handle_update(update(111, "/search 私有"))
    user = db.get_user_by_telegram("111")
    db.set_kol_acl(kid, [user["id"]])
    bot.handle_update(
        {
            "callback_query": {
                "id": "cq3",
                "from": {"username": "icekale"},
                "data": f"sub:{kid}",
                "message": {"chat": {"id": 111}, "message_id": 9},
            }
        }
    )
    assert db.subscribed_kol_ids(user["id"]) == {kid}


def _callback_update(chat_id, message_id, data, text="通知正文", keyboard=None):
    msg = {
        "chat": {"id": chat_id, "type": "private"},
        "message_id": message_id,
        "text": text,
    }
    if keyboard:
        msg["reply_markup"] = {"inline_keyboard": keyboard}
    return {
        "callback_query": {
            "id": f"cq-{message_id}",
            "from": {"id": chat_id, "username": "icekale"},
            "data": data,
            "message": msg,
        }
    }


def _edit_calls(calls):
    return [p for m, p in calls if m == "editMessageText"]


def test_bot_unsub_callback_with_undo():
    db, bot, kid, _ = make_env()
    user_id = db.add_user("u1", "hash", telegram_chat_id="111")
    db.add_subscription(user_id, kid, "both")
    db.set_subscription_favorite(user_id, kid, True)
    calls = []
    bot._call = lambda method, **params: calls.append((method, params))
    orig_kb = [
        [{"text": "🔗 查看原文", "url": "https://example.com/1"}],
        [
            {"text": "🔕 设为次要", "callback_data": f"sec:{kid}"},
            {"text": "退订", "callback_data": f"unsub:{kid}"},
        ],
    ]

    bot.handle_update(_callback_update(111, 1, f"unsub:{kid}", keyboard=orig_kb))
    assert db.get_subscription(user_id, kid) is None
    # 编辑消息保留正文，按钮换成撤销
    edit = _edit_calls(calls)[-1]
    assert edit["text"] == "通知正文"
    kb = json.loads(edit["reply_markup"])["inline_keyboard"]
    undo_data = kb[0][0]["callback_data"]
    assert undo_data == f"unsubundo:{kid}"

    # 撤销：真实场景下回调消息带的是撤销按钮键盘，必须用快照还原原始键盘
    bot.handle_update(_callback_update(111, 1, undo_data, text="通知正文", keyboard=kb))
    sub = db.get_subscription(user_id, kid)
    assert sub is not None
    assert sub["type"] == "both" and bool(sub["favorite"]) and not bool(sub["secondary"])
    restore = _edit_calls(calls)[-1]
    assert restore["text"] == "通知正文"
    restored_kb = json.loads(restore["reply_markup"])["inline_keyboard"]
    # 原始键盘：查看原文 + [设次要, 退订]
    assert restored_kb[0][0]["url"] == "https://example.com/1"
    assert any(b.get("callback_data") == f"sec:{kid}" for row in restored_kb for b in row)
    assert any(b.get("callback_data") == f"unsub:{kid}" for row in restored_kb for b in row)


def test_bot_sec_callback_toggle_and_undo():
    db, bot, kid, _ = make_env()
    user_id = db.add_user("u1", "hash", telegram_chat_id="111")
    db.add_subscription(user_id, kid)
    calls = []
    bot._call = lambda method, **params: calls.append((method, params))
    orig_kb = [
        [{"text": "🔗 查看原文", "url": "https://example.com/1"}],
        [
            {"text": "🔕 设为次要", "callback_data": f"sec:{kid}"},
            {"text": "退订", "callback_data": f"unsub:{kid}"},
        ],
    ]

    bot.handle_update(_callback_update(111, 2, f"sec:{kid}", keyboard=orig_kb))
    assert bool(db.get_subscription(user_id, kid)["secondary"])
    edit = _edit_calls(calls)[-1]
    assert "合并推送" in edit["text"]
    undo_data = json.loads(edit["reply_markup"])["inline_keyboard"][0][0]["callback_data"]
    assert undo_data == f"secundo:{kid}"

    bot.handle_update(_callback_update(111, 2, undo_data, text=edit["text"], keyboard=json.loads(edit["reply_markup"])["inline_keyboard"]))
    assert not bool(db.get_subscription(user_id, kid)["secondary"])
    # 还原编辑使用原始键盘
    restore = _edit_calls(calls)[-1]
    restored_kb = json.loads(restore["reply_markup"])["inline_keyboard"]
    assert any(b.get("callback_data") == f"sec:{kid}" for row in restored_kb for b in row)


def test_bot_sec_callback_requires_subscription():
    db, bot, kid, _ = make_env()
    db.add_user("u1", "hash", telegram_chat_id="111")
    calls = []
    bot._call = lambda method, **params: calls.append((method, params))

    bot.handle_update(_callback_update(111, 3, f"sec:{kid}"))
    assert "无法设置次要" in _edit_calls(calls)[-1]["text"]


def test_bot_unsub_undo_expired():
    db, bot, kid, _ = make_env()
    user_id = db.add_user("u1", "hash", telegram_chat_id="111")
    db.add_subscription(user_id, kid)
    calls = []
    bot._call = lambda method, **params: calls.append((method, params))
    orig_kb = [[{"text": "退订", "callback_data": f"unsub:{kid}"}]]

    bot.handle_update(_callback_update(111, 4, f"unsub:{kid}", keyboard=orig_kb))
    assert db.get_subscription(user_id, kid) is None
    # 回拨时间戳模拟超时
    key = "111:4"
    ts, payload = bot._undo_windows[key]
    bot._undo_windows[key] = (ts - 31, payload)

    bot.handle_update(_callback_update(111, 4, f"unsubundo:{kid}"))
    assert db.get_subscription(user_id, kid) is None
    assert "撤销超时" in _edit_calls(calls)[-1]["text"]


def test_bot_unsub_no_undo_when_not_subscribed():
    db, bot, kid, _ = make_env()
    db.add_user("u1", "hash", telegram_chat_id="111")
    calls = []
    bot._call = lambda method, **params: calls.append((method, params))

    bot.handle_update(_callback_update(111, 5, f"unsub:{kid}"))
    edit = _edit_calls(calls)[-1]
    assert "已取消订阅" in edit["text"]
    assert "撤销" not in edit["text"]
