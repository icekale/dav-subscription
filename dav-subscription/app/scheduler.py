"""调度器：轮询抓取、去重入库、推送通知、失败退避。"""
from __future__ import annotations

import asyncio
import logging
import random
import time

from .db import DB
from .fetchers.base import Fetcher, Post
from .notifiers.base import Notifier

logger = logging.getLogger(__name__)

WEIBO_WARNING_KEY = "weibo_warning_date"


class PlatformState:
    """每个平台连续失败次数与退避截止时间。"""

    def __init__(self):
        self.fail_count = 0
        self.skip_until = 0.0
        self.last_fetched: dict[int, float] = {}


def maybe_warn_weibo_login(db: DB, notifiers: list[Notifier], detail: str) -> None:
    """微博自动登录失败时向各渠道推告警，每天最多一次。"""
    today = time.strftime("%Y-%m-%d")
    if db.get_setting(WEIBO_WARNING_KEY) == today:
        return
    db.set_setting(WEIBO_WARNING_KEY, today)
    message = f"⚠️ 微博 cookie 自动登录失败，请检查 weibo.username/password 或手动更新 cookie。详情：{detail[:200]}"
    for notifier in notifiers:
        try:
            notifier.send_text(message)
        except Exception as exc:  # noqa: BLE001
            logger.warning("微博告警发送失败 channel=%s err=%s", notifier.channel, exc)


def notify_post(db: DB, post_id: int, post: Post, notifiers: list[Notifier]) -> None:
    """向所有通知器推送，失败记录日志并重试一次。"""
    for notifier in notifiers:
        try:
            notifier.notify(post)
            db.add_push_log(post_id, notifier.channel, "success")
        except Exception as exc:  # noqa: BLE001 - 推送失败只记录
            logger.warning("推送失败 channel=%s post=%s err=%s", notifier.channel, post.external_id, exc)
            db.add_push_log(post_id, notifier.channel, "failed", str(exc))
            try:
                notifier.notify(post)
                db.add_push_log(post_id, notifier.channel, "success")
            except Exception as exc2:  # noqa: BLE001
                logger.error("推送重试失败 channel=%s post=%s err=%s", notifier.channel, post.external_id, exc2)
                db.add_push_log(post_id, notifier.channel, "failed", str(exc2))


def notify_subscribers(db: DB, post_id: int, post: Post, notifiers_config) -> None:
    """把新帖推送给订阅了该大V的用户（各自绑定的渠道）。"""
    if notifiers_config is None:
        return
    from .notifiers.feishu import FeishuNotifier
    from .notifiers.telegram import TelegramNotifier

    for user in db.subscribers_of_kol(post.kol_id):
        if user["telegram_chat_id"] and notifiers_config.telegram.bot_token:
            notifier = TelegramNotifier(
                notifiers_config.telegram,
                chat_id=user["telegram_chat_id"],
            )
            try:
                notifier.notify(post)
                db.add_push_log(post_id, "telegram", "success", user_id=user["id"])
            except Exception as exc:  # noqa: BLE001
                db.add_push_log(post_id, "telegram", "failed", str(exc), user_id=user["id"])
                logger.warning("用户推送失败 user=%s channel=telegram err=%s", user["username"], exc)
        if user["feishu_open_id"]:
            # 优先用 p2p 会话 chat_id 发送（open_id 直发可能被飞书 230101 拦截）
            notifier = FeishuNotifier(
                notifiers_config.feishu,
                open_id=user["feishu_open_id"] if not user.get("feishu_chat_id") else None,
                chat_id=user.get("feishu_chat_id") or None,
            )
            try:
                notifier.notify(post)
                db.add_push_log(post_id, "feishu", "success", user_id=user["id"])
            except Exception as exc:  # noqa: BLE001
                db.add_push_log(post_id, "feishu", "failed", str(exc), user_id=user["id"])
                logger.warning("用户推送失败 user=%s channel=feishu err=%s", user["username"], exc)


def poll_once(
    db: DB,
    fetchers: dict[str, Fetcher],
    notifiers: list[Notifier],
    states: dict[str, PlatformState] | None = None,
    notifiers_config=None,
    interval_seconds: int = 180,
    priority_interval_seconds: int = 60,
) -> None:
    """执行一轮：遍历启用 KOL → 抓取 → 去重 → 推送。"""
    states = states if states is not None else {}
    now = time.monotonic()
    for kol in db.list_kols():
        if not kol["enabled"]:
            continue
        fetcher = fetchers.get(kol["platform"])
        if fetcher is None:
            continue
        state = states.setdefault(kol["platform"], PlatformState())
        if now < state.skip_until:
            continue
        # 按大V优先级错峰：优先大V用更短间隔，普通大V用全局间隔
        effective = priority_interval_seconds if kol.get("priority") else interval_seconds
        if now - state.last_fetched.get(kol["id"], 0) < effective:
            continue
        try:
            posts = fetcher.fetch(kol)
        except Exception as exc:  # noqa: BLE001 - 单源失败不影响其他
            state.fail_count += 1
            delay = min(30 * (2 ** (state.fail_count - 1)), 600)
            state.skip_until = time.monotonic() + delay
            logger.warning(
                "抓取失败 platform=%s kol=%s err=%s 下次尝试 %.0fs 后",
                kol["platform"],
                kol["name"],
                exc,
                delay,
            )
            if kol["platform"] == "weibo" and ("登录" in str(exc) or "login" in str(exc).lower()):
                maybe_warn_weibo_login(db, notifiers, str(exc))
            continue
        state.fail_count = 0
        state.last_fetched[kol["id"]] = now
        for post in posts:
            post.category = kol.get("category_name") or ""
            post_id = db.insert_post(
                post.platform,
                post.kol_id,
                post.external_id,
                post.title,
                post.content,
                post.url,
                post.published_at,
            )
            if post_id is None:
                continue
            logger.info("新帖 platform=%s kol=%s id=%s", post.platform, post.kol_name, post.external_id)
            notify_post(db, post_id, post, notifiers)
            notify_subscribers(db, post_id, post, notifiers_config)


class Scheduler:
    def __init__(self, db, fetchers, notifiers, polling_config, notifiers_config=None):
        self.db = db
        self.fetchers = fetchers
        self.notifiers = notifiers
        self.polling_config = polling_config
        self.notifiers_config = notifiers_config
        self.states: dict[str, PlatformState] = {}
        self._stop = asyncio.Event()
        self._last_cleanup = 0.0

    def stop(self):
        self._stop.set()

    async def _send_startup_message(self):
        for notifier in self.notifiers:
            try:
                await asyncio.to_thread(notifier.send_text, "✅ 大V订阅服务已启动")
            except Exception as exc:  # noqa: BLE001
                logger.warning("启动消息发送失败 channel=%s err=%s", notifier.channel, exc)

    async def run(self):
        if self.polling_config.notify_on_start:
            await self._send_startup_message()
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                await asyncio.to_thread(
                    poll_once,
                    self.db,
                    self.fetchers,
                    self.notifiers,
                    self.states,
                    self.notifiers_config,
                    self.polling_config.interval_seconds,
                    self.polling_config.priority_interval_seconds,
                )
                self.db.set_setting("stats_last_poll_at", str(int(time.time())))
                self.db.set_setting(
                    "stats_last_poll_duration_ms",
                    str(int((time.monotonic() - started) * 1000)),
                )
            except Exception:  # noqa: BLE001 - 任何异常都不能终止循环
                logger.exception("轮询周期异常")
                self.db.set_setting("stats_last_poll_error", "轮询周期异常")
            # 定期清理过期帖子（默认每 6 小时检查一次）
            now_mono = time.monotonic()
            if now_mono - self._last_cleanup > 6 * 3600:
                self._last_cleanup = now_mono
                retention = self.polling_config.posts_retention_days
                if retention > 0:
                    try:
                        removed = self.db.delete_posts_older_than(retention)
                        if removed:
                            logger.info("清理过期帖子 %d 条（保留 %d 天）", removed, retention)
                    except Exception:  # noqa: BLE001
                        logger.exception("帖子清理失败")
            elapsed = time.monotonic() - started
            delay = self.polling_config.interval_seconds + random.uniform(
                0, self.polling_config.jitter_seconds
            )
            await asyncio.sleep(max(0.0, delay - elapsed))
