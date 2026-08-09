"""飞书个人机器人：扫码注册（device-code 协议）、临时绑定监听、推送路由决策。

设计文档：docs/superpowers/specs/2026-08-09-feishu-personal-bot-registration-design.md

个人机器人只承担推送职责：无 /list /sub 等常驻命令、无卡片回调、无常驻连接。
验证成功前及失效后均回退到共享机器人，不动 users 表的共享飞书字段。
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
import time

import httpx

logger = logging.getLogger(__name__)

FEISHU_REGISTRATION_BASE = "https://accounts.feishu.cn"
LARK_REGISTRATION_BASE = "https://accounts.larksuite.com"

# 明确的应用/权限/凭据类错误码：命中即标记 degraded 并共享回退（设计 8.3）
DEFINITIVE_ERROR_CODES = frozenset({
    230101,  # 用户不存在
    91002,   # 无权限/未开通
    20001,   # 应用或能力不存在
    99991670,
})
BIND_CODE_TTL = 60  # 绑定码有效期（秒）
POLL_MAX_ACTIVE = 16  # 同时进行中的轮询/监听上限（ponytail: 简单上限防资源滥用）
POLL_MAX_INTERVAL = 30


def _fernet(key_b64: str):
    from cryptography.fernet import Fernet

    return Fernet(key_b64)


def encrypt_secret(key_b64: str, value: str) -> str:
    return _fernet(key_b64).encrypt(value.encode()).decode()


def decrypt_secret(key_b64: str, ciphertext: str) -> str:
    return _fernet(key_b64).decrypt(ciphertext.encode()).decode()


def hash_bind_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def mask_app_id(app_id: str) -> str:
    """脱敏应用标识：cli_ab12…（保留前 8 位），用于日志/API 展示。"""
    return f"{app_id[:8]}…" if len(app_id) > 8 else "…"


def qr_data_uri(url: str) -> str:
    """把链接渲染成二维码 PNG 的 data URI（前端 <img> 直接显示）。

    纯 Python 实现（qrcode + pypng），无 Pillow 依赖；失败返回空串由前端降级为链接。
    """
    try:
        import base64
        import io

        import qrcode
        from qrcode.image.pure import PyPNGImage

        img = qrcode.make(
            url, image_factory=PyPNGImage, box_size=8, border=2, error_correction=qrcode.constants.ERROR_CORRECT_M
        )
        buf = io.BytesIO()
        img.save(buf)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001 - 二维码生成失败降级为纯链接
        logger.warning("二维码生成失败，降级为链接 url=%s", (url or "")[:60])
        return ""


def _post_form(url: str, data: dict, timeout: int = 15) -> dict:
    resp = httpx.post(url, data=data, timeout=timeout)
    if resp.status_code == 400:
        # 注册协议用 HTTP 400 表达正常等待/业务错误（authorization_pending 等），
        # body 仍是 JSON；其余 4xx/5xx 直接抛给调用方按网络异常处理
        try:
            return resp.json()
        except ValueError:
            pass
    resp.raise_for_status()
    return resp.json()


class RegistrationFlowError(Exception):
    """注册协议流程错误：code 为协议错误标识（authorization_pending/slow_down/...）。"""

    def __init__(self, code: str, message: str, base_url: str = ""):
        super().__init__(message)
        self.code = code
        self.base_url = base_url


def begin_registration(base_url: str = FEISHU_REGISTRATION_BASE) -> tuple[dict, str]:
    """begin：发起扫码注册，返回 (响应字段, 实际 base_url)。

    响应字段含 device_code / verification_uri / verification_uri_complete /
    expires_in / interval。
    """
    body = _post_form(
        f"{base_url}/oauth/v1/app/registration",
        {
            "action": "begin",
            "archetype": "PersonalAgent",
            "auth_method": "client_secret",
            "request_user_info": "open_id",
        },
    )
    if body.get("device_code") and body.get("verification_uri"):
        return body, base_url
    raise RegistrationFlowError(
        str(body.get("error") or "unknown"), str(body.get("error_description") or body)
    )


def poll_registration(device_code: str, base_url: str) -> dict:
    """poll 一次注册结果。等待中抛 RegistrationFlowError(code='authorization_pending')。"""
    body = _post_form(
        f"{base_url}/oauth/v1/app/registration",
        {"action": "poll", "device_code": device_code},
    )
    error = body.get("error")
    if error:
        raise RegistrationFlowError(error, str(body.get("error_description") or ""), base_url)
    return body


def _parse_bind_code(text: str) -> str | None:
    """解析 p2p 消息里的 /bind <6位hex>（大小写不敏感、允许多余空白）。"""
    parts = (text or "").strip().split()
    if len(parts) != 2 or parts[0].lower() != "/bind":
        return None
    code = parts[1].strip().lower()
    if len(code) == 6 and all(c in "0123456789abcdef" for c in code):
        return code
    return None


class FeishuBindListener:
    """临时绑定监听：只接收 p2p 的 /bind 消息，成功后停止处理事件。

    每个注册会话最多一条 lark ws 长连接，daemon 线程；SDK 无公开停止 API，
    stop() 置位后事件直接忽略（ponytail: 连接随进程回收，上限受并发会话数约束）。
    """

    def __init__(self, db, manager, session_id: str, app_id: str, app_secret: str, expected_open_id: str):
        self.db = db
        self.manager = manager
        self.session_id = session_id
        self.app_id = app_id
        self.app_secret = app_secret
        self.expected_open_id = expected_open_id
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"fs-bind-{session_id[:8]}")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._done.set()

    def _on_message(self, event) -> None:
        if self._done.is_set():
            return
        try:
            message = event.event.message
            content = json.loads(message.content or "{}")
            text = content.get("text") or ""
            if (message.chat_type or "p2p") != "p2p":
                return
            sender = event.event.sender
            open_id = (sender.sender_id or {}).open_id or ""
            if self.expected_open_id and open_id != self.expected_open_id:
                logger.warning("绑定消息发送者与预期 open_id 不一致 session=%s", self.session_id[:8])
                return
            code = _parse_bind_code(text)
            if code is None:
                return  # 临时监听期间除 /bind 外一律忽略（设计 4.3）
            self.manager.handle_bind_message(self.session_id, code, open_id, message.chat_id or "")
        except Exception:  # noqa: BLE001 - 监听处理失败不影响主服务
            logger.exception("临时绑定监听处理失败 session=%s", self.session_id[:8])

    def _run(self) -> None:
        import lark_oapi
        from lark_oapi.event.dispatcher_handler import EventDispatcherHandler

        handler = (
            EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_message)
            .build()
        )
        ws_client = lark_oapi.ws.Client(
            self.app_id,
            self.app_secret,
            event_handler=handler,
            log_level=lark_oapi.LogLevel.INFO,
        )
        ws_client.start()  # 阻塞；daemon 线程随进程退出


class FeishuPersonalManager:
    """个人机器人注册会话管理器：轮询、绑定码、临时监听、测试激活、禁用。"""

    def __init__(self, db, config):
        self.db = db
        self.config = config  # FeishuConfig（含 credential_key）
        self._lock = threading.Lock()
        self._pollers: dict[str, threading.Thread] = {}
        self._listeners: dict[str, FeishuBindListener] = {}
        self._stopping = threading.Event()
        # 绑定码明文只存进程内存（DB 只存哈希）；状态接口/刷新码从内存读。
        # 进程重启即失效——用户点「重新生成绑定码」即可（设计：明文不落库）。
        self._bind_commands: dict[str, tuple[str, int]] = {}

    # ---- 可用性 ----
    def available(self) -> bool:
        return bool(self.config and self.config.credential_key)

    def _key(self) -> str:
        if not self.available():
            raise RuntimeError("服务端未配置 FEISHU_CREDENTIAL_KEY，个人机器人功能不可用")
        return self.config.credential_key

    # ---- 注册会话 ----
    def begin_session(self, user_id: int) -> dict:
        """开始扫码注册：取消旧会话 → begin → 存会话 → 起后台轮询。"""
        self.db.cancel_feishu_registration_sessions_by_user(user_id)
        body, base = begin_registration()
        session_id = secrets.token_urlsafe(16)
        expires_at = int(time.time()) + int(body.get("expires_in", 3600))
        self.db.create_feishu_registration_session(
            session_id=session_id,
            user_id=user_id,
            device_code_ciphertext=encrypt_secret(self._key(), body["device_code"]),
            registration_base_url=base,
            verification_uri=body.get("verification_uri_complete") or body["verification_uri"],
            session_expires_at=expires_at,
            poll_interval=int(body.get("interval", 5)),
            status="pending",
        )
        self._start_poller(session_id)
        return self.db.get_feishu_registration_session(session_id)

    def cancel_session(self, session_id: str) -> None:
        session = self.db.get_feishu_registration_session(session_id)
        if session is None or session["status"] in ("expired", "cancelled", "active"):
            return
        self.db.update_feishu_registration_session(session_id, status="cancelled")
        self._stop_listener(session_id)
        self._drop_bind_command(session_id)

    def disable(self, user_id: int) -> None:
        """解绑个人机器人：擦除凭据与绑定状态；共享飞书字段保持原值。"""
        self.db.delete_feishu_personal_bot(user_id)
        active = self.db.get_active_feishu_registration_session(user_id)
        if active is not None:
            self.cancel_session(active["session_id"])
        self.db.cancel_feishu_registration_sessions_by_user(user_id)

    def expire_stale(self) -> int:
        return self.db.expire_stale_feishu_registration_sessions()

    # ---- 轮询 ----
    def _start_poller(self, session_id: str) -> None:
        with self._lock:
            if session_id in self._pollers:
                return
            if len(self._pollers) >= POLL_MAX_ACTIVE:
                logger.warning("飞书个人注册轮询已达上限 %s", POLL_MAX_ACTIVE)
                return
            t = threading.Thread(target=self._poll_loop, args=(session_id,), daemon=True, name=f"fs-poll-{session_id[:8]}")
            self._pollers[session_id] = t
            t.start()

    def _poll_loop(self, session_id: str) -> None:
        try:
            session = self.db.get_feishu_registration_session(session_id)
            if session is None:
                return
            base = session["registration_base_url"]
            interval = max(1, int(session["poll_interval"] or 5))
            while not self._stopping.is_set():
                session = self.db.get_feishu_registration_session(session_id)
                if session is None or session["status"] != "pending":
                    return
                if int(session["session_expires_at"] or 0) < int(time.time()):
                    self.db.update_feishu_registration_session(session_id, status="expired")
                    return
                try:
                    dc = decrypt_secret(self._key(), session["device_code_ciphertext"])
                    body = poll_registration(dc, base)
                except RegistrationFlowError as exc:
                    if exc.code == "authorization_pending":
                        pass
                    elif exc.code == "slow_down":
                        interval = min(interval + 5, POLL_MAX_INTERVAL)
                    elif exc.code == "access_denied":
                        self.db.update_feishu_registration_session(session_id, status="cancelled", last_error="access_denied")
                        return
                    elif exc.code in ("expired_token", "invalid_grant"):
                        self.db.update_feishu_registration_session(session_id, status="expired", last_error=exc.code)
                        return
                    else:
                        self.db.update_feishu_registration_session(session_id, status="degraded", last_error=str(exc)[:300])
                        return
                except Exception as exc:  # noqa: BLE001 - 网络类异常保留 pending 下次重试
                    logger.warning("飞书注册轮询异常 session=%s err=%s", session_id[:8], exc)
                    time.sleep(interval)
                    continue
                else:
                    self._handle_poll_success(session_id, body, base)
                    return
                time.sleep(interval)
        finally:
            with self._lock:
                self._pollers.pop(session_id, None)

    def _handle_poll_success(self, session_id: str, body: dict, base: str) -> None:
        client_id = body.get("client_id") or body.get("app_id") or ""
        client_secret = body.get("client_secret") or body.get("app_secret") or ""
        user_info = body.get("user_info") or {}
        expected_open_id = user_info.get("open_id") or ""
        if not client_id or not client_secret or not expected_open_id:
            self.db.update_feishu_registration_session(
                session_id, status="degraded",
                last_error="注册结果缺少 client_id/client_secret/open_id",
            )
            return
        brand = "lark" if str(user_info.get("tenant_brand", "")).lower() == "lark" else "feishu"
        if brand == "lark" and base != LARK_REGISTRATION_BASE:
            # 租户为 Lark：后续流程切换国际域名（设计 5.1）
            base = LARK_REGISTRATION_BASE
        self.db.update_feishu_registration_session(
            session_id,
            status="credentials_created",
            candidate_app_id=client_id,
            candidate_app_secret_ciphertext=encrypt_secret(self._key(), client_secret),
            candidate_tenant_brand=brand,
            expected_open_id=expected_open_id,
            registration_base_url=base,
        )
        self.issue_bind_code(session_id)

    # ---- 绑定码 ----
    def issue_bind_code(self, session_id: str) -> dict:
        """生成/刷新 60 秒绑定码；作废旧码，新码立即生效。"""
        session = self.db.get_feishu_registration_session(session_id)
        if session is None:
            raise RuntimeError("注册会话不存在")
        if int(session["session_expires_at"] or 0) < int(time.time()):
            self.db.update_feishu_registration_session(session_id, status="expired")
            raise RuntimeError("注册会话已过期，请重新扫码")
        code = secrets.token_hex(3)
        expires_at = int(time.time()) + BIND_CODE_TTL
        self.db.update_feishu_registration_session(
            session_id,
            status="awaiting_bind",
            bind_code_hash=hash_bind_code(code),
            bind_code_expires_at=expires_at,
        )
        with self._lock:
            self._bind_commands[session_id] = (code, expires_at)
        self._ensure_listener(session_id)
        return {"bind_command": f"/bind {code}", "bind_code_expires_at": expires_at}

    def get_bind_command(self, session_id: str) -> tuple[str, int] | None:
        """返回 (绑定码, 过期时间戳)；过期或无则 None（调用方决定是否提示刷新）。"""
        with self._lock:
            entry = self._bind_commands.get(session_id)
        if not entry:
            return None
        code, expires_at = entry
        if expires_at < int(time.time()):
            self._drop_bind_command(session_id)
            return None
        return code, expires_at

    def _drop_bind_command(self, session_id: str) -> None:
        with self._lock:
            self._bind_commands.pop(session_id, None)

    # ---- 临时监听器 ----
    def _ensure_listener(self, session_id: str) -> None:
        session = self.db.get_feishu_registration_session(session_id)
        if session is None or not session.get("candidate_app_id"):
            return
        with self._lock:
            if session_id in self._listeners:
                return
            try:
                app_secret = decrypt_secret(self._key(), session["candidate_app_secret_ciphertext"])
            except Exception as exc:  # noqa: BLE001
                logger.warning("解密候选凭据失败 session=%s err=%s", session_id[:8], exc)
                return
            listener = FeishuBindListener(
                self.db, self, session_id, session["candidate_app_id"], app_secret,
                session.get("expected_open_id") or "",
            )
            self._listeners[session_id] = listener
            listener.start()

    def _stop_listener(self, session_id: str) -> None:
        with self._lock:
            listener = self._listeners.pop(session_id, None)
        if listener is not None:
            listener.stop()

    # ---- 绑定消费 ----
    def handle_bind_message(self, session_id: str, code: str, sender_open_id: str, chat_id: str) -> None:
        """收到 /bind：校验、单次消费、测试消息、激活个人机器人。"""
        session = self.db.get_feishu_registration_session(session_id)
        if session is None or session["status"] != "awaiting_bind":
            return
        if not session.get("bind_code_hash") or int(session.get("bind_code_expires_at") or 0) < int(time.time()):
            self.db.update_feishu_registration_session(session_id, status="degraded", last_error="绑定码已过期")
            self._stop_listener(session_id)
            return
        if hash_bind_code(code) != session["bind_code_hash"]:
            return  # 码不匹配：忽略，等待正确码
        if session.get("expected_open_id") and sender_open_id != session["expected_open_id"]:
            return
        # 单次消费：作废绑定码，进入测试
        self.db.update_feishu_registration_session(
            session_id, bind_code_hash="", bind_code_expires_at=None, status="testing"
        )
        self._drop_bind_command(session_id)
        app_id = session["candidate_app_id"]
        try:
            app_secret = decrypt_secret(self._key(), session["candidate_app_secret_ciphertext"])
        except Exception as exc:  # noqa: BLE001
            self.db.update_feishu_registration_session(session_id, status="degraded", last_error=f"解密失败: {exc}")
            return
        from .notifiers.feishu import FeishuNotifier

        user_id = session["user_id"]
        notifier = FeishuNotifier(self.config, app_id=app_id, app_secret=app_secret, chat_id=chat_id)
        try:
            notifier.send_text("✅ 个人机器人绑定成功！之后的新帖推送会通过本机器人发送。")
        except Exception as exc:  # noqa: BLE001
            self.db.update_feishu_registration_session(session_id, status="degraded", last_error=str(exc)[:300])
            self._stop_listener(session_id)
            logger.warning("飞书个人机器人测试消息失败 user=%s err=%s", user_id, exc)
            return
        try:
            # 测试成功：单事务 upsert 正式记录（旧 active 记录在新应用可用前始终保留）
            self.db.save_feishu_personal_bot(
                user_id, app_id, session["candidate_app_secret_ciphertext"],
                session["candidate_tenant_brand"], "active",
                open_id=sender_open_id, chat_id=chat_id,
            )
        except Exception as exc:  # noqa: BLE001 - app_id 唯一冲突（已被他人绑定）等
            self.db.update_feishu_registration_session(session_id, status="degraded", last_error=str(exc)[:300])
            self._stop_listener(session_id)
            logger.warning("保存个人机器人记录失败 user=%s err=%s", user_id, exc)
            return
        self.db.update_feishu_registration_session(session_id, status="active")
        self._stop_listener(session_id)
        logger.info("飞书个人机器人绑定成功 user=%s app=%s", user_id, mask_app_id(app_id))

    def shutdown(self) -> None:
        self._stopping.set()


def resolve_personal_target(db, config, user: dict) -> dict | None:
    """个人机器人 active 且有会话 → 返回个人推送目标；否则 None（走共享）。"""
    if not config or not getattr(config, "credential_key", ""):
        return None
    bot = db.get_feishu_personal_bot(user["id"])
    if bot is None or bot["status"] != "active" or not bot.get("chat_id"):
        return None
    try:
        app_secret = decrypt_secret(config.credential_key, bot["app_secret_ciphertext"])
    except Exception:  # noqa: BLE001 - 解密失败按共享处理
        return None
    return {
        "app_id": bot["app_id"],
        "app_secret": app_secret,
        "open_id": bot.get("open_id") or "",
        "chat_id": bot["chat_id"],
    }


def build_personal_feishu_kwargs(db, config, user: dict) -> dict:
    """构造 FeishuNotifier 需要的身份 kwargs：个人 active 优先，否则共享。

    供 channels/scheduler 各构造点统一使用：个人应用域身份 vs 共享应用域身份。
    注意：个人路由只下发 chat_id（open_id 置 None）——FeishuNotifier 优先按 open_id
    发送，而个人应用的 open_id 直发会被 230101 拦截，chat_id 是稳定路径
    （绑定测试消息即只传 chat_id 成功）。
    """
    target = resolve_personal_target(db, config, user)
    if target:
        return {
            "app_id": target["app_id"],
            "app_secret": target["app_secret"],
            "open_id": None,
            "chat_id": target["chat_id"],
        }
    return {
        "app_id": None,
        "app_secret": None,
        "open_id": user.get("feishu_open_id") if not user.get("feishu_chat_id") else None,
        "chat_id": user.get("feishu_chat_id") or None,
    }


def is_definitive_feishu_error(exc: Exception) -> bool:
    """明确的应用/权限/凭据类错误 → 降级并共享回退；网络类模糊错误不在此列。"""
    text = str(exc)
    for code in DEFINITIVE_ERROR_CODES:
        if f"code={code}" in text:
            return True
    for kw in ("权限", "未开通", "应用不存在", "用户不存在", "app_secret", "凭据"):
        if kw in text:
            return True
    return False


def mark_personal_degraded(db, user_id: int, message: str) -> None:
    bot = db.get_feishu_personal_bot(user_id)
    if bot is not None and bot["status"] == "active":
        db.update_feishu_personal_bot(user_id, status="degraded", last_error=str(message)[:300])
