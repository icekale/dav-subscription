import tempfile
import time
from pathlib import Path

from app.db import DB
from app.feishu_bot import FeishuBot


def make_bot():
    db = DB(Path(tempfile.mkdtemp()) / "fs.db")
    db.add_kol("xueqiu", "大V", "1")
    bot = FeishuBot(db, "app", "secret")
    sent = []
    bot._send = lambda identity_type, identity, text: sent.append((identity_type, identity, text))
    return db, bot, sent


def test_feishu_p2p_commands():
    db, bot, sent = make_bot()
    bot.handle_message("oc_p2p", "p2p", "ou_1", "Kale", "/list")
    assert sent[-1][0] == "feishu_chat_id" and sent[-1][1] == "oc_p2p"
    assert "大V" in sent[-1][2]

    user = db.get_user_by_feishu("ou_1")
    assert user is not None
    assert user["feishu_chat_id"] == "oc_p2p"
    bot.handle_message("oc_p2p", "p2p", "ou_1", "Kale", "/sub 1")
    assert db.subscribed_kol_ids(user["id"]) == {1}
    bot.handle_message("oc_p2p", "p2p", "ou_1", "Kale", "/mysubs")
    assert "大V" in sent[-1][2]


def test_list_pagination():
    db, bot, sent = make_bot()
    for i in range(21):
        db.add_kol("xueqiu", f"大V{i}", str(i))
    bot.handle_message("oc_p2p", "p2p", "ou_1", "Kale", "/list")
    assert "第 1/2 页" in sent[-1][2]
    bot.handle_message("oc_p2p", "p2p", "ou_1", "Kale", "/list 2")
    assert "第 2/2 页" in sent[-1][2]


def test_feishu_group_replies_to_chat():
    db, bot, sent = make_bot()
    bot.handle_message("oc_grp", "group", "ou_2", "Kale", "/list")
    assert sent[-1][0] == "feishu_chat_id" and sent[-1][1] == "oc_grp"
    assert db.get_user_by_feishu("ou_2") is not None


def test_feishu_bind():
    db, bot, sent = make_bot()
    target = db.add_user("webuser", "hash")
    db.create_bind_code("111222", target, int(time.time()) + 600)
    bot.handle_message("", "p2p", "ou_9", "Kale", "/bind 111222")
    assert "已绑定" in sent[-1][2]
    assert db.get_user(target)["feishu_open_id"] == "ou_9"
