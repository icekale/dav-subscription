"""调度器：轮询抓取、去重入库、推送通知、失败退避。"""
from __future__ import annotations

import asyncio
import email.utils
import logging
import random
import time
from datetime import datetime

from .db import DB
from .fetchers.base import Fetcher, Post
from .notifiers.base import Notifier

logger = logging.getLogger(__name__)

WEIBO_WARNING_KEY = "weibo_warning_date"
XUEQIU_WARNING_KEY = "xueqiu_warning_date"
PUSH_ALERT_KEY = "push_alert_last_at"
PUSH_ALERT_INTERVAL = 3600
SOURCE_ALERT_INTERVAL = 6 * 3600
SOURCE_FAIL_THRESHOLD = 3
PLATFORM_LABELS = {"xueqiu": "雪球", "weibo": "微博", "twitter": "X"}
SOURCE_OK_KEY = "source_ok_{platform}"
SOURCE_ERR_KEY = "source_err_{platform}"
SOURCE_FAILS_KEY = "source_fails_{platform}"
XUEQIU_PROBE_ALERT_KEY = "xueqiu_probe_alert_at"


def _post_sort_key(post: Post) -> float:
    """帖子发布时间 → 时间戳；无法解析的排在最后（保持抓取顺序）。"""
    raw = (post.published_at or "").strip()
    if not raw:
        return float("inf")
    if raw.isdigit():
        try:
            ts = int(raw)
            return ts / 1000 if ts > 1e12 else float(ts)
        except ValueError:
            pass
    for fmt in (
        "%a %b %d %H:%M:%S %z %Y",  # 微博
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
    ):
        try:
            return datetime.strptime(raw, fmt).timestamp()
        except ValueError:
            continue
    try:
        # RFC 2822（RSS 源常用），如 "Tue, 04 Aug 2026 21:00:00 +0800"
        return email.utils.parsedate_to_datetime(raw).timestamp()
    except (TypeError, ValueError):
        return float("inf")


class PlatformState:
    """每个平台连续失败次数与退避截止时间。"""

    def __init__(self):
        self.fail_count = 0
        self.skip_until = 0.0
        self.last_fetched: dict[int, float] = {}
        self.alerted = False


def maybe_alert_source_failure(
    db: DB, notifiers: list[Notifier], platform: str, kol_name: str, detail: str, fail_count: int
) -> None:
    """数据源连续失败时向管理员推送告警（每平台每 6 小时最多一次）。"""
    now = int(time.time())
    key = f"source_alert_{platform}"
    last = db.get_setting(key)
    if last and now - int(last) < SOURCE_ALERT_INTERVAL:
        return
    db.set_setting(key, str(now))
    label = PLATFORM_LABELS.get(platform, platform)
    message = (
        f"⚠️ 数据源告警：{label}「{kol_name}」连续失败 {fail_count} 次。\n"
        f"错误：{detail[:200]}"
    )
    for notifier in notifiers:
        try:
            notifier.send_text(message)
        except Exception as exc:  # noqa: BLE001
            logger.warning("数据源告警发送失败 channel=%s err=%s", notifier.channel, exc)


def maybe_alert_source_recovered(
    db: DB, notifiers: list[Notifier], platform: str, kol_name: str
) -> None:
    """数据源从连续失败中恢复后通知管理员。"""
    label = PLATFORM_LABELS.get(platform, platform)
    message = f"✅ 数据源已恢复：{label}「{kol_name}」重新抓取成功。"
    for notifier in notifiers:
        try:
            notifier.send_text(message)
        except Exception as exc:  # noqa: BLE001
            logger.warning("数据源恢复通知发送失败 channel=%s err=%s", notifier.channel, exc)


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


def maybe_warn_xueqiu_cookie(db: DB, notifiers: list[Notifier], detail: str) -> None:
    """雪球 cookie/WAF 失效时向各渠道推告警，每天最多一次。"""
    today = time.strftime("%Y-%m-%d")
    if db.get_setting(XUEQIU_WARNING_KEY) == today:
        return
    db.set_setting(XUEQIU_WARNING_KEY, today)
    message = f"⚠️ 雪球 cookie 自动续期失败（可能被 WAF 拦截），请手动更新 sources.xueqiu.cookie。详情：{detail[:200]}"
    for notifier in notifiers:
        try:
            notifier.send_text(message)
        except Exception as exc:  # noqa: BLE001
            logger.warning("雪球告警发送失败 channel=%s err=%s", notifier.channel, exc)


def maybe_alert_push_failure(db: DB, notifiers: list[Notifier], detail: str) -> None:
    """用户推送失败时向管理员告警，每小时最多一次避免刷屏。"""
    now = int(time.time())
    last = db.get_setting(PUSH_ALERT_KEY)
    if last and now - int(last) < PUSH_ALERT_INTERVAL:
        return
    db.set_setting(PUSH_ALERT_KEY, str(now))
    message = f"⚠️ 用户推送失败（每小时最多提醒一次）：{detail[:200]}"
    for notifier in notifiers:
        try:
            notifier.send_text(message)
        except Exception as exc:  # noqa: BLE001
            logger.warning("推送告警发送失败 channel=%s err=%s", notifier.channel, exc)


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


def notify_subscribers(db: DB, post_id: int, post: Post, notifiers_config, notifiers=None) -> None:
    """把新帖推送给订阅了该大V的用户（各自绑定的渠道）。"""
    if notifiers_config is None:
        return
    import httpx

    from .notifiers.feishu import FeishuNotifier
    from .notifiers.telegram import TelegramNotifier

    # 全局 TG 通知（config.chat_id）已覆盖的接收者，避免同一条帖子推两次
    global_tg_chat = notifiers_config.telegram.chat_id
    global_tg_active = bool(notifiers_config.telegram.bot_token and global_tg_chat)
    client = httpx.Client(timeout=15)
    try:
        for user in db.subscribers_of_kol(post.kol_id):
            if user["telegram_chat_id"] and notifiers_config.telegram.bot_token:
                if global_tg_active and user["telegram_chat_id"] == global_tg_chat:
                    continue  # 已由全局推送覆盖
                notifier = TelegramNotifier(
                    notifiers_config.telegram,
                    client=client,
                    chat_id=user["telegram_chat_id"],
                )
                try:
                    notifier.notify(post)
                    db.add_push_log(post_id, "telegram", "success", user_id=user["id"])
                except Exception as exc:  # noqa: BLE001
                    db.add_push_log(post_id, "telegram", "failed", str(exc), user_id=user["id"])
                    logger.warning("用户推送失败 user=%s channel=telegram err=%s", user["username"], exc)
                    maybe_alert_push_failure(
                        db, notifiers or [], f"user={user['username']} channel=telegram err={exc}"
                    )
            if user["feishu_open_id"]:
                # 优先用 p2p 会话 chat_id 发送（open_id 直发可能被飞书 230101 拦截）
                notifier = FeishuNotifier(
                    notifiers_config.feishu,
                    client=client,
                    open_id=user["feishu_open_id"] if not user.get("feishu_chat_id") else None,
                    chat_id=user.get("feishu_chat_id") or None,
                )
                try:
                    notifier.notify(post)
                    db.add_push_log(post_id, "feishu", "success", user_id=user["id"])
                except Exception as exc:  # noqa: BLE001
                    db.add_push_log(post_id, "feishu", "failed", str(exc), user_id=user["id"])
                    logger.warning("用户推送失败 user=%s channel=feishu err=%s", user["username"], exc)
                    maybe_alert_push_failure(
                        db, notifiers or [], f"user={user['username']} channel=feishu err={exc}"
                    )
    finally:
        client.close()


def poll_once(
    db: DB,
    fetchers: dict[str, Fetcher],
    notifiers: list[Notifier],
    states: dict[str, PlatformState] | None = None,
    notifiers_config=None,
    interval_seconds: int = 180,
    priority_interval_seconds: int = 60,
    digest: dict[int, list[Post]] | None = None,
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
            if state.fail_count == SOURCE_FAIL_THRESHOLD or state.fail_count % 10 == 0:
                maybe_alert_source_failure(
                    db, notifiers, kol["platform"], kol["name"], str(exc), state.fail_count
                )
                state.alerted = True
            logger.warning(
                "抓取失败 platform=%s kol=%s err=%s 下次尝试 %.0fs 后",
                kol["platform"],
                kol["name"],
                exc,
                delay,
            )
            if kol["platform"] == "weibo" and ("登录" in str(exc) or "login" in str(exc).lower()):
                maybe_warn_weibo_login(db, notifiers, str(exc))
            if kol["platform"] == "xueqiu" and any(
                kw in str(exc) for kw in ("cookie", "WAF", "反爬")
            ):
                maybe_warn_xueqiu_cookie(db, notifiers, str(exc))
            db.set_setting(SOURCE_ERR_KEY.format(platform=kol["platform"]), str(exc)[:300])
            db.set_setting(SOURCE_FAILS_KEY.format(platform=kol["platform"]), str(state.fail_count))
            continue
        if state.alerted:
            maybe_alert_source_recovered(db, notifiers, kol["platform"], kol["name"])
            state.alerted = False
        state.fail_count = 0
        db.set_setting(SOURCE_OK_KEY.format(platform=kol["platform"]), str(int(time.time())))
        db.set_setting(SOURCE_FAILS_KEY.format(platform=kol["platform"]), "0")
        db.set_setting(SOURCE_ERR_KEY.format(platform=kol["platform"]), "")
        state.last_fetched[kol["id"]] = now
        # 按发布时间升序推送，避免各平台返回顺序（置顶/反爬兜底）导致乱序
        posts = sorted(posts, key=_post_sort_key)
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
            if digest is not None and not kol.get("priority"):
                # 普通大V进入合并摘要缓冲，按 digest_interval 周期统一推送
                digest.setdefault(kol["id"], []).append(post)
            else:
                notify_post(db, post_id, post, notifiers)
                notify_subscribers(db, post_id, post, notifiers_config, notifiers)


def notify_digest_subscribers(
    db: DB, posts: list[Post], kol: dict, notifiers_config, notifiers=None
) -> None:
    """把合并摘要推送给订阅了该大V的用户（各自绑定的渠道，带退订按钮）。"""
    if notifiers_config is None or not posts:
        return
    import httpx

    from .notifiers.feishu import FeishuNotifier
    from .notifiers.telegram import TelegramNotifier

    global_tg_chat = notifiers_config.telegram.chat_id
    global_tg_active = bool(notifiers_config.telegram.bot_token and global_tg_chat)
    client = httpx.Client(timeout=15)
    try:
        for user in db.subscribers_of_kol(kol["id"]):
            if user["telegram_chat_id"] and notifiers_config.telegram.bot_token:
                if global_tg_active and user["telegram_chat_id"] == global_tg_chat:
                    continue
                notifier = TelegramNotifier(
                    notifiers_config.telegram,
                    client=client,
                    chat_id=user["telegram_chat_id"],
                    unsub_kol_id=kol["id"],
                )
                try:
                    notifier.send_digest(posts, kol["name"], kol["platform"])
                    for post in posts:
                        db.add_push_log(
                            db.get_post_id(post.platform, post.external_id),
                            "telegram",
                            "success",
                            user_id=user["id"],
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("摘要推送失败 user=%s channel=telegram err=%s", user["username"], exc)
                    for post in posts:
                        db.add_push_log(
                            db.get_post_id(post.platform, post.external_id),
                            "telegram",
                            "failed",
                            str(exc),
                            user_id=user["id"],
                        )
            if user["feishu_open_id"]:
                notifier = FeishuNotifier(
                    notifiers_config.feishu,
                    client=client,
                    open_id=user["feishu_open_id"] if not user.get("feishu_chat_id") else None,
                    chat_id=user.get("feishu_chat_id") or None,
                    unsub_kol_id=kol["id"],
                )
                try:
                    notifier.send_digest(posts, kol["name"], kol["platform"])
                    for post in posts:
                        db.add_push_log(
                            db.get_post_id(post.platform, post.external_id),
                            "feishu",
                            "success",
                            user_id=user["id"],
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("摘要推送失败 user=%s channel=feishu err=%s", user["username"], exc)
                    for post in posts:
                        db.add_push_log(
                            db.get_post_id(post.platform, post.external_id),
                            "feishu",
                            "failed",
                            str(exc),
                            user_id=user["id"],
                        )
    finally:
        client.close()


def flush_digest(db: DB, digest: dict[int, list[Post]], notifiers: list[Notifier], notifiers_config) -> None:
    """到点把缓冲的摘要统一推送：全局通知器 + 订阅者。"""
    if not digest:
        return
    items = list(digest.items())
    digest.clear()
    for kol_id, posts in items:
        kol = db.get_kol(kol_id)
        if kol is None or not posts:
            continue
        for notifier in notifiers:
            send = getattr(notifier, "send_digest", None)
            if send is None:
                for post in posts:
                    post_id = db.insert_post_id(post.platform, post.external_id)
                    if post_id:
                        notify_post(db, post_id, post, [notifier])
                continue
            try:
                send(posts, kol["name"], kol["platform"])
                for post in posts:
                    db.add_push_log(
                        db.get_post_id(post.platform, post.external_id),
                        notifier.channel,
                        "success",
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("全局摘要推送失败 channel=%s err=%s", notifier.channel, exc)
                for post in posts:
                    db.add_push_log(
                        db.get_post_id(post.platform, post.external_id),
                        notifier.channel,
                        "failed",
                        str(exc),
                    )
        notify_digest_subscribers(db, posts, kol, notifiers_config, notifiers)


def probe_xueqiu(db: DB, notifiers: list[Notifier], source_config) -> None:
    """主动探测雪球抓取接口可用性（与抓取同路径，不用首页——首页对
    数据中心 IP 常见 WAF，不能作为失效依据）。"""
    import httpx

    from .fetchers.xueqiu import XUEQIU_COOKIE_KEY, XUEQIU_TIMELINE_URL, _is_waf_html

    cookie = db.get_setting(XUEQIU_COOKIE_KEY) or source_config.cookie
    target = next((k for k in db.list_kols(platform="xueqiu") if k["enabled"]), None)
    if target is None:
        return  # 没有启用的雪球大V，无从探测
    client = httpx.Client(
        timeout=15,
        follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)",
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://xueqiu.com/u/{target['external_id']}",
            **({"Cookie": cookie} if cookie else {}),
        },
    )
    try:
        resp = client.get(
            XUEQIU_TIMELINE_URL,
            params={"user_id": target["external_id"], "page": 1, "count": 1},
        )
        blocked = (
            _is_waf_html(resp)
            or resp.status_code in (401, 403)
            or resp.headers.get("content-type", "").startswith("text/html")
        )
        if resp.status_code == 200 and not blocked:
            try:
                resp.json()
            except ValueError:
                blocked = True
        if blocked:
            db.set_setting(SOURCE_ERR_KEY.format(platform="xueqiu"), "接口异常/反爬拦截（探测）")
            now = int(time.time())
            last = db.get_setting(XUEQIU_PROBE_ALERT_KEY)
            if not last or now - int(last) >= SOURCE_ALERT_INTERVAL:
                db.set_setting(XUEQIU_PROBE_ALERT_KEY, str(now))
                message = (
                    "⚠️ 雪球探测异常：抓取接口被反爬拦截或返回异常，"
                    "cookie 可能失效。请到后台「数据源」页更新雪球 cookie。"
                )
                for notifier in notifiers:
                    try:
                        notifier.send_text(message)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("雪球探测告警发送失败 channel=%s err=%s", notifier.channel, exc)
            return
        db.set_setting(SOURCE_OK_KEY.format(platform="xueqiu"), str(int(time.time())))
        db.set_setting(SOURCE_ERR_KEY.format(platform="xueqiu"), "")
    except Exception as exc:  # noqa: BLE001
        db.set_setting(SOURCE_ERR_KEY.format(platform="xueqiu"), str(exc)[:300])
        logger.warning("雪球探测失败: %s", exc)
    finally:
        client.close()


class Scheduler:
    def __init__(
        self,
        db,
        fetchers,
        notifiers,
        polling_config,
        notifiers_config=None,
        xueqiu_config=None,
    ):
        self.db = db
        self.fetchers = fetchers
        self.notifiers = notifiers
        self.polling_config = polling_config
        self.notifiers_config = notifiers_config
        self.xueqiu_config = xueqiu_config
        self.states: dict[str, PlatformState] = {}
        self._digest: dict[int, list[Post]] = {}
        self._stop = asyncio.Event()
        self._last_cleanup = 0.0
        self._last_digest_flush = time.monotonic()
        self._last_xueqiu_probe = time.monotonic()

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
                    self._digest if self.polling_config.digest_interval_seconds > 0 else None,
                )
                self.db.set_setting("stats_last_poll_at", str(int(time.time())))
                self.db.set_setting(
                    "stats_last_poll_duration_ms",
                    str(int((time.monotonic() - started) * 1000)),
                )
                self.db.set_setting("stats_last_poll_error", "")
            except Exception:  # noqa: BLE001 - 任何异常都不能终止循环
                logger.exception("轮询周期异常")
                self.db.set_setting("stats_last_poll_error", "轮询周期异常")
            now_mono = time.monotonic()
            # 合并摘要到点统一推送（普通大V，优先大V保持实时）
            digest_interval = self.polling_config.digest_interval_seconds
            if (
                digest_interval > 0
                and self._digest
                and now_mono - self._last_digest_flush >= digest_interval
            ):
                self._last_digest_flush = now_mono
                try:
                    await asyncio.to_thread(
                        flush_digest,
                        self.db,
                        self._digest,
                        self.notifiers,
                        self.notifiers_config,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("摘要推送失败")
            # 雪球 cookie 主动探测
            probe_interval = self.polling_config.source_probe_interval_seconds
            if probe_interval > 0 and now_mono - self._last_xueqiu_probe >= probe_interval:
                self._last_xueqiu_probe = now_mono
                try:
                    await asyncio.to_thread(
                        probe_xueqiu,
                        self.db,
                        self.notifiers,
                        self.xueqiu_config,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("雪球探测异常")
            # 定期清理过期帖子（默认每 6 小时检查一次）
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
                log_retention = self.polling_config.push_logs_retention_days
                if log_retention > 0:
                    try:
                        removed_logs = self.db.delete_push_logs_older_than(log_retention)
                        if removed_logs:
                            logger.info("清理推送日志 %d 条（保留 %d 天）", removed_logs, log_retention)
                    except Exception:  # noqa: BLE001
                        logger.exception("推送日志清理失败")
            elapsed = time.monotonic() - started
            delay = self.polling_config.interval_seconds + random.uniform(
                0, self.polling_config.jitter_seconds
            )
            await asyncio.sleep(max(0.0, delay - elapsed))
