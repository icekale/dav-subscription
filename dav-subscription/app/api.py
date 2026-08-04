"""REST API：认证、订阅目录、我的动态、KOL/分类管理。"""
from __future__ import annotations

import re
import secrets
import time
import os

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from . import auth
from . import wechat
from .bot_core import BIND_CODE_TTL
from .db import ALLOWED_PLATFORMS, DB
from .fetchers.xueqiu import (
    XUEQIU_COOKIE_KEY,
    XUEQIU_COOKIE_TIME_KEY,
    resolve_profile,
)
from .fetchers.weibo import WEIBO_COOKIE_KEY
from .weibo_qr import create_qr, poll_qr


def _normalize_weibo_id(external_id: str) -> str:
    """微博主页链接（https://weibo.com/u/<uid>）提取 UID。"""
    match = re.search(r"weibo\.com/u/(\d+)", external_id)
    return match.group(1) if match else external_id


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
    feishu_open_id: str | None = None
    feishu_chat_id: str | None = None
    notify_enabled: bool | None = None
    daily_report_enabled: bool | None = None


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
        "feishu_open_id": user["feishu_open_id"],
        "feishu_chat_id": user["feishu_chat_id"],
        "notify_enabled": bool(user["notify_enabled"]),
        "daily_report_enabled": bool(user.get("daily_report")),
        "created_at": user["created_at"],
    }


def create_api_router(
    db: DB,
    secret: str,
    allow_register: bool = True,
    wechat_config=None,
    notifiers_config=None,
) -> APIRouter:
    router = APIRouter(prefix="/api")
    # 登录/注册限流（内存版，单实例够用）：每 IP 窗口内失败次数超限后 429
    login_attempts: dict[str, list[float]] = {}
    LOGIN_MAX_FAILURES = 8
    LOGIN_WINDOW = 300
    MAX_PASSWORD_LEN = 128
    # 微博扫码登录会话：qrid -> {client, created_at}
    weibo_qr_sessions: dict[str, dict] = {}

    def _client_ip(request: Request) -> str:
        """优先取 X-Forwarded-For 首段（反代场景），否则用直连 IP。"""
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
        # 防止无界增长：超过 1000 个 IP 时清掉窗口外旧记录
        if len(login_attempts) > 1000:
            expired = [k for k, v in login_attempts.items() if not v]
            for k in expired:
                login_attempts.pop(k, None)

    def _record_login_failure(ip: str) -> None:
        login_attempts.setdefault(ip, []).append(time.time())

    def _audit(admin: dict, action: str, target: str = "", detail: str = "") -> None:
        db.log_admin_action(admin["id"], action, target, detail)

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
    @router.post("/auth/register")
    def register(body: RegisterIn, request: Request):
        if not allow_register:
            raise HTTPException(status_code=403, detail="暂未开放注册")
        _check_login_limit(_client_ip(request))
        username = body.username.strip()
        if len(username) < 2 or len(body.password) < 6:
            raise HTTPException(status_code=400, detail="用户名至少2位，密码至少6位")
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
        user = db.get_user(uid)
        return {"token": auth.create_token(uid, username, secret), "user": public_user(user)}

    @router.post("/auth/login")
    def login(body: LoginIn, request: Request):
        ip = _client_ip(request)
        _check_login_limit(ip)
        user = db.get_user_by_username(body.username.strip())
        if user is None:
            auth.verify_password(body.password, auth.DUMMY_HASH)
            _record_login_failure(ip)
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        if not user["password_hash"]:
            # 机器人/微信自动创建的账号没有密码，不能通过账号密码登录
            auth.verify_password(body.password, auth.DUMMY_HASH)
            _record_login_failure(ip)
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        if not body.password or len(body.password) > MAX_PASSWORD_LEN:
            _record_login_failure(ip)
            raise HTTPException(status_code=400, detail=f"密码长度需在 1-{MAX_PASSWORD_LEN} 位之间")
        if not auth.verify_password(body.password, user["password_hash"]):
            _record_login_failure(ip)
            raise HTTPException(status_code=401, detail="用户名或密码错误")
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
            while db.get_user_by_username(username) is not None:
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
    @router.get("/me")
    def me(user: dict = Depends(get_current_user)):
        profile = public_user(user)
        profile["subscription_count"] = len(db.list_subscriptions(user["id"]))
        if notifiers_config is not None:
            profile["push_guide"] = {
                "telegram_bot_username": notifiers_config.telegram.bot_username,
                "feishu_bot_name": notifiers_config.feishu.bot_name,
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
        if "notify_enabled" in body.model_fields_set:
            db.update_user(user["id"], notify_enabled=body.notify_enabled)
        if "daily_report_enabled" in body.model_fields_set and body.daily_report_enabled is not None:
            db.update_user(user["id"], daily_report=body.daily_report_enabled)
        return public_user(db.get_user(user["id"]))

    @router.post("/me/bind-code")
    def create_bind_code(user: dict = Depends(get_current_user)):
        db.delete_expired_bind_codes()
        code = f"{secrets.randbelow(1_000_000):06d}"
        db.create_bind_code(code, user["id"], int(time.time()) + BIND_CODE_TTL)
        return {"code": code, "expires_in_seconds": BIND_CODE_TTL}

    @router.post("/me/password")
    def change_password(body: PasswordChangeIn, user: dict = Depends(get_current_user)):
        if len(body.new_password) < 6:
            raise HTTPException(status_code=400, detail="新密码至少6位")
        if len(body.new_password) > MAX_PASSWORD_LEN:
            raise HTTPException(status_code=400, detail=f"新密码最长{MAX_PASSWORD_LEN}位")
        if not auth.verify_password(body.old_password, user["password_hash"]):
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
        # 按优先级 + 最近活跃排序：优先大V在前，组内最近活跃的靠前
        last_post_at = db.last_post_time_by_kol()
        kols.sort(
            key=lambda k: (bool(k.get("priority")), last_post_at.get(k["id"]) or ""),
            reverse=True,
        )
        subscribed = db.subscribed_kol_ids(user["id"])
        return [{**kol, "subscribed": kol["id"] in subscribed} for kol in kols]

    @router.post("/subscriptions")
    def subscribe(body: SubscriptionIn, user: dict = Depends(get_current_user)):
        kol = db.get_kol(body.kol_id)
        if kol is None or (
            not user["is_admin"] and kol["id"] not in db.visible_kol_ids(user["id"])
        ):
            raise HTTPException(status_code=404, detail="大V不存在")
        db.add_subscription(user["id"], body.kol_id)
        return {"ok": True}

    @router.delete("/subscriptions/{kol_id}")
    def unsubscribe(kol_id: int, user: dict = Depends(get_current_user)):
        db.remove_subscription(user["id"], kol_id)
        return {"ok": True}

    @router.get("/my/subscriptions")
    def my_subscriptions(user: dict = Depends(get_current_user)):
        return db.list_subscriptions(user["id"])

    @router.get("/my/feed")
    def my_feed(limit: int = 100, user: dict = Depends(get_current_user)):
        kol_ids = sorted(db.subscribed_kol_ids(user["id"]))
        return db.list_feed_posts(kol_ids, limit=min(limit, 500))

    @router.get("/kols/{kol_id}")
    def get_kol(kol_id: int, user: dict = Depends(get_current_user)):
        kol = db.get_kol(kol_id)
        if kol is None or (
            not user["is_admin"] and kol["id"] not in db.visible_kol_ids(user["id"])
        ):
            raise HTTPException(status_code=404, detail="大V不存在")
        kol["subscribed"] = kol_id in db.subscribed_kol_ids(user["id"])
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
        return db.list_posts(limit=min(limit, 500), kol_id=kol_id)

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
        elif body.platform == "weibo":
            external_id = _normalize_weibo_id(external_id)
        if not external_id:
            raise HTTPException(status_code=400, detail="请提供大V主页链接或ID")
        try:
            db.add_kol_request(body.platform, external_id, user["id"], name=body.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
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
        name = req["name"] or f"{req['platform']}_{req['external_id']}"
        try:
            kid = db.add_kol(req["platform"], name, req["external_id"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        db.set_kol_request_status(request_id, "approved")
        _audit(admin, "approve_kol_request", str(request_id), f"{name} {req['external_id']}")
        try:
            db.add_subscription(req["user_id"], kid)
        except Exception:  # noqa: BLE001 - 自动订阅失败不阻塞审批
            pass
        if notifiers_config is not None:
            from .notifiers.feishu import FeishuNotifier
            from .notifiers.telegram import TelegramNotifier

            requester = db.get_user(req["user_id"])
            message = f"✅ 你申请的大V「{name}」已通过审批，已自动为你订阅"
            if requester and requester["telegram_chat_id"] and notifiers_config.telegram.bot_token:
                notifier = None
                try:
                    notifier = TelegramNotifier(
                        notifiers_config.telegram, chat_id=requester["telegram_chat_id"]
                    )
                    notifier.send_text(message)
                except Exception:  # noqa: BLE001
                    pass
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
                    pass
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
        _audit(admin, "set_xueqiu_cookie", "", "len=%d" % len(cookie))
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
        return db.list_admin_logs(limit=min(limit, 500))

    # ---- 管理（管理员）----
    @router.get("/kols", dependencies=[Depends(require_admin)])
    def list_kols(platform: str | None = None, category_id: int | None = None):
        return db.list_kols(platform, category_id)

    @router.post("/kols", dependencies=[Depends(require_admin)])
    def add_kol(body: KolIn, admin: dict = Depends(require_admin)):
        if body.platform not in ALLOWED_PLATFORMS:
            raise HTTPException(status_code=400, detail=f"不支持的平台: {body.platform}")
        external_id = body.external_id.strip()
        if body.platform == "xueqiu":
            # 支持直接粘贴雪球主页链接，自动提取 UID
            match = re.search(r"xueqiu\.com/(?:u/)?(\d+)", external_id)
            if match:
                external_id = match.group(1)
        elif body.platform == "weibo":
            # 支持直接粘贴微博主页链接，自动提取 UID
            external_id = _normalize_weibo_id(external_id)
        if not body.name.strip() or not external_id:
            raise HTTPException(status_code=400, detail="昵称与外部ID不能为空")
        if body.category_id is not None and db.get_category(body.category_id) is None:
            raise HTTPException(status_code=400, detail="分类不存在")
        kid = db.add_kol(
            body.platform,
            body.name.strip(),
            external_id,
            category_id=body.category_id,
            priority=body.priority,
            original_only=body.original_only,
        )
        _audit(admin, "add_kol", str(kid), f"{body.platform} {body.name.strip()} {external_id}")
        return db.get_kol(kid)

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
                weibo_match = re.search(r"weibo\.com/u/(\d+)", token)
                if xueqiu_match:
                    external_id = xueqiu_match.group(1)
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
                    db.update_kol_avatar(kid, avatar_url)
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
        if "category_id" in body.model_fields_set and body.category_id is not None:
            if db.get_category(body.category_id) is None:
                raise HTTPException(status_code=400, detail="分类不存在")
        name = body.name.strip() if body.name is not None else None
        external_id = body.external_id.strip() if body.external_id is not None else None
        if name == "" or external_id == "":
            raise HTTPException(status_code=400, detail="昵称与外部ID不能为空")
        kol = db.get_kol(kol_id)
        if external_id is not None and kol["platform"] == "weibo":
            external_id = _normalize_weibo_id(external_id)
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
                target = db.get_user_by_username(username.strip())
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

    @router.get("/categories", dependencies=[Depends(require_admin)])
    def list_categories():
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

    @router.get("/posts", dependencies=[Depends(require_admin)])
    def list_posts(limit: int = 100, platform: str | None = None, kol_id: int | None = None, q: str | None = None):
        return db.list_posts(limit=min(limit, 500), platform=platform, kol_id=kol_id, q=q)

    @router.get("/push-logs", dependencies=[Depends(require_admin)])
    def list_push_logs(
        limit: int = 100,
        user_id: int | None = None,
        channel: str | None = None,
        status: str | None = None,
    ):
        return db.list_push_logs(
            limit=min(limit, 500),
            user_id=user_id,
            channel=channel,
            status=status,
        )

    @router.get("/users", dependencies=[Depends(require_admin)])
    def list_users():
        return [public_user(u) for u in db.list_users()]

    @router.get("/stats", dependencies=[Depends(require_admin)])
    def stats():
        kols = db.list_kols()
        sources = []
        for platform in sorted(ALLOWED_PLATFORMS):
            ok_at = db.get_setting(f"source_ok_{platform}")
            err = db.get_setting(f"source_err_{platform}") or ""
            fails = db.get_setting(f"source_fails_{platform}") or "0"
            sources.append(
                {
                    "platform": platform,
                    "ok": bool(ok_at),
                    "last_ok_at": ok_at,
                    "last_error": err,
                    "consecutive_fails": int(fails),
                }
            )
        xueqiu_cookie = db.get_setting("xueqiu_cookie") or ""
        xueqiu_updated = db.get_setting("xueqiu_cookie_updated_at") or ""
        weibo_cookie = db.get_setting("weibo_cookie") or ""
        weibo_updated = db.get_setting("weibo_cookie_updated_at") or ""
        return {
            "polling_interval_seconds": int(db.get_setting("stats_polling_interval") or 0),
            "keepalive_interval_seconds": int(db.get_setting("stats_keepalive_interval") or 0),
            "posts_retention_days": int(db.get_setting("stats_posts_retention_days") or 0),
            "last_poll_at": db.get_setting("stats_last_poll_at"),
            "last_poll_duration_ms": db.get_setting("stats_last_poll_duration_ms"),
            "last_poll_error": db.get_setting("stats_last_poll_error") or "",
            "kols": len(kols),
            "enabled_kols": sum(1 for k in kols if k["enabled"]),
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
            if len(username) < 2 or len(username) > 30:
                raise HTTPException(status_code=400, detail="用户名需2-30位")
            existing = db.get_user_by_username(username)
            if existing is not None and existing["id"] != user_id:
                raise HTTPException(status_code=400, detail="用户名已存在")
            db.update_user(user_id, username=username)
        _audit(
            admin,
            "update_user",
            str(user_id),
            f"is_admin={body.is_admin} password={'*' if body.password else ''} username={body.username}",
        )
        return public_user(db.get_user(user_id))

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
        from .notifiers.feishu import FeishuNotifier
        from .notifiers.telegram import TelegramNotifier

        results = []
        if user["telegram_chat_id"] and notifiers_config.telegram.bot_token:
            notifier = TelegramNotifier(
                notifiers_config.telegram,
                chat_id=user["telegram_chat_id"],
            )
            try:
                notifier.send_text(f"【测试推送】{body.message}")
                results.append({"channel": "telegram", "ok": True})
            except Exception as exc:  # noqa: BLE001
                results.append({"channel": "telegram", "ok": False, "error": str(exc)})
            finally:
                notifier.client.close()
        if user.get("feishu_open_id") or user.get("feishu_chat_id"):
            notifier = FeishuNotifier(
                notifiers_config.feishu,
                open_id=user["feishu_open_id"] if not user.get("feishu_chat_id") else None,
                chat_id=user.get("feishu_chat_id") or None,
            )
            try:
                notifier.send_text(f"【测试推送】{body.message}")
                results.append({"channel": "feishu", "ok": True})
            except Exception as exc:  # noqa: BLE001
                results.append({"channel": "feishu", "ok": False, "error": str(exc)})
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

    return router
