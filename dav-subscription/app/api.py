"""REST API：认证、订阅目录、我的动态、KOL/分类管理。"""
from __future__ import annotations

import re
import secrets
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from . import auth
from . import wechat
from .bot_core import BIND_CODE_TTL
from .db import ALLOWED_PLATFORMS, DB


class RegisterIn(BaseModel):
    username: str
    password: str


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


class PasswordChangeIn(BaseModel):
    old_password: str
    new_password: str


class KolIn(BaseModel):
    platform: str
    name: str
    external_id: str
    category_id: int | None = None
    priority: bool = False


class KolUpdate(BaseModel):
    name: str | None = None
    external_id: str | None = None
    enabled: bool | None = None
    category_id: int | None = None
    priority: bool | None = None


class CategoryIn(BaseModel):
    name: str


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

    def _check_login_limit(ip: str) -> None:
        now = time.time()
        recent = [t for t in login_attempts.get(ip, []) if now - t < LOGIN_WINDOW]
        login_attempts[ip] = recent
        if len(recent) >= LOGIN_MAX_FAILURES:
            raise HTTPException(status_code=429, detail="尝试次数过多，请 5 分钟后再试")

    def _record_login_failure(ip: str) -> None:
        login_attempts.setdefault(ip, []).append(time.time())

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
        _check_login_limit(request.client.host if request.client else "unknown")
        username = body.username.strip()
        if len(username) < 2 or len(body.password) < 6:
            raise HTTPException(status_code=400, detail="用户名至少2位，密码至少6位")
        if len(username) > 30:
            raise HTTPException(status_code=400, detail="用户名最长30位")
        try:
            # 管理员只能在网页后台指定，注册用户一律为普通用户
            uid = db.add_user(username, auth.hash_password(body.password))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        user = db.get_user(uid)
        return {"token": auth.create_token(uid, username, secret), "user": public_user(user)}

    @router.post("/auth/login")
    def login(body: LoginIn, request: Request):
        ip = request.client.host if request.client else "unknown"
        _check_login_limit(ip)
        user = db.get_user_by_username(body.username.strip())
        if user is None:
            auth.verify_password(body.password, auth.DUMMY_HASH)
            _record_login_failure(ip)
            raise HTTPException(status_code=401, detail="用户名或密码错误")
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
                auth.hash_password(""),
                wechat_openid=openid,
            )
            user = db.get_user(uid)
        return {"token": auth.create_token(user["id"], user["username"], secret), "user": public_user(user)}

    # ---- 我的 ----
    @router.get("/me")
    def me(user: dict = Depends(get_current_user)):
        profile = public_user(user)
        profile["subscription_count"] = len(db.list_subscriptions(user["id"]))
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
        if not auth.verify_password(body.old_password, user["password_hash"]):
            raise HTTPException(status_code=400, detail="原密码错误")
        db.update_user(user["id"], password_hash=auth.hash_password(body.new_password))
        return {"ok": True}

    # ---- 目录与订阅 ----
    @router.get("/catalog")
    def catalog(platform: str | None = None, category_id: int | None = None, user: dict = Depends(get_current_user)):
        kols = db.list_kols(platform, category_id)
        subscribed = db.subscribed_kol_ids(user["id"])
        return [{**kol, "subscribed": kol["id"] in subscribed} for kol in kols]

    @router.post("/subscriptions")
    def subscribe(body: SubscriptionIn, user: dict = Depends(get_current_user)):
        if db.get_kol(body.kol_id) is None:
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
        if kol is None:
            raise HTTPException(status_code=404, detail="大V不存在")
        kol["subscribed"] = kol_id in db.subscribed_kol_ids(user["id"])
        return kol

    @router.get("/kols/{kol_id}/posts")
    def kol_posts(kol_id: int, limit: int = 100, user: dict = Depends(get_current_user)):
        if db.get_kol(kol_id) is None:
            raise HTTPException(status_code=404, detail="大V不存在")
        return db.list_posts(limit=min(limit, 500), kol_id=kol_id)

    # ---- 管理（管理员）----
    @router.get("/kols", dependencies=[Depends(require_admin)])
    def list_kols(platform: str | None = None, category_id: int | None = None):
        return db.list_kols(platform, category_id)

    @router.post("/kols", dependencies=[Depends(require_admin)])
    def add_kol(body: KolIn):
        if body.platform not in ALLOWED_PLATFORMS:
            raise HTTPException(status_code=400, detail=f"不支持的平台: {body.platform}")
        external_id = body.external_id.strip()
        if body.platform == "xueqiu":
            # 支持直接粘贴雪球主页链接，自动提取 UID
            match = re.search(r"xueqiu\.com/(?:u/)?(\d+)", external_id)
            if match:
                external_id = match.group(1)
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
        )
        return db.get_kol(kid)

    @router.put("/kols/{kol_id}", dependencies=[Depends(require_admin)])
    def update_kol(kol_id: int, body: KolUpdate):
        if db.get_kol(kol_id) is None:
            raise HTTPException(status_code=404, detail="KOL 不存在")
        if "category_id" in body.model_fields_set and body.category_id is not None:
            if db.get_category(body.category_id) is None:
                raise HTTPException(status_code=400, detail="分类不存在")
        name = body.name.strip() if body.name is not None else None
        external_id = body.external_id.strip() if body.external_id is not None else None
        if name == "" or external_id == "":
            raise HTTPException(status_code=400, detail="昵称与外部ID不能为空")
        db.update_kol(
            kol_id,
            name=name,
            external_id=external_id,
            enabled=body.enabled,
            category_id=body.category_id if "category_id" in body.model_fields_set else None,
            priority=body.priority if "priority" in body.model_fields_set else None,
        )
        return db.get_kol(kol_id)

    @router.delete("/kols/{kol_id}", dependencies=[Depends(require_admin)])
    def delete_kol(kol_id: int):
        if db.get_kol(kol_id) is None:
            raise HTTPException(status_code=404, detail="KOL 不存在")
        db.delete_kol(kol_id)
        return {"ok": True}

    @router.get("/categories", dependencies=[Depends(require_admin)])
    def list_categories():
        return db.list_categories()

    @router.post("/categories", dependencies=[Depends(require_admin)])
    def add_category(body: CategoryIn):
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="分类名不能为空")
        try:
            cid = db.add_category(name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        return db.get_category(cid)

    @router.put("/categories/{category_id}", dependencies=[Depends(require_admin)])
    def rename_category(category_id: int, body: CategoryIn):
        if db.get_category(category_id) is None:
            raise HTTPException(status_code=404, detail="分类不存在")
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="分类名不能为空")
        try:
            db.rename_category(category_id, name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        return db.get_category(category_id)

    @router.delete("/categories/{category_id}", dependencies=[Depends(require_admin)])
    def delete_category(category_id: int):
        if db.get_category(category_id) is None:
            raise HTTPException(status_code=404, detail="分类不存在")
        db.delete_category(category_id)
        return {"ok": True}

    @router.get("/posts", dependencies=[Depends(require_admin)])
    def list_posts(limit: int = 100, platform: str | None = None, kol_id: int | None = None):
        return db.list_posts(limit=min(limit, 500), platform=platform, kol_id=kol_id)

    @router.get("/push-logs", dependencies=[Depends(require_admin)])
    def list_push_logs(limit: int = 100):
        return db.list_push_logs(limit=min(limit, 500))

    @router.get("/users", dependencies=[Depends(require_admin)])
    def list_users():
        return [public_user(u) for u in db.list_users()]

    @router.get("/stats", dependencies=[Depends(require_admin)])
    def stats():
        kols = db.list_kols()
        return {
            "polling_interval_seconds": int(db.get_setting("stats_polling_interval") or 0),
            "posts_retention_days": int(db.get_setting("stats_posts_retention_days") or 0),
            "last_poll_at": db.get_setting("stats_last_poll_at"),
            "last_poll_duration_ms": db.get_setting("stats_last_poll_duration_ms"),
            "last_poll_error": db.get_setting("stats_last_poll_error") or "",
            "kols": len(kols),
            "enabled_kols": sum(1 for k in kols if k["enabled"]),
            "priority_kols": sum(1 for k in kols if k.get("priority")),
            "users": db.count_users(),
            "posts": db.count_posts(),
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
            db.update_user(user_id, password_hash=auth.hash_password(password))
        if "username" in body.model_fields_set:
            username = (body.username or "").strip()
            if len(username) < 2 or len(username) > 30:
                raise HTTPException(status_code=400, detail="用户名需2-30位")
            existing = db.get_user_by_username(username)
            if existing is not None and existing["id"] != user_id:
                raise HTTPException(status_code=400, detail="用户名已存在")
            db.update_user(user_id, username=username)
        return public_user(db.get_user(user_id))

    @router.delete("/users/{user_id}", dependencies=[Depends(require_admin)])
    def delete_user(user_id: int, admin: dict = Depends(require_admin)):
        if user_id == admin["id"]:
            raise HTTPException(status_code=400, detail="不能删除自己的账号")
        target = db.get_user(user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        db.delete_user(user_id)
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
        if user["feishu_open_id"]:
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

    return router
