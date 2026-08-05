from app.bot_core import SubscriptionBot
from app.db import DB


def make_bot():
    db = DB(":memory:")
    sent = []

    def send(identity_type, identity, text, **kwargs):
        sent.append(text)

    def get_or_create_user(identity_type, identity, display_name):
        if identity_type == "telegram_chat_id":
            user = db.get_user_by_telegram(identity)
        else:
            user = db.get_user_by_feishu(identity)
        if user is None:
            uid = db.add_user(display_name, "hash")
            db.update_user(uid, telegram_chat_id=identity)
            user = db.get_user(uid)
        return user

    return db, SubscriptionBot(db, send, get_or_create_user), sent


def test_ask_creates_request_and_list_filters_private():
    db, bot, sent = make_bot()
    public_id = db.add_kol("xueqiu", "公开", "1")
    private_id = db.add_kol("xueqiu", "私有", "2")
    db.update_kol(private_id, is_private=True)
    db.set_kol_acl(private_id, [])

    # 普通用户 /list 只看到公开大V
    bot.handle("telegram_chat_id", "111", "u1", "/list")
    list_text = sent[-1]
    assert f"{public_id}. 公开" in list_text
    assert f"{private_id}. 私有" not in list_text

    # 普通用户 /ask 提交申请
    bot.handle("telegram_chat_id", "111", "u1", "/ask https://xueqiu.com/u/77777")
    assert "已提交申请" in sent[-1]
    requests = db.list_kol_requests(status="pending")
    assert len(requests) == 1
    assert requests[0]["platform"] == "xueqiu" and requests[0]["external_id"] == "77777"
    assert requests[0]["user_id"] == 1  # u1 是第一个自动创建的用户

    # 重复 /ask 被拦截
    bot.handle("telegram_chat_id", "111", "u1", "/ask https://xueqiu.com/u/77777")
    assert "处理中" in sent[-1]

    # 普通用户无法订阅不可见的私有大V
    bot.handle("telegram_chat_id", "111", "u1", f"/sub {private_id}")
    assert "没找到该大V" in sent[-1]

    # 白名单用户（第二个账号，昵称 admin）可见并可订阅
    bot.handle("telegram_chat_id", "999", "admin", "/list")
    admin_id = db.get_user_by_username("admin")["id"]
    db.set_kol_acl(private_id, [admin_id])
    bot.handle("telegram_chat_id", "999", "admin", f"/sub {private_id}")
    assert "已订阅 私有" in sent[-1]


def test_pasted_bind_code_auto_merges():
    db, bot, sent = make_bot()
    target_id = db.add_user("web_user", "hash")
    db.create_bind_code("654321", target_id, 9999999999)
    # 机器人账号已存在（TG 发过命令自动创建）
    bot.handle("telegram_chat_id", "111", "u1", "/list")
    bot_account = db.get_user_by_telegram("111")

    # 直接粘贴 6 位绑定码（无 /bind 前缀）自动绑定
    bot.handle("telegram_chat_id", "111", "u1", "654321")
    assert "已绑定到账号 web_user" in sent[-1]
    target = db.get_user(target_id)
    assert target["telegram_chat_id"] == "111"
    assert db.get_user(bot_account["id"]) is None  # 独立账号已合并删除


def test_telegram_deeplink_start_bind():
    db, bot, sent = make_bot()
    target_id = db.add_user("web_user", "hash")
    db.create_bind_code("111222", target_id, 9999999999)
    bot.handle("telegram_chat_id", "222", "u2", "/list")
    bot_account = db.get_user_by_telegram("222")

    # 深链触发：Telegram 自动发送 /start bind_码
    bot.handle("telegram_chat_id", "222", "u2", "/start bind_111222")
    assert "已绑定到账号 web_user" in sent[-1]
    assert db.get_user(target_id)["telegram_chat_id"] == "222"
    assert db.get_user(bot_account["id"]) is None
