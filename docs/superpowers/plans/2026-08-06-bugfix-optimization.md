# dav-subscription Bug 修复与优化 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复代码审查发现的 7 个 bug（优先大V抓取间隔失效、登录/注册限流可绕过、X/微博时间戳原始英文、删除用户残留孤儿数据、SQLite 并发写锁风险、微博并发自动登录竞态、免打扰汇总漏写推送日志），并落地 3 项低风险优化（me 接口 COUNT 查询、X queryId 防雷群、小程序推送设置页轮询收敛）。

**Architecture:** 全部改动集中在后端 `app/` 与小程序 `miniprogram/`。调度器主循环等待时长改为取优先/全局间隔最小值，让 `poll_once` 更频繁被调用、由内部到期判断决定各 KOL 是否抓取；API 限流改为显式信任反代头 + 注册失败计数 + 登录成功清零；时间戳解析在 `format_published_at` 统一处理 RFC2822；数据库层补 busy_timeout、删除级联、COUNT 查询；网络资源加锁防并发。每任务遵循 TDD（除无测试设施的小程序任务，用手工步骤验证）。

**Tech Stack:** Python 3.12、FastAPI、SQLite、httpx、pytest、WeChat 小程序（无测试框架，手工验证）。

**约定：** 项目根为 `dav-subscription/`；所有命令在工作目录 `dav-subscription/` 下执行（先 `source .venv/bin/activate`）；每个任务结束时提交一次 git。测试命令用 `python -m pytest`。

---

## Task 1: 优先大V抓取间隔真正生效

**Files:**
- Modify: `app/scheduler.py`（模块内新增 `_scheduler_loop_delay`，`run()` 末尾改用它）
- Test: `tests/test_scheduler.py`

**问题背景：** `Scheduler.run()` 主循环固定 sleep `interval_seconds`（默认 180s），只每轮调用一次 `poll_once`。`poll_once` 内部对优先大V按 `priority_interval_seconds`（默认 60s）判断到期，但下一次 `poll_once` 要等 180s 才来，优先间隔永远无法生效。修复后主循环按 `min(interval, priority)` sleep，由 `poll_once` 的到期判断决定每个 KOL 本轮是否抓取。

- [ ] **Step 1: 写失败测试（纯函数 + 集成测试）**

在 `tests/test_scheduler.py` 末尾追加（`_scheduler_loop_delay` 与 `asyncio` 均为本地引用，无需改文件头 import）：

```python
def test_scheduler_loop_delay_uses_min_interval():
    from app.scheduler import _scheduler_loop_delay

    assert _scheduler_loop_delay(180, 60, 0) == 60
    assert _scheduler_loop_delay(180, 180, 0) == 180
    assert _scheduler_loop_delay(60, 180, 0) == 60
    assert 60 <= _scheduler_loop_delay(180, 60, 30) <= 90


def test_scheduler_run_loop_sleeps_priority_interval(monkeypatch):
    """主循环单轮等待时长应取优先间隔，而非全局间隔。"""
    import asyncio

    db = make_db()
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
    )
    polling = SimpleNamespace(
        notify_on_start=False,
        jitter_seconds=0,
        interval_seconds=180,
        priority_interval_seconds=60,
        digest_interval_seconds=0,
        source_probe_interval_seconds=0,
        cookie_keepalive_interval_seconds=0,
        daily_report_hour=23,
        posts_retention_days=0,
        push_logs_retention_days=0,
    )
    scheduler = Scheduler(
        db,
        {},
        [],
        polling,
        notifiers_config=ncfg,
        xueqiu_config=SimpleNamespace(cookie=""),
        weibo_config=SimpleNamespace(cookie="", username="", password=""),
    )
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)
        scheduler._stop.set()  # 睡一次就停，只验证单轮等待时长

    monkeypatch.setattr("app.scheduler.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("app.scheduler.poll_once", lambda *a, **k: None)
    asyncio.run(scheduler.run())

    assert sleeps, "主循环应至少 sleep 一次"
    assert 59 < sleeps[0] <= 60, f"应约为优先间隔 60s，实际 {sleeps[0]}"
```

> 说明：`59 < sleeps[0] <= 60` 而非 `== 60`，因为 `sleep = delay - elapsed`，`elapsed` 是 `to_thread` + 落库的真实耗时（毫秒级）。修复前该值约为 `180 - elapsed`，断言可明确区分。

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -m pytest tests/test_scheduler.py::test_scheduler_loop_delay_uses_min_interval tests/test_scheduler.py::test_scheduler_run_loop_sleeps_priority_interval -v`
Expected: 两个测试均 FAIL（`_scheduler_loop_delay` 未定义 / `sleeps[0]` 约为 180）。

- [ ] **Step 3: 实现**

在 `app/scheduler.py` 模块级（`Scheduler` 类定义之前，放在 `flush_digest` 之后）新增：

```python
def _scheduler_loop_delay(
    interval_seconds: int, priority_interval_seconds: int, jitter_seconds: int
) -> float:
    """主循环单轮等待时间：取优先与全局间隔中较小者，保证优先大V更频繁被调度。

    此前主循环固定按全局间隔 sleep，导致 poll_once 里对优先大V的更短到期判断
    永远等不到下一次调用，优先间隔形同虚设。由 poll_once 的内部到期判断决定
    每个 KOL 本轮是否抓取，这里只负责把轮询节奏提到最短间隔。
    """
    base = min(interval_seconds, priority_interval_seconds)
    return base + random.uniform(0, jitter_seconds)
```

把 `app/scheduler.py:1404-1408` 的 `run()` 末尾：

```python
            elapsed = time.monotonic() - started
            delay = interval_seconds + random.uniform(
                0, self.polling_config.jitter_seconds
            )
            await asyncio.sleep(max(0.0, delay - elapsed))
```

改为：

```python
            elapsed = time.monotonic() - started
            delay = _scheduler_loop_delay(
                interval_seconds,
                priority_interval,
                self.polling_config.jitter_seconds,
            )
            await asyncio.sleep(max(0.0, delay - elapsed))
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -m pytest tests/test_scheduler.py::test_scheduler_loop_delay_uses_min_interval tests/test_scheduler.py::test_scheduler_run_loop_sleeps_priority_interval -v`
Expected: 2 passed。

Run: `python -m pytest tests/test_scheduler.py -q`
Expected: 全部通过（回归，含原有 `test_priority_kol_fetched_more_often`）。

- [ ] **Step 5: 提交**

```bash
git add app/scheduler.py tests/test_scheduler.py
git commit -m "fix: 优先大V抓取间隔生效，主循环按最短间隔调度"
```

---

## Task 2: 登录/注册限流加固

**Files:**
- Modify: `app/config.py`（`WebConfig` 加 `trust_proxy`，`_ENV_MAP`、`_validate`、bool 环境变量分支）
- Modify: `app/api.py`（`create_api_router` 加 `trust_proxy` 参数；`_client_ip` 信任可配；注册失败计数；登录成功清零）
- Modify: `app/main.py`（传入 `trust_proxy`）
- Modify: `tests/test_config.py`（`ALL_ENV` 加 `WEB_TRUST_PROXY` + 新测试）
- Test: `tests/test_api.py`

**问题背景：** `_client_ip` 无条件信任 `X-Forwarded-For`，直连暴露时攻击者改头即可绕过登录/注册限流；`register` 失败从不计数；登录成功后历史失败不清零会把正常用户锁死 5 分钟。

- [ ] **Step 1: 写失败测试**

在 `tests/test_config.py` 顶部 `ALL_ENV` 列表末尾追加 `"WEB_TRUST_PROXY",`。文件末尾追加：

```python
def test_web_trust_proxy_default_false_and_env_override(tmp_path, monkeypatch):
    for name in ALL_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    assert load_config(tmp_path / "nope.yaml").web.trust_proxy is False
    monkeypatch.setenv("WEB_TRUST_PROXY", "true")
    assert load_config(tmp_path / "nope.yaml").web.trust_proxy is True
```

在 `tests/test_api.py` 末尾追加：

```python
def test_login_rate_limit_blocks_after_8_failures():
    client = make_client()
    user_headers(client, "victim")
    for _ in range(8):
        assert client.post("/api/auth/login", json={"username": "victim", "password": "bad"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "victim", "password": "bad"}).status_code == 429


def test_xff_spoof_cannot_bypass_rate_limit_without_trust_proxy():
    """未显式信任反代时，伪造 X-Forwarded-For 不能绕过限流。"""
    client = make_client()
    user_headers(client, "victim")
    for i in range(8):
        r = client.post(
            "/api/auth/login",
            json={"username": "victim", "password": "bad"},
            headers={"X-Forwarded-For": f"1.1.1.{i}"},
        )
        assert r.status_code == 401
    r = client.post(
        "/api/auth/login",
        json={"username": "victim", "password": "bad"},
        headers={"X-Forwarded-For": "9.9.9.9"},
    )
    assert r.status_code == 429


def test_xff_trusted_when_trust_proxy_enabled():
    """显式信任反代后，X-Forwarded-For 才作为分桶依据。"""
    cfg = Config()
    cfg.web.trust_proxy = True
    client = make_client(config=cfg)
    user_headers(client, "victim")
    for _ in range(8):
        assert client.post(
            "/api/auth/login",
            json={"username": "victim", "password": "bad"},
            headers={"X-Forwarded-For": "1.1.1.1"},
        ).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"username": "victim", "password": "bad"},
        headers={"X-Forwarded-For": "1.1.1.1"},
    ).status_code == 429
    # 不同伪造 IP 是不同桶，不受影响
    assert client.post(
        "/api/auth/login",
        json={"username": "victim", "password": "bad"},
        headers={"X-Forwarded-For": "2.2.2.2"},
    ).status_code == 401


def test_register_failures_count_toward_limit():
    client = make_client()
    for _ in range(8):
        r = client.post(
            "/api/auth/register",
            json={"username": f"u{_}", "password": "secret123", "code": "INVALID"},
        )
        assert r.status_code == 400
    r = client.post(
        "/api/auth/register",
        json={"username": "u9", "password": "secret123", "code": "INVALID"},
    )
    assert r.status_code == 429


def test_login_success_clears_failure_count():
    client = make_client()
    user_headers(client, "victim")
    for _ in range(8):
        assert client.post("/api/auth/login", json={"username": "victim", "password": "bad"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "victim", "password": "bad"}).status_code == 429
    # 输对密码成功后清零
    assert client.post("/api/auth/login", json={"username": "victim", "password": "pass123456"}).status_code == 200
    assert client.post("/api/auth/login", json={"username": "victim", "password": "bad"}).status_code == 401
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -m pytest tests/test_config.py::test_web_trust_proxy_default_false_and_env_override tests/test_api.py::test_xff_spoof_cannot_bypass_rate_limit_without_trust_proxy tests/test_api.py::test_register_failures_count_toward_limit tests/test_api.py::test_login_success_clears_failure_count -v`
Expected: FAIL（`trust_proxy` 属性不存在 / XFF 伪造可绕过 / 注册失败不计数 / 登录成功不清零）。

- [ ] **Step 3: 实现**

`app/config.py`：

在 `WebConfig` 里加字段：

```python
@dataclass
class WebConfig:
    allow_register: bool = True
    admin_password: str = ""
    token_secret: str = ""
    trust_proxy: bool = False  # 位于可信反向代理之后时置 true，才信任 X-Forwarded-For
```

`_ENV_MAP` 加一行（放在 `"WEB_TOKEN_SECRET"` 行后）：

```python
    "WEB_TRUST_PROXY": ("web", "trust_proxy"),
```

`load_config` 里 bool 环境变量解析分支（`elif env_name in ("NOTIFY_ON_START", "WEB_ALLOW_REGISTER"):`）改为：

```python
            elif env_name in ("NOTIFY_ON_START", "WEB_ALLOW_REGISTER", "WEB_TRUST_PROXY"):
                value = value.strip().lower() in ("1", "true", "yes", "on")
```

`_validate` 的 checks 元组加一行（放在 `("web.allow_register", ...)` 行后）：

```python
        ("web.trust_proxy", config.web, "trust_proxy", bool),
```

`app/api.py`：

`create_api_router` 签名（第 210-216 行）改为：

```python
def create_api_router(
    db: DB,
    secret: str,
    allow_register: bool = True,
    wechat_config=None,
    notifiers_config=None,
    trust_proxy: bool = False,
) -> APIRouter:
```

`_client_ip`（第 226-233 行）改为：

```python
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
```

`login` 成功分支（第 426 行 `return {...}` 之前）插入一行，清零历史失败：

```python
        login_attempts.pop(ip, None)  # 登录成功清零，避免历史失败锁住正常用户
```

`register`（第 384-404 行）整体改为：

```python
    @router.post("/auth/register")
    def register(body: RegisterIn, request: Request):
        if not allow_register:
            raise HTTPException(status_code=403, detail="暂未开放注册")
        ip = _client_ip(request)
        _check_login_limit(ip)
        try:
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
        except HTTPException:
            # 注册失败同样计入限流，避免邀请码爆破
            _record_login_failure(ip)
            raise
        user = db.get_user(uid)
        return {"token": auth.create_token(uid, username, secret), "user": public_user(user)}
```

`app/main.py`（第 130-137 行）`create_api_router(...)` 调用加一行：

```python
            notifiers_config=config.notifiers,
            trust_proxy=config.web.trust_proxy,
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -m pytest tests/test_config.py tests/test_api.py::test_login_rate_limit_blocks_after_8_failures tests/test_api.py::test_xff_spoof_cannot_bypass_rate_limit_without_trust_proxy tests/test_api.py::test_xff_trusted_when_trust_proxy_enabled tests/test_api.py::test_register_failures_count_toward_limit tests/test_api.py::test_login_success_clears_failure_count -v`
Expected: 全部通过。

Run: `python -m pytest tests/test_api.py -q`
Expected: 全部通过（回归，原限流/注册测试不受影响）。

- [ ] **Step 5: 提交**

```bash
git add app/config.py app/api.py app/main.py tests/test_config.py tests/test_api.py
git commit -m "fix: 登录/注册限流加固，X-Forwarded-For 需显式信任"
```

---

## Task 3: X / 微博 RFC2822 时间戳统一转为北京时间

**Files:**
- Modify: `app/fetchers/base.py`（`format_published_at` 支持 RFC2822；顶部加 `import email.utils`）
- Test: `tests/test_format.py`

**问题背景：** X 与微博的 `created_at` 是 `"Fri Aug 06 10:00:00 +0000 2026"` 格式，`format_published_at` 只处理纯数字时间戳，导致通知/小程序里显示原始英文长格式，与其他平台的 `2026-08-06 18:00` 不一致。

- [ ] **Step 1: 写失败测试**

在 `tests/test_format.py` 顶部 import 加 `from app.fetchers.base import format_published_at`。文件末尾追加：

```python
def test_format_published_at_rfc2822():
    # X：UTC +0000 转北京时间
    assert format_published_at("Fri Aug 06 10:00:00 +0000 2026") == "2026-08-06 18:00"
    # 微博：已带 +0800
    assert format_published_at("Wed Aug 05 21:00:00 +0800 2026") == "2026-08-05 21:00"
    # 已是可读格式的不动
    assert format_published_at("2026-08-04 21:00") == "2026-08-04 21:00"
    # 纯数字毫秒时间戳继续转换
    assert format_published_at("1720000000000") == "2024-07-03 17:46"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -m pytest tests/test_format.py::test_format_published_at_rfc2822 -v`
Expected: FAIL（RFC2822 字符串原样返回）。

- [ ] **Step 3: 实现**

`app/fetchers/base.py` 顶部（`from datetime import ...` 行后）加：

```python
import email.utils
```

把 `format_published_at`（第 58-68 行）整体替换为：

```python
def format_published_at(raw: str) -> str:
    """把时间戳（毫秒/秒）或 RFC2822（X/微博）格式化为可读时间，其他格式原样返回。"""
    raw = (raw or "").strip()
    if raw.isdigit():
        ts = int(raw)
        ts = ts / 1000 if ts > 1e12 else ts
        try:
            return datetime.fromtimestamp(ts, tz=CN_TZ).strftime("%Y-%m-%d %H:%M")
        except (ValueError, OSError):
            return raw
    try:
        dt = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return raw
    if dt is None:
        return raw
    return dt.astimezone(CN_TZ).strftime("%Y-%m-%d %H:%M")
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -m pytest tests/test_format.py -v`
Expected: 全部通过。

Run: `python -m pytest tests/test_fetchers.py -q`
Expected: 全部通过（回归，雪球组合 `format_published_at` 调用不受影响）。

- [ ] **Step 5: 提交**

```bash
git add app/fetchers/base.py tests/test_format.py
git commit -m "fix: X/微博 RFC2822 时间戳统一转为北京时间"
```

---

## Task 4: 删除用户时级联清理推送日志与 ACL

**Files:**
- Modify: `app/db.py`（`delete_user`）
- Test: `tests/test_api.py`

**问题背景：** `delete_user` 只清理 bind_codes 与 subscriptions，`push_logs.user_id` 和 `kol_acl.user_id` 指向已删用户的孤儿行会残留。

- [ ] **Step 1: 写失败测试**

在 `tests/test_api.py` 末尾追加：

```python
def test_admin_delete_user_cleans_push_logs_and_acl():
    client = make_client()
    admin_headers = auth_headers(client, "boss")
    reg = register(client, "doomed")
    uid = reg.json()["user"]["id"]
    db = client.app.state.db
    kid = client.post(
        "/api/kols", headers=admin_headers,
        json={"platform": "xueqiu", "name": "A", "external_id": "1"},
    ).json()["id"]
    # 直接造数据：私有大V ACL + 一条推送日志
    db.set_kol_acl(kid, [uid])
    post_id = db.insert_post("xueqiu", kid, "p1", "t", "c", "u", "2026-08-06")
    db.add_push_log(post_id, "telegram", "success", user_id=uid)

    assert client.delete(f"/api/users/{uid}", headers=admin_headers).status_code == 200
    assert db.list_push_logs(user_id=uid) == []
    assert db.acl_user_ids(kid) == []
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -m pytest tests/test_api.py::test_admin_delete_user_cleans_push_logs_and_acl -v`
Expected: FAIL（`list_push_logs(user_id=uid)` 仍有 1 行、`acl_user_ids(kid)` 仍含 uid）。

- [ ] **Step 3: 实现**

`app/db.py` `delete_user`（第 791-794 行）改为：

```python
    def delete_user(self, user_id: int) -> None:
        self._execute("DELETE FROM bind_codes WHERE user_id = ?", (user_id,))
        self._execute("DELETE FROM subscriptions WHERE user_id = ?", (user_id,))
        self._execute("DELETE FROM push_logs WHERE user_id = ?", (user_id,))
        self._execute("DELETE FROM kol_acl WHERE user_id = ?", (user_id,))
        self._execute("DELETE FROM users WHERE id = ?", (user_id,))
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -m pytest tests/test_api.py::test_admin_delete_user_cleans_push_logs_and_acl tests/test_api.py::test_admin_delete_user_cascades -v`
Expected: 2 passed。

- [ ] **Step 5: 提交**

```bash
git add app/db.py tests/test_api.py
git commit -m "fix: 删除用户时级联清理推送日志与 ACL"
```

---

## Task 5: SQLite 设置 busy_timeout

**Files:**
- Modify: `app/db.py`（`DB.__init__`）
- Test: `tests/test_api.py`

**问题背景：** 单进程内靠 `threading.Lock` 串行化，但多 worker/多进程或健康检查并发写时会直接抛 "database is locked"（rollback journal 模式下）。加 `busy_timeout` 兜底。

- [ ] **Step 1: 写失败测试**

在 `tests/test_api.py` 末尾追加：

```python
def test_db_busy_timeout_set():
    client = make_client()
    value = client.app.state.db._conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert value == 5000
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -m pytest tests/test_api.py::test_db_busy_timeout_set -v`
Expected: FAIL（当前 busy_timeout 为 0）。

- [ ] **Step 3: 实现**

`app/db.py` `DB.__init__`（第 172-177 行）在 `self._lock = threading.Lock()` 之后、`PRAGMA journal_mode=DELETE` 之前插入：

```python
        # 并发写（多 worker/健康检查脚本）时等待而非直接报错
        self._conn.execute("PRAGMA busy_timeout = 5000")
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -m pytest tests/test_api.py::test_db_busy_timeout_set -v`
Expected: PASS。

Run: `python -m pytest -q`
Expected: 全部通过（全量回归）。

- [ ] **Step 5: 提交**

```bash
git add app/db.py tests/test_api.py
git commit -m "fix: SQLite 设置 busy_timeout 防并发写锁"
```

---

## Task 6: 微博自动登录加锁，避免并发 worker 互相覆盖 cookie

**Files:**
- Modify: `app/fetchers/weibo.py`（模块级 `_login_lock`；`_login` 拆出 `_do_login`）
- Test: `tests/test_fetchers.py`

**问题背景：** 多个轮询 worker 同时命中 `_login_required` 会并发执行登录，两次登录的 cookie 后写覆盖前写、重复触发风控。

- [ ] **Step 1: 写失败测试**

在 `tests/test_fetchers.py` 末尾追加：

```python
def test_weibo_login_lock_serializes(monkeypatch):
    """并发触发登录时同一时刻只有一个登录流程在跑。"""
    import threading
    import time

    from app.fetchers.weibo import WeiboFetcher

    db = DB(":memory:")
    cfg = SimpleNamespace(cookie="", token="", username="u", password="p")
    fetcher = WeiboFetcher(cfg, db)

    counter = {"active": 0, "max_active": 0, "calls": 0}
    cl = threading.Lock()

    def fake_prelogin(self):
        with cl:
            counter["active"] += 1
            counter["max_active"] = max(counter["max_active"], counter["active"])
            counter["calls"] += 1
        time.sleep(0.05)
        with cl:
            counter["active"] -= 1
        return {"pcid": "", "rsakv": "", "servertime": "1", "nonce": "n", "pubkey": "1"}

    class FakeCookie:
        name = "SUB"
        value = "x"
        domain = "weibo.com"

    class FakeCookies:
        jar = [FakeCookie()]

        def get(self, name, default=None):
            return "x" if name == "SUB" else default

    class FakeClient:
        cookies = FakeCookies()

        def post(self, *a, **k):
            return httpx.Response(200, text="callback(retcode=0)")

    monkeypatch.setattr(WeiboFetcher, "_prelogin", fake_prelogin)
    monkeypatch.setattr(
        WeiboFetcher, "_encrypt_password", staticmethod(lambda pwd, pub, nonce: "enc")
    )
    fetcher.client = FakeClient()

    threads = [threading.Thread(target=fetcher._login) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert counter["calls"] == 2
    assert counter["max_active"] == 1  # 串行：无并发登录
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -m pytest tests/test_fetchers.py::test_weibo_login_lock_serializes -v`
Expected: FAIL（`max_active` 为 2，无锁时两个线程同时进入 `_prelogin`）。

- [ ] **Step 3: 实现**

`app/fetchers/weibo.py` 顶部（第 11 行 `import httpx` 附近）加 `import threading`；在 `WEIBO_COOKIE_KEY = "weibo_cookie"` 附近加模块级锁：

```python
# 同一时刻只允许一个微博登录流程（并发 worker 触发时互斥，避免 cookie 互相覆盖）
_login_lock = threading.Lock()
```

把 `_login`（第 196-246 行）拆成两个方法：

```python
    def _login(self) -> None:
        """weibo.cn passport 登录：拿 SUB 等 cookie 并持久化。"""
        if not self.source_config.username or not self.source_config.password:
            raise RuntimeError("未配置 weibo.username/password，无法自动登录")
        with _login_lock:
            self._do_login()

    def _do_login(self) -> None:
        pre = self._prelogin()
        data = {
            "entry": "weibo",
            "gateway": "1",
            "from": "",
            "savestate": "7",
            "qrcode_flag": "false",
            "useticket": "1",
            "pagerefer": "https://weibo.cn/",
            "door": "",
            "pcid": pre.get("pcid", ""),
            "pwencode": "rsa2",
            "rsakv": pre.get("rsakv", ""),
            "servertime": pre.get("servertime", ""),
            "nonce": pre.get("nonce", ""),
            "pubkey": pre.get("pubkey", ""),
            "encoding": "UTF-8",
            "prelt": "30",
            "url": "https://weibo.cn/",
            "returntype": "META",
            "service": "miniblog",
            "su": base64.b64encode(self.source_config.username.encode()).decode(),
            "sp": self._encrypt_password(self.source_config.password, pre["pubkey"], pre["nonce"]),
        }
        resp = self.client.post(
            LOGIN_URL,
            params={"client": "ssologin.js(v1.4.19)", "_": int(time.time() * 1000)},
            data=data,
        )
        resp.raise_for_status()
        text = resp.text
        if "retcode=0" not in text:
            raise RuntimeError(f"微博登录失败（可能需要验证码或凭据错误）: {text[:200]}")
        # returntype=META 的响应里带 meta refresh 跳转（ticket 交换），
        # httpx 不会自动跟随 meta refresh，需手动 GET 才能拿到 SUB 等会话 cookie。
        if not any(c.name == "SUB" for c in self.client.cookies.jar):
            match = re.search(r"url\s*=\s*['\"]([^'\"]+)['\"]", text)
            if match:
                redirect_url = html.unescape(match.group(1))
                try:
                    self.client.get(redirect_url)
                except Exception as exc:  # noqa: BLE001
                    raise RuntimeError(f"微博登录票据交换失败: {exc}") from None
        if not any(c.name == "SUB" for c in self.client.cookies.jar):
            raise RuntimeError("微博登录后未获取到 SUB cookie")
        cookie = cookie_header(self.client.cookies)
        self.db.set_setting(WEIBO_COOKIE_KEY, cookie)
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -m pytest tests/test_fetchers.py::test_weibo_login_lock_serializes -v`
Expected: PASS（`max_active == 1`）。

Run: `python -m pytest tests/test_fetchers.py -q`
Expected: 全部通过（回归）。

- [ ] **Step 5: 提交**

```bash
git add app/fetchers/weibo.py tests/test_fetchers.py
git commit -m "fix: 微博自动登录加锁，避免并发 worker 互相覆盖 cookie"
```

---

## Task 7: 免打扰汇总推送补写推送日志

**Files:**
- Modify: `app/scheduler.py`（`_send_dnd_summary`）
- Test: `tests/test_scheduler.py`

**问题背景：** DND 时段缓冲的帖子在 `_send_dnd_summary` 里发送成功但不写 `push_logs`，管理后台看不到这些推送记录（审计缺口）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_scheduler.py` 末尾追加：

```python
def test_dnd_summary_writes_push_logs(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_subscription(uid, kid)
    post = make_post(kid)
    db.insert_post("xueqiu", kid, post.external_id, post.title, post.content, post.url, post.published_at)
    sent = []

    class FakeTG:
        channel = "telegram"

        def __init__(self, config, chat_id=None, client=None, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)

        def send_dnd_summary(self, posts):
            sent.append(posts)

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FakeTG)
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="t", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
    )
    scheduler = Scheduler(
        db,
        {},
        [],
        SimpleNamespace(),
        notifiers_config=ncfg,
        xueqiu_config=SimpleNamespace(cookie=""),
        weibo_config=SimpleNamespace(cookie="", username="", password=""),
    )

    scheduler._send_dnd_summary(db.get_user(uid), [post])

    assert len(sent) == 1
    logs = db.list_push_logs(user_id=uid)
    assert len(logs) == 1
    assert logs[0]["channel"] == "telegram"
    assert logs[0]["status"] == "success"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -m pytest tests/test_scheduler.py::test_dnd_summary_writes_push_logs -v`
Expected: FAIL（`len(logs) == 0`，当前不写 push_log）。

- [ ] **Step 3: 实现**

`app/scheduler.py` 的 `_send_dnd_summary`（第 1515-1579 行）整体替换为：

```python
    def _send_dnd_summary(self, user: dict, posts: list[Post]) -> None:
        """把免打扰时段缓冲的动态汇总成一条推送给用户（按所选通道），并补写推送日志。"""
        if self.notifiers_config is None or not posts:
            return
        import httpx

        from .notifiers.feishu import FeishuNotifier
        from .notifiers.telegram import TelegramNotifier
        from .notifiers.wecom import WeComNotifier

        client = httpx.Client(timeout=15)
        try:
            if user["telegram_chat_id"] and _channel_enabled(user, "telegram") and (
                self.notifiers_config.telegram.bot_token or user.get("telegram_bot_token")
            ):
                notifier = TelegramNotifier(
                    self.notifiers_config.telegram,
                    client=client,
                    chat_id=user["telegram_chat_id"],
                    bot_token=user.get("telegram_bot_token") or None,
                )
                try:
                    notifier.send_dnd_summary(posts)
                    for post in posts:
                        post_id = self.db.get_post_id(post.platform, post.external_id)
                        if post_id:
                            self.db.add_push_log(post_id, "telegram", "success", user_id=user["id"])
                except Exception as exc:  # noqa: BLE001
                    logger.warning("免打扰汇总 TG 发送失败 user=%s err=%s", user["username"], exc)
                    maybe_alert_push_failure(
                        self.db,
                        self.notifiers or [],
                        f"user={user['username']} channel=telegram dnd err={exc}",
                    )
            if _channel_enabled(user, "feishu") and (
                user.get("feishu_open_id") or user.get("feishu_chat_id")
            ):
                notifier = FeishuNotifier(
                    self.notifiers_config.feishu,
                    client=client,
                    open_id=user["feishu_open_id"] if not user.get("feishu_chat_id") else None,
                    chat_id=user.get("feishu_chat_id") or None,
                )
                try:
                    notifier.send_dnd_summary(posts)
                    for post in posts:
                        post_id = self.db.get_post_id(post.platform, post.external_id)
                        if post_id:
                            self.db.add_push_log(post_id, "feishu", "success", user_id=user["id"])
                except Exception as exc:  # noqa: BLE001
                    logger.warning("免打扰汇总飞书发送失败 user=%s err=%s", user["username"], exc)
                    maybe_alert_push_failure(
                        self.db,
                        self.notifiers or [],
                        f"user={user['username']} channel=feishu dnd err={exc}",
                    )
            if user.get("wecom_webhook") and _channel_enabled(user, "wecom"):
                notifier = WeComNotifier(
                    self.notifiers_config.wecom,
                    client=client,
                    webhook_url=user["wecom_webhook"],
                )
                try:
                    notifier.send_dnd_summary(posts)
                    for post in posts:
                        post_id = self.db.get_post_id(post.platform, post.external_id)
                        if post_id:
                            self.db.add_push_log(post_id, "wecom", "success", user_id=user["id"])
                except Exception as exc:  # noqa: BLE001
                    logger.warning("免打扰汇总企业微信发送失败 user=%s err=%s", user["username"], exc)
                    maybe_alert_push_failure(
                        self.db,
                        self.notifiers or [],
                        f"user={user['username']} channel=wecom dnd err={exc}",
                    )
        finally:
            client.close()
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -m pytest tests/test_scheduler.py::test_dnd_summary_writes_push_logs tests/test_scheduler.py::test_dnd_summary_failure_alerts_admin tests/test_scheduler.py::test_flush_dnd_buffers_sends_summary -v`
Expected: 3 passed。

Run: `python -m pytest tests/test_scheduler.py -q`
Expected: 全部通过（回归）。

- [ ] **Step 5: 提交**

```bash
git add app/scheduler.py tests/test_scheduler.py
git commit -m "fix: 免打扰汇总推送补写推送日志"
```

---

## Task 8: me 接口订阅数改用 COUNT 查询

**Files:**
- Modify: `app/db.py`（新增 `count_subscriptions`）
- Modify: `app/api.py`（`me` 使用它）
- Test: `tests/test_api.py`

**问题背景：** `me` 的 `subscription_count` 用 `list_subscriptions` 全表取行再 `len()`，改为 COUNT 减少数据传输。

- [ ] **Step 1: 写失败测试**

在 `tests/test_api.py` 末尾追加：

```python
def test_me_subscription_count():
    client = make_client()
    admin_headers = auth_headers(client)
    kid1 = client.post(
        "/api/kols", headers=admin_headers,
        json={"platform": "xueqiu", "name": "A", "external_id": "1"},
    ).json()["id"]
    kid2 = client.post(
        "/api/kols", headers=admin_headers,
        json={"platform": "xueqiu", "name": "B", "external_id": "2"},
    ).json()["id"]
    uh = user_headers(client, "user")
    assert client.get("/api/me", headers=uh).json()["subscription_count"] == 0
    client.post("/api/subscriptions", headers=uh, json={"kol_id": kid1})
    client.post("/api/subscriptions", headers=uh, json={"kol_id": kid2})
    assert client.get("/api/me", headers=uh).json()["subscription_count"] == 2
```

- [ ] **Step 2: 运行测试，确认通过（当前实现即可通过，属重构基准测试）**

Run: `python -m pytest tests/test_api.py::test_me_subscription_count -v`
Expected: PASS（当前 `list_subscriptions` 实现满足断言，作为行为基准）。

- [ ] **Step 3: 实现**

`app/db.py` 在 `list_subscriptions` 方法后新增：

```python
    def count_subscriptions(self, user_id: int) -> int:
        rows = self._rows(
            "SELECT COUNT(*) AS n FROM subscriptions WHERE user_id = ?", (user_id,)
        )
        return rows[0]["n"]
```

`app/api.py` `me`（第 456 行）：

```python
        profile["subscription_count"] = len(db.list_subscriptions(user["id"]))
```

改为：

```python
        profile["subscription_count"] = db.count_subscriptions(user["id"])
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -m pytest tests/test_api.py::test_me_subscription_count -v`
Expected: PASS。

Run: `python -m pytest tests/test_api.py -q`
Expected: 全部通过（回归）。

- [ ] **Step 5: 提交**

```bash
git add app/db.py app/api.py tests/test_api.py
git commit -m "perf: me 接口订阅数改用 COUNT 查询"
```

---

## Task 9: X queryId 刷新加锁，防止并发拉取前端

**Files:**
- Modify: `app/fetchers/twitter.py`（模块级 `_query_ids_lock`；`_refresh_query_ids` 包锁）
- Test: `tests/test_twitter_fetcher.py`

**问题背景：** 冷启动多个 worker 同时发现 `_query_ids` TTL 过期，会并发拉取 X 前端 main bundle（浪费请求、易触发风控）。加锁让同一时刻只拉一次。

- [ ] **Step 1: 写失败测试**

在 `tests/test_twitter_fetcher.py` 末尾追加：

```python
def test_query_id_refresh_single_fetch_within_ttl(monkeypatch):
    """TTL 内多次调用只拉取一次前端（避免并发雷群）。"""
    from app.fetchers import twitter as tw_mod

    saved_loaded = tw_mod._query_ids_loaded
    saved_error = tw_mod._query_ids_error_until
    tw_mod._query_ids_loaded = 0.0
    tw_mod._query_ids_error_until = 0.0
    clock = {"t": 100000.0}
    monkeypatch.setattr(tw_mod.time, "time", lambda: clock["t"])

    class Handler:
        def __init__(self):
            self.requests = 0

        def __call__(self, request):
            self.requests += 1
            if "abs.twimg.com" in str(request.url):
                return httpx.Response(
                    200,
                    text='queryId:"abc123"xxxoperationName:"UserTweets"',
                )
            return httpx.Response(
                200,
                text='<script src="https://abs.twimg.com/responsive-web/client-web/main.abc.js"></script>',
            )

    handler = Handler()
    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        tw_mod._refresh_query_ids(client, "auth_token=x; ct0=y")
        first = handler.requests
        tw_mod._refresh_query_ids(client, "auth_token=x; ct0=y")
        assert handler.requests == first  # TTL 内不重复拉取
    finally:
        tw_mod._query_ids_loaded = saved_loaded
        tw_mod._query_ids_error_until = saved_error
```

- [ ] **Step 2: 运行测试，确认通过（当前实现即可通过，属基准测试）**

Run: `python -m pytest tests/test_twitter_fetcher.py::test_query_id_refresh_single_fetch_within_ttl -v`
Expected: PASS（现有 TTL 检查已满足断言，作为行为基准）。

- [ ] **Step 3: 实现**

`app/fetchers/twitter.py` 顶部（第 11 行 `import logging` 附近）加 `import threading`；在模块级状态变量（第 66-68 行）后加：

```python
_query_ids_lock = threading.Lock()
```

`_refresh_query_ids`（第 94-130 行）整体替换为（在 `with _query_ids_lock:` 内执行原逻辑）：

```python
def _refresh_query_ids(client: httpx.Client, cookie: str) -> None:
    """从 X 前端 main bundle 提取最新的 UserTweets / UserByScreenName queryId。"""
    global _query_ids_loaded, _query_ids_error_until
    with _query_ids_lock:
        now = time.time()
        if now - _query_ids_loaded < QUERY_ID_TTL:
            return
        if now < _query_ids_error_until:
            return  # 上次提取失败，冷却期内不重复打前端
        try:
            headers = _auth_headers(cookie)
            page = client.get("https://x.com/", headers=headers)
            page.raise_for_status()
            match = re.search(
                r'src="(https://abs\.twimg\.com/responsive-web/client-web/main\.[^"]+\.js)"',
                page.text,
            )
            if not match:
                return
            bundle = client.get(match.group(1))
            bundle.raise_for_status()
            text = bundle.text
            for op in ("UserTweets", "UserByScreenName"):
                found = re.search(
                    r'queryId:"([^"]+)"[^}]{0,300}?operationName:"' + re.escape(op) + r'"',
                    text,
                )
                if found:
                    _query_ids[op] = found.group(1)
            _query_ids_loaded = now
            logger.info("X queryId 已从前端更新: %s", _query_ids)
        except Exception as exc:  # noqa: BLE001 - 提取失败用内置默认值兜底
            _query_ids_error_until = now + QUERY_ID_RETRY_COOLDOWN
            logger.warning(
                "X queryId 提取失败，使用默认值，%.0f 秒后重试: %s",
                QUERY_ID_RETRY_COOLDOWN,
                exc,
            )
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -m pytest tests/test_twitter_fetcher.py -v`
Expected: 全部通过（含新增基准测试与原有失败退避测试）。

- [ ] **Step 5: 提交**

```bash
git add app/fetchers/twitter.py tests/test_twitter_fetcher.py
git commit -m "perf: X queryId 刷新加锁，防止并发拉取前端"
```

---

## Task 10: 小程序推送设置页仅在生成绑定码后轮询

**Files:**
- Modify: `miniprogram/pages/settings/settings.js`

**问题背景：** `onShow` 每 5 秒轮询 `/api/me` 最多 20 次，即使只是进页查看也持续打接口。改为仅当用户点了「生成绑定码」后才开始轮询，等待机器人在线 `/bind`，绑定齐或 20 次后自动停止。

> 注：小程序无自动化测试设施，此任务用微信开发者工具手工验证。

- [ ] **Step 1: 修改 `onShow` / `onHide`，新增 `_stopPolling` / `_startPolling`**

`miniprogram/pages/settings/settings.js` 的 `onShow`（第 51-63 行）替换为：

```js
  onShow() {
    this.wecomDirty = false;
    this.load();
  },

  onHide() {
    this._stopPolling();
  },

  _stopPolling() {
    if (this._pollTimer) {
      clearInterval(this._pollTimer);
      this._pollTimer = null;
    }
  },

  // 生成绑定码后开启轮询，等待用户在机器人里 /bind 完成，绑定齐或超时后自动停止
  _startPolling() {
    this._stopPolling();
    this._pollCount = 0;
    this._pollTimer = setInterval(() => {
      this._pollCount += 1;
      this.load();
      if (this._pollCount >= 20) {
        this._stopPolling();
      }
    }, 5000);
  },
```

- [ ] **Step 2: `genBindCode` 成功后启动轮询**

`miniprogram/pages/settings/settings.js` 的 `genBindCode`（第 245-252 行）改为：

```js
  async genBindCode() {
    try {
      const data = await request("/api/me/bind-code", { method: "POST" });
      this.setData({ bindCode: data.code, bindMinutes: Math.floor(data.expires_in_seconds / 60) });
      this._startPolling();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },
```

> `load()` 中「全部渠道绑定齐则停表」的逻辑（第 98-107 行）保持不变：仅当 `this._pollTimer` 存在时才触发清理，普通查看不再自动轮询。

- [ ] **Step 3: 手工验证**

用微信开发者工具打开小程序：
1. 进入「我的 → 推送设置」，网络面板应只在首次进入时请求一次 `/api/me`，之后无轮询。
2. 点「生成绑定码」→ 5 秒后开始出现周期性 `/api/me` 请求。
3. 在机器人里 `/bind <码>` → 设置页轮询停止（或 20 次后自动停止，最长 100 秒）。
4. 切走页面（`onHide`）→ 定时器清理，无残留请求。

- [ ] **Step 4: 提交**

```bash
git add miniprogram/pages/settings/settings.js
git commit -m "perf: 小程序推送设置页仅在生成绑定码后轮询"
```

---

## 收尾验证

所有任务完成后，在工作目录 `dav-subscription/` 下执行：

```bash
source .venv/bin/activate
python -m pytest -q
ruff check app tests
```

Expected: `221 + 新增用例` 全部通过；`ruff check` 输出 `All checks passed!`（若新增 noqa 需求，参照 `pyproject.toml` 现有忽略项说明）。

## 自审清单

- **覆盖率**：分析报告中的高优先级（优先大V间隔、限流绕过）、中优先级（时间戳、删用户孤儿数据、busy_timeout）、低优先级（微博并发登录、DND 漏写日志）以及三项低成本优化（COUNT、queryId 锁、小程序轮询）均有对应任务。
- **有意不做**（范围外，需单独评估）：翻译并发度、httpx 连接池重构、token 吊销、头像大小预检、跨实例限流、密码过长返回 400、小程序 401 循环、index 订阅态同步。这些风险低或改动面大，不在本计划内。
- **类型一致**：`trust_proxy` 贯穿 config → api → main；`_scheduler_loop_delay` 在 Task 1 定义并唯一引用；`count_subscriptions` 在 Task 8 定义并唯一引用；`_do_login` 仅 Task 6 使用。
