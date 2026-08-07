"""推送渠道注册表与统一分发骨架。

新增推送渠道只需四步：
1. 在 app/notifiers/ 下实现 notifier 类（继承 Notifier，channel 属性）；
2. 在 CHANNELS 元组里加渠道名；
3. channel_bound / build_channel_notifier 各加一个分支；
4. 前端（Web 推送设置页 + 小程序设置页）的通道选择/状态卡片同步。

分发骨架（成功日志 / 失败日志+重试+告警）由 deliver_post 统一提供，
各调用点（实时推送 / 免打扰汇总 / 管理员通知 / 测试推送 / 失败重试）不再各自复制。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 渠道顺序即推送顺序
CHANNELS = ("telegram", "feishu", "wecom", "bark")
CHANNEL_LABELS = {
    "telegram": "Telegram",
    "feishu": "飞书",
    "wecom": "企业微信",
    "bark": "Bark",
}


def channel_enabled(user: dict, channel: str) -> bool:
    """用户是否选择了用该渠道接收推送（push_channels 为空时默认全部启用）。"""
    selected = user.get("push_channels") or ""
    if not selected:
        return True
    return channel in {c.strip() for c in selected.split(",") if c.strip()}


def channel_bound(user: dict, channel: str, notifiers_config=None) -> bool:
    """用户绑定关系是否成立（未做 push_channels 过滤）。

    telegram 额外要求有可用机器人（全局共享 bot token 或用户自建 token），
    否则有会话也发不出消息。
    """
    if channel == "telegram":
        if not user.get("telegram_chat_id"):
            return False
        global_bot = (
            notifiers_config is not None
            and getattr(notifiers_config, "telegram", None) is not None
            and bool(notifiers_config.telegram.bot_token)
        )
        return bool(user.get("telegram_bot_token") or global_bot)
    if channel == "feishu":
        return bool(user.get("feishu_open_id") or user.get("feishu_chat_id"))
    if channel == "wecom":
        return bool(user.get("wecom_webhook"))
    if channel == "bark":
        return bool(user.get("bark_key"))
    return False


def build_channel_notifier(
    channel: str,
    user: dict,
    notifiers_config,
    client=None,
    *,
    favorite: bool = False,
    keyword: bool = False,
):
    """按渠道与用户绑定信息构造 notifier；未绑定抛 RuntimeError。

    注意：notifier 类用函数内延迟导入，保证测试里
    monkeypatch.setattr("app.notifiers.xxx.Notifier", Fake) 对本模块生效。
    """
    if channel == "telegram":
        from .notifiers.telegram import TelegramNotifier

        if not user.get("telegram_chat_id"):
            raise RuntimeError("用户未绑定 Telegram")
        return TelegramNotifier(
            notifiers_config.telegram,
            client=client,
            chat_id=user["telegram_chat_id"],
            bot_token=user.get("telegram_bot_token") or None,
            favorite=favorite,
            keyword=keyword,
        )
    if channel == "feishu":
        from .notifiers.feishu import FeishuNotifier

        if not (user.get("feishu_open_id") or user.get("feishu_chat_id")):
            raise RuntimeError("用户未绑定飞书")
        return FeishuNotifier(
            notifiers_config.feishu,
            client=client,
            open_id=user["feishu_open_id"] if not user.get("feishu_chat_id") else None,
            chat_id=user.get("feishu_chat_id") or None,
            favorite=favorite,
            keyword=keyword,
        )
    if channel == "wecom":
        from .notifiers.wecom import WeComNotifier

        if not user.get("wecom_webhook"):
            raise RuntimeError("用户未绑定企业微信")
        return WeComNotifier(
            notifiers_config.wecom,
            client=client,
            webhook_url=user["wecom_webhook"],
            favorite=favorite,
            keyword=keyword,
        )
    if channel == "bark":
        from .notifiers.bark import BarkNotifier

        if not user.get("bark_key"):
            raise RuntimeError("用户未绑定 Bark")
        return BarkNotifier(
            getattr(notifiers_config, "bark", None) if notifiers_config is not None else None,
            client=client,
            bark_key=user["bark_key"],
            favorite=favorite,
            keyword=keyword,
        )
    raise RuntimeError(f"未知渠道: {channel}")


def deliver_post(
    db,
    post_id: int,
    post,
    user: dict,
    channel: str,
    notifiers_config,
    client,
    retry_queue=None,
    alert_notifiers=None,
    alert_cb=None,
    *,
    favorite: bool = False,
    keyword: bool = False,
) -> None:
    """单个用户单个渠道的新帖推送骨架。

    成功写成功日志；失败写失败日志 + 进重试队列 + 调 alert_cb 通知管理员。
    调用方负责先做 channel_enabled / channel_bound 过滤。
    """
    notifier = build_channel_notifier(
        channel,
        user,
        notifiers_config,
        client=client,
        favorite=favorite,
        keyword=keyword,
    )
    try:
        notifier.notify(post)
        db.add_push_log(post_id, channel, "success", user_id=user["id"])
    except Exception as exc:  # noqa: BLE001 - 单渠道失败不影响其他渠道/用户
        db.add_push_log(post_id, channel, "failed", str(exc), user_id=user["id"])
        logger.warning("用户推送失败 user=%s channel=%s err=%s", user["username"], channel, exc)
        if retry_queue is not None:
            retry_queue.add(post, channel, user["id"])
        if alert_cb is not None:
            alert_cb(db, alert_notifiers or [], f"user={user['username']} channel={channel} err={exc}")
