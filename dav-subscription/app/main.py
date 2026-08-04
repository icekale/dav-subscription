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
    scheduler = Scheduler(db, fetchers, notifiers, config.polling, config.notifiers)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(scheduler.run())
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
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
        )
    )
    app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
    return app


app = create_app()
