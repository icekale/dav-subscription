"""Telegram Rich Message 运行时开关：后台设置优先，未保存过则跟 yaml/env。"""
from __future__ import annotations

SETTING_KEY = "config_telegram_rich_messages"


def parse_telegram_rich_setting(raw: str | None, default: bool) -> bool:
    if raw is None or raw == "":
        return bool(default)
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def get_telegram_rich_messages(db, default: bool = True) -> bool:
    if db is None:
        return bool(default)
    return parse_telegram_rich_setting(db.get_setting(SETTING_KEY), default)


def set_telegram_rich_messages(db, enabled: bool) -> None:
    db.set_setting(SETTING_KEY, "1" if enabled else "0")
