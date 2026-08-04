"""调度器：轮询抓取、去重入库、推送通知、失败退避。"""
from __future__ import annotations

import asyncio
import email.utils
import logging
import random
import threading
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
COOKIE_KEEPALIVE_ALERT_KEY = "cookie_keepalive_alert_at"
WEIBO_COOKIE_TIME_KEY = "weibo_cookie_updated_at"
WEIBO_QR_RENEWAL_KEY = "weibo_qr_renewal_at"
WEIBO_QR_RENEWAL_COOLDOWN = 15 * 60


def _polling_setting(db: DB, key: str, default: int) -> int:
    """读取后台可覆盖的抓取配置（config_*），未设置时用启动配置默认值。"""
    value = db.get_setting(key)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _polling_bool(db: DB, key: str, default: bool = False) -> bool:
    value = db.get_setting(key)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def translate_text(text: str, target: str = "zh-CN", client=None, xai_key: str | None = None, model: str | None = None) -> str:
    """把 X 内容转成中文：配了 XAI_API_KEY 优先用 Grok，否则 Google → MyMemory 降级。"""
    import os

    import httpx

    text = (text or "").strip()
    if not text:
        return text
    xai_key = xai_key or os.environ.get("XAI_API_KEY", "")
    model = model or os.environ.get("XAI_MODEL", "") or "grok-2-latest"
    owns_client = client is None
    client = client or httpx.Client(timeout=15)
    errors = []
    try:
        # 1) Grok（质量最好，需 xAI API Key）
        if xai_key:
            try:
                resp = client.post(
                    "https://api.x.ai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {xai_key}"},
                    json={
                        "model": model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "你是专业译者。把用户提供的文本翻译成简体中文，"
                                "只输出译文本身，不要解释、不要额外内容。",
                            },
                            {"role": "user", "content": text[:4000]},
                        ],
                        "temperature": 0.3,
                    },
                )
                resp.raise_for_status()
                content = (
                    ((resp.json() or {}).get("choices") or [{}])[0]
                    .get("message", {})
                    .get("content")
                    or ""
                )
                if content.strip():
                    return content.strip()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"grok: {exc}")
        # 1) Google translate（海外网络可用）
        try:
            resp = client.get(
                "https://translate.googleapis.com/translate_a/single",
                params={"client": "gtx", "sl": "auto", "tl": target, "dt": "t", "q": text[:2000]},
            )
            resp.raise_for_status()
            data = resp.json()
            translated = "".join(part[0] for part in data[0] if part and part[0])
            if translated:
                return translated
        except Exception as exc:  # noqa: BLE001
            errors.append(f"google: {exc}")
        # 2) MyMemory（国内网络可用，单条限 500 字符）
        try:
            resp = client.get(
                "https://api.mymemory.translated.net/get",
                params={"q": text[:500], "langpair": "en|zh-CN"},
            )
            resp.raise_for_status()
            translated = ((resp.json() or {}).get("responseData") or {}).get("translatedText") or ""
            if translated:
                return translated
        except Exception as exc:  # noqa: BLE001
            errors.append(f"mymemory: {exc}")
    finally:
        if owns_client:
            client.close()
    raise RuntimeError("; ".join(errors) or "无可用翻译源")


class PushRetryQueue:
    """推送失败重试队列：指数退避（1m/5m/15m），超过次数放弃。"""

    RETRY_DELAYS = (60, 300, 900)

    def __init__(self):
        self._items: dict[tuple, dict] = {}
        self._lock = threading.Lock()

    def add(self, post: Post, channel: str, user_id: int | None = None) -> None:
        key = (channel, user_id, post.external_id)
        with self._lock:
            if key not in self._items:
                self._items[key] = {
                    "post": post,
                    "channel": channel,
                    "user_id": user_id,
                    "attempts": 0,
                    "next_at": time.monotonic() + self.RETRY_DELAYS[0],
                    "key": key,
                }

    def due(self) -> list[dict]:
        now = time.monotonic()
        with self._lock:
            return [item for item in list(self._items.values()) if item["next_at"] <= now]

    def pending(self) -> int:
        with self._lock:
            return len(self._items)

    def fail(self, item: dict) -> bool:
        """记录一次重试失败；超过次数上限则移除，返回是否继续保留。"""
        with self._lock:
            item["attempts"] += 1
            if item["attempts"] >= len(self.RETRY_DELAYS):
                self._items.pop(item["key"], None)
                return False
            item["next_at"] = time.monotonic() + self.RETRY_DELAYS[item["attempts"]]
            return True

    def drop(self, item: dict) -> None:
        with self._lock:
            self._items.pop(item["key"], None)


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


def notify_post(
    db: DB,
    post_id: int,
    post: Post,
    notifiers: list[Notifier],
    retry_queue: PushRetryQueue | None = None,
) -> None:
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
                if retry_queue is not None:
                    retry_queue.add(post, notifier.channel)


def notify_subscribers(
    db: DB,
    post_id: int,
    post: Post,
    notifiers_config,
    notifiers=None,
    retry_queue: PushRetryQueue | None = None,
) -> None:
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
                    if retry_queue is not None:
                        retry_queue.add(post, "telegram", user["id"])
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
                    if retry_queue is not None:
                        retry_queue.add(post, "feishu", user["id"])
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
    retry_queue: PushRetryQueue | None = None,
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
            if (
                post.platform == "twitter"
                and _polling_bool(db, "config_translate_twitter_content", False)
                and db.get_post_id(post.platform, post.external_id) is None
            ):
                # 仅翻译新帖，避免每轮重复调用翻译接口
                try:
                    post.title = translate_text(post.title or "")
                    post.content = translate_text(post.content or "")
                except Exception as exc:  # noqa: BLE001 - 翻译失败退回原文
                    logger.warning("X 内容翻译失败 post=%s err=%s", post.external_id, exc)
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
                notify_post(db, post_id, post, notifiers, retry_queue)
                notify_subscribers(db, post_id, post, notifiers_config, notifiers, retry_queue)


def notify_digest_subscribers(
    db: DB,
    posts: list[Post],
    kol: dict,
    notifiers_config,
    notifiers=None,
    retry_queue: PushRetryQueue | None = None,
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
                    if retry_queue is not None:
                        for post in posts:
                            retry_queue.add(post, "telegram", user["id"])
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
                    if retry_queue is not None:
                        for post in posts:
                            retry_queue.add(post, "feishu", user["id"])
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


def flush_digest(
    db: DB,
    digest: dict[int, list[Post]],
    notifiers: list[Notifier],
    notifiers_config,
    retry_queue: PushRetryQueue | None = None,
) -> None:
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
                    post_id = db.get_post_id(post.platform, post.external_id)
                    if post_id:
                        notify_post(db, post_id, post, [notifier], retry_queue)
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
                if retry_queue is not None:
                    for post in posts:
                        retry_queue.add(post, notifier.channel)
                for post in posts:
                    db.add_push_log(
                        db.get_post_id(post.platform, post.external_id),
                        notifier.channel,
                        "failed",
                        str(exc),
                    )
        notify_digest_subscribers(db, posts, kol, notifiers_config, notifiers, retry_queue)


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


def _merge_cookie_string(old: str, client, prefer_domain: str) -> str:
    """合并旧 cookie 与本次响应下发的 cookie（同名多域时优先 prefer_domain 的新值）。"""
    items: dict[str, str] = {}
    for part in (old or "").split(";"):
        if "=" in part:
            key, value = part.strip().split("=", 1)
            items[key] = value
    for cookie in client.cookies.jar:
        if prefer_domain in (cookie.domain or "") or cookie.name not in items:
            items[cookie.name] = cookie.value
    return "; ".join(f"{k}={v}" for k, v in items.items())


def _alert_cookie_keepalive(db: DB, notifiers: list[Notifier], label: str, detail: str = "") -> None:
    now = int(time.time())
    last = db.get_setting(COOKIE_KEEPALIVE_ALERT_KEY)
    if last and now - int(last) < SOURCE_ALERT_INTERVAL:
        return
    db.set_setting(COOKIE_KEEPALIVE_ALERT_KEY, str(now))
    message = (
        f"⚠️ {label} cookie 保活失败：会话可能已过期或登录态被清除。"
        f"请到后台「数据源」页更新 {label} cookie，或配置账号密码自动续期。"
        + (f" 详情：{detail[:120]}" if detail else "")
    )
    for notifier in notifiers:
        try:
            notifier.send_text(message)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cookie 保活告警发送失败 channel=%s err=%s", notifier.channel, exc)


def keepalive_xueqiu_cookie(
    db: DB, notifiers: list[Notifier], source_config, client=None
) -> None:
    """定时访问雪球首页刷新会话，持久化最新 cookie。"""
    from .fetchers.xueqiu import XUEQIU_COOKIE_KEY, XUEQIU_COOKIE_TIME_KEY, _is_waf_html

    cookie = db.get_setting(XUEQIU_COOKIE_KEY) or source_config.cookie
    if not cookie:
        return
    import httpx

    owns_client = client is None
    client = client or httpx.Client(
        timeout=20,
        follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)",
            "Referer": "https://xueqiu.com/",
            "Cookie": cookie,
        },
    )
    try:
        resp = client.get("https://xueqiu.com/")
        if resp.status_code in (401, 403) or _is_waf_html(resp):
            db.set_setting(SOURCE_ERR_KEY.format(platform="xueqiu"), "保活被反爬拦截")
            _alert_cookie_keepalive(db, notifiers, "雪球", f"HTTP {resp.status_code}")
            return
        new_cookie = _merge_cookie_string(cookie, client, "xueqiu.com")
        if new_cookie:
            db.set_setting(XUEQIU_COOKIE_KEY, new_cookie)
            db.set_setting(XUEQIU_COOKIE_TIME_KEY, str(int(time.time())))
            db.set_setting(SOURCE_ERR_KEY.format(platform="xueqiu"), "")
    finally:
        if owns_client:
            client.close()


def keepalive_weibo_cookie(db: DB, notifiers: list[Notifier], weibo_config, client=None) -> None:
    """定时访问微博首页刷新会话；失效时尝试账号密码自动登录，失败则告警。"""
    from .fetchers.weibo import WEIBO_COOKIE_KEY, WeiboFetcher

    cookie = db.get_setting(WEIBO_COOKIE_KEY) or weibo_config.cookie
    if not cookie:
        return
    import httpx

    owns_client = client is None
    client = client or httpx.Client(
        timeout=20,
        follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Referer": "https://weibo.com/",
            "Cookie": cookie,
        },
    )
    try:
        resp = client.get("https://weibo.com/")
        # 会话有效：最终停留在 weibo.com（未登录会被 302 到 passport 登录页）
        if resp.status_code == 200 and "passport.weibo.com" not in str(resp.url):
            new_cookie = _merge_cookie_string(cookie, client, "weibo.com")
            if new_cookie:
                db.set_setting(WEIBO_COOKIE_KEY, new_cookie)
                db.set_setting(WEIBO_COOKIE_TIME_KEY, str(int(time.time())))
                db.set_setting(SOURCE_ERR_KEY.format(platform="weibo"), "")
            return
        # 会话已失效：有账号密码则自动登录续期，否则告警
        db.set_setting(SOURCE_ERR_KEY.format(platform="weibo"), "保活：会话已失效")
        if weibo_config.username and weibo_config.password:
            try:
                fetcher = WeiboFetcher(weibo_config, db, client=client)
                fetcher._login()
                db.set_setting(WEIBO_COOKIE_TIME_KEY, str(int(time.time())))
                db.set_setting(SOURCE_ERR_KEY.format(platform="weibo"), "")
                logger.info("微博 cookie 保活：已通过账号密码自动续期")
            except Exception as exc:  # noqa: BLE001
                _alert_cookie_keepalive(db, notifiers, "微博", str(exc))
                db.set_setting(SOURCE_ERR_KEY.format(platform="weibo"), f"保活登录失败: {exc}"[:300])
        else:
            # 没有账号密码：直接把二维码发到管理员 TG，扫码后自动保存
            if not _start_weibo_qr_renewal(db, notifiers):
                _alert_cookie_keepalive(db, notifiers, "微博")
    finally:
        if owns_client:
            client.close()


def _start_weibo_qr_renewal(db: DB, notifiers: list[Notifier]) -> bool:
    """把微博扫码二维码发到管理员 TG，后台线程轮询并自动保存 cookie。"""
    import threading

    from .fetchers.weibo import WEIBO_COOKIE_KEY
    from .weibo_qr import create_qr, poll_qr

    now = int(time.time())
    last = db.get_setting(WEIBO_QR_RENEWAL_KEY)
    if last and now - int(last) < WEIBO_QR_RENEWAL_COOLDOWN:
        return False  # 冷却期内不重复发码
    tg = next((n for n in notifiers if n.channel == "telegram"), None)
    if tg is None or not getattr(tg, "chat_id", None):
        return False
    try:
        client, qrid, image_url = create_qr()
        image = client.get(image_url).content
    except Exception as exc:  # noqa: BLE001
        logger.warning("微博续期二维码生成失败: %s", exc)
        return False
    db.set_setting(WEIBO_QR_RENEWAL_KEY, str(now))
    try:
        tg.send_photo(image, "⚠️ 微博会话已过期，请用微博 App 扫码登录（10 分钟内有效）")
    except Exception as exc:  # noqa: BLE001
        logger.warning("微博二维码发送失败: %s", exc)
        client.close()
        return False

    def _poll():
        try:
            for _ in range(200):  # 每 3 秒，最长 10 分钟
                time.sleep(3)
                result = poll_qr(client, qrid)
                if result["status"] in ("pending", "scanned"):
                    continue
                if result["status"] == "ok" and result.get("cookie"):
                    db.set_setting(WEIBO_COOKIE_KEY, result["cookie"])
                    db.set_setting(WEIBO_COOKIE_TIME_KEY, str(int(time.time())))
                    tg.send_text("✅ 微博 cookie 已更新，抓取恢复")
                else:
                    tg.send_text(
                        f"微博扫码未完成：{result.get('detail') or result['status']}，"
                        "可到后台「数据源」页重新扫码"
                    )
                break
            else:
                tg.send_text("微博二维码已过期，可到后台「数据源」页重新扫码")
        except Exception as exc:  # noqa: BLE001
            logger.warning("微博续期轮询异常: %s", exc)
        finally:
            client.close()

    threading.Thread(target=_poll, daemon=True).start()
    return True


class Scheduler:
    def __init__(
        self,
        db,
        fetchers,
        notifiers,
        polling_config,
        notifiers_config=None,
        xueqiu_config=None,
        weibo_config=None,
    ):
        self.db = db
        self.fetchers = fetchers
        self.notifiers = notifiers
        self.polling_config = polling_config
        self.notifiers_config = notifiers_config
        self.xueqiu_config = xueqiu_config
        self.weibo_config = weibo_config
        self.states: dict[str, PlatformState] = {}
        self._digest: dict[int, list[Post]] = {}
        self.retry_queue = PushRetryQueue()
        self._stop = asyncio.Event()
        self._last_cleanup = 0.0
        self._last_digest_flush = time.monotonic()
        self._last_xueqiu_probe = time.monotonic()
        self._last_cookie_keepalive = time.monotonic()
        self._last_retry = 0.0

    def stop(self):
        self._stop.set()
        # 尽力把缓冲中未推送的合并摘要发出去，避免重启/关闭丢消息
        try:
            flush_digest(self.db, self._digest, self.notifiers, self.notifiers_config)
        except Exception:  # noqa: BLE001
            logger.exception("关闭时摘要推送失败")

    async def _send_startup_message(self):
        for notifier in self.notifiers:
            try:
                await asyncio.to_thread(notifier.send_text, "✅ 大V订阅服务已启动")
            except Exception as exc:  # noqa: BLE001
                logger.warning("启动消息发送失败 channel=%s err=%s", notifier.channel, exc)

    async def run(self):
        if self.polling_config.notify_on_start:
            await self._send_startup_message()
        self._recover_failed_pushes()
        while not self._stop.is_set():
            started = time.monotonic()
            interval_seconds = _polling_setting(
                self.db, "config_interval_seconds", self.polling_config.interval_seconds
            )
            priority_interval = _polling_setting(
                self.db,
                "config_priority_interval_seconds",
                self.polling_config.priority_interval_seconds,
            )
            digest_interval = _polling_setting(
                self.db, "config_digest_interval_seconds", self.polling_config.digest_interval_seconds
            )
            try:
                await asyncio.to_thread(
                    poll_once,
                    self.db,
                    self.fetchers,
                    self.notifiers,
                    self.states,
                    self.notifiers_config,
                    interval_seconds,
                    priority_interval,
                    self._digest if digest_interval > 0 else None,
                    self.retry_queue,
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
            # 推送失败重试（每 60 秒检查一次）
            if now_mono - self._last_retry >= 60:
                self._last_retry = now_mono
                for item in self.retry_queue.due():
                    try:
                        self._retry_push(item)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("重试推送失败 channel=%s err=%s", item["channel"], exc)
                        self.retry_queue.fail(item)
            # 合并摘要到点统一推送（普通大V，优先大V保持实时）
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
            probe_interval = _polling_setting(
                self.db,
                "config_source_probe_interval_seconds",
                self.polling_config.source_probe_interval_seconds,
            )
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
            # 雪球/微博 cookie 保活（刷新会话防过期）
            keepalive_interval = _polling_setting(
                self.db,
                "config_cookie_keepalive_interval_seconds",
                self.polling_config.cookie_keepalive_interval_seconds,
            )
            if keepalive_interval > 0 and now_mono - self._last_cookie_keepalive >= keepalive_interval:
                self._last_cookie_keepalive = now_mono
                try:
                    await asyncio.to_thread(
                        keepalive_xueqiu_cookie,
                        self.db,
                        self.notifiers,
                        self.xueqiu_config,
                    )
                    await asyncio.to_thread(
                        keepalive_weibo_cookie,
                        self.db,
                        self.notifiers,
                        self.weibo_config,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("cookie 保活异常")
            # 每日精选：每天到达设定小时且当天未发过时推送
            if self._daily_report_due():
                self.db.set_setting("daily_report_last_date", time.strftime("%Y-%m-%d"))
                try:
                    await asyncio.to_thread(self._send_daily_report)
                except Exception:  # noqa: BLE001
                    logger.exception("每日精选推送异常")
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
            delay = interval_seconds + random.uniform(
                0, self.polling_config.jitter_seconds
            )
            await asyncio.sleep(max(0.0, delay - elapsed))

    def _recover_failed_pushes(self) -> None:
        """重启后把最近 24 小时失败的推送重新入队。"""
        if self.notifiers_config is None:
            return
        from .fetchers.base import Post

        rows = self.db.list_failed_push_logs(since_hours=24, limit=200)
        recovered = 0
        for row in rows:
            post_row = self.db.get_post(row["post_id"])
            if post_row is None:
                continue
            user_id = row["user_id"]
            if user_id is not None:
                user = self.db.get_user(user_id)
                if user is None:
                    continue
                if row["channel"] == "telegram" and not user.get("telegram_chat_id"):
                    continue
                if row["channel"] == "feishu" and not user.get("feishu_open_id"):
                    continue
            post = Post(
                platform=post_row["platform"],
                kol_id=post_row["kol_id"],
                kol_name=post_row["kol_name"] or "",
                external_id=post_row["external_id"],
                title=post_row["title"],
                content=post_row["content"],
                url=post_row["url"],
                published_at=post_row["published_at"],
            )
            self.retry_queue.add(post, row["channel"], user_id)
            recovered += 1
        if recovered:
            logger.info("重启恢复待重试推送 %d 条", recovered)

    def _retry_push(self, item: dict) -> None:
        post = item["post"]
        notifier = self._build_retry_notifier(item["channel"], item["user_id"])
        notifier.notify(post)
        post_id = self.db.get_post_id(post.platform, post.external_id)
        if post_id:
            self.db.mark_failed_push_success(post_id, item["channel"], item["user_id"])
        self.retry_queue.drop(item)

    def _build_retry_notifier(self, channel: str, user_id: int | None):
        from .notifiers.feishu import FeishuNotifier
        from .notifiers.telegram import TelegramNotifier

        if user_id is None:
            for notifier in self.notifiers:
                if notifier.channel == channel:
                    return notifier
            raise RuntimeError(f"无全局通知器: {channel}")
        user = self.db.get_user(user_id)
        if user is None:
            raise RuntimeError("用户不存在")
        if channel == "telegram":
            if not user.get("telegram_chat_id"):
                raise RuntimeError("用户未绑定 Telegram")
            return TelegramNotifier(self.notifiers_config.telegram, chat_id=user["telegram_chat_id"])
        if channel == "feishu":
            if not user.get("feishu_open_id"):
                raise RuntimeError("用户未绑定飞书")
            return FeishuNotifier(
                self.notifiers_config.feishu,
                open_id=user["feishu_open_id"] if not user.get("feishu_chat_id") else None,
                chat_id=user.get("feishu_chat_id") or None,
            )
        raise RuntimeError(f"未知渠道: {channel}")

    def _daily_report_due(self) -> bool:
        hour_cfg = _polling_setting(
            self.db, "config_daily_report_hour", self.polling_config.daily_report_hour
        )
        now = datetime.now()
        if now.hour < hour_cfg:
            return False
        return self.db.get_setting("daily_report_last_date") != now.strftime("%Y-%m-%d")

    def _send_daily_report(self) -> None:
        """给开启每日精选的用户推送今日订阅总览。"""
        if self.notifiers_config is None:
            return
        from .fetchers.base import Post
        from .notifiers.feishu import FeishuNotifier
        from .notifiers.telegram import TelegramNotifier

        since = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        for user in self.db.daily_report_users():
            kol_ids = sorted(self.db.subscribed_kol_ids(user["id"]))
            rows = self.db.list_daily_posts(kol_ids, since, 15)
            if not rows:
                continue
            posts = [
                Post(
                    platform=r["platform"],
                    kol_id=r["kol_id"],
                    kol_name=r["kol_name"] or "",
                    external_id=r["external_id"],
                    title=r["title"],
                    content=r["content"],
                    url=r["url"],
                    published_at=r["published_at"],
                )
                for r in rows
            ]
            if user.get("telegram_chat_id") and self.notifiers_config.telegram.bot_token:
                notifier = TelegramNotifier(
                    self.notifiers_config.telegram, chat_id=user["telegram_chat_id"]
                )
                try:
                    notifier.send_daily(posts)
                    for post in posts:
                        post_id = self.db.get_post_id(post.platform, post.external_id)
                        if post_id:
                            self.db.add_push_log(post_id, "telegram", "success", user_id=user["id"])
                except Exception as exc:  # noqa: BLE001
                    logger.warning("每日精选推送失败 user=%s channel=telegram err=%s", user["username"], exc)
                finally:
                    notifier.client.close()
            if user.get("feishu_open_id"):
                notifier = FeishuNotifier(
                    self.notifiers_config.feishu,
                    open_id=user["feishu_open_id"] if not user.get("feishu_chat_id") else None,
                    chat_id=user.get("feishu_chat_id") or None,
                )
                try:
                    notifier.send_daily(posts)
                    for post in posts:
                        post_id = self.db.get_post_id(post.platform, post.external_id)
                        if post_id:
                            self.db.add_push_log(post_id, "feishu", "success", user_id=user["id"])
                except Exception as exc:  # noqa: BLE001
                    logger.warning("每日精选推送失败 user=%s channel=feishu err=%s", user["username"], exc)
                finally:
                    notifier.client.close()
