"""诊断飞书个人机器人 230101：分别试文本 / 卡片，定位失败范围。"""
import httpx

from app.config import load_config
from app.db import DB
from app.fetchers.base import Post
from app.notifiers.feishu import FeishuNotifier

cfg = load_config("/app/config.yaml")
db = DB(cfg.db_path)

USER_ID = 3
user = db.get_user(USER_ID)
bot = db.get_feishu_personal_bot(USER_ID)
print(f"个人机器人: status={bot['status']} app={bot['app_id']} chat={bot['chat_id']} open={bot['open_id']}")
print(f"last_error: {bot['last_error']!r}")

from app.feishu_personal import decrypt_secret

app_secret = decrypt_secret(cfg.notifiers.feishu.credential_key, bot["app_secret_ciphertext"])
client = httpx.Client(timeout=20)
notifier = FeishuNotifier(
    cfg.notifiers.feishu,
    client=client,
    chat_id=bot["chat_id"],
    app_id=bot["app_id"],
    app_secret=app_secret,
)

# 1) 纯文本
try:
    notifier.send_text("🧪 诊断：个人通道文本消息")
    print("send_text: OK ✅")
except Exception as exc:
    print(f"send_text: FAIL ❌ {exc}")

# 2) 卡片（新帖卡片）
post = Post(
    platform="xueqiu", kol_id=9, kol_name="药神", external_id="404305971",
    title="", content="路径\naio商品化产物\nCoding／Agent\n数字劳动力与知识工作自动化\nAI4S",
    url="https://xueqiu.com/2292705444/404305971", published_at="2026-08-09 17:59",
    post_type="post",
)
try:
    notifier.notify(post)
    print("notify(卡片): OK ✅")
except Exception as exc:
    print(f"notify(卡片): FAIL ❌ {exc}")

# 3) 用 open_id 试（如果 chat_id 有问题）
try:
    notifier2 = FeishuNotifier(
        cfg.notifiers.feishu, client=httpx.Client(timeout=20),
        open_id=bot["open_id"], app_id=bot["app_id"], app_secret=app_secret,
    )
    notifier2.send_text("🧪 诊断：open_id 文本消息")
    print("open_id send_text: OK ✅")
except Exception as exc:
    print(f"open_id send_text: FAIL ❌ {exc}")
finally:
    client.close()
