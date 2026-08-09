"""REST API：认证、订阅目录、我的动态、KOL/分类管理。"""
from __future__ import annotations

import logging
import os
import re
import secrets
import time

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel

from . import auth, wechat
from .avatar_cache import cache_avatar
from .bot_core import BIND_CODE_TTL
from .db import ALLOWED_PLATFORMS, DB
from .feed import build_rss_xml
from .fetchers.base import Post
from .fetchers.combination import extract_cube_symbol, resolve_combination_profile
from .fetchers.twitter import resolve_x_profile
from .fetchers.weibo import WEIBO_COOKIE_KEY, resolve_weibo_profile
from .fetchers.xueqiu import (
    XUEQIU_COOKIE_KEY,
    XUEQIU_COOKIE_TIME_KEY,
    resolve_profile,
)
from .weibo_qr import create_qr, poll_qr

# 关键词提醒规则上限（每个用户）与单关键词长度上限
KEYWORDS_MAX_COUNT = 20
KEYWORDS_MAX_LENGTH = 50


def _normalize_weibo_id(external_id: str) -> str:
    """微博主页链接（https://weibo.com/u/<uid>）提取 UID。"""
    match = re.search(r"weibo\.com/u/(\d+)", external_id)
    return match.group(1) if match else external_id


def _account_key(username: str) -> str:
    """账号锁定/失败计数的统一键：去空白 + casefold。

    登录大小写不敏感（COLLATE NOCASE），锁定键必须同样规范化，
    否则 Alice/alice 会用不同字典键分散失败计数、绕过账号锁定。
    """
    return (username or "").strip().casefold()


def _resolve_telegram_bot(token: str) -> tuple[str, str, str]:
    """验证用户自建 bot token：返回 (bot_username, chat_id, error)。

    自动通过 getUpdates 识别用户给自己 bot 发消息时的 chat_id，
    用户无需手动填写 chat_id。
    """
    import httpx

    try:
        with httpx.Client(timeout=15) as client:
            me = client.get(f"https://api.telegram.org/bot{token}/getMe")
            me.raise_for_status()
            me_data = me.json()
            if not me_data.get("ok"):
                return "", "", f"token 无效：{me_data.get('description', '未知错误')}"
            bot_username = (me_data.get("result") or {}).get("username") or ""
            updates = client.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"limit": 5},
            )
            updates.raise_for_status()
            up_data = updates.json()
            if not up_data.get("ok"):
                return bot_username, "", (
                    f"获取会话失败：{up_data.get('description', '未知错误')}"
                )
            chat_ids = []
            for update in up_data.get("result") or []:
                msg = update.get("message") or {}
                chat_id = (msg.get("chat") or {}).get("id")
                if chat_id:
                    chat_ids.append(str(chat_id))
            if not chat_ids:
                return bot_username, "", "请先给你的机器人发一条消息（如 /start），再点保存"
            return bot_username, chat_ids[-1], ""
    except Exception as exc:  # noqa: BLE001
        return "", "", f"无法连接 Telegram：{exc}"


class RegisterIn(BaseModel):
    username: str
    password: str
    code: str = ""


class LoginIn(BaseModel):
    username: str
    password: str


class WechatLoginIn(BaseModel):
    code: str


class MeUpdate(BaseModel):
    telegram_chat_id: str | None = None
    telegram_bot_token: str | None = None
    feishu_open_id: str | None = None
    feishu_chat_id: str | None = None
    wecom_webhook: str | None = None
    bark_key: str | None = None
    notify_enabled: bool | None = None
    daily_report_enabled: bool | None = None
    push_channels: str | None = None
    dnd_start: str | None = None
    dnd_end: str | None = None
    dnd_allow_favorite: bool | None = None
    keywords: list[str] | None = None
    llm_api_base: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None


class PasswordChangeIn(BaseModel):
    old_password: str
    new_password: str


class KolIn(BaseModel):
    platform: str
    name: str
    external_id: str
    category_id: int | None = None
    priority: bool = False
    original_only: bool = False


class KolBatchIn(BaseModel):
    platform: str = "xueqiu"
    lines: str
    category_id: int | None = None
    priority: bool = False
    original_only: bool = False


class KolUpdate(BaseModel):
    name: str | None = None
    external_id: str | None = None
    enabled: bool | None = None
    category_id: int | None = None
    priority: bool | None = None
    is_private: bool | None = None
    visible_users: list[str] | None = None
    original_only: bool | None = None


class CategoryIn(BaseModel):
    name: str


class TagRuleIn(BaseModel):
    tag: str
    keywords: list[str] = []


class TagAliasIn(BaseModel):
    alias: str
    stock: str


class TagVocabularyIn(BaseModel):
    tags: list[TagRuleIn]
    stock_names: list[str] = []
    stock_aliases: list[TagAliasIn] = []


class TagBackfillIn(BaseModel):
    limit: int = 200


class KolRequestIn(BaseModel):
    platform: str
    external_id: str
    name: str = ""


class RegisterCodeGenIn(BaseModel):
    count: int = 5
    note: str = ""


class PollingConfigIn(BaseModel):
    interval_seconds: int | None = None
    priority_interval_seconds: int | None = None
    digest_interval_seconds: int | None = None
    source_probe_interval_seconds: int | None = None
    cookie_keepalive_interval_seconds: int | None = None
    daily_report_hour: int | None = None
    translate_twitter_content: bool | None = None


class CookieIn(BaseModel):
    cookie: str


class SubscriptionIn(BaseModel):
    kol_id: int
    type: str = "post"


class SubscriptionTypeIn(BaseModel):
    type: str


class SubscriptionFavoriteIn(BaseModel):
    favorite: bool


class UserUpdate(BaseModel):
    is_admin: bool | None = None
    password: str | None = None
    username: str | None = None


class TestPushIn(BaseModel):
    user_id: int
    message: str = "这是一条测试推送 ✅"


def public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "username": user["username"],
        "is_admin": bool(user["is_admin"]),
        "telegram_chat_id": user["telegram_chat_id"],
        "custom_telegram_bot": bool(user.get("telegram_bot_token")),
        "feishu_open_id": user["feishu_open_id"],
        "feishu_chat_id": user["feishu_chat_id"],
        "wecom_webhook": user["wecom_webhook"],
        "bark_key": user.get("bark_key") or "",
        "feed_token": user.get("feed_token") or "",
        "notify_enabled": bool(user["notify_enabled"]),
        "daily_report_enabled": bool(user.get("daily_report")),
        "push_channels": user.get("push_channels") or "",
        "dnd_start": user.get("dnd_start") or "",
        "dnd_end": user.get("dnd_end") or "",
        "dnd_allow_favorite": bool(user.get("dnd_allow_favorite")),
        "llm_api_base": user.get("llm_api_base") or "",
        "llm_api_key": user.get("llm_api_key") or "",
        "llm_model": user.get("llm_model") or "",
        "created_at": user["created_at"],
    }


# 图片代理白名单图床：这些域名在部分家庭/公司网络会被 DNS 劫持到透明代理网段
# （198.18/15 保留段），SSRF 的 IP 网段校验会误拒。白名单内放宽网段校验，
# 但仍强制图片类型与大小限制，避免被当作任意内容代理。
IMAGE_PROXY_HOSTS = frozenset({
    "pbs.twimg.com", "video.twimg.com", "abs.twimg.com",
    "xqimg.imedao.com", "xueqiuimg.com",
    "wx1.sinaimg.cn", "wx2.sinaimg.cn", "wx3.sinaimg.cn", "wx4.sinaimg.cn",
})


def admin_user_summary(user: dict) -> dict:
    """管理员用户列表摘要：只暴露管理所需字段，不含 feed_token/bark_key/wecom_webhook/llm_api_key 等凭证。"""
    return {
        "id": user["id"],
        "username": user["username"],
        "is_admin": bool(user["is_admin"]),
        "created_at": user["created_at"],
        "notify_enabled": bool(user["notify_enabled"]),
        "daily_report_enabled": bool(user.get("daily_report")),
        "push_channels": user.get("push_channels") or "",
        "telegram_bound": bool(user.get("telegram_chat_id")),
        "feishu_bound": bool(user.get("feishu_open_id") or user.get("feishu_chat_id")),
        "wecom_bound": bool(user.get("wecom_webhook")),
        "bark_bound": bool(user.get("bark_key")),
        "custom_telegram_bot": bool(user.get("telegram_bot_token")),
    }


def bounded_limit(value: int, default: int = 100) -> int:
    """分页 limit 统一钳制：负数/0 按 1 处理（SQLite 的 LIMIT -1 表示不限制），上限 500。"""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(value, 500))


def _prune_window_dict(
    entries: dict[str, list[float]],
    window: float,
    now: float,
    max_entries: int,
) -> None:
    """限流字典清理：删除全部已过期条目（无论列表是否为空），仍超上限时删最旧。

    旧的清理只删 `not v` 的空列表键，而窗口外记录的列表本身非空，导致过期条目
    永不清理、字典可持续增长。这里按当前时间过滤每个键的所有时间戳。
    """
    expired = [
        k for k, ts_list in entries.items()
        if not any(now - t < window for t in ts_list)
    ]
    for k in expired:
        entries.pop(k, None)
    if len(entries) > max_entries:
        # 删最旧：按每条记录的最后失败时间排序，只保留最近的 max_entries 条
        oldest = sorted(entries.keys(), key=lambda k: max(entries[k]))
        for k in oldest[: len(entries) - max_entries]:
            entries.pop(k, None)


def create_api_router(
    db: DB,
    secret: str,
    allow_register: bool = True,
    wechat_config=None,
    notifiers_config=None,
    trust_proxy: bool = False,
) -> APIRouter:
    router = APIRouter(prefix="/api")
    # 登录/注册限流（内存版，单实例够用）：每 IP 窗口内失败次数超限后 429
    login_attempts: dict[str, list[float]] = {}
    LOGIN_MAX_FAILURES = 8
    LOGIN_WINDOW = 300
    # 账号级失败锁定（防 IP 轮换爆破，独立于上面的 IP 限流）：
    # 1 小时滚动窗口内连续失败超阈值即锁定该账号，锁定期内即使密码正确也拒绝；
    # 管理员账号更敏感（3 次锁 30 分钟），普通账号 10 次锁 15 分钟；成功登录立即解锁。
    account_failures: dict[str, list[float]] = {}  # username -> [窗口内失败时间戳]
    account_locked_until: dict[str, float] = {}  # username -> 解锁时间戳
    ACCOUNT_FAILURE_WINDOW = 3600
    LOGIN_ACCOUNT_LOCK_THRESHOLD = 10
    LOGIN_ACCOUNT_LOCK_WINDOW = 900
    ADMIN_LOGIN_LOCK_THRESHOLD = 3
    ADMIN_LOGIN_LOCK_WINDOW = 1800
    MAX_PASSWORD_LEN = 128
    # 微博扫码登录会话：qrid -> {client, created_at}
    weibo_qr_sessions: dict[str, dict] = {}

    def _client_ip(request: Request) -> str:
        """优先取 X-Forwarded-For 首段（仅当位于可信反代之后），否则用直连 IP。

        未配置 trust_proxy 时若直接信任该头，攻击者改 header 即可绕过登录/注册限流。
        """
        if trust_proxy:
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                first = forwarded.split(",")[0].strip()
                if first:
                    return first
        return request.client.host if request.client else "unknown"

    def _check_login_limit(ip: str) -> None:
        now = time.time()
        recent = [t for t in login_attempts.get(ip, []) if now - t < LOGIN_WINDOW]
        login_attempts[ip] = recent
        if len(recent) >= LOGIN_MAX_FAILURES:
            raise HTTPException(status_code=429, detail="尝试次数过多，请 5 分钟后再试")
        # 每次登录尝试顺带清理全量过期 IP 记录，防止无界增长（不能只删空列表）
        _prune_window_dict(login_attempts, LOGIN_WINDOW, now, max_entries=1000)

    def _record_login_failure(ip: str) -> None:
        login_attempts.setdefault(ip, []).append(time.time())

    def _account_lock_seconds_left(username: str) -> int:
        """账号剩余锁定秒数；未锁定返回 0（过期记录自动清理）。"""
        key = _account_key(username)
        until = account_locked_until.get(key)
        if not until:
            return 0
        left = int(until - time.time())
        if left <= 0:
            account_locked_until.pop(key, None)
            return 0
        return left

    def _record_account_failure(username: str, is_admin: bool, ip: str) -> None:
        """账号级失败计数（1 小时滚动窗口）；超阈值锁定账号并写操作日志。"""
        key = _account_key(username)
        now = time.time()
        recent = [t for t in account_failures.get(key, []) if now - t < ACCOUNT_FAILURE_WINDOW]
        recent.append(now)
        account_failures[key] = recent
        threshold = ADMIN_LOGIN_LOCK_THRESHOLD if is_admin else LOGIN_ACCOUNT_LOCK_THRESHOLD
        if len(recent) >= threshold:
            window = ADMIN_LOGIN_LOCK_WINDOW if is_admin else LOGIN_ACCOUNT_LOCK_WINDOW
            account_locked_until[key] = now + window
            db.log_admin_action(
                None,
                "login_locked",
                username,
                f"ip={ip} role={'admin' if is_admin else 'user'} 1小时内失败{len(recent)}次，锁定{window // 60}分钟",
            )
        # 每次失败顺带清理全量过期账号记录，防止无界增长（不能只删空列表）
        _prune_window_dict(account_failures, ACCOUNT_FAILURE_WINDOW, now, max_entries=2000)

    def _audit(admin: dict, action: str, target: str = "", detail: str = "") -> None:
        db.log_admin_action(admin["id"], action, target, detail)

    def _notify_admins_new_request(platform: str, ref: str, requester: dict) -> None:
        """新的大V添加申请：按管理员各自绑定的渠道通知。"""
        if notifiers_config is None:
            return
        import httpx

        from .channels import CHANNELS, build_channel_notifier, channel_bound

        label = {"xueqiu": "雪球", "combination": "雪球组合", "weibo": "微博", "twitter": "X"}.get(
            platform, platform
        )
        message = (
            f"🆕 新的大V添加申请：{label}「{ref}」\n"
            f"申请人：{requester['username']}\n"
            "请到管理后台「求添加」审批。"
        )
        client = httpx.Client(timeout=15)
        try:
            for user in db.list_users():
                if not user.get("is_admin"):
                    continue
                for channel in CHANNELS:
                    if not channel_bound(user, channel, notifiers_config):
                        continue
                    try:
                        notifier = build_channel_notifier(channel, user, notifiers_config, client=client, db=db)
                        notifier.send_text(message)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "大V申请通知失败 user=%s channel=%s err=%s",
                            user["username"],
                            channel,
                            exc,
                        )
        finally:
            client.close()

    POLLING_FIELDS = [
        ("interval_seconds", "config_interval_seconds", "stats_polling_interval", 1, 3600),
        (
            "priority_interval_seconds",
            "config_priority_interval_seconds",
            "stats_priority_interval_seconds",
            1,
            600,
        ),
        ("digest_interval_seconds", "config_digest_interval_seconds", "stats_digest_interval_seconds", 0, 86400),
        (
            "source_probe_interval_seconds",
            "config_source_probe_interval_seconds",
            "stats_source_probe_interval_seconds",
            0,
            86400,
        ),
        (
            "cookie_keepalive_interval_seconds",
            "config_cookie_keepalive_interval_seconds",
            "stats_keepalive_interval",
            0,
            86400,
        ),
        ("daily_report_hour", "config_daily_report_hour", "stats_daily_report_hour", 0, 23),
    ]

    def _effective_polling() -> dict:
        out = {}
        for name, cfg_key, stat_key, _lo, _hi in POLLING_FIELDS:
            raw = db.get_setting(cfg_key) or db.get_setting(stat_key)
            try:
                out[name] = int(raw)
            except (TypeError, ValueError):
                out[name] = 0
        out["translate_twitter_content"] = (
            db.get_setting("config_translate_twitter_content") == "1"
        )
        return out

    def get_current_user(authorization: str | None = Header(None)):
        token = ""
        if authorization and authorization.startswith("Bearer "):
            token = authorization[7:]
        payload = auth.verify_token(token, secret)
        if not payload:
            raise HTTPException(status_code=401, detail="未登录或登录已过期")
        user = db.get_user(payload.get("uid"))
        if user is None:
            raise HTTPException(status_code=401, detail="用户不存在")
        return user

    def require_admin(user: dict = Depends(get_current_user)):
        if not user["is_admin"]:
            raise HTTPException(status_code=403, detail="需要管理员权限")
        return user

    # ---- 认证 ----
    @router.get("/version")
    def version_info():
        """当前版本与 GitHub 最新版本（带缓存），用于前端更新提示。"""
        from .version import APP_VERSION, is_newer, latest_github_version

        latest, has = latest_github_version(db)
        return {
            "current": APP_VERSION,
            "latest": latest,
            "update_available": bool(has and is_newer(latest, APP_VERSION)),
            "url": "https://github.com/icekale/dav-subscription/releases",
        }

    @router.post("/auth/register")
    def register(body: RegisterIn, request: Request):
        if not allow_register:
            raise HTTPException(status_code=403, detail="暂未开放注册")
        ip = _client_ip(request)
        _check_login_limit(ip)
        try:
            username = body.username.strip()
            if len(username) < 6 or len(body.password) < 6:
                raise HTTPException(status_code=400, detail="用户名至少6位，密码至少6位")
            if len(username) > 30:
                raise HTTPException(status_code=400, detail="用户名最长30位")
            if len(body.password) > MAX_PASSWORD_LEN:
                raise HTTPException(status_code=400, detail=f"密码最长{MAX_PASSWORD_LEN}位")
            if not body.code.strip():
                raise HTTPException(status_code=400, detail="注册需要邀请码，请向管理员索取")
            try:
                # 管理员只能在网页后台指定，注册用户一律为普通用户
                uid = db.register_with_code(body.code, username, auth.hash_password(body.password))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from None
        except HTTPException:
            # 注册失败同样计入限流，避免邀请码爆破
            _record_login_failure(ip)
            raise
        user = db.get_user(uid)
        return {"token": auth.create_token(uid, username, secret), "user": public_user(user)}

    @router.post("/auth/login")
    def login(body: LoginIn, request: Request):
        ip = _client_ip(request)
        _check_login_limit(ip)
        username = body.username.strip()
        locked_left = _account_lock_seconds_left(username)
        if locked_left > 0:
            # 锁定期内一律拒绝（即使密码正确），不泄露密码有效性，也不再累计计数
            minutes = max(1, (locked_left + 59) // 60)
            raise HTTPException(
                status_code=429,
                detail=f"该账号因多次失败登录被临时锁定，请约 {minutes} 分钟后再试",
            )
        # 注册按 COLLATE NOCASE 判重，登录同样大小写不敏感，避免同名不同大小写无法登录
        user = db.get_user_by_username_ci(username)
        if user is None:
            auth.verify_password(body.password, auth.DUMMY_HASH)
            _record_login_failure(ip)
            _record_account_failure(username, False, ip)
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        if not user["password_hash"]:
            # 机器人/微信自动创建的账号没有密码，不能通过账号密码登录
            auth.verify_password(body.password, auth.DUMMY_HASH)
            _record_login_failure(ip)
            _record_account_failure(username, bool(user["is_admin"]), ip)
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        if not body.password or len(body.password) > MAX_PASSWORD_LEN:
            _record_login_failure(ip)
            _record_account_failure(username, bool(user["is_admin"]), ip)
            raise HTTPException(status_code=400, detail=f"密码长度需在 1-{MAX_PASSWORD_LEN} 位之间")
        if not auth.verify_password(body.password, user["password_hash"]):
            _record_login_failure(ip)
            _record_account_failure(username, bool(user["is_admin"]), ip)
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        login_attempts.pop(ip, None)  # 登录成功清零，避免历史失败锁住正常用户
        account_failures.pop(_account_key(username), None)
        account_locked_until.pop(_account_key(username), None)
        return {"token": auth.create_token(user["id"], user["username"], secret), "user": public_user(user)}

    @router.post("/auth/wechat")
    def wechat_login(body: WechatLoginIn):
        if wechat_config is None or not wechat_config.app_id or not wechat_config.app_secret:
            raise HTTPException(status_code=400, detail="未配置微信小程序 app_id/app_secret")
        try:
            data = wechat.code2session(body.code, wechat_config.app_id, wechat_config.app_secret)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from None
        openid = data["openid"]
        user = db.get_user_by_openid(openid)
        if user is None:
            base = f"wx_{openid[:10]}"
            username, i = base, 1
            while db.get_user_by_username_ci(username) is not None:
                username = f"{base}{i}"
                i += 1
            uid = db.add_user(
                username,
                "",
                wechat_openid=openid,
            )
            user = db.get_user(uid)
        return {"token": auth.create_token(user["id"], user["username"], secret), "user": public_user(user)}

    # ---- 我的 ----
    @router.get("/feed/{token}.xml")
    def rss_feed(token: str, request: Request):
        """私有 RSS 订阅源：token 即凭证，无需登录（供 RSS 阅读器拉取）。"""
        user = db.get_user_by_feed_token(token)
        if user is None:
            raise HTTPException(status_code=404, detail="feed 地址无效或已失效")
        kol_ids = db.readable_subscribed_kol_ids(user["id"], bool(user.get("is_admin")))
        posts = db.list_feed_posts(kol_ids, limit=50, user_id=user["id"])
        base = str(request.base_url).rstrip("/")
        xml = build_rss_xml(posts, user["username"], base)
        return Response(
            content=xml,
            media_type="application/rss+xml; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    @router.post("/me/feed-token/regenerate")
    def regenerate_feed_token(user: dict = Depends(get_current_user)):
        """重新生成 RSS 订阅 token：旧 token 立即失效（比如地址泄露后）。"""
        db.update_user(user["id"], feed_token=secrets.token_urlsafe(32))
        return {"feed_token": db.get_user(user["id"])["feed_token"]}

    @router.get("/me")
    def me(user: dict = Depends(get_current_user)):
        # 首次访问即确保 feed token 存在，RSS 地址在推送设置页展示
        db.ensure_feed_token(user["id"])
        user = db.get_user(user["id"])
        profile = public_user(user)
        profile["subscription_count"] = db.count_subscriptions(user["id"])
        profile["keywords"] = db.get_user_keywords(user["id"])
        if notifiers_config is not None:
            profile["push_guide"] = {
                "telegram_bot_username": notifiers_config.telegram.bot_username,
                "feishu_bot_name": notifiers_config.feishu.bot_name,
            }
        from .feishu_personal import FeishuPersonalManager, mask_app_id

        fs_personal_mgr = FeishuPersonalManager(
            db, notifiers_config.feishu if notifiers_config is not None else None
        )
        personal_bot = db.get_feishu_personal_bot(user["id"])
        profile["feishu_personal"] = {
            "available": fs_personal_mgr.available(),
            "status": personal_bot["status"] if personal_bot else "",
            "app_id_masked": mask_app_id(personal_bot["app_id"]) if personal_bot else "",
        }
        return profile

    @router.put("/me")
    def update_me(body: MeUpdate, user: dict = Depends(get_current_user)):
        if "telegram_chat_id" in body.model_fields_set:
            value = (body.telegram_chat_id or "").strip()
            if value:
                owner = db.get_user_by_telegram(value)
                if owner is not None and owner["id"] != user["id"]:
                    raise HTTPException(status_code=400, detail="该 Telegram 已绑定其他账号")
            db.update_user(user["id"], telegram_chat_id=value)
        if "telegram_bot_token" in body.model_fields_set:
            value = (body.telegram_bot_token or "").strip()
            if value:
                owner = db.get_user_by_telegram_bot(value)
                if owner is not None and owner["id"] != user["id"]:
                    raise HTTPException(status_code=400, detail="该机器人 token 已被其他账号使用")
                _bot_username, chat_id, error = _resolve_telegram_bot(value)
                if not chat_id:
                    raise HTTPException(
                        status_code=400,
                        detail=f"自建机器人绑定失败：{error}",
                    )
                db.update_user(
                    user["id"],
                    telegram_bot_token=value,
                    telegram_chat_id=chat_id,
                )
            else:
                db.update_user(user["id"], telegram_bot_token="")
        if "feishu_open_id" in body.model_fields_set:
            value = (body.feishu_open_id or "").strip()
            if value:
                owner = db.get_user_by_feishu(value)
                if owner is not None and owner["id"] != user["id"]:
                    raise HTTPException(status_code=400, detail="该飞书账号已绑定其他账号")
            db.update_user(user["id"], feishu_open_id=value)
        if "feishu_chat_id" in body.model_fields_set:
            value = (body.feishu_chat_id or "").strip()
            if value:
                owner = db.get_user_by_feishu_chat(value)
                if owner is not None and owner["id"] != user["id"]:
                    raise HTTPException(status_code=400, detail="该飞书会话已绑定其他账号")
            db.update_user(user["id"], feishu_chat_id=value)
        if "wecom_webhook" in body.model_fields_set:
            value = (body.wecom_webhook or "").strip()
            if value:
                from .notifiers.wecom import is_valid_wecom_webhook

                if not is_valid_wecom_webhook(value):
                    raise HTTPException(
                        status_code=400,
                        detail="企业微信 webhook 地址无效，应为 https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=... 格式",
                    )
                owner = db.get_user_by_wecom_webhook(value)
                if owner is not None and owner["id"] != user["id"]:
                    raise HTTPException(status_code=400, detail="该企业微信群机器人已绑定其他账号")
            db.update_user(user["id"], wecom_webhook=value)
        if "bark_key" in body.model_fields_set:
            value = (body.bark_key or "").strip()
            if value:
                from .notifiers.bark import is_valid_bark_key

                if not is_valid_bark_key(value):
                    raise HTTPException(
                        status_code=400,
                        detail="Bark key 无效：应为手机 Bark App 里的推送 key（形如 AaBbCcDdEeFf...）",
                    )
                owner = db.get_user_by_bark_key(value)
                if owner is not None and owner["id"] != user["id"]:
                    raise HTTPException(status_code=400, detail="该 Bark key 已绑定其他账号")
            db.update_user(user["id"], bark_key=value)
        if "keywords" in body.model_fields_set:
            keywords = [k.strip() for k in (body.keywords or []) if k.strip()]
            if len(keywords) > KEYWORDS_MAX_COUNT:
                raise HTTPException(
                    status_code=400,
                    detail=f"关键词最多 {KEYWORDS_MAX_COUNT} 个",
                )
            for keyword in keywords:
                if len(keyword) > KEYWORDS_MAX_LENGTH:
                    raise HTTPException(
                        status_code=400,
                        detail=f"单个关键词最长 {KEYWORDS_MAX_LENGTH} 字：{keyword}",
                    )
            db.set_user_keywords(user["id"], keywords)
        if "notify_enabled" in body.model_fields_set:
            db.update_user(user["id"], notify_enabled=body.notify_enabled)
        if "daily_report_enabled" in body.model_fields_set and body.daily_report_enabled is not None:
            db.update_user(user["id"], daily_report=body.daily_report_enabled)
        if "push_channels" in body.model_fields_set:
            value = (body.push_channels or "").strip()
            channels = [c.strip() for c in value.split(",") if c.strip()] if value else []
            invalid = [c for c in channels if c not in ("telegram", "feishu", "wecom", "bark")]
            if invalid:
                raise HTTPException(
                    status_code=400,
                    detail=f"无效的推送渠道: {', '.join(invalid)}",
                )
            db.update_user(user["id"], push_channels=",".join(channels))
        if "dnd_start" in body.model_fields_set:
            value = (body.dnd_start or "").strip()
            if value and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
                raise HTTPException(status_code=400, detail="免打扰开始时间需为 HH:MM 格式（00:00-23:59）")
            db.update_user(user["id"], dnd_start=value)
        if "dnd_end" in body.model_fields_set:
            value = (body.dnd_end or "").strip()
            if value and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
                raise HTTPException(status_code=400, detail="免打扰结束时间需为 HH:MM 格式（00:00-23:59）")
            db.update_user(user["id"], dnd_end=value)
        if "dnd_allow_favorite" in body.model_fields_set:
            db.update_user(user["id"], dnd_allow_favorite=body.dnd_allow_favorite)
        if "llm_api_key" in body.model_fields_set:
            db.update_user(user["id"], llm_api_key=(body.llm_api_key or "").strip())
        if "llm_api_base" in body.model_fields_set:
            db.update_user(user["id"], llm_api_base=(body.llm_api_base or "").strip())
        if "llm_model" in body.model_fields_set:
            db.update_user(user["id"], llm_model=(body.llm_model or "").strip())
        return public_user(db.get_user(user["id"]))

    @router.post("/me/bind-code")
    def create_bind_code(user: dict = Depends(get_current_user)):
        db.delete_expired_bind_codes()
        code = f"{secrets.randbelow(1_000_000):06d}"
        db.create_bind_code(code, user["id"], int(time.time()) + BIND_CODE_TTL)
        return {"code": code, "expires_in_seconds": BIND_CODE_TTL}

    # ---- 飞书个人机器人（扫码注册） ----
    _fs_personal_mgr = {}

    def _feishu_personal_manager():
        # 单例：轮询线程/临时监听器/绑定码明文都挂在这个实例上，不能每次 new
        if "mgr" not in _fs_personal_mgr:
            from .feishu_personal import FeishuPersonalManager

            _fs_personal_mgr["mgr"] = FeishuPersonalManager(
                db, notifiers_config.feishu if notifiers_config is not None else None
            )
        return _fs_personal_mgr["mgr"]

    def _require_feishu_personal():
        manager = _feishu_personal_manager()
        if not manager.available():
            raise HTTPException(
                status_code=400,
                detail="个人机器人功能未启用（服务端未配置 FEISHU_CREDENTIAL_KEY）",
            )
        return manager

    def _personal_session_payload(session: dict) -> dict:
        """注册会话状态接口：只暴露展示字段，不返回密钥/设备码。

        绑定码明文只在本进程内存（DB 只存哈希），仅当前用户能通过本人 session 查询；
        过期/重启后为空，前端可点「重新生成绑定码」。
        """
        from .feishu_personal import mask_app_id, qr_data_uri

        personal_bot = db.get_feishu_personal_bot(session["user_id"])
        bind_command = ""
        bind_code_expires_at = session.get("bind_code_expires_at")
        if session["status"] == "awaiting_bind":
            entry = _feishu_personal_manager().get_bind_command(session["session_id"])
            if entry:
                code, expires_at = entry
                bind_command = f"/bind {code}"
                bind_code_expires_at = expires_at
        return {
            "session_id": session["session_id"],
            "status": session["status"],
            "verification_uri": session["verification_uri"],
            "qr_uri": qr_data_uri(session["verification_uri"]),
            "session_expires_at": session["session_expires_at"],
            "bind_command": bind_command,
            "bind_code_expires_at": bind_code_expires_at,
            "last_error": session.get("last_error") or "",
            "candidate_app_id_masked": mask_app_id(session["candidate_app_id"])
            if session.get("candidate_app_id") else "",
            "personal_bot_status": personal_bot["status"] if personal_bot else "",
            "personal_bot_app_id_masked": mask_app_id(personal_bot["app_id"])
            if personal_bot else "",
        }

    @router.post("/me/feishu-personal/register")
    def feishu_personal_register(user: dict = Depends(get_current_user)):
        manager = _require_feishu_personal()
        try:
            session = manager.begin_session(user["id"])
        except Exception as exc:  # noqa: BLE001 - 飞书协议异常，展示给用户
            raise HTTPException(status_code=502, detail=f"发起注册失败：{exc}") from exc
        return _personal_session_payload(session)

    @router.get("/me/feishu-personal/register/{session_id}")
    def feishu_personal_register_status(session_id: str, user: dict = Depends(get_current_user)):
        session = db.get_feishu_registration_session(session_id)
        if session is None or session["user_id"] != user["id"]:
            raise HTTPException(status_code=404, detail="注册会话不存在")
        return _personal_session_payload(session)

    @router.post("/me/feishu-personal/register/{session_id}/refresh-code")
    def feishu_personal_refresh_code(session_id: str, user: dict = Depends(get_current_user)):
        session = db.get_feishu_registration_session(session_id)
        if session is None or session["user_id"] != user["id"]:
            raise HTTPException(status_code=404, detail="注册会话不存在")
        if session["status"] != "awaiting_bind":
            raise HTTPException(status_code=400, detail="当前状态无需刷新绑定码")
        manager = _feishu_personal_manager()
        try:
            issued = manager.issue_bind_code(session_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        session = db.get_feishu_registration_session(session_id)
        payload = _personal_session_payload(session)
        payload["bind_command"] = issued["bind_command"]
        payload["bind_code_expires_at"] = issued["bind_code_expires_at"]
        return payload

    @router.post("/me/feishu-personal/register/{session_id}/cancel")
    def feishu_personal_cancel(session_id: str, user: dict = Depends(get_current_user)):
        session = db.get_feishu_registration_session(session_id)
        if session is None or session["user_id"] != user["id"]:
            raise HTTPException(status_code=404, detail="注册会话不存在")
        _feishu_personal_manager().cancel_session(session_id)
        return {"ok": True}

    @router.delete("/me/feishu-personal")
    def feishu_personal_delete(user: dict = Depends(get_current_user)):
        """解绑个人机器人：擦除个人凭据与身份；共享飞书字段保持原值。"""
        _feishu_personal_manager().disable(user["id"])
        return {"ok": True}

    @router.post("/me/password")
    def change_password(body: PasswordChangeIn, user: dict = Depends(get_current_user)):
        if len(body.new_password) < 6:
            raise HTTPException(status_code=400, detail="新密码至少6位")
        if len(body.new_password) > MAX_PASSWORD_LEN:
            raise HTTPException(status_code=400, detail=f"新密码最长{MAX_PASSWORD_LEN}位")
        # 微信/机器人自动创建的账号没有密码：已持有会话即可首次设密
        if user["password_hash"] and not auth.verify_password(body.old_password, user["password_hash"]):
            raise HTTPException(status_code=400, detail="原密码错误")
        db.update_user(user["id"], password_hash=auth.hash_password(body.new_password))
        return {"ok": True}

    # ---- 目录与订阅 ----
    @router.get("/catalog")
    def catalog(platform: str | None = None, category_id: int | None = None, user: dict = Depends(get_current_user)):
        kols = db.list_kols(platform, category_id)
        if not user["is_admin"]:
            visible = db.visible_kol_ids(user["id"])
            kols = [k for k in kols if k["id"] in visible]
        # 已订阅置顶 → 优先大V → 最近活跃：组内已订阅的靠前，其余保持原排序
        subscribed_types = db.subscribed_kol_types(user["id"])
        last_post_at = db.last_post_time_by_kol()
        kols.sort(
            key=lambda k: (
                k["id"] in subscribed_types,
                bool(k.get("priority")),
                last_post_at.get(k["id"]) or "",
            ),
            reverse=True,
        )
        favorite_ids = db.subscribed_favorite_ids(user["id"])
        return [
            {
                **kol,
                "subscribed": kol["id"] in subscribed_types,
                "subscribe_type": subscribed_types.get(kol["id"], "post"),
                "favorite": kol["id"] in favorite_ids,
            }
            for kol in kols
        ]

    @router.get("/recommendations")
    def recommendations(user: dict = Depends(get_current_user)):
        """新用户引导：按订阅人数推荐大V（仅首次引导使用）。"""
        return [
            {
                "id": k["id"],
                "name": k["name"],
                "platform": k["platform"],
                "avatar_url": k["avatar_url"],
                "category_name": k["category_name"],
                "subscriber_count": int(k["subscriber_count"] or 0),
                "subscribed": bool(k["subscribed"]),
            }
            for k in db.recommended_kols(user["id"], 4)
        ]

    @router.post("/subscriptions")
    def subscribe(body: SubscriptionIn, user: dict = Depends(get_current_user)):
        kol = db.get_kol(body.kol_id)
        if kol is None or (
            not user["is_admin"] and kol["id"] not in db.visible_kol_ids(user["id"])
        ):
            raise HTTPException(status_code=404, detail="大V不存在")
        if body.type not in ("post", "reply", "both"):
            raise HTTPException(status_code=400, detail="订阅类型需为 post / reply / both")
        db.add_subscription(user["id"], body.kol_id, type=body.type)
        return {"ok": True}

    @router.put("/subscriptions/{kol_id}")
    def update_subscription_type(kol_id: int, body: SubscriptionTypeIn, user: dict = Depends(get_current_user)):
        kol = db.get_kol(kol_id)
        if kol is None:
            raise HTTPException(status_code=404, detail="大V不存在")
        if body.type not in ("post", "reply", "both"):
            raise HTTPException(status_code=400, detail="订阅类型需为 post / reply / both")
        if not db.update_subscription_type(user["id"], kol_id, body.type):
            raise HTTPException(status_code=404, detail="尚未订阅该大V")
        return {"ok": True}

    @router.put("/subscriptions/{kol_id}/favorite")
    def set_subscription_favorite(kol_id: int, body: SubscriptionFavoriteIn, user: dict = Depends(get_current_user)):
        if db.get_kol(kol_id) is None:
            raise HTTPException(status_code=404, detail="大V不存在")
        if not db.set_subscription_favorite(user["id"], kol_id, body.favorite):
            raise HTTPException(status_code=404, detail="尚未订阅该大V")
        return {"ok": True}

    @router.delete("/subscriptions/{kol_id}")
    def unsubscribe(kol_id: int, user: dict = Depends(get_current_user)):
        db.remove_subscription(user["id"], kol_id)
        return {"ok": True}

    @router.get("/my/subscriptions")
    def my_subscriptions(user: dict = Depends(get_current_user)):
        return db.list_subscriptions(user["id"])

    @router.get("/my/feed")
    def my_feed(
        limit: int = 100,
        offset: int = 0,
        platform: str | None = None,
        category_id: int | None = None,
        q: str | None = None,
        favorite: int = 0,
        tag: str | None = None,
        user: dict = Depends(get_current_user),
    ):
        kol_ids = sorted(db.readable_subscribed_kol_ids(user["id"], user["is_admin"]))
        return db.list_feed_posts(
            kol_ids,
            limit=bounded_limit(limit),
            user_id=user["id"],
            offset=max(offset, 0),
            platform=platform,
            category_id=category_id,
            q=q,
            favorite=bool(favorite),
            tag=tag,
        )

    @router.get("/kols/{kol_id}")
    def get_kol(kol_id: int, user: dict = Depends(get_current_user)):
        kol = db.get_kol(kol_id)
        if kol is None or (
            not user["is_admin"] and kol["id"] not in db.visible_kol_ids(user["id"])
        ):
            raise HTTPException(status_code=404, detail="大V不存在")
        kol["subscribed"] = kol_id in db.subscribed_kol_ids(user["id"])
        kol["subscribe_type"] = db.subscribed_kol_types(user["id"]).get(kol_id, "post")
        kol["favorite"] = kol_id in db.subscribed_favorite_ids(user["id"])
        if user["is_admin"]:
            acl_ids = set(db.acl_user_ids(kol_id))
            kol["visible_users"] = [u["username"] for u in db.list_users() if u["id"] in acl_ids]
        return kol

    @router.get("/kols/{kol_id}/posts")
    def kol_posts(kol_id: int, limit: int = 100, user: dict = Depends(get_current_user)):
        kol = db.get_kol(kol_id)
        if kol is None or (
            not user["is_admin"] and kol["id"] not in db.visible_kol_ids(user["id"])
        ):
            raise HTTPException(status_code=404, detail="大V不存在")
        return db.list_posts(limit=bounded_limit(limit), kol_id=kol_id)

    @router.post("/kol-requests")
    def create_kol_request(body: KolRequestIn, user: dict = Depends(get_current_user)):
        """用户申请添加大V，管理员审批后入库。"""
        if body.platform not in ALLOWED_PLATFORMS:
            raise HTTPException(status_code=400, detail=f"不支持的平台: {body.platform}")
        external_id = body.external_id.strip()
        if body.platform == "xueqiu":
            match = re.search(r"xueqiu\.com/(?:u/)?(\d+)", external_id)
            if match:
                external_id = match.group(1)
        elif body.platform == "combination":
            symbol = extract_cube_symbol(external_id)
            if symbol:
                external_id = symbol
        elif body.platform == "weibo":
            external_id = _normalize_weibo_id(external_id)
        if not external_id:
            raise HTTPException(status_code=400, detail="请提供大V主页链接或ID")
        try:
            db.add_kol_request(body.platform, external_id, user["id"], name=body.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        # 通知管理员有新申请（通知失败不影响申请提交）
        try:
            _notify_admins_new_request(body.platform, body.name or external_id, user)
        except Exception as exc:  # noqa: BLE001
            logger.warning("大V申请通知管理员失败 err=%s", exc)
        return {"ok": True}

    @router.get("/my/kol-requests")
    def my_kol_requests(user: dict = Depends(get_current_user)):
        return [r for r in db.list_kol_requests() if r["user_id"] == user["id"]]

    @router.get("/admin/kol-requests", dependencies=[Depends(require_admin)])
    def admin_kol_requests(status: str | None = None):
        return db.list_kol_requests(status)

    @router.post("/admin/kol-requests/{request_id}/approve", dependencies=[Depends(require_admin)])
    def approve_kol_request(request_id: int, admin: dict = Depends(require_admin)):
        req = db.get_kol_request(request_id)
        if req is None or req["status"] != "pending":
            raise HTTPException(status_code=404, detail="申请不存在或已处理")
        name = (req["name"] or "").strip()
        avatar_url = ""
        # 申请通常只填了主页链接，审批时自动补昵称与头像，避免上架占位名
        if req["platform"] == "xueqiu":
            profile = resolve_profile(
                req["external_id"],
                db.get_setting(XUEQIU_COOKIE_KEY) or os.environ.get("XUEQIU_COOKIE", ""),
            )
            name = name or profile.get("screen_name") or ""
            avatar_url = profile.get("avatar_url") or ""
        elif req["platform"] == "combination":
            profile = resolve_combination_profile(
                req["external_id"],
                db.get_setting(XUEQIU_COOKIE_KEY) or os.environ.get("XUEQIU_COOKIE", ""),
            )
            name = name or profile.get("name") or ""
            avatar_url = profile.get("avatar_url") or ""
        elif req["platform"] == "weibo":
            profile = resolve_weibo_profile(
                req["external_id"],
                db.get_setting(WEIBO_COOKIE_KEY) or os.environ.get("WEIBO_COOKIE", ""),
            )
            name = name or profile.get("name") or ""
            avatar_url = profile.get("avatar_url") or ""
        elif req["platform"] == "twitter":
            profile = resolve_x_profile(req["external_id"])
            name = name or profile.get("name") or ""
            avatar_url = profile.get("avatar_url") or ""
        name = name or f"{req['platform']}_{req['external_id']}"
        try:
            kid = db.add_kol(req["platform"], name, req["external_id"])
            if avatar_url:
                db.update_kol_avatar(kid, cache_avatar(db, kid, avatar_url))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        db.set_kol_request_status(request_id, "approved")
        _audit(admin, "approve_kol_request", str(request_id), f"{name} {req['external_id']}")
        try:
            db.add_subscription(req["user_id"], kid)
        except Exception:  # noqa: BLE001 - 自动订阅失败不阻塞审批
            logger.warning("审批后自动订阅失败 request=%s", request_id, exc_info=True)
        if notifiers_config is not None:
            from .notifiers.feishu import FeishuNotifier
            from .notifiers.telegram import TelegramNotifier
            from .notifiers.wecom import WeComNotifier

            requester = db.get_user(req["user_id"])
            message = f"✅ 你申请的大V「{name}」已通过审批，已自动为你订阅"
            if requester and requester["telegram_chat_id"] and notifiers_config.telegram.bot_token:
                notifier = None
                try:
                    notifier = TelegramNotifier(
                        notifiers_config.telegram,
                        chat_id=requester["telegram_chat_id"],
                        bot_token=requester.get("telegram_bot_token") or None,
                    )
                    notifier.send_text(message)
                except Exception:  # noqa: BLE001
                    logger.warning("审批通知 TG 发送失败 user=%s", requester["username"], exc_info=True)
                finally:
                    if notifier is not None:
                        notifier.client.close()
            if requester and (requester.get("feishu_open_id") or requester.get("feishu_chat_id")):
                notifier = None
                try:
                    notifier = FeishuNotifier(
                        notifiers_config.feishu,
                        open_id=requester["feishu_open_id"] if not requester.get("feishu_chat_id") else None,
                        chat_id=requester.get("feishu_chat_id") or None,
                    )
                    notifier.send_text(message)
                except Exception:  # noqa: BLE001
                    logger.warning("审批通知飞书发送失败 user=%s", requester["username"], exc_info=True)
                finally:
                    if notifier is not None:
                        notifier.client.close()
            if requester and requester.get("wecom_webhook"):
                notifier = None
                try:
                    notifier = WeComNotifier(
                        notifiers_config.wecom,
                        webhook_url=requester["wecom_webhook"],
                    )
                    notifier.send_text(message)
                except Exception:  # noqa: BLE001
                    logger.warning("审批通知企业微信发送失败 user=%s", requester["username"], exc_info=True)
                finally:
                    if notifier is not None:
                        notifier.client.close()
        return db.get_kol(kid)

    @router.post("/admin/kol-requests/{request_id}/reject", dependencies=[Depends(require_admin)])
    def reject_kol_request(request_id: int, admin: dict = Depends(require_admin)):
        req = db.get_kol_request(request_id)
        if req is None or req["status"] != "pending":
            raise HTTPException(status_code=404, detail="申请不存在或已处理")
        db.set_kol_request_status(request_id, "rejected")
        _audit(admin, "reject_kol_request", str(request_id), req["external_id"])
        return {"ok": True}

    @router.post("/admin/register-codes", dependencies=[Depends(require_admin)])
    def generate_register_codes(body: RegisterCodeGenIn, admin: dict = Depends(require_admin)):
        """批量生成一次性注册码。"""
        count = max(1, min(body.count, 100))
        alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
        existing = {r["code"] for r in db.list_register_codes()}
        codes = []
        while len(codes) < count:
            code = "".join(secrets.choice(alphabet) for _ in range(8))
            if code in existing:
                continue
            existing.add(code)
            db.add_register_code(code, note=body.note)
            codes.append(code)
        _audit(admin, "generate_register_codes", "", f"count={len(codes)} note={body.note}")
        return {"codes": codes, "count": len(codes)}

    @router.get("/admin/register-codes", dependencies=[Depends(require_admin)])
    def list_register_codes():
        return db.list_register_codes()

    @router.get("/admin/xueqiu-cookie", dependencies=[Depends(require_admin)])
    def get_xueqiu_cookie():
        cookie = db.get_setting(XUEQIU_COOKIE_KEY) or ""
        return {
            "set": bool(cookie),
            "updated_at": db.get_setting(XUEQIU_COOKIE_TIME_KEY) or "",
            "preview": (cookie[:40] + "…") if len(cookie) > 40 else cookie,
        }

    @router.get("/admin/polling-config", dependencies=[Depends(require_admin)])
    def get_polling_config():
        return _effective_polling()

    @router.put("/admin/polling-config", dependencies=[Depends(require_admin)])
    def update_polling_config(body: PollingConfigIn, admin: dict = Depends(require_admin)):
        changed = []
        for name, cfg_key, _stat, lo, hi in POLLING_FIELDS:
            value = getattr(body, name)
            if value is None:
                continue
            if not (lo <= value <= hi):
                raise HTTPException(status_code=400, detail=f"{name} 需在 {lo}-{hi} 之间")
            db.set_setting(cfg_key, str(value))
            changed.append(name)
        if body.translate_twitter_content is not None:
            db.set_setting(
                "config_translate_twitter_content",
                "1" if body.translate_twitter_content else "0",
            )
            changed.append("translate_twitter_content")
        _audit(admin, "update_polling_config", "", ",".join(changed))
        return _effective_polling()

    @router.post("/admin/xueqiu-cookie", dependencies=[Depends(require_admin)])
    def set_xueqiu_cookie(body: CookieIn, admin: dict = Depends(require_admin)):
        cookie = body.cookie.strip()
        if not cookie:
            raise HTTPException(status_code=400, detail="cookie 不能为空")
        db.set_setting(XUEQIU_COOKIE_KEY, cookie)
        db.set_setting(XUEQIU_COOKIE_TIME_KEY, str(int(time.time())))
        _audit(admin, "set_xueqiu_cookie", "", f"len={len(cookie)}")
        return {"ok": True}

    @router.delete("/admin/register-codes/{code}", dependencies=[Depends(require_admin)])
    def revoke_register_code(code: str, admin: dict = Depends(require_admin)):
        row = db.get_register_code(code)
        if row is None:
            raise HTTPException(status_code=404, detail="注册码不存在")
        if row["used_by"]:
            raise HTTPException(status_code=400, detail="该注册码已被使用，不能删除")
        db.delete_register_code(code)
        _audit(admin, "revoke_register_code", code)
        return {"ok": True}

    @router.get("/admin/logs", dependencies=[Depends(require_admin)])
    def list_audit_logs(limit: int = 100):
        return db.list_admin_logs(limit=bounded_limit(limit))

    @router.get("/admin/dashboard", dependencies=[Depends(require_admin)])
    def dashboard():
        """业务数据看板：用户/订阅/帖子/推送/数据源健康聚合。"""
        return db.dashboard_stats()

    @router.get("/admin/system-logs", dependencies=[Depends(require_admin)])
    def list_system_logs(
        limit: int = 200,
        level: str | None = None,
        q: str | None = None,
    ):
        """返回内存环形缓冲里的最近日志行，可按级别与关键词过滤（用于网页/Agent 调试）。"""
        from .logging_setup import recent_logs

        if level and level.upper() not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            raise HTTPException(status_code=400, detail="level 需为 DEBUG/INFO/WARNING/ERROR/CRITICAL")
        return {
            "lines": recent_logs(
                min(max(limit, 10), 2000),
                level=level,
                q=(q or "").strip() or None,
            )
        }

    # ---- 管理（管理员）----
    @router.get("/kols", dependencies=[Depends(require_admin)])
    def list_kols(platform: str | None = None, category_id: int | None = None):
        return db.list_kols(platform, category_id)

    @router.post("/kols", dependencies=[Depends(require_admin)])
    def add_kol(body: KolIn, admin: dict = Depends(require_admin)):
        if body.platform not in ALLOWED_PLATFORMS:
            raise HTTPException(status_code=400, detail=f"不支持的平台: {body.platform}")
        external_id = body.external_id.strip()
        name = body.name.strip()
        if body.platform == "xueqiu":
            # 支持直接粘贴雪球主页链接，自动提取 UID
            match = re.search(r"xueqiu\.com/(?:u/)?(\d+)", external_id)
            if match:
                external_id = match.group(1)
        elif body.platform == "combination":
            # 支持直接粘贴组合主页链接，自动提取组合编码 ZHxxxxxx
            symbol = extract_cube_symbol(external_id)
            if symbol:
                external_id = symbol
        elif body.platform == "weibo":
            # 支持直接粘贴微博主页链接，自动提取 UID
            external_id = _normalize_weibo_id(external_id)
        if not external_id:
            raise HTTPException(status_code=400, detail="昵称与外部ID不能为空")
        if not name:
            if body.platform == "combination":
                # 没填昵称时自动查组合名称（失败退回占位名）
                cookie = db.get_setting(XUEQIU_COOKIE_KEY) or os.environ.get("XUEQIU_COOKIE", "")
                profile = resolve_combination_profile(external_id, cookie)
                name = profile.get("name") or f"combination_{external_id}"
            elif body.platform == "weibo":
                # 没填昵称时自动查微博昵称（公开接口，失败退回占位名）
                profile = resolve_weibo_profile(
                    external_id,
                    db.get_setting(WEIBO_COOKIE_KEY) or os.environ.get("WEIBO_COOKIE", ""),
                )
                name = profile.get("name") or f"weibo_{external_id}"
            elif body.platform == "twitter":
                # 没填昵称时自动查 X 显示名（需 TWITTER_COOKIE，失败退回占位名）
                profile = resolve_x_profile(external_id)
                name = profile.get("name") or f"twitter_{external_id}"
        if body.category_id is not None and db.get_category(body.category_id) is None:
            raise HTTPException(status_code=400, detail="分类不存在")
        kid = db.add_kol(
            body.platform,
            name,
            external_id,
            category_id=body.category_id,
            priority=body.priority,
            original_only=body.original_only,
        )
        _audit(admin, "add_kol", str(kid), f"{body.platform} {name} {external_id}")
        kol = db.get_kol(kid)
        if not kol["avatar_url"]:
            if body.platform == "combination":
                profile = resolve_combination_profile(
                    external_id, db.get_setting(XUEQIU_COOKIE_KEY) or ""
                )
            elif body.platform == "weibo":
                profile = resolve_weibo_profile(
                    external_id,
                    db.get_setting(WEIBO_COOKIE_KEY) or os.environ.get("WEIBO_COOKIE", ""),
                )
            elif body.platform == "twitter":
                profile = resolve_x_profile(external_id)
            else:
                profile = {}
            if profile.get("avatar_url"):
                db.update_kol_avatar(kid, cache_avatar(db, kid, profile["avatar_url"]))
                kol = db.get_kol(kid)
        return kol

    @router.post("/kols/batch", dependencies=[Depends(require_admin)])
    def batch_add_kols(body: KolBatchIn, admin: dict = Depends(require_admin)):
        """批量导入：每行一个「昵称 链接/UID」或「链接/UID」，支持雪球主页链接。"""
        if body.platform not in ALLOWED_PLATFORMS:
            raise HTTPException(status_code=400, detail=f"不支持的平台: {body.platform}")
        if body.category_id is not None and db.get_category(body.category_id) is None:
            raise HTTPException(status_code=400, detail="分类不存在")
        results = []
        for raw in body.lines.splitlines():
            line = raw.strip()
            if not line:
                continue
            external_id = ""
            nickname = ""
            for token in line.split():
                xueqiu_match = re.search(r"xueqiu\.com/(?:u/)?(\d+)", token)
                combination_match = re.search(r"xueqiu\.com/P/(ZH\d+)", token)
                weibo_match = re.search(r"weibo\.com/u/(\d+)", token)
                if xueqiu_match:
                    external_id = xueqiu_match.group(1)
                elif combination_match:
                    external_id = combination_match.group(1)
                elif re.fullmatch(r"ZH\d+", token):
                    external_id = token
                elif weibo_match:
                    external_id = weibo_match.group(1)
                elif token.startswith(("http://", "https://")) and not external_id:
                    external_id = token  # X/RSS 等直接用源地址
                elif token.isdigit() and not external_id:
                    external_id = token
                else:
                    nickname = f"{nickname} {token}".strip()
            if not external_id:
                results.append({"ok": False, "line": line[:80], "error": "未识别到链接或ID"})
                continue
            name = nickname or f"{body.platform}_{external_id}"
            avatar_url = ""
            if not nickname and body.platform == "xueqiu" and external_id.isdigit():
                # 没填昵称时自动查雪球昵称与头像（失败则退回 xueqiu_uid）
                cookie = db.get_setting(XUEQIU_COOKIE_KEY) or os.environ.get("XUEQIU_COOKIE", "")
                profile = resolve_profile(external_id, cookie)
                if profile.get("screen_name"):
                    name = profile["screen_name"]
                avatar_url = profile.get("avatar_url") or ""
            elif body.platform == "xueqiu" and external_id.isdigit():
                # 已填昵称也补头像（与微博批量行为一致）
                cookie = db.get_setting(XUEQIU_COOKIE_KEY) or os.environ.get("XUEQIU_COOKIE", "")
                profile = resolve_profile(external_id, cookie)
                avatar_url = profile.get("avatar_url") or ""
            elif body.platform == "combination":
                # 自动查组合名称（没填昵称时）与主理人头像
                cookie = db.get_setting(XUEQIU_COOKIE_KEY) or os.environ.get("XUEQIU_COOKIE", "")
                profile = resolve_combination_profile(external_id, cookie)
                if not nickname and profile.get("name"):
                    name = profile["name"]
                avatar_url = profile.get("avatar_url") or ""
            elif body.platform == "twitter":
                # 自动查 X 显示名（没填昵称时）与头像（需 TWITTER_COOKIE）
                profile = resolve_x_profile(external_id)
                if not nickname and profile.get("name"):
                    name = profile["name"]
                avatar_url = profile.get("avatar_url") or ""
            elif body.platform == "weibo":
                # 微博批量导入始终拉取头像（填了昵称也查）；昵称为空时顺带补昵称
                profile = resolve_weibo_profile(
                    external_id,
                    db.get_setting(WEIBO_COOKIE_KEY) or os.environ.get("WEIBO_COOKIE", ""),
                )
                if not nickname and profile.get("name"):
                    name = profile["name"]
                avatar_url = profile.get("avatar_url") or ""
            try:
                kid = db.add_kol(
                    body.platform,
                    name,
                    external_id,
                    category_id=body.category_id,
                    priority=body.priority,
                    original_only=body.original_only,
                )
                if avatar_url:
                    db.update_kol_avatar(kid, cache_avatar(db, kid, avatar_url))
                results.append({"ok": True, "id": kid, "name": name, "external_id": external_id})
            except ValueError as exc:
                results.append({"ok": False, "line": line[:80], "error": str(exc)})
        ok_count = sum(1 for r in results if r["ok"])
        _audit(admin, "batch_add_kols", "", f"ok={ok_count}/{len(results)}")
        return {
            "total": len(results),
            "ok": ok_count,
            "failed": [r for r in results if not r["ok"]],
        }

    @router.put("/kols/{kol_id}", dependencies=[Depends(require_admin)])
    def update_kol(kol_id: int, body: KolUpdate, admin: dict = Depends(require_admin)):
        if db.get_kol(kol_id) is None:
            raise HTTPException(status_code=404, detail="KOL 不存在")
        if "category_id" in body.model_fields_set and body.category_id is not None and db.get_category(body.category_id) is None:
            raise HTTPException(status_code=400, detail="分类不存在")
        name = body.name.strip() if body.name is not None else None
        external_id = body.external_id.strip() if body.external_id is not None else None
        if name == "" or external_id == "":
            raise HTTPException(status_code=400, detail="昵称与外部ID不能为空")
        kol = db.get_kol(kol_id)
        if external_id is not None and kol["platform"] == "weibo":
            external_id = _normalize_weibo_id(external_id)
        if external_id is not None:
            dup = db.get_kol_by_external(kol["platform"], external_id)
            if dup is not None and dup["id"] != kol_id:
                raise HTTPException(status_code=400, detail="该平台已存在相同的外部ID")
        db.update_kol(
            kol_id,
            name=name,
            external_id=external_id,
            enabled=body.enabled,
            category_id=body.category_id if "category_id" in body.model_fields_set else None,
            priority=body.priority if "priority" in body.model_fields_set else None,
        )
        if "is_private" in body.model_fields_set and body.is_private is not None:
            db.update_kol(kol_id, is_private=body.is_private)
        if "original_only" in body.model_fields_set and body.original_only is not None:
            db.update_kol(kol_id, original_only=body.original_only)
        if "visible_users" in body.model_fields_set and body.visible_users is not None:
            user_ids = []
            for username in body.visible_users:
                target = db.get_user_by_username_ci(username.strip())
                if target is None:
                    raise HTTPException(status_code=400, detail=f"用户不存在: {username}")
                user_ids.append(target["id"])
            db.set_kol_acl(kol_id, user_ids)
        _audit(admin, "update_kol", str(kol_id), f"name={name} enabled={body.enabled}")
        return db.get_kol(kol_id)

    @router.delete("/kols/{kol_id}", dependencies=[Depends(require_admin)])
    def delete_kol(kol_id: int, admin: dict = Depends(require_admin)):
        if db.get_kol(kol_id) is None:
            raise HTTPException(status_code=404, detail="KOL 不存在")
        db.delete_kol(kol_id)
        _audit(admin, "delete_kol", str(kol_id))
        return {"ok": True}

    @router.get("/categories")
    def list_categories(user: dict = Depends(get_current_user)):
        """分类列表：登录用户可读（动态页分类筛选），管理与写入仍需管理员。"""
        return db.list_categories()

    @router.post("/categories", dependencies=[Depends(require_admin)])
    def add_category(body: CategoryIn, admin: dict = Depends(require_admin)):
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="分类名不能为空")
        try:
            cid = db.add_category(name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        _audit(admin, "add_category", name)
        return db.get_category(cid)

    @router.put("/categories/{category_id}", dependencies=[Depends(require_admin)])
    def rename_category(category_id: int, body: CategoryIn, admin: dict = Depends(require_admin)):
        if db.get_category(category_id) is None:
            raise HTTPException(status_code=404, detail="分类不存在")
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="分类名不能为空")
        try:
            db.rename_category(category_id, name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        _audit(admin, "rename_category", str(category_id), name)
        return db.get_category(category_id)

    @router.delete("/categories/{category_id}", dependencies=[Depends(require_admin)])
    def delete_category(category_id: int, admin: dict = Depends(require_admin)):
        if db.get_category(category_id) is None:
            raise HTTPException(status_code=404, detail="分类不存在")
        db.delete_category(category_id)
        _audit(admin, "delete_category", str(category_id))
        return {"ok": True}

    @router.get("/tags")
    def list_tags(user: dict = Depends(get_current_user)):
        """贴文话题词表：登录用户可读（动态页标签筛选），管理与写入仍需管理员。

        stats 供管理端展示已打标/待打标贴文数量。
        stock_names 为常用股票名表（纯文字提及打标用）；dynamic_tags 为贴文里
        实际出现过的标签（含股票名，去重按频次），供时间线筛选下拉合并展示。
        stock_aliases 为黑话别名表（LLM 每日自动识别 + 管理端可手动修正）。
        """
        return {
            "tags": db.get_tag_vocabulary(),
            "stock_names": db.get_stock_names(),
            "stock_aliases": db.get_stock_aliases(),
            "dynamic_tags": db.aggregate_post_tags(),
            "stats": db.tag_stats(),
        }

    @router.put("/tags", dependencies=[Depends(require_admin)])
    def update_tag_vocabulary(body: TagVocabularyIn, admin: dict = Depends(require_admin)):
        from .tagging import TAG_VOCABULARY_MAX

        tags = []
        for rule in body.tags:
            tag = (rule.tag or "").strip()
            if not tag:
                continue
            tags.append(
                {
                    "tag": tag,
                    "keywords": [
                        str(k).strip() for k in (rule.keywords or []) if str(k).strip()
                    ],
                }
            )
        # 按 tag 去重（保留首个）
        seen, deduped = set(), []
        for rule in tags:
            if rule["tag"] not in seen:
                seen.add(rule["tag"])
                deduped.append(rule)
        if not deduped:
            raise HTTPException(status_code=400, detail="词表不能为空")
        if len(deduped) > TAG_VOCABULARY_MAX:
            raise HTTPException(
                status_code=400, detail=f"词表最多 {TAG_VOCABULARY_MAX} 个标签"
            )
        db.set_tag_vocabulary(deduped)
        if body.stock_names is not None:
            stock_names = [n.strip() for n in body.stock_names if n and n.strip()]
            seen_stocks, deduped_stocks = set(), []
            for n in stock_names:
                if n not in seen_stocks:
                    seen_stocks.add(n)
                    deduped_stocks.append(n)
            db.set_stock_names(deduped_stocks)
        if body.stock_aliases is not None:
            cleaned_aliases = []
            for a in body.stock_aliases:
                alias = (a.alias or "").strip()
                stock = (a.stock or "").strip()
                if alias and stock:
                    cleaned_aliases.append({"alias": alias, "stock": stock})
            db.set_stock_aliases(cleaned_aliases)
        _audit(admin, "update_tag_vocabulary", detail=f"{len(deduped)} tags")
        return {
            "tags": db.get_tag_vocabulary(),
            "stock_names": db.get_stock_names(),
            "stock_aliases": db.get_stock_aliases(),
            "dynamic_tags": db.aggregate_post_tags(),
        }

    @router.post("/tags/backfill", dependencies=[Depends(require_admin)])
    def backfill_post_tags(body: TagBackfillIn, admin: dict = Depends(require_admin)):
        """给全部未打标贴文补标签（关键词规则，零成本）。

        用 id 游标分页：未命中关键词的帖子保持未打标（tags 为空），若按
        untagged_only 循环拉取会永远捞起同一批帖而死循环——游标只扫一遍。
        """
        from .tagging import rule_tag_posts, stock_tag_posts

        tag_rules = db.get_tag_vocabulary()
        stock_names = db.get_stock_names()
        stock_aliases = db.get_stock_aliases()
        processed = 0
        tagged_count = 0
        below_id: int | None = None  # None 表示从最新开始，之后按每批最小 id 推进
        while True:
            batch = db.list_posts(
                limit=500, untagged_only=True, below_id=below_id
            )
            if not batch:
                break
            posts = [
                Post(
                    platform=p["platform"],
                    kol_id=p["kol_id"],
                    kol_name=p["kol_name"],
                    external_id=p["external_id"],
                    title=p["title"],
                    content=p["content"],
                    url=p["url"],
                    published_at=p["published_at"],
                    category=p.get("category_name") or "",
                    post_type=p.get("post_type") or "",
                    images=p.get("images") or [],
                )
                for p in batch
            ]
            tagged = rule_tag_posts(posts, tag_rules)
            stock_tagged = stock_tag_posts(posts, stock_names, aliases=stock_aliases)
            for i, post in enumerate(posts):
                # 合并：话题（≤3）+ 股票（≤2）
                merged = list((tagged.get(i) or [])[:3]) + list((stock_tagged.get(i) or [])[:2])
                if merged:
                    db.update_post_tags(batch[i]["id"], merged)
                    tagged_count += 1
            processed += len(batch)
            # 游标推进到本批最小 id（ORDER BY id DESC），下一批只扫更早的帖
            below_id = min(p["id"] for p in batch)
        _audit(
            admin, "backfill_post_tags", detail=f"processed={processed} tagged={tagged_count}"
        )
        return {"processed": processed, "tagged": tagged_count}

    @router.get("/posts", dependencies=[Depends(require_admin)])
    def list_posts(limit: int = 100, platform: str | None = None, kol_id: int | None = None, q: str | None = None, offset: int = 0):
        return db.list_posts(limit=bounded_limit(limit), platform=platform, kol_id=kol_id, q=q, offset=offset)

    @router.get("/push-logs", dependencies=[Depends(require_admin)])
    def list_push_logs(
        limit: int = 100,
        user_id: int | None = None,
        channel: str | None = None,
        status: str | None = None,
    ):
        return db.list_push_logs(
            limit=bounded_limit(limit),
            user_id=user_id,
            channel=channel,
            status=status,
        )

    @router.get("/users", dependencies=[Depends(require_admin)])
    def list_users():
        return [admin_user_summary(u) for u in db.list_users()]

    @router.get("/stats", dependencies=[Depends(require_admin)])
    def stats():
        kols = db.list_kols()
        # 「正常」状态有新鲜度窗口：source_ok 太久没更新视为近期无成功，
        # 避免平台曾成功过一次就永远显示正常（连续失败被掩盖）。
        # 窗口取 2× 全局轮询间隔，至少 5 分钟；无启用大V的平台不判定。
        try:
            poll_interval = int(db.get_setting("config_interval_seconds") or 0)
        except (TypeError, ValueError):
            poll_interval = 0
        ok_window = max(poll_interval * 2, 300)
        now = int(time.time())
        enabled_by_platform: dict[str, int] = {}
        for k in kols:
            if k["enabled"]:
                enabled_by_platform[k["platform"]] = enabled_by_platform.get(k["platform"], 0) + 1
        sources = []
        for platform in sorted(ALLOWED_PLATFORMS):
            ok_at = db.get_setting(f"source_ok_{platform}")
            err = db.get_setting(f"source_err_{platform}") or ""
            fails = db.get_setting(f"source_fails_{platform}") or "0"
            ev = db.source_event_stats(platform, 24)
            total = ev["ok"] + ev["fail"]
            fresh = False
            if ok_at:
                try:
                    fresh = now - int(ok_at) <= ok_window
                except (TypeError, ValueError):
                    fresh = True  # 时间戳格式异常时按有效处理，不阻断展示
            if enabled_by_platform.get(platform, 0) == 0:
                fresh = bool(ok_at)  # 无启用大V：不判过期，保留原语义
            src = {
                "platform": platform,
                "ok": fresh,
                "last_ok_at": ok_at,
                "last_error": err,
                "consecutive_fails": int(fails),
                "ok_24h": ev["ok"],
                "fail_24h": ev["fail"],
                "warn_24h": ev["warn"],
                "success_rate_24h": round(ev["ok"] * 100 / total) if total else None,
                "next_retry_at": db.get_setting(f"source_next_retry_at_{platform}") or "",
                "last_alert_at": db.get_setting(f"source_alert_{platform}") or "",
            }
            if platform == "twitter":
                # X 通道状态：直抓（官方接口）为主，降级时用 RSSHub 备用
                direct_ok = db.get_setting("x_direct_last_ok_at")
                fallback_at = db.get_setting("x_direct_last_fallback_at")
                if fallback_at and (not direct_ok or fallback_at > direct_ok):
                    src["direct_mode"] = "fallback"
                elif direct_ok:
                    src["direct_mode"] = "direct"
                else:
                    src["direct_mode"] = "unknown"
                src["direct_last_ok_at"] = direct_ok
                src["direct_fallback_reason"] = (
                    db.get_setting("x_direct_fallback_reason") or ""
                )
            sources.append(src)
        xueqiu_cookie = db.get_setting("xueqiu_cookie") or ""
        xueqiu_updated = db.get_setting("xueqiu_cookie_updated_at") or ""
        weibo_cookie = db.get_setting("weibo_cookie") or ""
        weibo_updated = db.get_setting("weibo_cookie_updated_at") or ""
        last_post_at = db.last_post_time_by_kol()
        kol_health = [
            {
                "id": k["id"],
                "name": k["name"],
                "platform": k["platform"],
                "enabled": bool(k["enabled"]),
                "last_post_at": last_post_at.get(k["id"]) or "",
            }
            for k in kols
        ]
        kol_health.sort(key=lambda h: h["last_post_at"])
        return {
            "polling_interval_seconds": int(db.get_setting("stats_polling_interval") or 0),
            "keepalive_interval_seconds": int(db.get_setting("stats_keepalive_interval") or 0),
            "posts_retention_days": int(db.get_setting("stats_posts_retention_days") or 0),
            "last_poll_at": db.get_setting("stats_last_poll_at"),
            "last_poll_duration_ms": db.get_setting("stats_last_poll_duration_ms"),
            "last_poll_error": db.get_setting("stats_last_poll_error") or "",
            "kols": len(kols),
            "enabled_kols": sum(1 for k in kols if k["enabled"]),
            "active_kols": len(db.kol_ids_with_subscribers()),  # 有订阅者、正在被抓取的大V数
            "priority_kols": sum(1 for k in kols if k.get("priority")),
            "users": db.count_users(),
            "posts": db.count_posts(),
            "sources": sources,
            "xueqiu_cookie": {
                "set": bool(xueqiu_cookie),
                "updated_at": xueqiu_updated,
                "preview": (xueqiu_cookie[:40] + "…") if len(xueqiu_cookie) > 40 else xueqiu_cookie,
            },
            "weibo_cookie": {
                "set": bool(weibo_cookie),
                "updated_at": weibo_updated,
                "preview": (weibo_cookie[:40] + "…") if len(weibo_cookie) > 40 else weibo_cookie,
            },
            "polling_config": _effective_polling(),
            "recent_source_events": db.recent_source_events(30),
            "kol_health": kol_health,
            "retry_pending": int(db.get_setting("stats_retry_pending") or 0),
            "alerts": {
                "push_alert_last_at": db.get_setting("push_alert_last_at") or "",
                "x_direct_alert_at": db.get_setting("x_direct_alert_at") or "",
                "cookie_keepalive_alert_at": db.get_setting("cookie_keepalive_alert_at") or "",
                "xueqiu_probe_alert_at": db.get_setting("xueqiu_probe_alert_at") or "",
            },
        }

    @router.put("/users/{user_id}", dependencies=[Depends(require_admin)])
    def update_user(user_id: int, body: UserUpdate, admin: dict = Depends(require_admin)):
        target = db.get_user(user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        if "is_admin" in body.model_fields_set:
            if user_id == admin["id"] and not body.is_admin:
                raise HTTPException(status_code=400, detail="不能取消自己的管理员权限")
            db.update_user(user_id, is_admin=body.is_admin)
        if "password" in body.model_fields_set:
            password = body.password or ""
            if len(password) < 6:
                raise HTTPException(status_code=400, detail="密码至少6位")
            if len(password) > MAX_PASSWORD_LEN:
                raise HTTPException(status_code=400, detail=f"密码最长{MAX_PASSWORD_LEN}位")
            db.update_user(user_id, password_hash=auth.hash_password(password))
        if "username" in body.model_fields_set:
            username = (body.username or "").strip()
            if len(username) < 6 or len(username) > 30:
                raise HTTPException(status_code=400, detail="用户名需6-30位")
            existing = db.get_user_by_username_ci(username)
            if existing is not None and existing["id"] != user_id:
                raise HTTPException(status_code=400, detail="用户名已存在")
            db.update_user(user_id, username=username)
        _audit(
            admin,
            "update_user",
            str(user_id),
            f"is_admin={body.is_admin} password={'*' if body.password else ''} username={body.username}",
        )
        return admin_user_summary(db.get_user(user_id))

    @router.delete("/users/{user_id}", dependencies=[Depends(require_admin)])
    def delete_user(user_id: int, admin: dict = Depends(require_admin)):
        if user_id == admin["id"]:
            raise HTTPException(status_code=400, detail="不能删除自己的账号")
        target = db.get_user(user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        db.delete_user(user_id)
        _audit(admin, "delete_user", str(user_id), target["username"])
        return {"ok": True}

    @router.post("/admin/test-push", dependencies=[Depends(require_admin)])
    def test_push(body: TestPushIn):
        user = db.get_user(body.user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        if notifiers_config is None:
            raise HTTPException(status_code=400, detail="未配置推送渠道")
        from .channels import CHANNELS, build_channel_notifier, channel_bound

        results = []
        for channel in CHANNELS:
            if not channel_bound(user, channel, notifiers_config):
                continue
            notifier = build_channel_notifier(channel, user, notifiers_config, db=db)
            try:
                notifier.send_text(f"【测试推送】{body.message}")
                results.append({"channel": channel, "ok": True})
            except Exception as exc:  # noqa: BLE001
                results.append({"channel": channel, "ok": False, "error": str(exc)})
            finally:
                notifier.client.close()
        if not results:
            raise HTTPException(status_code=400, detail="该用户未绑定任何推送渠道")
        return {"results": results}

    @router.post("/admin/weibo-qr/start", dependencies=[Depends(require_admin)])
    def weibo_qr_start():
        """生成微博扫码登录二维码，返回 qrid 与二维码图片地址。"""
        now = time.time()
        # 清理超过 5 分钟的旧会话
        for qrid, session in list(weibo_qr_sessions.items()):
            if now - session["created_at"] > 300:
                session["client"].close()
                weibo_qr_sessions.pop(qrid, None)
        try:
            client, qrid, qrurl = create_qr()
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="获取微博二维码失败，请稍后重试")
        weibo_qr_sessions[qrid] = {
            "client": client,
            "created_at": now,
        }
        return {"qrid": qrid, "qrurl": qrurl}

    @router.get("/admin/weibo-qr/status", dependencies=[Depends(require_admin)])
    def weibo_qr_status(qrid: str):
        """轮询扫码状态；确认后自动完成登录并保存 Cookie。"""
        session = weibo_qr_sessions.get(qrid)
        if session is None:
            raise HTTPException(status_code=404, detail="二维码已过期，请重新生成")
        client = session["client"]
        try:
            result = poll_qr(client, qrid)
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="微博登录状态获取失败，请重试") from None
        status = result.get("status")
        if status == "pending":
            return {"status": "pending"}
        if status == "scanned":
            return {"status": "scanned"}
        if status == "expired":
            raise HTTPException(status_code=400, detail="二维码已失效，请重新生成")
        if status == "ok" and result.get("cookie"):
            cookie = result["cookie"]
            db.set_setting(WEIBO_COOKIE_KEY, cookie)
            client.close()
            weibo_qr_sessions.pop(qrid, None)
            return {"status": "ok"}
        raise HTTPException(
            status_code=400,
            detail=f"微博登录异常: {result.get('detail') or status}",
        )

    @router.get("/img-proxy")
    def img_proxy(url: str, request: Request):
        """第三方图床图片代理：X/雪球图床在部分网络（如大陆直连 X）不可达，经服务器转发。

        优先走 safe_get 的 SSRF 校验（仅 http/https、拒绝内网/保留网段、重定向逐跳校验）。
        已知公共图床域名（pbs.twimg.com 等）在部分家庭/公司网络会被 DNS 劫持到
        透明代理地址（198.18/15 保留段），SSRF 校验会误拒；对这些白名单域名放宽
        IP 网段校验（仍强制图片类型与大小限制，防被当作任意内容代理）。
        """
        from urllib.parse import urlparse

        from .url_safety import safe_get

        url = (url or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="缺少 url 参数")
        try:
            parsed = urlparse(url)
        except ValueError:
            raise HTTPException(status_code=400, detail="非法 url") from None
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise HTTPException(status_code=400, detail="非法 url")
        import httpx

        client = httpx.Client(
            timeout=15,
            follow_redirects=False,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
                "Referer": "https://weibo.com/",  # 部分图床防盗链；对 X/雪球无副作用
            },
        )
        try:
            if parsed.hostname.lower() in IMAGE_PROXY_HOSTS:
                # 白名单图床：DNS 可能被劫持到透明代理网段，跳过 IP 网段校验直接下载
                resp = client.get(url, timeout=15, follow_redirects=False)
            else:
                try:
                    resp = safe_get(client, url)
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from None
            content_type = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
            if content_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
                raise HTTPException(status_code=400, detail="非图片内容")
            body = resp.content
            if len(body) > 10 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="图片过大")
            return Response(
                content=body,
                media_type=content_type,
                headers={"Cache-Control": "public, max-age=86400"},
            )
        finally:
            client.close()

    return router
