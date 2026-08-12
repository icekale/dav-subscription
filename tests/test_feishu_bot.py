import json
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
    bot._send_card = lambda chat_id, card: sent.append(("card", chat_id, card))
    return db, bot, sent


def test_feishu_p2p_commands():
    db, bot, sent = make_bot()
    bot.handle_message("oc_p2p", "p2p", "ou_1", "Kale", "/list")
    assert sent[-1][0] == "card" and sent[-1][1] == "oc_p2p"
    assert "大V" in json.dumps(sent[-1][2], ensure_ascii=False)

    user = db.get_user_by_feishu("ou_1")
    assert user is not None
    assert user["feishu_chat_id"] == "oc_p2p"
    bot.handle_message("oc_p2p", "p2p", "ou_1", "Kale", "/sub 1")
    assert db.subscribed_kol_ids(user["id"]) == {1}
    bot.handle_message("oc_p2p", "p2p", "ou_1", "Kale", "/mysubs")
    assert "大V" in sent[-1][2]


def test_list_pagination():
    db, bot, sent = make_bot()
    for i in range(2, 23):  # make_bot 已有一个 external_id=1 的大V
        db.add_kol("xueqiu", f"大V{i}", str(i))
    bot.handle_message("oc_p2p", "p2p", "ou_1", "Kale", "/list")
    assert "第 1/2 页" in json.dumps(sent[-1][2], ensure_ascii=False)
    bot.handle_message("oc_p2p", "p2p", "ou_1", "Kale", "/list 2")
    assert "第 2/2 页" in json.dumps(sent[-1][2], ensure_ascii=False)


def test_feishu_card_action_subscribe():
    db, bot, _ = make_bot()
    from lark_oapi.event.callback.model.p2_card_action_trigger import (
        P2CardActionTrigger,
    )

    event = P2CardActionTrigger(
        {
            "event": {
                "operator": {"open_id": "ou_9"},
                "action": {"value": {"action": "sub", "kol_id": 1}},
            }
        }
    )
    resp = bot._on_card_action(event)
    assert resp.toast is not None and "已订阅" in resp.toast.content
    user = db.get_user_by_feishu("ou_9")
    assert user is not None and db.subscribed_kol_ids(user["id"]) == {1}

    event2 = P2CardActionTrigger(
        {
            "event": {
                "operator": {"open_id": "ou_9"},
                "action": {"value": {"action": "unsub", "kol_id": 1}},
            }
        }
    )
    resp2 = bot._on_card_action(event2)
    assert resp2.toast is not None and "已取消订阅" in resp2.toast.content
    assert db.subscribed_kol_ids(user["id"]) == set()


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


def test_feishu_card_hides_private_kol_and_denies_sub():
    db, bot, sent = make_bot()
    private_id = db.add_kol("xueqiu", "私有大V", "99")
    db.update_kol(private_id, is_private=True)

    # 新用户打开 /list 卡片，私有大V不应出现在按钮里
    bot.handle_message("oc_p2p", "p2p", "ou_1", "Kale", "/list")
    card_text = json.dumps(sent[-1][2], ensure_ascii=False)
    assert "私有大V" not in card_text
    assert "大V" in card_text  # 公开大V仍在

    # 直接触发私有大V的订阅回调应被拒绝
    from lark_oapi.event.callback.model.p2_card_action_trigger import (
        P2CardActionTrigger,
    )

    event = P2CardActionTrigger(
        {
            "event": {
                "operator": {"open_id": "ou_9"},
                "action": {"value": {"action": "sub", "kol_id": private_id}},
            }
        }
    )
    resp = bot._on_card_action(event)
    assert resp.toast is not None and "无权订阅" in resp.toast.content
    assert db.subscribed_kol_ids(db.get_user_by_feishu("ou_9")["id"]) == set()


def test_feishu_card_action_sec_toggle():
    db, bot, _ = make_bot()
    from lark_oapi.event.callback.model.p2_card_action_trigger import (
        P2CardActionTrigger,
    )

    def fire():
        return bot._on_card_action(
            P2CardActionTrigger(
                {
                    "event": {
                        "operator": {"open_id": "ou_9"},
                        "action": {"value": {"action": "sec", "kol_id": 1}},
                    }
                }
            )
        )

    # 建号但未订阅 → 拒绝
    resp = fire()
    assert resp.toast is not None and "未订阅" in resp.toast.content
    user = db.get_user_by_feishu("ou_9")
    assert user is not None
    db.add_subscription(user["id"], 1)

    resp = fire()
    assert "已设为次要" in resp.toast.content
    assert bool(db.get_subscription(user["id"], 1)["secondary"])

    resp = fire()
    assert "已恢复实时推送" in resp.toast.content
    assert not bool(db.get_subscription(user["id"], 1)["secondary"])
