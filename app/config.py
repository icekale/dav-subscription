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
    # 飞书个人机器人凭据加密密钥（Fernet 兼容的 32 字节 Base64）。
    # 只从环境变量读取，不写入 SQLite；缺失时个人机器人功能不可用，共享机器人照常。
    credential_key: str = ""


@dataclass
class WeComConfig:
    webhook_url: str = ""


@dataclass
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""
    proxy: str = ""
    bot_username: str = ""


@dataclass
class BarkConfig:
    """Bark 推送服务器（用户 key 存在各自账号里）。

    bark_server 默认官方 https://api.day.app；自建实例时配置，如 https://bark.example.com。
    bark_key 为系统级默认 key（可选）：配置后系统告警也会发 Bark。
    """

    bark_server: str = ""
    bark_key: str = ""


@dataclass
class LLMConfig:
    """可选 LLM 摘要：配置 api_key 即启用（免打扰汇总/每日精选生成 AI 要点）。

    使用 OpenAI 兼容接口（/chat/completions），可对接 OpenAI、DeepSeek、
    本地 Ollama/vLLM 等任何兼容服务。未配置时推送管线完全不受影响。
    """

    api_base: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"


@dataclass
class NotifiersConfig:
    feishu: FeishuConfig = field(default_factory=FeishuConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    wecom: WeComConfig = field(default_factory=WeComConfig)
    bark: BarkConfig = field(default_factory=BarkConfig)


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
class RssConfig:
    rsshub_base: str = "https://rsshub.app"


@dataclass
class SourcesConfig:
    xueqiu: XueqiuConfig = field(default_factory=XueqiuConfig)
    weibo: WeiboConfig = field(default_factory=WeiboConfig)
    rss: RssConfig = field(default_factory=RssConfig)


@dataclass
class PollingConfig:
    interval_seconds: int = 180
    priority_interval_seconds: int = 60
    jitter_seconds: int = 30
    notify_on_start: bool = True
    posts_retention_days: int = 30
    push_logs_retention_days: int = 90
    digest_interval_seconds: int = 600
    secondary_interval_seconds: int = 900
    secondary_idle_cap_seconds: int = 3600
    secondary_digest_interval_seconds: int = 3600
    source_probe_interval_seconds: int = 600
    cookie_keepalive_interval_seconds: int = 21600
    daily_report_hour: int = 20


@dataclass
class WebConfig:
    allow_register: bool = True
    admin_password: str = ""
    token_secret: str = ""
    trust_proxy: bool = False  # 位于可信反向代理之后时置 true，才信任 X-Forwarded-For


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
    llm: LLMConfig = field(default_factory=LLMConfig)
    db_path: str = "data/dav.db"
    # 管理员告警总开关：false 时不发任何告警、不启动 TG/飞书 bot 长轮询。
    # 本地开发/测试实例务必置 false，避免用生产 config 误发告警、抢生产 bot 轮询。
    alerts_enabled: bool = True


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
    "FEISHU_CREDENTIAL_KEY": ("notifiers", "feishu", "credential_key"),
    "WECOM_WEBHOOK_URL": ("notifiers", "wecom", "webhook_url"),
    "BARK_SERVER": ("notifiers", "bark", "bark_server"),
    "BARK_KEY": ("notifiers", "bark", "bark_key"),
    "LLM_API_BASE": ("llm", "api_base"),
    "LLM_API_KEY": ("llm", "api_key"),
    "LLM_MODEL": ("llm", "model"),
    "XUEQIU_COOKIE": ("sources", "xueqiu", "cookie"),
    "WEIBO_COOKIE": ("sources", "weibo", "cookie"),
    "WEIBO_TOKEN": ("sources", "weibo", "token"),
    "WEIBO_USERNAME": ("sources", "weibo", "username"),
    "WEIBO_PASSWORD": ("sources", "weibo", "password"),
    "RSSHUB_BASE": ("sources", "rss", "rsshub_base"),
    "POLLING_INTERVAL_SECONDS": ("polling", "interval_seconds"),
    "POLLING_PRIORITY_INTERVAL_SECONDS": ("polling", "priority_interval_seconds"),
    "POLLING_JITTER_SECONDS": ("polling", "jitter_seconds"),
    "POLLING_POSTS_RETENTION_DAYS": ("polling", "posts_retention_days"),
    "POLLING_PUSH_LOGS_RETENTION_DAYS": ("polling", "push_logs_retention_days"),
    "POLLING_DIGEST_INTERVAL_SECONDS": ("polling", "digest_interval_seconds"),
    "POLLING_SECONDARY_INTERVAL_SECONDS": ("polling", "secondary_interval_seconds"),
    "POLLING_SECONDARY_IDLE_CAP_SECONDS": ("polling", "secondary_idle_cap_seconds"),
    "POLLING_SECONDARY_DIGEST_INTERVAL_SECONDS": ("polling", "secondary_digest_interval_seconds"),
    "POLLING_SOURCE_PROBE_INTERVAL_SECONDS": ("polling", "source_probe_interval_seconds"),
    "POLLING_COOKIE_KEEPALIVE_INTERVAL_SECONDS": ("polling", "cookie_keepalive_interval_seconds"),
    "POLLING_DAILY_REPORT_HOUR": ("polling", "daily_report_hour"),
    "NOTIFY_ON_START": ("polling", "notify_on_start"),
    "WEB_ALLOW_REGISTER": ("web", "allow_register"),
    "WEB_ADMIN_PASSWORD": ("web", "admin_password"),
    "WEB_TOKEN_SECRET": ("web", "token_secret"),
    "WEB_TRUST_PROXY": ("web", "trust_proxy"),
    "WECHAT_APP_ID": ("wechat", "app_id"),
    "WECHAT_APP_SECRET": ("wechat", "app_secret"),
    "DB_PATH": ("db_path",),
    "ALERTS_ENABLED": ("alerts_enabled",),
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
        ("polling.daily_report_hour", config.polling, "daily_report_hour", int),
        ("polling.notify_on_start", config.polling, "notify_on_start", bool),
        ("web.allow_register", config.web, "allow_register", bool),
        ("web.trust_proxy", config.web, "trust_proxy", bool),
        ("alerts_enabled", config, "alerts_enabled", bool),
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
        except (TypeError, ValueError) as exc:
            raise ValueError(f"配置项 {label} 无效: {exc}") from exc
        setattr(obj, attr, value)
    if config.polling.interval_seconds < 1:
        raise ValueError("配置项 polling.interval_seconds 必须 >= 1")
    if config.polling.priority_interval_seconds < 1:
        raise ValueError("配置项 polling.priority_interval_seconds 必须 >= 1")
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
    if not 0 <= config.polling.daily_report_hour <= 23:
        raise ValueError("配置项 polling.daily_report_hour 需在 0-23 之间")


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
        # 原始字符串交给 _validate 的 checks 表归一化（str→int/bool），不在此重复转换
        _set_path(config, attr_path, value)
    _validate(config)
    return config
