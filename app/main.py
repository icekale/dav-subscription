"""应用入口：FastAPI + 调度器生命周期。"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import auth
from .api import create_api_router
from .config import load_config
from .db import DB
from .fetchers import build_fetchers
from .notifiers import build_notifiers
from .scheduler import Scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
# httpx 访问日志会打印完整 URL（含 bot token），降到 WARNING 防泄露
logging.getLogger("httpx").setLevel(logging.WARNING)


def create_app(config=None, db_path: str | Path | None = None) -> FastAPI:
    config = config or load_config()
    if db_path is not None:
        config.db_path = str(db_path)
    db = DB(config.db_path)
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
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(scheduler.run())
        bot_task = None
        if config.notifiers.telegram.bot_token:
            from .telegram_bot import TelegramBot

            bot = TelegramBot(
                db,
                config.notifiers.telegram.bot_token,
                secret,
                proxy=config.notifiers.telegram.proxy,
            )
            bot_task = asyncio.create_task(bot.run())
        if config.notifiers.feishu.app_id and config.notifiers.feishu.app_secret:
            from .feishu_bot import FeishuBot

            FeishuBot(db, config.notifiers.feishu.app_id, config.notifiers.feishu.app_secret).start()
        yield
        task.cancel()
        if bot_task is not None:
            bot_task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        if bot_task is not None:
            try:
                await bot_task
            except asyncio.CancelledError:
                pass
        # 关停前把合并摘要缓冲发出去，避免重启/更新丢消息
        scheduler.stop()
        db.close()

    app = FastAPI(title="大V订阅", lifespan=lifespan)
    app.state.db = db

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
        )
    )
    # 本地头像缓存（数据目录/avatars），避免第三方图床过期/外链失效
    avatars_dir = Path(config.db_path).parent / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/avatars", StaticFiles(directory=avatars_dir), name="avatars")
    app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
    return app


app = create_app()
