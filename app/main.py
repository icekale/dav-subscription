"""应用入口：FastAPI + 调度器生命周期。"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from . import auth
from .api import create_api_router
from .config import load_config
from .db import DB
from .fetchers import build_fetchers
from .logging_setup import setup_logging
from .notifiers import build_notifiers
from .scheduler import Scheduler, set_alerts_enabled

# 纯 UI 调试模式开关：置 1 时跳过调度器与机器人长连接，避免测试实例
# 抢生产 Telegram 机器人（getUpdates 409）、用测试配置误发降级告警
# （曾因本地测试实例未配 TWITTER_COOKIE 给生产群发「未配置 TWITTER_COOKIE」）。
WORKERS_ENV = "DAV_UI_ONLY"

logger = logging.getLogger(__name__)


def background_workers_enabled() -> bool:
    """调度器/机器人等后台任务是否启用（DAV_UI_ONLY=1 时关闭）。"""
    return os.environ.get(WORKERS_ENV, "0") != "1"


class _NoCacheStaticFiles(StaticFiles):
    """html/js/css 每次请求都重新校验（ETag/304），避免浏览器缓存旧版本前端。"""

    def file_response(self, full_path, stat_result, scope, status_code=200):
        response = super().file_response(full_path, stat_result, scope, status_code)
        if str(full_path).endswith((".html", ".js", ".css")):
            response.headers["Cache-Control"] = "no-cache"
        return response

setup_logging()
access_logger = logging.getLogger("app.access")


def create_app(config=None, db_path: str | Path | None = None) -> FastAPI:
    config = config or load_config()
    if db_path is not None:
        config.db_path = str(db_path)
    db = DB(config.db_path)
    existing_xueqiu_cookie = db.get_setting("xueqiu_cookie")
    if existing_xueqiu_cookie:
        try:
            from .fetchers.xueqiu import write_xueqiu_seed_cookie

            write_xueqiu_seed_cookie(existing_xueqiu_cookie)
        except OSError:
            logger.warning("雪球 sidecar seed cookie 启动同步失败")
    db.set_setting("stats_polling_interval", str(config.polling.interval_seconds))
    db.set_setting("stats_posts_retention_days", str(config.polling.posts_retention_days))
    db.set_setting(
        "stats_keepalive_interval",
        str(config.polling.cookie_keepalive_interval_seconds),
    )
    db.set_setting("stats_priority_interval_seconds", str(config.polling.priority_interval_seconds))
    db.set_setting("stats_digest_interval_seconds", str(config.polling.digest_interval_seconds))
    db.set_setting(
        "stats_source_probe_interval_seconds",
        str(config.polling.source_probe_interval_seconds),
    )
    db.set_setting("stats_daily_report_hour", str(config.polling.daily_report_hour))
    # 采集频率档位默认值（无新帖自适应降频参数）：首次启动写入，后台可覆盖
    from .scheduler import (
        COMBINATION_BASE_SECONDS,
        COMBINATION_IDLE_CAP_SECONDS,
        NORMAL_IDLE_CAP_SECONDS,
        PRIORITY_IDLE_CAP_SECONDS,
        X_FALLBACK_CAP_SECONDS,
    )

    for key, value in (
        ("config_combination_base_seconds", COMBINATION_BASE_SECONDS),
        ("config_combination_idle_cap_seconds", COMBINATION_IDLE_CAP_SECONDS),
        ("config_normal_idle_cap_seconds", NORMAL_IDLE_CAP_SECONDS),
        ("config_priority_idle_cap_seconds", PRIORITY_IDLE_CAP_SECONDS),
        ("config_x_fallback_cap_seconds", X_FALLBACK_CAP_SECONDS),
    ):
        db.set_setting(key, str(value))
    # 次要大V档位：从 polling 配置取值（ENV 可覆盖），且不覆盖管理员已调值
    for key, value in (
        ("config_secondary_base_seconds", config.polling.secondary_interval_seconds),
        ("config_secondary_idle_cap_seconds", config.polling.secondary_idle_cap_seconds),
        ("config_secondary_digest_interval_seconds", config.polling.secondary_digest_interval_seconds),
    ):
        if db.get_setting(key) is None:
            db.set_setting(key, str(value))
    secret = auth.get_or_create_secret(db, config.web.token_secret)

    if config.web.admin_password:
        admin = db.get_user_by_username("admin")
        if admin is None:
            db.add_user(
                "admin",
                auth.hash_password(config.web.admin_password),
                is_admin=True,
            )
    fetchers = build_fetchers(config, db)
    notifiers = build_notifiers(config)
    scheduler = Scheduler(
        db,
        fetchers,
        notifiers,
        config.polling,
        config.notifiers,
        config.sources.xueqiu,
        config.sources.weibo,
        config.llm,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = None
        bot_task = None
        # 告警总开关统一用 config.alerts_enabled（config.yaml 与 ALERTS_ENABLED 环境变量均可配置）；
        # 在 lifespan 内注入而非模块级，避免导入即钉死全局 flag、影响测试对环境变量的操控
        set_alerts_enabled(config.alerts_enabled)
        if background_workers_enabled():
            task = asyncio.create_task(scheduler.run())
            if config.alerts_enabled and config.notifiers.telegram.bot_token:
                from .telegram_bot import TelegramBot

                bot = TelegramBot(
                    db,
                    config.notifiers.telegram.bot_token,
                    secret,
                    proxy=config.notifiers.telegram.proxy,
                )
                bot_task = asyncio.create_task(bot.run())
            if (
                config.alerts_enabled
                and config.notifiers.feishu.app_id
                and config.notifiers.feishu.app_secret
            ):
                from .feishu_bot import FeishuBot

                FeishuBot(db, config.notifiers.feishu.app_id, config.notifiers.feishu.app_secret).start()
            # 飞书个人机器人：清理进程重启遗留的未结束注册会话
            if config.notifiers.feishu.credential_key:
                from .feishu_personal import FeishuPersonalManager

                FeishuPersonalManager(db, config.notifiers.feishu).expire_stale()
        else:
            logger.warning("DAV_UI_ONLY=1 已跳过调度器与机器人长连接，仅提供网页 UI")
        yield
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if bot_task is not None:
            bot_task.cancel()
            try:
                await bot_task
            except asyncio.CancelledError:
                pass
        # 关停前把合并摘要缓冲发出去，避免重启/更新丢消息
        if task is not None:
            scheduler.stop()
        db.close()

    app = FastAPI(title="大V订阅", lifespan=lifespan)
    app.state.db = db

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        """基础安全响应头：防 MIME 嗅探 / 点击劫持 / Referer 泄露。"""
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        """API 请求日志：默认 DEBUG；超过 1 秒的慢请求 WARNING 提醒（方便排查）。"""
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        user = ""
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            payload = auth.verify_token(auth_header[7:], secret)
            if payload:
                user = payload.get("name") or ""
        line = (
            f"{request.method} {request.url.path} -> {response.status_code} "
            f"({duration_ms:.0f}ms) user={user}"
        )
        if duration_ms >= 1000:
            access_logger.warning("SLOW %s", line)
        else:
            access_logger.debug("%s", line)
        return response

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    app.include_router(
        create_api_router(
            db,
            secret,
            allow_register=config.web.allow_register,
            wechat_config=config.wechat,
            notifiers_config=config.notifiers,
            trust_proxy=config.web.trust_proxy,
        )
    )
    # 本地头像缓存（数据目录/avatars），避免第三方图床过期/外链失效
    avatars_dir = Path(config.db_path).parent / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/avatars", StaticFiles(directory=avatars_dir), name="avatars")
    app.mount(
        "/",
        _NoCacheStaticFiles(directory=Path(__file__).parent / "static", html=True),
        name="static",
    )
    return app


app = create_app()
