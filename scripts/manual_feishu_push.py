"""手动推送验证：使用数据库完整帖文内容（235 字 + 标签），走完整 deliver_post 管线。"""
import httpx

from app.channels import deliver_post
from app.config import load_config
from app.db import DB
from app.fetchers.base import Post

cfg = load_config("/app/config.yaml")
db = DB(cfg.db_path)

USER_ID = 3

user = db.get_user(USER_ID)
bot = db.get_feishu_personal_bot(USER_ID)
print(f"个人机器人: {bot['status']} chat={bot['chat_id'][:16]}")
assert bot and bot["status"] == "active"

# 完整帖文（与生产库 posts.id=2201126 一致：235 字全文 + 标签）
post = Post(
    platform="xueqiu",
    kol_id=9,
    kol_name="药神",
    external_id="404305971",
    title="",
    content=(
        "路径                                ai商品化产物\n"
        "Coding／Agent        数字劳动力与知识工作自动化\n"
        "AI4S             科研效率、知识产权与新产品发现能力\n"
        "Physical AI   物理劳动力、机器自主性与工业自动化\n"
        "Coding与Agent阶段，硬件是商业化最好的表达。\n"
        "AI4S阶段，AI偏赋能，下游行业与ai平台转化是商业化表达。\n"
        "Physical AI阶段，硬件内部切换从云上运算演变成终端硬件。"
    ),
    url="https://xueqiu.com/2292705444/404305971",
    published_at="2026-08-09 17:59",
    post_type="post",
    tags=["科技"],
)

post_id = db.get_post_id(post.platform, post.external_id)
client = httpx.Client(timeout=20)
try:
    deliver_post(db, post_id, post, user, "feishu", cfg.notifiers, client,
                 retry_queue=None, alert_notifiers=[], alert_cb=lambda *a: None)
    print("deliver_post 完成")
finally:
    client.close()

logs = db.list_push_logs(user_id=USER_ID, channel="feishu")
print("最近推送日志:", [(r["status"], r["created_at"]) for r in logs[:2]])
print("个人机器人状态:", db.get_feishu_personal_bot(USER_ID)["status"])
