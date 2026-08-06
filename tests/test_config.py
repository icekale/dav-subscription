import pytest

from app.config import load_config

ALL_ENV = [
    "CONFIG_PATH",
    "DB_PATH",
    "FEISHU_WEBHOOK_URL",
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "WECOM_WEBHOOK_URL",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_PROXY",
    "XUEQIU_COOKIE",
    "WEIBO_COOKIE",
    "WEIBO_TOKEN",
    "POLLING_INTERVAL_SECONDS",
    "POLLING_PRIORITY_INTERVAL_SECONDS",
    "POLLING_JITTER_SECONDS",
    "POLLING_POSTS_RETENTION_DAYS",
    "NOTIFY_ON_START",
    "WEB_ALLOW_REGISTER",
    "WEB_ADMIN_PASSWORD",
    "WEB_TOKEN_SECRET",
    "WECHAT_APP_ID",
    "WECHAT_APP_SECRET",
    "WEB_TRUST_PROXY",
]


def test_defaults_without_file(tmp_path, monkeypatch):
    for name in ALL_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    config = load_config(tmp_path / "nope.yaml")
    assert config.polling.interval_seconds == 180
    assert config.notifiers.feishu.webhook_url == ""
    assert config.db_path == "data/dav.db"


def test_yaml_and_env_overrides(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(
        "polling:\n  interval_seconds: 60\nweb:\n  admin_password: secret\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("POLLING_INTERVAL_SECONDS", "90")
    config = load_config(tmp_path / "config.yaml")
    assert config.polling.interval_seconds == 90
    assert config.web.admin_password == "secret"


def test_telegram_proxy_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_PROXY", "http://127.0.0.1:7890")
    config = load_config(tmp_path / "nope.yaml")
    assert config.notifiers.telegram.proxy == "http://127.0.0.1:7890"


def test_wecom_webhook_env(tmp_path, monkeypatch):
    monkeypatch.setenv("WECOM_WEBHOOK_URL", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x")
    config = load_config(tmp_path / "nope.yaml")
    assert config.notifiers.wecom.webhook_url == "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x"


def test_quoted_yaml_types_normalized(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "polling:\n"
        '  interval_seconds: "60"\n'
        '  jitter_seconds: "5"\n'
        '  notify_on_start: "false"\n',
        encoding="utf-8",
    )
    config = load_config(tmp_path / "config.yaml")
    assert config.polling.interval_seconds == 60
    assert isinstance(config.polling.interval_seconds, int)
    assert config.polling.jitter_seconds == 5
    assert config.polling.notify_on_start is False


def test_invalid_int_value_raises(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "polling:\n  interval_seconds: \"abc\"\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="interval_seconds"):
        load_config(tmp_path / "config.yaml")


def test_wrong_type_raises(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "polling:\n  interval_seconds: [1, 2]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="interval_seconds"):
        load_config(tmp_path / "config.yaml")


def test_bad_env_int_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("POLLING_INTERVAL_SECONDS", "abc")
    with pytest.raises(ValueError, match="POLLING_INTERVAL_SECONDS"):
        load_config(tmp_path / "nope.yaml")


def test_empty_config_path_uses_default(tmp_path, monkeypatch):
    for name in ALL_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CONFIG_PATH", "")
    monkeypatch.chdir(tmp_path)
    config = load_config()
    assert config.polling.interval_seconds == 180


def test_priority_interval_seconds_must_be_positive(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(
        "polling:\n  priority_interval_seconds: 0\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_config(tmp_path / "config.yaml")


def test_web_trust_proxy_default_false_and_env_override(tmp_path, monkeypatch):
    for name in ALL_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    assert load_config(tmp_path / "nope.yaml").web.trust_proxy is False
    monkeypatch.setenv("WEB_TRUST_PROXY", "true")
    assert load_config(tmp_path / "nope.yaml").web.trust_proxy is True
