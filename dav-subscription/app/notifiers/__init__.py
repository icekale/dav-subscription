from __future__ import annotations

from .base import Notifier
from .feishu import FeishuNotifier
from .telegram import TelegramNotifier
from .wecom import WeComNotifier


def build_notifiers(config) -> list[Notifier]:
    """只启用已配置的通知渠道。"""
    notifiers = []
    if config.notifiers.feishu.webhook_url:
        notifiers.append(FeishuNotifier(config.notifiers.feishu))
    if config.notifiers.telegram.bot_token and config.notifiers.telegram.chat_id:
        notifiers.append(TelegramNotifier(config.notifiers.telegram))
    if config.notifiers.wecom.webhook_url:
        notifiers.append(WeComNotifier(config.notifiers.wecom))
    return notifiers
