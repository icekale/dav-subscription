import tempfile
import time
import json
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


def update(chat_id, text):
    return {
        "message": {
            "chat": {"id": chat_id},
            "from": {"username": "icekale"},
            "text": text,
        }
    }


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
    db, bot, kid, sent = make_env()
    bot.handle_update(update(222, "/sub 8790885129"))
    user = db.get_user_by_telegram("222")
    assert db.subscribed_kol_ids(user["id"]) == {kid}


def test_bot_sub_resolve_by_homepage_link():
    for link in ("https://xueqiu.com/8790885129", "https://xueqiu.com/u/8790885129"):
        db, bot, kid, sent = make_env()
        bot.handle_update(update(999, f"/sub {link}"))
        user = db.get_user_by_telegram("999")
        assert db.subscribed_kol_ids(user["id"]) == {kid}, link


def test_bot_sub_ignores_nickname():
    db, bot, _, sent = make_env()
    bot.handle_update(update(555, "/sub 超级鹿鼎公"))
    assert "没找到" in sent[-1][1]


def test_bot_unknown_sub():
    db, bot, _, sent = make_env()
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
