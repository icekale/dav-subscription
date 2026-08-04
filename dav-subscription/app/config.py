"""配置加载：YAML 文件 + 环境变量覆盖。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path

import yaml


@dataclass
class FeishuConfig:
    webhook_url: str = ""
    app_id: str = ""
    app_secret: str = ""
    bot_name: str = ""


@dataclass
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""
    proxy: str = ""
    bot_username: str = ""


@dataclass
class NotifiersConfig:
    feishu: FeishuConfig = field(default_factory=FeishuConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)


@dataclass
class XueqiuConfig:
    cookie: str = ""


@dataclass
class WeiboConfig:
    cookie: str = ""
    token: str = ""
    username: str = ""
    password: str = ""


@dataclass
class SourcesConfig:
    xueqiu: XueqiuConfig = field(default_factory=XueqiuConfig)
    weibo: WeiboConfig = field(default_factory=WeiboConfig)


@dataclass
class PollingConfig:
    interval_seconds: int = 180
    priority_interval_seconds: int = 60
    jitter_seconds: int = 30
    notify_on_start: bool = True
    posts_retention_days: int = 30
    push_logs_retention_days: int = 90
    digest_interval_seconds: int = 600
    source_probe_interval_seconds: int = 600
    cookie_keepalive_interval_seconds: int = 21600


@dataclass
class WebConfig:
    password: str = ""
    allow_register: bool = True
    admin_password: str = ""
    token_secret: str = ""


@dataclass
class WeChatConfig:
    app_id: str = ""
    app_secret: str = ""


@dataclass
class Config:
    notifiers: NotifiersConfig = field(default_factory=NotifiersConfig)
    sources: SourcesConfig = field(default_factory=SourcesConfig)
    polling: PollingConfig = field(default_factory=PollingConfig)
    web: WebConfig = field(default_factory=WebConfig)
    wechat: WeChatConfig = field(default_factory=WeChatConfig)
    db_path: str = "data/dav.db"


# 环境变量 -> Config 属性路径（用于覆盖）
_ENV_MAP = {
    "FEISHU_WEBHOOK_URL": ("notifiers", "feishu", "webhook_url"),
    "FEISHU_APP_ID": ("notifiers", "feishu", "app_id"),
    "FEISHU_APP_SECRET": ("notifiers", "feishu", "app_secret"),
    "TELEGRAM_BOT_TOKEN": ("notifiers", "telegram", "bot_token"),
    "TELEGRAM_CHAT_ID": ("notifiers", "telegram", "chat_id"),
    "TELEGRAM_PROXY": ("notifiers", "telegram", "proxy"),
    "TELEGRAM_BOT_USERNAME": ("notifiers", "telegram", "bot_username"),
    "FEISHU_BOT_NAME": ("notifiers", "feishu", "bot_name"),
    "XUEQIU_COOKIE": ("sources", "xueqiu", "cookie"),
    "WEIBO_COOKIE": ("sources", "weibo", "cookie"),
    "WEIBO_TOKEN": ("sources", "weibo", "token"),
    "WEIBO_USERNAME": ("sources", "weibo", "username"),
    "WEIBO_PASSWORD": ("sources", "weibo", "password"),
    "POLLING_INTERVAL_SECONDS": ("polling", "interval_seconds"),
    "POLLING_PRIORITY_INTERVAL_SECONDS": ("polling", "priority_interval_seconds"),
    "POLLING_JITTER_SECONDS": ("polling", "jitter_seconds"),
    "POLLING_POSTS_RETENTION_DAYS": ("polling", "posts_retention_days"),
    "POLLING_PUSH_LOGS_RETENTION_DAYS": ("polling", "push_logs_retention_days"),
    "POLLING_DIGEST_INTERVAL_SECONDS": ("polling", "digest_interval_seconds"),
    "POLLING_SOURCE_PROBE_INTERVAL_SECONDS": ("polling", "source_probe_interval_seconds"),
    "POLLING_COOKIE_KEEPALIVE_INTERVAL_SECONDS": ("polling", "cookie_keepalive_interval_seconds"),
    "NOTIFY_ON_START": ("polling", "notify_on_start"),
    "WEB_PASSWORD": ("web", "password"),
    "WEB_ALLOW_REGISTER": ("web", "allow_register"),
    "WEB_ADMIN_PASSWORD": ("web", "admin_password"),
    "WEB_TOKEN_SECRET": ("web", "token_secret"),
    "WECHAT_APP_ID": ("wechat", "app_id"),
    "WECHAT_APP_SECRET": ("wechat", "app_secret"),
    "DB_PATH": ("db_path",),
}


def _fill(dc, data: dict) -> None:
    """用嵌套 dict 就地填充 dataclass，忽略未知字段。"""
    for f in fields(dc):
        if f.name not in data:
            continue
        value = data[f.name]
        child = getattr(dc, f.name)
        if is_dataclass(child) and isinstance(value, dict):
            _fill(child, value)
        else:
            setattr(dc, f.name, value)


def _set_path(obj, path, value) -> None:
    for key in path[:-1]:
        obj = getattr(obj, key)
    setattr(obj, path[-1], value)


def _validate(config: Config) -> None:
    """类型归一化与校验：配置错误在启动时尽早暴露。"""
    checks = (
        ("polling.interval_seconds", config.polling, "interval_seconds", int),
        ("polling.priority_interval_seconds", config.polling, "priority_interval_seconds", int),
        ("polling.jitter_seconds", config.polling, "jitter_seconds", int),
        ("polling.posts_retention_days", config.polling, "posts_retention_days", int),
        ("polling.push_logs_retention_days", config.polling, "push_logs_retention_days", int),
        ("polling.digest_interval_seconds", config.polling, "digest_interval_seconds", int),
        ("polling.source_probe_interval_seconds", config.polling, "source_probe_interval_seconds", int),
        ("polling.cookie_keepalive_interval_seconds", config.polling, "cookie_keepalive_interval_seconds", int),
        ("polling.notify_on_start", config.polling, "notify_on_start", bool),
        ("web.allow_register", config.web, "allow_register", bool),
    )
    for label, obj, attr, expected in checks:
        value = getattr(obj, attr)
        try:
            if expected is bool and isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in ("1", "true", "yes", "on"):
                    value = True
                elif lowered in ("0", "false", "no", "off"):
                    value = False
                else:
                    raise ValueError(f"无法解析为布尔值: {value!r}")
            elif expected is bool and isinstance(value, int) and value in (0, 1):
                value = bool(value)
            elif expected is int and isinstance(value, str):
                value = int(value.strip())
            if not isinstance(value, expected):
                raise ValueError(
                    f"期望 {expected.__name__}, 实际 {type(value).__name__}: {value!r}"
                )
        except ValueError as exc:
            raise ValueError(f"配置项 {label} 无效: {exc}") from exc
        setattr(obj, attr, value)
    if config.polling.interval_seconds < 1:
        raise ValueError("配置项 polling.interval_seconds 必须 >= 1")
    if config.polling.jitter_seconds < 0:
        raise ValueError("配置项 polling.jitter_seconds 必须 >= 0")
    if config.polling.posts_retention_days < 0:
        raise ValueError("配置项 polling.posts_retention_days 必须 >= 0")
    if config.polling.push_logs_retention_days < 0:
        raise ValueError("配置项 polling.push_logs_retention_days 必须 >= 0")
    if config.polling.digest_interval_seconds < 0:
        raise ValueError("配置项 polling.digest_interval_seconds 必须 >= 0")
    if config.polling.source_probe_interval_seconds < 0:
        raise ValueError("配置项 polling.source_probe_interval_seconds 必须 >= 0")
    if config.polling.cookie_keepalive_interval_seconds < 0:
        raise ValueError("配置项 polling.cookie_keepalive_interval_seconds 必须 >= 0")


def load_config(path: str | Path | None = None) -> Config:
    """加载 config.yaml（如存在），再用环境变量覆盖。"""
    path = Path(path or os.environ.get("CONFIG_PATH") or "config.yaml")
    config = Config()
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        _fill(config, raw)
    for env_name, attr_path in _ENV_MAP.items():
        value = os.environ.get(env_name)
        if not value:
            continue
        try:
            if env_name in (
                "POLLING_INTERVAL_SECONDS",
                "POLLING_PRIORITY_INTERVAL_SECONDS",
                "POLLING_JITTER_SECONDS",
                "POLLING_POSTS_RETENTION_DAYS",
                "POLLING_PUSH_LOGS_RETENTION_DAYS",
                "POLLING_DIGEST_INTERVAL_SECONDS",
                "POLLING_SOURCE_PROBE_INTERVAL_SECONDS",
                "POLLING_COOKIE_KEEPALIVE_INTERVAL_SECONDS",
            ):
                value = int(value)
            elif env_name in ("NOTIFY_ON_START", "WEB_ALLOW_REGISTER"):
                value = value.strip().lower() in ("1", "true", "yes", "on")
        except ValueError as exc:
            raise ValueError(f"环境变量 {env_name} 无效: {exc}") from exc
        _set_path(config, attr_path, value)
    _validate(config)
    return config
