import tempfile
from pathlib import Path

from app.db import DB
from app.telegram_bot import TelegramBot


def make_env():
    db = DB(Path(tempfile.mkdtemp()) / "bot.db")
    kid = db.add_kol("xueqiu", "超级鹿鼎公", "8790885129")
    bot = TelegramBot(db, "test_token", "secret")
    sent = []
    bot._send = lambda chat_id, text: sent.append((chat_id, text))
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
    assert "帮助" in sent[-1][1]
    # 首次命令自动建号并绑定 chat_id
    user = db.get_user_by_telegram("111")
    assert user is not None and user["username"] == "icekale"

    bot.handle_update(update(111, "/list"))
    assert "超级鹿鼎公" in sent[-1][1]
    assert "⬜" in sent[-1][1]

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
