"""调度器：轮询抓取、去重入库、推送通知、失败退避。"""
from __future__ import annotations

import asyncio
import email.utils
import json
import logging
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from .channels import channel_enabled
from .db import ALLOWED_PLATFORMS, DB
from .fetchers.base import Fetcher, Post
from .notifiers.base import Notifier

logger = logging.getLogger(__name__)

WEIBO_WARNING_KEY = "weibo_warning_date"
XUEQIU_WARNING_KEY = "xueqiu_warning_date"
PUSH_ALERT_KEY = "push_alert_last_at"
PUSH_ALERT_INTERVAL = 3600
SOURCE_ALERT_INTERVAL = 6 * 3600
SOURCE_FAIL_THRESHOLD = 3
X_DIRECT_ALERT_KEY = "x_direct_alert_at"
X_DIRECT_ALERT_INTERVAL = 6 * 3600
PLATFORM_LABELS = {"xueqiu": "雪球", "combination": "雪球组合", "weibo": "微博", "twitter": "X"}
SOURCE_OK_KEY = "source_ok_{platform}"
SOURCE_ERR_KEY = "source_err_{platform}"
SOURCE_FAILS_KEY = "source_fails_{platform}"
XUEQIU_PROBE_ALERT_KEY = "xueqiu_probe_alert_at"
COOKIE_KEEPALIVE_ALERT_KEY = "cookie_keepalive_alert_at"
WEIBO_COOKIE_TIME_KEY = "weibo_cookie_updated_at"
WEIBO_QR_RENEWAL_KEY = "weibo_qr_renewal_at"
# 平台级健康阈值告警：与 maybe_alert_source_failure（单 KOL 连续失败）互补，
# 管「平台整体变差但每轮恰有 1 个大V成功」的温水煮蛙场景。每 6 小时最多一条。
SOURCE_HEALTH_ALERT_KEY = "source_health_alert_at"
SOURCE_HEALTH_MIN_ATTEMPTS = 10  # 24h 尝试次数门槛，够多才评估成功率避免偶发误报
SOURCE_HEALTH_LOW_RATE = 70.0  # 24h 成功率低于此值告警
SOURCE_HEALTH_SILENT_HOURS = 6  # 超过 N 小时无成功抓取判定「整体静默」
SOURCE_HEALTH_CHECK_INTERVAL = 600  # 主循环里每 10 分钟检查一次
WEIBO_QR_RENEWAL_COOLDOWN = 15 * 60

# X 网页端公开的 guest bearer token（来自 abs.twimg.com 前端包），用于内部翻译接口
X_GUEST_BEARER_TOKEN = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)


def extract_tweet_id(external_id: str) -> str:
    """从 x.com / twitter.com 状态链接或纯 ID 里提取数字推文 ID。"""
    match = re.search(r"(?:x\.com|twitter\.com)/\w+/status/(\d+)", external_id or "")
    if match:
        return match.group(1)
    return (external_id or "").strip()


def parse_twitter_cookie(cookie: str) -> dict:
    """从完整 Cookie 字符串里解析 X 官方翻译所需的 auth_token / ct0。"""
    out: dict[str, str] = {}
    for part in (cookie or "").split(";"):
        part = part.strip()
        if "=" in part:
            key, _, value = part.partition("=")
            if key.strip() in ("auth_token", "ct0"):
                out[key.strip()] = value.strip()
    return out


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


# 无新帖自适应降频：空轮越多间隔越长（2 倍步进），有新帖立即恢复基础间隔。
# 以下为默认值，均可在后台「数据源」页抓取设置区调参（config_* 即时生效）：
#   普通大V空轮封顶 900s（合并推送周期 600s，低活跃大V晚几分钟看到可接受）；
#   优先大V温和拉伸封顶 180s（实时性最坏 +2min）；X 降级 RSSHub 期间再 ×4（封顶 1800s）；
#   雪球组合独立高频档：基础 30s、空轮封顶 120s，调仓最坏 ~2min 内发现并实时推送；
#   次要大V低频档：基础 900s（15min）、空轮封顶 3600s（1h）、长摘要 3600s（1h）。
NORMAL_IDLE_CAP_SECONDS = 900
PRIORITY_IDLE_CAP_SECONDS = 180
X_FALLBACK_CAP_SECONDS = 1800
COMBINATION_BASE_SECONDS = 30
COMBINATION_IDLE_CAP_SECONDS = 120
SECONDARY_BASE_SECONDS = 900
SECONDARY_IDLE_CAP_SECONDS = 3600
SECONDARY_DIGEST_INTERVAL_SECONDS = 3600
SECONDARY_MIN_DIGEST_COUNT = 1


def _frequency_setting(db: DB, key: str, default: int) -> int:
    """读取后台可覆盖的采集频率参数（config_*），未设置/非法时用默认常量。"""
    if db is None:
        return default
    value = db.get_setting(key)
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _in_x_fallback(db: DB) -> bool:
    """X 直抓当前是否处于 RSSHub 降级状态（最近一次降级晚于最近一次直抓成功）。"""
    fallback_at = db.get_setting("x_direct_last_fallback_at")
    if not fallback_at:
        return False
    direct_ok = db.get_setting("x_direct_last_ok_at")
    return not direct_ok or fallback_at > direct_ok


def _effective_interval(
    db: DB,
    kol: dict,
    state: PlatformState,
    interval_seconds: int,
    priority_interval_seconds: int,
) -> int:
    """单个大V本轮的有效抓取间隔。

    基础间隔（雪球组合高频档 > 优先大V > 普通大V）× 空轮拉伸（2 倍步进，
    封顶）→ 有效间隔；平台为 X 且处于 RSSHub 降级时再 ×4（封顶），
    避免打爆备用通道。各档位数值可在后台「数据源」页调参。
    """
    if kol["platform"] == "combination":
        base = _frequency_setting(db, "config_combination_base_seconds", COMBINATION_BASE_SECONDS)
        cap = _frequency_setting(
            db, "config_combination_idle_cap_seconds", COMBINATION_IDLE_CAP_SECONDS
        )
    else:
        if kol.get("priority"):
            base = priority_interval_seconds
            cap = _frequency_setting(db, "config_priority_idle_cap_seconds", PRIORITY_IDLE_CAP_SECONDS)
        elif kol.get("secondary"):
            base = _frequency_setting(db, "config_secondary_base_seconds", SECONDARY_BASE_SECONDS)
            cap = _frequency_setting(db, "config_secondary_idle_cap_seconds", SECONDARY_IDLE_CAP_SECONDS)
        else:
            base = interval_seconds
            cap = _frequency_setting(db, "config_normal_idle_cap_seconds", NORMAL_IDLE_CAP_SECONDS)
    empty = min(state.empty_rounds.get(kol["id"], 0), 6)
    effective = min(base * (2**empty), cap)
    if kol["platform"] == "twitter" and db is not None and _in_x_fallback(db):
        x_cap = _frequency_setting(db, "config_x_fallback_cap_seconds", X_FALLBACK_CAP_SECONDS)
        effective = min(effective * 4, x_cap)
    return effective


def translate_text(
    text: str,
    target: str = "zh-CN",
    client=None,
    xai_key: str | None = None,
    model: str | None = None,
    tweet_id: str | None = None,
    twitter_cookie: str | None = None,
) -> str:
    """把 X 内容转成中文。

    优先用 X 官方翻译（同网页版 Grok 翻译，需 X 登录 cookie，免 API key）；
    未提供 cookie 时按 xAI Grok → Google → MyMemory 降级。
    """
    import httpx

    text = (text or "").strip()
    if not text:
        return text
    xai_key = xai_key or os.environ.get("XAI_API_KEY", "")
    model = model or os.environ.get("XAI_MODEL", "") or "grok-2-latest"
    if twitter_cookie is None:
        twitter_cookie = os.environ.get("TWITTER_COOKIE", "")
    owns_client = client is None
    client = client or httpx.Client(timeout=15)
    errors = []
    try:
        # 0) X 官方翻译：与 X 网页版同源（内部 Grok），需要登录 cookie + 推文 ID，免 API key
        x_cookie = parse_twitter_cookie(twitter_cookie)
        if tweet_id and x_cookie.get("auth_token") and x_cookie.get("ct0"):
            try:
                resp = client.post(
                    "https://api.x.com/2/grok/translation.json",
                    headers={
                        "Authorization": f"Bearer {X_GUEST_BEARER_TOKEN}",
                        "Content-Type": "application/json",
                        "Cookie": (
                            f"auth_token={x_cookie['auth_token']}; ct0={x_cookie['ct0']}; lang=zh-CN"
                        ),
                        "x-csrf-token": x_cookie["ct0"],
                        "x-twitter-active-user": "yes",
                        "User-Agent": (
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                        ),
                    },
                    json={
                        "content_type": "POST",
                        "id": tweet_id,
                        "dst_lang": "zh-cn",
                        "include_polls": True,
                    },
                )
                resp.raise_for_status()
                translated = ((resp.json() or {}).get("result") or {}).get("text") or ""
                if translated.strip():
                    return translated.strip()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"x_translate: {exc}")
        # 1) Grok（xAI API，质量好，需 Key）
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
        # 2) Google translate（海外网络可用）
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
        # 3) MyMemory（国内网络可用，单条限 500 字符）
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
        # external_id 在不同平台可能相同（如数字 UID），key 必须带上平台避免互相覆盖
        key = (channel, user_id, post.platform, post.external_id)
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


def _sub_type_matches(sub_type: str, post_type: str) -> bool:
    """订阅类型（post/reply/both）是否覆盖这条动态（post/reply/空）。"""
    if post_type == "reply":
        return sub_type in ("reply", "both")
    return sub_type in ("post", "both", "")


# 渠道选择判断与 channels.channel_enabled 逐字一致，本地别名保持调用点不变
_channel_enabled = channel_enabled


def _can_still_push(user: dict, channel: str, post: Post, db: DB) -> bool:
    """推送前复查用户状态：通知开关、渠道选择与绑定、订阅关系与类型是否仍成立。

    失败重试/重启恢复时使用，避免退订、关闭通知或改选渠道的用户仍收到旧帖重试。
    """
    if not user or not user.get("notify_enabled"):
        return False
    if not _channel_enabled(user, channel):
        return False
    if channel == "telegram" and not user.get("telegram_chat_id"):
        return False
    if channel == "feishu" and not (user.get("feishu_open_id") or user.get("feishu_chat_id")):
        return False
    if channel == "wecom" and not user.get("wecom_webhook"):
        return False
    if channel == "bark" and not user.get("bark_key"):
        return False
    sub_type = db.subscribed_kol_types(user["id"]).get(post.kol_id)
    if sub_type is None:
        return False
    return _sub_type_matches(sub_type, post.post_type)


def _in_dnd_window(user: dict, now=None) -> bool:
    """用户是否处于免打扰时段（支持跨午夜；start/end 留空或相同时关闭）。"""
    start = (user.get("dnd_start") or "").strip()
    end = (user.get("dnd_end") or "").strip()
    if not start or not end or start == end:
        return False
    now = now or datetime.now()
    cur = now.strftime("%H:%M")
    if start < end:
        return start <= cur < end
    return cur >= start or cur < end  # 跨午夜（如 23:00-07:00）


def _dnd_favorite_passthrough(user: dict) -> bool:
    """用户是否允许「特别关注」的大V穿透免打扰（默认不穿透）。"""
    return bool(user.get("dnd_allow_favorite"))


def _keyword_hit(keywords: list[str], post: Post) -> bool:
    """帖子正文/标题是否命中任一关键词（大小写不敏感）。"""
    if not keywords:
        return False
    text = ((post.content or "") + "\n" + (post.title or "")).lower()
    return any(kw.lower() in text for kw in keywords if kw.strip())


class PlatformState:
    """每个平台连续失败次数、退避截止时间与各 KOL 空轮计数。"""

    def __init__(self):
        self.fail_count = 0
        self.skip_until = 0.0
        self.last_fetched: dict[int, float] = {}
        self.empty_rounds: dict[int, int] = {}  # 无新帖连续空轮数，驱动自适应降频
        self.alerted = False


# 告警总开关：默认 None 时回退环境变量 ALERTS_ENABLED（兼容测试与老配置）；
# 应用启动时由 main.py 按 config.alerts_enabled 注入（config.yaml 与环境变量均可配置）
_ALERTS_ENABLED_FLAG: bool | None = None


def set_alerts_enabled(value: bool) -> None:
    """应用启动时注入告警总开关（config.alerts_enabled 统一来源）。"""
    global _ALERTS_ENABLED_FLAG
    _ALERTS_ENABLED_FLAG = bool(value)


def _alerts_enabled() -> bool:
    """管理员告警总开关（默认 true）。

    本地开发/测试实例务必置 false：用生产 config 启动时会抢生产 bot 轮询、
    并向真实管理员误发告警（典型场景：没配 TWITTER_COOKIE 触发 X 降级告警）。
    """
    if _ALERTS_ENABLED_FLAG is not None:
        return _ALERTS_ENABLED_FLAG
    return os.environ.get("ALERTS_ENABLED", "true").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def maybe_alert_source_failure(
    db: DB, notifiers: list[Notifier], platform: str, kol_name: str, detail: str, fail_count: int
) -> None:
    """数据源连续失败时向管理员推送告警（每平台每 6 小时最多一次）。"""
    if not _alerts_enabled():
        return
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
    if not _alerts_enabled():
        return
    label = PLATFORM_LABELS.get(platform, platform)
    message = f"✅ 数据源已恢复：{label}「{kol_name}」重新抓取成功。"
    for notifier in notifiers:
        try:
            notifier.send_text(message)
        except Exception as exc:  # noqa: BLE001
            logger.warning("数据源恢复通知发送失败 channel=%s err=%s", notifier.channel, exc)


def maybe_alert_source_health(db: DB, notifiers: list[Notifier]) -> None:
    """平台级健康阈值告警：24h 成功率过低、或长时间无成功抓取（整体静默）。

    与 maybe_alert_source_failure（单 KOL 连续失败）互补——那个管单点失败，
    这里管「平台整体变差但每轮恰有 1 个大V成功」的温水煮蛙场景：
    降频后每轮 KOL 少，成功率口径可能仍高，但若长时间整体没成功就该人工介入。
    每 6 小时最多一条（SOURCE_ALERT_INTERVAL），多平台问题合并推送。
    """
    if not _alerts_enabled():
        return
    now = int(time.time())
    last = db.get_setting(SOURCE_HEALTH_ALERT_KEY)
    if last:
        try:
            if now - int(last) < SOURCE_ALERT_INTERVAL:
                return
        except (TypeError, ValueError):
            pass
    issues = []
    for platform in sorted(ALLOWED_PLATFORMS):
        if not any(k["enabled"] for k in db.list_kols(platform=platform)):
            continue  # 无启用大V的平台不评估
        label = PLATFORM_LABELS.get(platform, platform)
        # 1) 24h 成功率过低（尝试次数足够多才评估，避免偶发误报）
        ev = db.source_event_stats(platform, 24)
        total = ev["ok"] + ev["fail"]
        if total >= SOURCE_HEALTH_MIN_ATTEMPTS:
            rate = ev["ok"] * 100 / total
            if rate < SOURCE_HEALTH_LOW_RATE:
                issues.append(
                    f"{label}：24h 成功率 {rate:.0f}%（成功 {ev['ok']}/失败 {ev['fail']}）"
                )
        # 2) 长时间无成功抓取（整体静默，如平台全挂但退避未触发单点告警）
        ok_at = db.get_setting(f"source_ok_{platform}")
        if ok_at:
            try:
                silent_hours = (now - int(ok_at)) / 3600
            except (TypeError, ValueError):
                silent_hours = 0
            if silent_hours >= SOURCE_HEALTH_SILENT_HOURS:
                issues.append(f"{label}：已 {silent_hours:.0f} 小时无成功抓取")
    if not issues:
        return
    db.set_setting(SOURCE_HEALTH_ALERT_KEY, str(now))
    message = "⚠️ 数据源健康告警\n" + "\n".join(f"· {i}" for i in issues)
    for notifier in notifiers:
        try:
            notifier.send_text(message)
        except Exception as exc:  # noqa: BLE001
            logger.warning("数据源健康告警发送失败 channel=%s err=%s", notifier.channel, exc)


def maybe_warn_weibo_login(db: DB, notifiers: list[Notifier], detail: str) -> None:
    """微博自动登录失败时向各渠道推告警，每天最多一次。"""
    if not _alerts_enabled():
        return
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
    if not _alerts_enabled():
        return
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
    if not _alerts_enabled():
        return
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


def _x_fallback_advice(reason: str) -> str:
    """按降级原因给出对应建议，避免把瞬时故障误报成 Cookie 失效。

    优先看响应体里的 X 错误 code（_graphql 已把 code 拼进原因）：
    - code 353：X 反爬规则更新（需会话绑定的 guest token），要升级代码
    - code 89 / 32：auth token 真失效，才建议重新登录
    - queryId：接口轮换，要更新代码
    无 code 的裸 401/403 两者皆有可能，提示兼顾。
    """
    text = (reason or "").lower()
    if "code 353" in text:
        return "X 反爬规则已更新（GraphQL 需会话绑定的 guest token），需要升级代码后重新部署。"
    if any(k in text for k in ("invalidrequest", "queryid")):
        return "X 已轮换 GraphQL queryId，需要更新代码中的 DEFAULT_QUERY_IDS 后重新部署。"
    if "未配置" in text and "twitter_cookie" in text:
        return "未配置 TWITTER_COOKIE，请在部署环境配置后重启。"
    if any(k in text for k in (
        "code 89", "code 32", "invalid or expired token",
        "could not authenticate", "not authorized",
    )):
        return "请检查 TWITTER_COOKIE 是否失效，必要时重新登录 X 更新 Cookie。"
    if any(k in text for k in (
        "500", "502", "503", "504", "429", "serviceunavailable", "unavailable",
        "ssl", "timeout", "timed out", "eof", "connection", "reset", "network",
        "deadline",  # DeadlineExceeded: X 后端超时，同 503 一类瞬时故障
    )):
        return "X 服务端暂时不可用或网络抖动，已自动回退 RSSHub，无需操作；持续出现再检查 Cookie。"
    if any(k in text for k in ("401", "403", "forbidden", "unauthorized")):
        return "X 拒绝了请求（401/403）：请检查 TWITTER_COOKIE 是否失效（Cookie 刚更新仍复现则可能是 X 接口规则变更，需升级代码）。"
    return "已自动回退 RSSHub 备用通道，请留意后续是否持续降级。"


def maybe_alert_x_fallback(db: DB, notifiers: list[Notifier]) -> None:
    """X 直抓降级到 RSSHub 备用通道时通知管理员（每 6 小时最多一次）。"""
    if not _alerts_enabled():
        return
    fallback_at = db.get_setting("x_direct_last_fallback_at")
    if not fallback_at:
        return
    try:
        fallback_ts = int(fallback_at)
    except (TypeError, ValueError):
        return
    now = int(time.time())
    last = db.get_setting(X_DIRECT_ALERT_KEY)
    if last:
        try:
            if int(last) >= fallback_ts:
                return  # 本次降级已告警过
            if now - int(last) < X_DIRECT_ALERT_INTERVAL:
                return  # 仍在告警冷却期
        except (TypeError, ValueError):
            pass
    reason = db.get_setting("x_direct_fallback_reason") or "X 官方接口不可用"
    message = (
        "⚠️ X 直抓已降级到 RSSHub 备用通道\n"
        f"原因：{reason[:200]}\n"
        f"{_x_fallback_advice(reason)}"
    )
    for notifier in notifiers:
        try:
            notifier.send_text(message)
        except Exception as exc:  # noqa: BLE001
            logger.warning("X 降级告警发送失败 channel=%s err=%s", notifier.channel, exc)
    db.set_setting(X_DIRECT_ALERT_KEY, str(now))


def notify_subscribers(
    db: DB,
    post_id: int,
    post: Post,
    notifiers_config,
    notifiers=None,
    retry_queue: PushRetryQueue | None = None,
    client=None,
    dnd_buffer: dict[int, list[Post]] | None = None,
    secondary_buffer: dict[int, list[Post]] | None = None,
) -> None:
    """把新帖推送给订阅了该大V的用户（各自绑定的渠道）。"""
    if notifiers_config is None:
        return
    import httpx

    from .channels import CHANNELS, channel_bound, channel_enabled, deliver_post

    owns_client = client is None
    client = client or httpx.Client(timeout=15)
    try:
        for user in db.subscribers_of_kol(post.kol_id):
            sub_type = user.get("subscribe_type") or "post"
            if not _sub_type_matches(sub_type, post.post_type):
                continue  # 订阅类型不覆盖该动态（帖子/回复分订）
            favorite = bool(user.get("favorite"))
            keywords = db.get_user_keywords(user["id"])
            keyword_hit = _keyword_hit(keywords, post)
            if (
                dnd_buffer is not None
                and _in_dnd_window(user)
                and not (favorite and _dnd_favorite_passthrough(user))
                and not keyword_hit
            ):
                # 免打扰时段：缓冲，结束时统一补一条汇总（关键词命中实时穿透）
                dnd_buffer.setdefault(user["id"], []).append(post)
                continue
            # 个人次要：非 favorite 用户进延迟缓冲，按 digest 周期统一推摘要
            if bool(user.get("secondary")) and not favorite and secondary_buffer is not None:
                secondary_buffer.setdefault(user["id"], []).append(post)
                continue
            for channel in CHANNELS:
                if not channel_enabled(user, channel) or not channel_bound(user, channel, notifiers_config):
                    continue
                deliver_post(
                    db,
                    post_id,
                    post,
                    user,
                    channel,
                    notifiers_config,
                    client,
                    retry_queue=retry_queue,
                    alert_notifiers=notifiers,
                    alert_cb=maybe_alert_push_failure,
                    favorite=favorite,
                    keyword=keyword_hit,
                    secondary=bool(user.get("secondary")),
                )
    finally:
        if owns_client:
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
    dnd_buffer: dict[int, list[Post]] | None = None,
    secondary_buffer: dict[int, list[Post]] | None = None,
    llm_config=None,
) -> None:
    """执行一轮：并发抓取启用 KOL → 去重 → 推送。"""
    states = states if states is not None else {}
    now = time.monotonic()
    # 无人订阅的大V不抓取：没有订阅者就没有推送/阅读对象，白耗抓取配额。
    # 新上架的大V需要先有用户订阅（订阅广场/组合订阅）才开始抓取。
    subscribed_ids = db.kol_ids_with_subscribers()
    jobs = []
    for kol in db.list_kols():
        if not kol["enabled"]:
            continue
        if kol["id"] not in subscribed_ids:
            continue
        fetcher = fetchers.get(kol["platform"])
        if fetcher is None:
            continue
        state = states.setdefault(kol["platform"], PlatformState())
        if now < state.skip_until:
            continue
        # 自适应间隔：优先大V更短，空轮拉伸，X 降级 RSSHub 期间加倍
        effective = _effective_interval(
            db, kol, state, interval_seconds, priority_interval_seconds
        )
        # 从未抓取过的大V首轮立即抓取（monotonic 基准在容器启动早期可能小于间隔，
        # 用「从未抓取」标记判断而不是拿 0 当基准，避免首轮被误跳过）
        if kol["id"] in state.last_fetched and now - state.last_fetched[kol["id"]] < effective:
            continue
        jobs.append((kol, fetcher, state))
    if not jobs:
        maybe_alert_x_fallback(db, notifiers)
        return
    # 并发抓取：跨平台并行、同平台最多 2 个并发，兼顾提速与反爬风控
    platforms = {kol["platform"] for kol, _, _ in jobs}
    platform_sem = {p: threading.Semaphore(2) for p in platforms}
    platform_lock = {p: threading.Lock() for p in platforms}
    # 本轮各平台 ok/fail 计数（稳定性事件表，避免每轮每个大V都记一条）
    round_stats: dict[str, dict] = {}

    import httpx

    client = httpx.Client(timeout=15)
    try:
        def _worker(job):
            kol, fetcher, state = job
            with platform_sem[kol["platform"]]:
                _fetch_kol_once(
                    db,
                    fetchers,
                    notifiers,
                    states,
                    kol,
                    fetcher,
                    state,
                    now,
                    interval_seconds,
                    priority_interval_seconds,
                    notifiers_config,
                    digest,
                    retry_queue,
                    platform_lock[kol["platform"]],
                    client,
                    dnd_buffer,
                    secondary_buffer,
                    round_stats,
                    llm_config,
                )

        with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as ex:
            list(ex.map(_worker, jobs))
        for platform, st in round_stats.items():
            if st["ok"]:
                db.add_source_event(
                    platform,
                    "ok",
                    f"ok={st['ok']} fail={st['fail']}",
                    ok_count=st["ok"],
                )
            if st["fail"]:
                db.add_source_event(
                    platform,
                    "fail",
                    f"fail={st['fail']} ok={st['ok']} kol={st['kol']} err={st['err'][:200]}",
                    fail_count=st["fail"],
                )
            # 健康最终状态按整轮聚合写入（worker 内不再写），并发顺序不再影响结果
            if st["fail"]:
                db.set_setting(SOURCE_ERR_KEY.format(platform=platform), st["err"][:300])
                db.set_setting(SOURCE_FAILS_KEY.format(platform=platform), str(st["fail"]))
                db.set_setting(
                    f"source_next_retry_at_{platform}",
                    str(int(time.time()) + min(30 * (2 ** (st["fail"] - 1)), 600)),
                )
            elif st["ok"]:
                db.set_setting(SOURCE_OK_KEY.format(platform=platform), str(int(time.time())))
                db.set_setting(SOURCE_ERR_KEY.format(platform=platform), "")
                db.set_setting(SOURCE_FAILS_KEY.format(platform=platform), "0")
                # 整轮无失败才清掉重试倒计时；有失败保留，避免并发顺序导致状态抖动
                db.set_setting(f"source_next_retry_at_{platform}", "")
    finally:
        client.close()
    logger.info("轮询完成：%d 个大V，耗时 %.0fms", len(jobs), (time.monotonic() - now) * 1000)
    maybe_alert_x_fallback(db, notifiers)


def _fetch_kol_once(
    db: DB,
    fetchers: dict[str, Fetcher],
    notifiers: list[Notifier],
    states: dict[str, PlatformState],
    kol: dict,
    fetcher: Fetcher,
    state: PlatformState,
    now: float,
    interval_seconds: int,
    priority_interval_seconds: int,
    notifiers_config,
    digest: dict[int, list[Post]] | None,
    retry_queue: PushRetryQueue | None,
    state_lock: threading.Lock,
    client=None,
    dnd_buffer: dict[int, list[Post]] | None = None,
    secondary_buffer: dict[int, list[Post]] | None = None,
    round_stats: dict[str, dict] | None = None,
    llm_config=None,
) -> None:
    """并发 worker：抓取单个大V并处理新帖（状态读写加锁保护）。"""
    effective = _effective_interval(
        db, kol, state, interval_seconds, priority_interval_seconds
    )
    # 与 poll_once 一致：从未抓取过的大V立即抓取，避免用 0 当基准误跳过首轮
    if kol["id"] in state.last_fetched and now - state.last_fetched[kol["id"]] < effective:
        return
    # 轮内随机错峰（0.2~1.2s）：打破同平台并发请求的固定节律指纹，降低被反爬识别的概率
    time.sleep(random.uniform(0.2, 1.2))
    if kol["id"] not in state.last_fetched:
        # 冷启动首轮错峰：避免应用启动瞬间各平台请求同时打出
        time.sleep(random.uniform(0, 5))
    try:
        posts = fetcher.fetch(kol)
    except Exception as exc:  # noqa: BLE001 - 单源失败不影响其他
        with state_lock:
            state.fail_count += 1
            delay = min(30 * (2 ** (state.fail_count - 1)), 600)
            state.skip_until = time.monotonic() + delay
            if round_stats is not None:
                st = round_stats.setdefault(
                    kol["platform"], {"ok": 0, "fail": 0, "err": "", "kol": ""}
                )
                st["fail"] += 1
                st["err"] = str(exc)[:300]
                st["kol"] = kol["name"]
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
        # 数据源健康最终状态由 poll_once 依据 round_stats 聚合后一次性写入，
        # 避免并发 worker 互相清空同平台的成功/失败状态
        return
    with state_lock:
        if state.alerted:
            maybe_alert_source_recovered(db, notifiers, kol["platform"], kol["name"])
            state.alerted = False
        state.fail_count = 0
        state.last_fetched[kol["id"]] = now
        if round_stats is not None:
            st = round_stats.setdefault(
                kol["platform"], {"ok": 0, "fail": 0, "err": "", "kol": ""}
            )
            st["ok"] += 1
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
                tweet_id = extract_tweet_id(post.external_id)
                x_cookie = parse_twitter_cookie(os.environ.get("TWITTER_COOKIE", ""))
                if tweet_id and x_cookie.get("auth_token") and x_cookie.get("ct0"):
                    # X 官方翻译按整条推文返回，翻译一次后拆出标题
                    translated = translate_text(
                        post.content or "",
                        tweet_id=tweet_id,
                        twitter_cookie=os.environ.get("TWITTER_COOKIE", ""),
                    )
                    post.content = translated
                    post.title = translated.splitlines()[0][:80] if translated else (post.title or "")
                else:
                    post.title = translate_text(post.title or "")
                    post.content = translate_text(post.content or "")
            except Exception as exc:  # noqa: BLE001 - 翻译失败退回原文
                logger.warning("X 内容翻译失败 post=%s err=%s", post.external_id, exc)
    # 关键词规则打标：仅对新帖（与翻译同判据），纯本地计算零成本，异常不影响入库
    try:
        from .tagging import rule_tag_posts, stock_tag_posts

        fresh = [p for p in posts if db.get_post_id(p.platform, p.external_id) is None]
        if fresh:
            tag_rules = db.get_tag_vocabulary()
            tagged = rule_tag_posts(fresh, tag_rules)
            stock_names = db.get_stock_names()
            stock_aliases = db.get_stock_aliases()
            stock_tagged = stock_tag_posts(fresh, stock_names, aliases=stock_aliases)
            for i, post in enumerate(fresh):
                # 合并：话题标签（≤3）+ 股票标签（≤2），总上限 5
                topics = tagged.get(i, [])
                stocks = stock_tagged.get(i, [])
                post.tags = list(topics[:3]) + list(stocks[:2])
    except Exception as exc:  # noqa: BLE001 - 打标失败不影响抓取/推送
        logger.warning(
            "规则打标失败 platform=%s kol=%s err=%s", kol["platform"], kol["name"], exc
        )
    # 批量入库（一个事务），再逐条推送
    # 首次抓取判定：该大V库中尚无任何帖子 → 本轮仅建立历史基线，不推送。
    # 否则订阅新大V时，最近 N 条历史帖会一次性连推（连珠炮刷屏）。
    first_fetch = not db.kol_has_posts(kol["id"])
    post_ids = db.insert_posts_batch(posts)
    # 空轮判定用「本轮是否新增入库」：时间线接口总是返回最近 N 条（含旧帖），
    # 用 posts 是否为空会永远判为有新帖，降频失效；有新帖立即重置，否则空轮 +1
    new_count = sum(1 for pid in post_ids if pid is not None)
    with state_lock:
        state.empty_rounds[kol["id"]] = 0 if new_count else state.empty_rounds.get(kol["id"], 0) + 1
    for post, post_id in zip(posts, post_ids):
        if post_id is None:
            continue
        logger.info("新帖 platform=%s kol=%s id=%s", post.platform, post.kol_name, post.external_id)
        if first_fetch:
            continue  # 首轮仅入库建基线，历史帖不推送；后续轮次新帖正常推送
        if not kol.get("priority") and kol["platform"] != "combination":
            if kol.get("secondary"):
                if secondary_buffer is not None:
                    # 次要大V：所有非特别关注订阅者进用户级合并缓冲，
                    # 跨大V按 secondary_digest_interval 周期统一推一条摘要
                    _buffer_secondary_subscribers(db, kol["id"], post, secondary_buffer)
                else:
                    # 次要合并禁用（secondary_digest_interval=0）时实时推送
                    notify_subscribers(
                        db, post_id, post, notifiers_config, notifiers, retry_queue,
                        client=client, dnd_buffer=dnd_buffer, secondary_buffer=secondary_buffer,
                    )
            elif digest is not None:
                # 普通大V进入合并摘要缓冲，按 digest_interval 周期统一推送
                digest.setdefault(kol["id"], []).append(post)
                _buffer_personal_secondary(db, kol["id"], post, secondary_buffer)
            else:
                notify_subscribers(
                    db, post_id, post, notifiers_config, notifiers, retry_queue,
                    client=client, dnd_buffer=dnd_buffer, secondary_buffer=secondary_buffer,
                )
        else:
            notify_subscribers(
                db, post_id, post, notifiers_config, notifiers, retry_queue,
                client=client, dnd_buffer=dnd_buffer, secondary_buffer=secondary_buffer,
            )


def _buffer_personal_secondary(db, kol_id: int, post: Post, secondary_buffer) -> None:
    """KOL 级摘要缓冲时，把个人次要用户（非特别关注）的帖子同时进用户级延迟缓冲。

    这些用户不参与 KOL 摘要（notify_digest_subscribers 会跳过），改由用户级
    延迟缓冲按次要合并周期统一推送，避免同一帖双重到达。
    """
    if secondary_buffer is None:
        return
    for user in db.subscribers_of_kol(kol_id):
        if bool(user.get("secondary")) and not bool(user.get("favorite")):
            secondary_buffer.setdefault(user["id"], []).append(post)


def _buffer_secondary_subscribers(db, kol_id: int, post: Post, secondary_buffer) -> None:
    """次要大V新帖：所有非特别关注订阅者进用户级合并缓冲。

    与 _buffer_personal_secondary 的区别：次要大V是全局档位，所有订阅者
    （除特别关注）都应延迟合并推送，而不是只有个人次要用户。多条次要大V
    共享同一缓冲，flush 时按用户跨大V合并成一条摘要，避免每个次要大V
    各发一条摘要。
    """
    if secondary_buffer is None:
        return
    for user in db.subscribers_of_kol(kol_id):
        if not bool(user.get("favorite")):
            secondary_buffer.setdefault(user["id"], []).append(post)


def _user_llm_config(user: dict, fallback=None):
    """用户自配 LLM 优先；不安全地址忽略并回退管理员全局配置。"""
    if not user.get("llm_api_key"):
        return fallback
    from types import SimpleNamespace

    from .url_safety import is_allowed_user_llm_base

    api_base = user.get("llm_api_base") or "https://api.deepseek.com"
    if not is_allowed_user_llm_base(api_base):
        return fallback
    return SimpleNamespace(
        api_base=api_base,
        api_key=user["llm_api_key"],
        model=user.get("llm_model") or "deepseek-chat",
        user_supplied=True,
    )


def notify_digest_subscribers(
    db: DB,
    posts: list[Post],
    kol: dict,
    notifiers_config,
    notifiers=None,
    retry_queue: PushRetryQueue | None = None,
    dnd_buffer: dict[int, list[Post]] | None = None,
    llm_config=None,
    summary_cache: dict | None = None,
) -> None:
    """把合并摘要推送给订阅了该大V的用户（各自绑定的渠道，带退订按钮）。

    用户自配 LLM（或全局 llm_config）时，先发一条 AI 要点再发摘要卡片；
    生成失败自动降级，不影响摘要推送。summary_cache 透传给 summarize_posts，
    同一批帖文多个订阅用户只调一次大模型。
    """
    if notifiers_config is None or not posts:
        return
    import httpx

    from .notifiers.bark import BarkNotifier
    from .notifiers.feishu import FeishuNotifier
    from .notifiers.telegram import TelegramNotifier
    from .notifiers.wecom import WeComNotifier

    client = httpx.Client(timeout=15)
    try:
        for user in db.subscribers_of_kol(kol["id"]):
            sub_type = user.get("subscribe_type") or "post"
            matched = [p for p in posts if _sub_type_matches(sub_type, p.post_type)]
            if not matched:
                continue
            favorite = bool(user.get("favorite"))
            if bool(user.get("secondary")) and not favorite:
                # 个人次要用户不参与 KOL 摘要：帖子已进用户级延迟缓冲，避免重复推送
                continue
            if (
                dnd_buffer is not None
                and _in_dnd_window(user)
                and not (favorite and _dnd_favorite_passthrough(user))
            ):
                # 免打扰时段：摘要也进入免打扰缓冲，结束时统一补推
                dnd_buffer.setdefault(user["id"], []).extend(matched)
                continue
            summary = None
            llm_cfg = _user_llm_config(user, llm_config)
            if llm_cfg is not None:
                try:
                    from .llm import summarize_posts

                    summary = summarize_posts(matched, llm_cfg, cache=summary_cache)
                except Exception as exc:  # noqa: BLE001 - 摘要失败降级，不影响推送
                    logger.warning(
                        "LLM 摘要异常 user=%s kol=%s err=%s", user["username"], kol["name"], exc
                    )
            if user["telegram_chat_id"] and _channel_enabled(user, "telegram") and (
                notifiers_config.telegram.bot_token or user.get("telegram_bot_token")
            ):
                notifier = TelegramNotifier(
                    notifiers_config.telegram,
                    client=client,
                    chat_id=user["telegram_chat_id"],
                    unsub_kol_id=kol["id"],
                    bot_token=user.get("telegram_bot_token") or None,
                    favorite=favorite,
                    secondary=bool(user.get("secondary")),
                )
                try:
                    if summary:
                        notifier.send_text(f"📊 AI 摘要\n\n{summary}")
                    notifier.send_digest(matched, kol["name"], kol["platform"])
                    for post in matched:
                        db.add_push_log(
                            db.get_post_id(post.platform, post.external_id),
                            "telegram",
                            "success",
                            user_id=user["id"],
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("摘要推送失败 user=%s channel=telegram err=%s", user["username"], exc)
                    maybe_alert_push_failure(
                        db,
                        notifiers or [],
                        f"user={user['username']} channel=telegram digest err={exc}",
                    )
                    if retry_queue is not None:
                        for post in matched:
                            retry_queue.add(post, "telegram", user["id"])
                    for post in matched:
                        db.add_push_log(
                            db.get_post_id(post.platform, post.external_id),
                            "telegram",
                            "failed",
                            str(exc),
                            user_id=user["id"],
                        )
            if _channel_enabled(user, "feishu") and (
                user.get("feishu_open_id") or user.get("feishu_chat_id")
            ):
                from .feishu_personal import build_personal_feishu_kwargs

                fs_kwargs = build_personal_feishu_kwargs(db, notifiers_config.feishu, user)
                notifier = FeishuNotifier(
                    notifiers_config.feishu,
                    client=client,
                    open_id=fs_kwargs["open_id"],
                    chat_id=fs_kwargs["chat_id"],
                    unsub_kol_id=kol["id"],
                    favorite=favorite,
                    secondary=bool(user.get("secondary")),
                    app_id=fs_kwargs["app_id"],
                    app_secret=fs_kwargs["app_secret"],
                    interactive_buttons=not bool(fs_kwargs["app_id"]),
                )
                try:
                    if summary:
                        notifier.send_text(f"📊 AI 摘要\n\n{summary}")
                    notifier.send_digest(matched, kol["name"], kol["platform"])
                    for post in matched:
                        db.add_push_log(
                            db.get_post_id(post.platform, post.external_id),
                            "feishu",
                            "success",
                            user_id=user["id"],
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("摘要推送失败 user=%s channel=feishu err=%s", user["username"], exc)
                    maybe_alert_push_failure(
                        db,
                        notifiers or [],
                        f"user={user['username']} channel=feishu digest err={exc}",
                    )
                    if retry_queue is not None:
                        for post in matched:
                            retry_queue.add(post, "feishu", user["id"])
                    for post in matched:
                        db.add_push_log(
                            db.get_post_id(post.platform, post.external_id),
                            "feishu",
                            "failed",
                            str(exc),
                            user_id=user["id"],
                        )
            if user.get("wecom_webhook") and _channel_enabled(user, "wecom"):
                notifier = WeComNotifier(
                    notifiers_config.wecom,
                    client=client,
                    webhook_url=user["wecom_webhook"],
                    favorite=favorite,
                )
                try:
                    if summary:
                        notifier.send_text(f"📊 AI 摘要\n\n{summary}")
                    notifier.send_digest(matched, kol["name"], kol["platform"])
                    for post in matched:
                        db.add_push_log(
                            db.get_post_id(post.platform, post.external_id),
                            "wecom",
                            "success",
                            user_id=user["id"],
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("摘要推送失败 user=%s channel=wecom err=%s", user["username"], exc)
                    maybe_alert_push_failure(
                        db,
                        notifiers or [],
                        f"user={user['username']} channel=wecom digest err={exc}",
                    )
                    if retry_queue is not None:
                        for post in matched:
                            retry_queue.add(post, "wecom", user["id"])
                    for post in matched:
                        db.add_push_log(
                            db.get_post_id(post.platform, post.external_id),
                            "wecom",
                            "failed",
                            str(exc),
                            user_id=user["id"],
                        )
            if user.get("bark_key") and _channel_enabled(user, "bark"):
                notifier = BarkNotifier(
                    getattr(notifiers_config, "bark", None) if notifiers_config is not None else None,
                    client=client,
                    bark_key=user["bark_key"],
                    favorite=favorite,
                )
                try:
                    if summary:
                        notifier.send_text(f"📊 AI 摘要\n\n{summary}")
                    notifier.send_digest(matched, kol["name"], kol["platform"])
                    for post in matched:
                        db.add_push_log(
                            db.get_post_id(post.platform, post.external_id),
                            "bark",
                            "success",
                            user_id=user["id"],
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("摘要推送失败 user=%s channel=bark err=%s", user["username"], exc)
                    maybe_alert_push_failure(
                        db,
                        notifiers or [],
                        f"user={user['username']} channel=bark digest err={exc}",
                    )
                    if retry_queue is not None:
                        for post in matched:
                            retry_queue.add(post, "bark", user["id"])
                    for post in matched:
                        db.add_push_log(
                            db.get_post_id(post.platform, post.external_id),
                            "bark",
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
    dnd_buffer: dict[int, list[Post]] | None = None,
    llm_config=None,
) -> None:
    """到点把缓冲的摘要统一推送给订阅者（不再做全局推送）。"""
    if not digest:
        return
    summary_cache: dict = {}
    items = list(digest.items())
    digest.clear()
    for kol_id, posts in items:
        kol = db.get_kol(kol_id)
        if kol is None or not posts:
            continue
        notify_digest_subscribers(
            db, posts, kol, notifiers_config, notifiers, retry_queue, dnd_buffer, llm_config, summary_cache
        )


def _scheduler_loop_delay(
    interval_seconds: int,
    priority_interval_seconds: int,
    jitter_seconds: int,
    db=None,
) -> float:
    """主循环单轮等待时间：取全局/优先/雪球组合间隔中较小者，保证更短间隔被调度。

    此前主循环固定按全局间隔 sleep，导致 poll_once 里对优先大V的更短到期判断
    永远等不到下一次调用，优先间隔形同虚设。由 poll_once 的内部到期判断决定
    每个 KOL 本轮是否抓取，这里只负责把轮询节奏提到最短间隔。
    """
    combination_base = _frequency_setting(db, "config_combination_base_seconds", COMBINATION_BASE_SECONDS)
    base = min(interval_seconds, priority_interval_seconds, combination_base)
    base = max(base, 1)  # 防御：非法配置（0/负值）不能退化成忙轮询
    return base + random.uniform(0, jitter_seconds)


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
    """定时探测雪球 cookie 是否仍有效，失效时告警（与抓取同路径）。

    首页已被阿里云 WAF JS 挑战页接管，且不再下发登录态 token，无法续期；
    改为请求 timeline JSON 接口（与 probe_xueqiu / fetch 同路径）：
    有效 cookie → 200 正常返回；无/失效 cookie → 400 需登录。
    保活从「续期」退化为「失效检测 + 告警」，cookie 需手动更新。
    """
    from .fetchers.xueqiu import (
        XUEQIU_COOKIE_KEY,
        XUEQIU_COOKIE_TIME_KEY,
        XUEQIU_TIMELINE_URL,
    )

    cookie = db.get_setting(XUEQIU_COOKIE_KEY) or source_config.cookie
    if not cookie:
        return
    # 没有启用的雪球大V则无从探测（与 probe_xueqiu 一致）
    target = next((k for k in db.list_kols(platform="xueqiu") if k["enabled"]), None)
    if target is None:
        return
    import httpx

    owns_client = client is None
    client = client or httpx.Client(
        timeout=20,
        follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)",
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://xueqiu.com/u/{target['external_id']}",
            "Cookie": cookie,
        },
    )
    try:
        resp = client.get(
            XUEQIU_TIMELINE_URL,
            params={"user_id": target["external_id"], "page": 1, "count": 1},
        )
        status = resp.status_code
        if status == 200:
            try:
                resp.json()
            except ValueError:
                status = 0  # 内容不是合法 JSON，按失效处理
        if status != 200:
            db.set_setting(SOURCE_ERR_KEY.format(platform="xueqiu"), "cookie 无效或已过期（保活探测）")
            _alert_cookie_keepalive(db, notifiers, "雪球", f"timeline HTTP {status}")
            return
        # 会话有效：合并本次响应下发的 cookie（一般无新 token，原样保留），更新状态
        new_cookie = _merge_cookie_string(cookie, client, "xueqiu.com")
        if new_cookie:
            db.set_setting(XUEQIU_COOKIE_KEY, new_cookie)
            db.set_setting(XUEQIU_COOKIE_TIME_KEY, str(int(time.time())))
        db.set_setting(SOURCE_OK_KEY.format(platform="xueqiu"), str(int(time.time())))
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
        llm_config=None,
    ):
        self.db = db
        self.fetchers = fetchers
        self.notifiers = notifiers
        self.polling_config = polling_config
        self.notifiers_config = notifiers_config
        self.xueqiu_config = xueqiu_config
        self.weibo_config = weibo_config
        self.llm_config = llm_config
        self.states: dict[str, PlatformState] = {}
        self._digest: dict[int, list[Post]] = {}
        self._dnd_buffer: dict[int, list[Post]] = {}
        self._secondary_buffer: dict[int, list[Post]] = {}
        self._last_secondary_buffer_flush = time.monotonic()
        self.retry_queue = PushRetryQueue()
        self._stop = asyncio.Event()
        self._last_cleanup = 0.0
        self._last_digest_flush = time.monotonic()
        self._last_xueqiu_probe = time.monotonic()
        self._last_cookie_keepalive = time.monotonic()
        self._last_retry = 0.0
        self._last_health_check = time.monotonic()

    def stop(self):
        self._stop.set()
        # 尽力把缓冲中未推送的合并摘要发出去，避免重启/关闭丢消息
        try:
            flush_digest(
                self.db, self._digest, self.notifiers, self.notifiers_config,
                retry_queue=self.retry_queue,
                dnd_buffer=self._dnd_buffer,
            )
        except Exception:  # noqa: BLE001
            logger.exception("关闭时摘要推送失败")
        # 免打扰缓冲也尽量补推（关闭时立即发汇总，避免丢失）
        try:
            self._flush_dnd_buffers(force=True)
        except Exception:  # noqa: BLE001
            logger.exception("关闭时免打扰汇总推送失败")
        # 个人次要缓冲同样补推，避免重启丢消息
        try:
            self._flush_secondary_buffers()
        except Exception:  # noqa: BLE001
            logger.exception("关闭时个人次要缓冲推送失败")

    async def _send_startup_message(self):
        """启动提示只推送给管理员（走管理员各自绑定的渠道），普通用户不推送。"""
        if self.notifiers_config is None:
            return
        import httpx

        from .notifiers.feishu import FeishuNotifier
        from .notifiers.telegram import TelegramNotifier
        from .notifiers.wecom import WeComNotifier

        message = "✅ V Push服务已启动"
        client = httpx.Client(timeout=15)
        sent_any = False
        try:
            admins = [u for u in self.db.list_users() if u.get("is_admin")]
            for user in admins:
                if (
                    user["telegram_chat_id"]
                    and _channel_enabled(user, "telegram")
                    and (self.notifiers_config.telegram.bot_token or user.get("telegram_bot_token"))
                ):
                    notifier = TelegramNotifier(
                        self.notifiers_config.telegram,
                        client=client,
                        chat_id=user["telegram_chat_id"],
                        bot_token=user.get("telegram_bot_token") or None,
                    )
                    try:
                        await asyncio.to_thread(notifier.send_text, message)
                        sent_any = True
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("启动提示 TG 发送失败 user=%s err=%s", user["username"], exc)
                if (user.get("feishu_open_id") or user.get("feishu_chat_id")) and _channel_enabled(
                    user, "feishu"
                ):
                    from .feishu_personal import build_personal_feishu_kwargs

                    fs_kwargs = build_personal_feishu_kwargs(self.db, self.notifiers_config.feishu, user)
                    notifier = FeishuNotifier(
                        self.notifiers_config.feishu,
                        client=client,
                        open_id=fs_kwargs["open_id"],
                        chat_id=fs_kwargs["chat_id"],
                        app_id=fs_kwargs["app_id"],
                        app_secret=fs_kwargs["app_secret"],
                    )
                    try:
                        await asyncio.to_thread(notifier.send_text, message)
                        sent_any = True
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("启动提示飞书发送失败 user=%s err=%s", user["username"], exc)
                if user.get("wecom_webhook") and _channel_enabled(user, "wecom"):
                    notifier = WeComNotifier(
                        self.notifiers_config.wecom,
                        client=client,
                        webhook_url=user["wecom_webhook"],
                    )
                    try:
                        await asyncio.to_thread(notifier.send_text, message)
                        sent_any = True
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("启动提示企业微信发送失败 user=%s err=%s", user["username"], exc)
        finally:
            client.close()
        if not sent_any:
            logger.info("没有可接收启动提示的管理员绑定渠道")

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
            secondary_digest_interval = _polling_setting(
                self.db,
                "config_secondary_digest_interval_seconds",
                self.polling_config.secondary_digest_interval_seconds,
            )
            secondary_min_count = _polling_setting(
                self.db,
                "config_secondary_min_digest_count",
                SECONDARY_MIN_DIGEST_COUNT,
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
                    self._dnd_buffer,
                    secondary_buffer=self._secondary_buffer if secondary_digest_interval > 0 else None,
                    llm_config=self.llm_config,
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
            # 把待重试数量落库，供后台「数据源」页展示
            self.db.set_setting("stats_retry_pending", str(self.retry_queue.pending()))
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
                        self.retry_queue,
                        self._dnd_buffer,
                        self.llm_config,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("摘要推送失败")
            # 次要大V长周期合并摘要到点统一推送：与普通摘要独立计时，
            # 个人次要（bell）用户共用同一缓冲与周期，跨大V合并成一条
            if (
                secondary_digest_interval > 0
                and self._secondary_buffer
                and now_mono - self._last_secondary_buffer_flush >= secondary_digest_interval
            ):
                self._last_secondary_buffer_flush = now_mono
                try:
                    await asyncio.to_thread(self._flush_secondary_buffers, secondary_min_count)
                except Exception:  # noqa: BLE001
                    logger.exception("次要大V合并摘要推送失败")
            # 免打扰时段结束：补推汇总
            try:
                self._flush_dnd_buffers()
            except Exception:  # noqa: BLE001
                logger.exception("免打扰汇总推送失败")
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
            # 每日精选：每天到达设定小时且当天未发过时推送；发送成功才标记已发，
            # 失败保留未发状态下一轮重试，避免发送失败当天漏发
            if self._daily_report_due():
                try:
                    report_ok = await asyncio.to_thread(self._send_daily_report)
                except Exception:  # noqa: BLE001
                    logger.exception("每日精选推送异常")
                    report_ok = False
                if report_ok:
                    self.db.set_setting("daily_report_last_date", time.strftime("%Y-%m-%d"))
            # 平台级健康阈值检查（每 10 分钟一次，轻量 SQL）：成功率过低/整体静默告警
            if now_mono - self._last_health_check >= SOURCE_HEALTH_CHECK_INTERVAL:
                self._last_health_check = now_mono
                try:
                    await asyncio.to_thread(
                        maybe_alert_source_health, self.db, self.notifiers
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("数据源健康告警异常")
            # 股票黑话别名识别 + 误标清理：每天一次（配 LLM 才识别，清理恒执行）
            if self._stock_alias_due():
                try:
                    await asyncio.to_thread(self._run_stock_alias_task)
                except Exception:  # noqa: BLE001
                    logger.exception("股票别名识别异常")
                finally:
                    # 无论成功失败都标记已跑，避免识别失败每天反复重试消耗 token
                    self.db.set_setting("stock_alias_last_date", time.strftime("%Y-%m-%d"))
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
                # 数据源稳定性事件保留 7 天足够看趋势，过长无意义
                try:
                    removed_events = self.db.delete_source_events_older_than(7)
                    if removed_events:
                        logger.info("清理数据源事件 %d 条（保留 7 天）", removed_events)
                except Exception:  # noqa: BLE001
                    logger.exception("数据源事件清理失败")
                # 管理员操作日志保留 180 天，避免无限增长
                try:
                    removed_admin = self.db.delete_admin_logs_older_than(180)
                    if removed_admin:
                        logger.info("清理操作日志 %d 条（保留 180 天）", removed_admin)
                except Exception:  # noqa: BLE001
                    logger.exception("操作日志清理失败")
            elapsed = time.monotonic() - started
            delay = _scheduler_loop_delay(
                interval_seconds,
                priority_interval,
                self.polling_config.jitter_seconds,
                db=self.db,
            )
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=max(0.0, delay - elapsed)
                )
            except TimeoutError:
                pass

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
            kol = self.db.get_kol(post_row["kol_id"])
            try:
                detail = json.loads(post_row["detail"]) if post_row.get("detail") else None
            except (TypeError, ValueError):
                detail = None
            try:
                images = json.loads(post_row["images"]) if post_row.get("images") else []
            except (TypeError, ValueError):
                images = []
            if not isinstance(images, list):
                images = []
            post = Post(
                platform=post_row["platform"],
                kol_id=post_row["kol_id"],
                kol_name=post_row["kol_name"] or "",
                external_id=post_row["external_id"],
                title=post_row["title"],
                content=post_row["content"],
                url=post_row["url"],
                published_at=post_row["published_at"],
                category=(kol or {}).get("category_name") or "",
                post_type=post_row.get("post_type") or "",
                detail=detail,
                images=images,
            )
            # 重试前复查：退订/关闭通知/改选渠道的用户不再恢复推送
            if user_id is not None:
                user = self.db.get_user(user_id)
                if user is None or not _can_still_push(user, row["channel"], post, self.db):
                    continue
            self.retry_queue.add(post, row["channel"], user_id)
            recovered += 1
        if recovered:
            logger.info("重启恢复待重试推送 %d 条", recovered)

    def _retry_push(self, item: dict) -> None:
        post = item["post"]
        user = self.db.get_user(item["user_id"]) if item["user_id"] is not None else None
        # 退订/关闭通知/改选渠道后不再重试旧帖
        if item["user_id"] is not None and (
            user is None or not _can_still_push(user, item["channel"], post, self.db)
        ):
            self.retry_queue.drop(item)
            return
        favorite = bool(
            item["user_id"] is not None
            and post.kol_id in self.db.subscribed_favorite_ids(item["user_id"])
        )
        if (
            user is not None
            and _in_dnd_window(user)
            and not (favorite and _dnd_favorite_passthrough(user))
        ):
            # 免打扰时段内的重试也进免打扰缓冲，避免深夜打扰
            self._dnd_buffer.setdefault(user["id"], []).append(post)
            self.retry_queue.drop(item)
            return
        notifier = self._build_retry_notifier(
            item["channel"], item["user_id"], favorite=favorite, unsub_kol_id=post.kol_id
        )
        try:
            notifier.notify(post)
        finally:
            # 按用户重建的 notifier 持有独立 client，用完即关；
            # user_id 为 None 时复用全局 notifier，不能关它的连接
            if item["user_id"] is not None and getattr(notifier, "client", None) is not None:
                notifier.client.close()
        post_id = self.db.get_post_id(post.platform, post.external_id)
        if post_id:
            # 翻转前取原失败原因落日志：mark_failed_push_success 会清空 error，不记就追溯不到了
            orig_error = self.db.get_failed_push_error(post_id, item["channel"], item["user_id"])
            if orig_error:
                logger.info(
                    "推送重试成功 channel=%s user=%s post=%s（原失败原因: %s）",
                    item["channel"], item["user_id"], post_id, orig_error,
                )
            self.db.mark_failed_push_success(post_id, item["channel"], item["user_id"])
        self.retry_queue.drop(item)

    def _flush_dnd_buffers(self, force: bool = False) -> None:
        """免打扰时段结束后，给每个用户补推一条汇总。"""
        if not self._dnd_buffer:
            return
        now = datetime.now()
        for user_id in list(self._dnd_buffer):
            posts = self._dnd_buffer.get(user_id) or []
            if not posts:
                continue
            user = self.db.get_user(user_id)
            if user is None:
                self._dnd_buffer.pop(user_id, None)
                continue
            if not force and _in_dnd_window(user, now):
                continue  # 仍在免打扰时段，等时段结束再推
            self._dnd_buffer.pop(user_id, None)
            try:
                self._send_dnd_summary(user, posts)
            except Exception as exc:  # noqa: BLE001
                logger.warning("免打扰汇总推送失败 user=%s err=%s", user["username"], exc)

    def _flush_secondary_buffers(self, min_count: int = 1) -> None:
        """次要大V合并缓冲到点：把每位用户积压的新帖以摘要样式推送（跨大V合并）。

        min_count：合并推送最低条数（后台「次要大V合并推送最低条数」），
        积压条数不足时不推、保留继续攒，够数才推。
        """
        if not self._secondary_buffer:
            return
        now = datetime.now()
        for user_id in list(self._secondary_buffer):
            posts = self._secondary_buffer.get(user_id) or []
            if not posts:
                continue
            if len(posts) < min_count:
                continue  # 积压不足最低条数：继续攒，下个周期再判断
            user = self.db.get_user(user_id)
            if user is None:
                self._secondary_buffer.pop(user_id, None)
                continue
            if _in_dnd_window(user, now):
                continue  # 已进入免打扰时段，留给 dnd 机制处理，下轮再试
            self._secondary_buffer.pop(user_id, None)
            try:
                # 次要大V合并：纯汇总即可，不消耗 LLM token（use_llm=False）
                self._send_dnd_summary(user, posts, title="🔕 次要大V合并摘要", use_llm=False)
            except Exception as exc:  # noqa: BLE001
                logger.warning("次要大V汇总推送失败 user=%s err=%s", user["username"], exc)
                # 发送失败：帖子写失败日志并入重试队列（_send_dnd_summary 内部处理），
                # 缓冲已弹出，不重复推送

    def _send_dnd_summary(
        self, user: dict, posts: list[Post], title: str | None = None, use_llm: bool = True
    ) -> None:
        """把缓冲的动态汇总成一条推送给用户（按所选通道），并补写推送日志。

        默认标题为「免打扰时段汇总」；次要大V合并摘要传 title="🔕 次要大V合并摘要"
        且 use_llm=False（纯汇总，不调 LLM 不耗 token）。use_llm=True 时先尝试
        生成 AI 要点（失败自动降级为普通汇总，不影响推送）。
        """
        if self.notifiers_config is None or not posts:
            return
        import httpx

        from .channels import (
            CHANNELS,
            build_channel_notifier,
            channel_bound,
            channel_enabled,
        )

        summary = None
        if use_llm:
            from .llm import summarize_posts

            llm_cfg = _user_llm_config(user, getattr(self, "llm_config", None))
            if llm_cfg is not None:
                try:
                    summary = summarize_posts(posts, llm_cfg)
                except Exception as exc:  # noqa: BLE001 - 摘要失败降级，不影响汇总
                    logger.warning("LLM 摘要异常 user=%s err=%s", user["username"], exc)

        client = httpx.Client(timeout=15)
        try:
            for channel in CHANNELS:
                if not channel_enabled(user, channel) or not channel_bound(user, channel, self.notifiers_config):
                    continue
                try:
                    notifier = build_channel_notifier(channel, user, self.notifiers_config, client=client, db=self.db)
                    if summary:
                        notifier.send_text(f"📊 AI 摘要\n\n{summary}")
                    if title is not None:
                        notifier.send_dnd_summary(posts, title=title)
                    else:
                        notifier.send_dnd_summary(posts)
                    for post in posts:
                        post_id = self.db.get_post_id(post.platform, post.external_id)
                        if post_id:
                            self.db.add_push_log(post_id, channel, "success", user_id=user["id"])
                except Exception as exc:  # noqa: BLE001
                    logger.warning("免打扰汇总 %s 发送失败 user=%s err=%s", channel, user["username"], exc)
                    maybe_alert_push_failure(
                        self.db,
                        self.notifiers or [],
                        f"user={user['username']} channel={channel} dnd err={exc}",
                    )
                    # 失败渠道的帖子逐条写失败日志并入重试队列，避免免打扰缓冲静默丢失；
                    # 重试按单帖发送（_retry_push），不依赖内存中的摘要文本
                    for post in posts:
                        post_id = self.db.get_post_id(post.platform, post.external_id)
                        if post_id:
                            self.db.add_push_log(
                                post_id, channel, "failed", f"dnd summary: {exc}", user_id=user["id"]
                            )
                        self.retry_queue.add(post, channel, user["id"])
        finally:
            client.close()

    def _build_retry_notifier(
        self,
        channel: str,
        user_id: int | None,
        favorite: bool = False,
        unsub_kol_id: int | None = None,
    ):
        from .channels import CHANNEL_LABELS, build_channel_notifier, channel_bound

        if user_id is None:
            for notifier in self.notifiers:
                if notifier.channel == channel:
                    return notifier
            raise RuntimeError(f"无全局通知器: {channel}")
        user = self.db.get_user(user_id)
        if user is None:
            raise RuntimeError("用户不存在")
        if not channel_bound(user, channel, self.notifiers_config):
            raise RuntimeError(f"用户未绑定 {CHANNEL_LABELS.get(channel, channel)}")
        return build_channel_notifier(
            channel,
            user,
            self.notifiers_config,
            favorite=favorite,
            unsub_kol_id=unsub_kol_id,
            db=self.db,
        )

    def _daily_report_due(self) -> bool:
        hour_cfg = _polling_setting(
            self.db, "config_daily_report_hour", self.polling_config.daily_report_hour
        )
        now = datetime.now()
        if now.hour < hour_cfg:
            return False
        return self.db.get_setting("daily_report_last_date") != now.strftime("%Y-%m-%d")

    def _stock_alias_due(self) -> bool:
        """股票别名识别任务是否到期：每天最多一次（settings 日期键控制）。"""
        return self.db.get_setting("stock_alias_last_date") != datetime.now().strftime("%Y-%m-%d")

    def _run_stock_alias_task(self) -> None:
        """股票黑话别名自动识别（LLM，每日一次）+ 历史误标清理（纯规则）。

        识别流程：取最近帖子 → 提取候选词 → LLM 判断别名 → high 置信度写入别名表；
        然后清理不在当前有效标签集合里的旧标签（观点/策略/生活等残留）。
        未配置 LLM 时跳过识别（不阻塞清理）。
        """
        from .fetchers.base import Post
        from .tagging import (
            cleanup_stale_tags,
            extract_alias_candidates,
        )

        # 1) 误标清理：有效标签 = 话题词表 + 股票名表 + 别名正式名
        tag_rules = self.db.get_tag_vocabulary()
        stock_names = self.db.get_stock_names()
        aliases = self.db.get_stock_aliases()
        valid_tags = [r["tag"] for r in tag_rules] + stock_names
        valid_tags += [a["stock"] for a in aliases]
        try:
            removed = cleanup_stale_tags(self.db, valid_tags)
            if removed:
                logger.info("清理过期贴文标签 %d 条", removed)
        except Exception as exc:  # noqa: BLE001
            logger.warning("贴文标签清理失败: %s", exc)

        # 2) 别名识别：需要 LLM 配置
        llm_cfg = getattr(self, "llm_config", None)
        if llm_cfg is None or not getattr(llm_cfg, "api_key", ""):
            return
        try:
            from .llm import resolve_stock_marks, suggest_stock_aliases
            from .tagging import extract_stock_marks

            # 取最近 500 帖做候选词提取
            rows = self.db.list_posts(limit=500)
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
                    post_type=r.get("post_type") or "",
                )
                for r in rows
            ]
            known = valid_tags  # 股票名 + 话题 + 现有别名正式名
            candidates = extract_alias_candidates(posts, known)
            if not candidates:
                logger.info("股票别名识别：本轮无候选词")
            else:
                suggestions = suggest_stock_aliases(candidates, stock_names, llm_cfg)
                # 只采纳 high 置信度（medium 留给人看/后续修正）
                new_aliases = [s for s in suggestions if s.get("confidence") == "high"]
                # 去重合并写入（别名不重复、上限 200 条防膨胀）
                existing = {a["alias"] for a in aliases}
                merged = list(aliases)
                for s in new_aliases:
                    if s["alias"] not in existing and len(merged) < 200:
                        merged.append({"alias": s["alias"], "stock": s["stock"]})
                        existing.add(s["alias"])
                if new_aliases:
                    self.db.set_stock_aliases(merged)
                    logger.info(
                        "股票别名识别：新增 %d 个别名（共 %d）", len(new_aliases), len(merged)
                    )

            # 3) $标记$ 自动扩充：新官方名进名表，戏称/简称进别名表（精确来源，带代码）
            marks = extract_stock_marks(posts)
            known_names = {n for n in stock_names}
            known_names.update(a["alias"] for a in aliases)
            known_names.update(a["stock"] for a in aliases)
            known_names.update(r["tag"] for r in tag_rules)
            new_marks = [(n, c) for n, c in marks if n not in known_names]
            if new_marks:
                resolved = resolve_stock_marks(new_marks, llm_cfg)
                if resolved:
                    new_stock_names = list(stock_names)
                    new_aliases_list = list(aliases)
                    existing_aliases = {a["alias"] for a in aliases}
                    existing_stocks = set(new_stock_names)
                    for item in resolved:
                        if not item.get("is_alias"):
                            # 官方名 → 股票名表
                            official = item["official"]
                            if official not in existing_stocks and len(new_stock_names) < 200:
                                new_stock_names.append(official)
                                existing_stocks.add(official)
                        else:
                            # 戏称 → 别名表；同时确保正式名在名表（否则别名无对照）
                            official = item["official"]
                            if official not in existing_stocks and len(new_stock_names) < 200:
                                new_stock_names.append(official)
                                existing_stocks.add(official)
                            alias = item["name"]
                            if alias not in existing_aliases and len(new_aliases_list) < 200:
                                new_aliases_list.append({"alias": alias, "stock": official})
                                existing_aliases.add(alias)
                    if new_stock_names != stock_names:
                        self.db.set_stock_names(new_stock_names)
                        logger.info(
                            "$标记$ 自动扩充：股票名表新增 %d 只（共 %d）",
                            len(new_stock_names) - len(stock_names),
                            len(new_stock_names),
                        )
                    if new_aliases_list != aliases:
                        self.db.set_stock_aliases(new_aliases_list)
                        logger.info(
                            "$标记$ 自动扩充：别名表新增 %d 条（共 %d）",
                            len(new_aliases_list) - len(aliases),
                            len(new_aliases_list),
                        )
        except Exception as exc:  # noqa: BLE001
            logger.warning("股票别名识别异常: %s", exc)

    def _send_daily_report(self) -> bool:
        """给开启每日精选的用户推送今日订阅总览；全部成功返回 True，任一失败返回 False。

        返回 False 时调用方不标记「今日已发」，下一轮会重试，避免发送失败当天漏发。
        """
        if self.notifiers_config is None:
            return True
        # 清理过期的每日精选投递状态（每天一次，防止表无限增长）
        try:
            self.db.delete_daily_report_deliveries_older_than(
                max(1, getattr(self.polling_config, "push_logs_retention_days", 90))
            )
        except Exception:  # noqa: BLE001 - 清理失败不影响推送
            logger.warning("每日精选投递状态清理失败", exc_info=True)
        from .feishu_personal import build_personal_feishu_kwargs
        from .fetchers.base import Post
        from .notifiers.bark import BarkNotifier
        from .notifiers.feishu import FeishuNotifier
        from .notifiers.telegram import TelegramNotifier
        from .notifiers.wecom import WeComNotifier

        failed = False
        report_date = datetime.now().strftime("%Y-%m-%d")
        since = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())

        def _deliver(channel: str, condition: bool, build_notifier, user) -> None:
            """按渠道幂等投递每日精选：当日该渠道已成功则跳过（部分失败重试不重复发）。

            成功立即标记投递状态（持久化，进程重启也不重复）；异常只标记该渠道失败。
            """
            nonlocal failed
            if not condition:
                return
            if self.db.daily_report_delivered(user["id"], report_date, channel):
                logger.info(
                    "每日精选 channel=%s 当日已投递成功，跳过 user=%s",
                    channel, user["username"],
                )
                return
            notifier = build_notifier()
            try:
                if daily_text:
                    notifier.send_text(daily_text)
                else:
                    notifier.send_daily(posts)
                for post in posts:
                    post_id = self.db.get_post_id(post.platform, post.external_id)
                    if post_id:
                        self.db.add_push_log(post_id, channel, "success", user_id=user["id"])
                self.db.mark_daily_report_delivered(user["id"], report_date, channel)
            except Exception as exc:  # noqa: BLE001
                failed = True
                self.db.mark_daily_report_failed(user["id"], report_date, channel)
                logger.warning(
                    "每日精选推送失败 user=%s channel=%s err=%s", user["username"], channel, exc
                )
                maybe_alert_push_failure(
                    self.db,
                    self.notifiers or [],
                    f"user={user['username']} channel={channel} daily err={exc}",
                )
            finally:
                client = getattr(notifier, "client", None)
                if client is not None:
                    client.close()

        for user in self.db.daily_report_users():
            kol_ids = sorted(
                self.db.readable_subscribed_kol_ids(user["id"], bool(user.get("is_admin")))
            )
            rows = self.db.list_daily_posts(kol_ids, since, 15, user_id=user["id"])
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
                    favorite=bool(r.get("favorite")),
                )
                for r in rows
            ]
            summary = None
            # 每日综述是系统级推送内容，用全局 LLM 配置保证输出格式稳定；
            # 用户级自配模型（可能含推理模型）继续用于 digest/免打扰汇总。
            llm_cfg = getattr(self, "llm_config", None)
            if llm_cfg is not None:
                try:
                    from .llm import summarize_daily

                    summary = summarize_daily(posts, llm_cfg)
                except Exception as exc:  # noqa: BLE001 - 综述失败降级为原始列表，不影响推送
                    logger.warning("LLM 每日综述异常 user=%s err=%s", user["username"], exc)
            # LLM 精炼综述优先；未配置/失败时降级为原始贴文列表（保底不空发）
            daily_text = None
            if summary is not None:
                from .llm import render_daily_summary

                daily_text = render_daily_summary(summary, posts)

            _deliver(
                "telegram",
                bool(
                    user.get("telegram_chat_id")
                    and _channel_enabled(user, "telegram")
                    and (
                        self.notifiers_config.telegram.bot_token or user.get("telegram_bot_token")
                    )
                ),
                lambda u=user: TelegramNotifier(
                    self.notifiers_config.telegram,
                    chat_id=u["telegram_chat_id"],
                    bot_token=u.get("telegram_bot_token") or None,
                ),
                user,
            )
            _deliver(
                "feishu",
                bool(
                    _channel_enabled(user, "feishu")
                    and (user.get("feishu_open_id") or user.get("feishu_chat_id"))
                ),
                lambda u=user: FeishuNotifier(
                    self.notifiers_config.feishu,
                    **build_personal_feishu_kwargs(self.db, self.notifiers_config.feishu, u),
                ),
                user,
            )
            _deliver(
                "wecom",
                bool(user.get("wecom_webhook") and _channel_enabled(user, "wecom")),
                lambda u=user: WeComNotifier(
                    self.notifiers_config.wecom,
                    webhook_url=u["wecom_webhook"],
                ),
                user,
            )
            _deliver(
                "bark",
                bool(user.get("bark_key") and _channel_enabled(user, "bark")),
                lambda u=user: BarkNotifier(bark_key=u["bark_key"]),
                user,
            )
        return not failed
