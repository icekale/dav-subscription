# 非活跃用户标记与自动清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户页可配置 N/M 天：注册满 N 天且从未登录、未绑渠道、无推送记录则列为非活跃；再满 M 天物理删除。每天扫一次。

**Architecture:** `users.last_login_at` 只在密码登录和微信登录成功时写入。判定用 SQL 现算（复用 `_user_has_channel_sql`），不设粘性标记。调度器距上次成功 ≥24h 调用 `purge_inactive_users`。用户页改 `settings` 里的两个天数并加「非活跃」Tab。

**Tech Stack:** FastAPI、SQLite/`app/db.py`、`app/scheduler.py`、vanilla `app.js`、pytest（`.venv/bin/python -m pytest`）。

---

## 交接

- 规格：`docs/superpowers/specs/2026-08-16-inactive-users-cleanup-design.md`
- 工作目录用 git worktree，不要直接改正在用的 `main` 工作区直到合并
- 不要提交 `DESIGN.md`、`.impeccable/`
- 不要改 `APP_VERSION` / `1.12.9`
- 不要推送部署除非明确要求
- XSS：不要把 username 插进 onclick
- 验证：`.venv/bin/python -m pytest tests/test_api.py tests/test_scheduler.py tests/test_frontend_interactions.py tests/test_frontend_xss.py -q` 中与本功能相关的用例必须过

## 文件地图

| 文件 | 职责 |
|---|---|
| `app/db.py` | `last_login_at` 迁移；policy 读写；inactive 查询；`purge_inactive_users` |
| `app/api.py` | 登录写 last_login；list_users 增加字段；policy GET/PUT |
| `app/scheduler.py` | 24h 调用 purge |
| `app/static/app.js` | 用户页设置行 + 非活跃 Tab + 状态列 |
| `app/static/style.css` | 设置行紧凑布局（可很少） |
| `app/static/index.html` / `sw.js` | 缓存 +1 |
| `tests/test_api.py` | 登录、policy、inactive 字段 |
| `tests/test_scheduler.py` | 24h 删除 |
| `tests/test_frontend_interactions.py` | markup |

复用：`app/db.py` 的 `_user_has_channel_sql`、`delete_user`、`set_setting`/`get_setting`；调度器里现有 6h 帖子清理**旁边另开** 24h 逻辑，不要塞进 `_last_cleanup`。

默认 N=90、M=30。合法 0–3650。N=0 不标记不删。M=0 只标记不删。

---

### Task 1: last_login_at 与登录写入

**Files:**
- Modify: `app/db.py`（users 迁移、`_UPDATE_USER_COLUMNS` 加 `last_login_at`）
- Modify: `app/api.py`（`login` 与 `wechat_login` 成功后 `update_user(..., last_login_at=...)`；`register` 不写）
- Modify: `tests/test_api.py`

- [ ] **Step 1: 写失败测试**

```python
def test_login_sets_last_login_at_register_does_not():
    client = make_client()
    admin_headers = auth_headers(client)
    code = client.post(
        "/api/admin/register-codes", headers=admin_headers, json={"count": 1, "note": "inact"}
    ).json()["codes"][0]
    reg = register(client, "neverlogin", password="pass123456", code=code)
    uid = reg.json()["user"]["id"]
    db = client.app.state.db
    row = db.get_user(uid)
    assert not row.get("last_login_at")
    assert client.post(
        "/api/auth/login", json={"username": "neverlogin", "password": "pass123456"}
    ).status_code == 200
    row = db.get_user(uid)
    assert row["last_login_at"]
```

- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_api.py::test_login_sets_last_login_at_register_does_not -q` → FAIL

- [ ] **Step 3: 实现**

在 `db.py` 的 users 列迁移处（`token_version` 那段后面）增加：

```python
        if "last_login_at" not in user_cols:
            self._conn.execute("ALTER TABLE users ADD COLUMN last_login_at TEXT")
```

`_UPDATE_USER_COLUMNS` 加入 `"last_login_at"`。CREATE TABLE users 也可加上该列（新库），与 ALTER 并存。

`login` 在 `return { token...` 之前：

```python
        db.update_user(user["id"], last_login_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
```

`datetime`/`timezone` 已在 `app/api.py` 顶部导入。

`wechat_login` 在发 token 前同样 `update_user`（含首次自动建号之后）。注册成功路径不要写。

写入值用 UTC、格式与 `created_at` 的 `datetime('now')` 一致（无 tz 后缀）。也可用 SQLite：`db._execute("UPDATE users SET last_login_at = datetime('now') WHERE id = ?", (uid,))` — 更一致，优先这条，不必走 update_user 的 Python 时钟。若用 `_execute`，仍要把列加入白名单以备后用。

推荐登录两处都：

```python
        db.touch_last_login(user["id"])
```

```python
    def touch_last_login(self, user_id: int) -> None:
        self._execute(
            "UPDATE users SET last_login_at = datetime('now') WHERE id = ?",
            (user_id,),
        )
```

- [ ] **Step 4:** 同一条 pytest → PASS

- [ ] **Step 5: Commit** `feat(auth): 登录写入 last_login_at`

---

### Task 2: 判定、policy 接口、用户列表字段

**Files:** `app/db.py`, `app/api.py`, `tests/test_api.py`

- [ ] **Step 1: 测试**

```python
def test_inactive_user_policy_and_list_flags():
    client = make_client()
    admin_headers = auth_headers(client)
    db = client.app.state.db
    assert client.get("/api/admin/inactive-users-policy", headers=admin_headers).json() == {
        "inactive_after_days": 90,
        "inactive_purge_after_days": 30,
    }
    uh = user_headers(client, "inact_norm")
    assert client.put(
        "/api/admin/inactive-users-policy",
        headers=uh,
        json={"inactive_after_days": 10, "inactive_purge_after_days": 5},
    ).status_code == 403
    assert client.put(
        "/api/admin/inactive-users-policy",
        headers=admin_headers,
        json={"inactive_after_days": 10, "inactive_purge_after_days": 5},
    ).status_code == 200

    ghost = db.add_user("ghost90", "h")
    db._execute("UPDATE users SET created_at = datetime('now', '-12 days') WHERE id = ?", (ghost,))
    rows = {u["id"]: u for u in client.get("/api/users", headers=admin_headers).json()}
    assert rows[ghost]["inactive"] is True
    assert rows[ghost]["days_until_purge"] == 3  # 10+5-12

    db.update_user(ghost, telegram_chat_id="1")
    rows = {u["id"]: u for u in client.get("/api/users", headers=admin_headers).json()}
    assert rows[ghost]["inactive"] is False
    assert rows[ghost]["days_until_purge"] is None

    ghost2 = db.add_user("ghost91", "h")
    db._execute("UPDATE users SET created_at = datetime('now', '-12 days') WHERE id = ?", (ghost2,))
    db.add_push_log(0, "telegram", "success", user_id=ghost2)
    assert next(u for u in client.get("/api/users", headers=admin_headers).json() if u["id"] == ghost2)["inactive"] is False

    ghost3 = db.add_user("ghost92", "h")
    db._execute("UPDATE users SET created_at = datetime('now', '-12 days') WHERE id = ?", (ghost3,))
    db.touch_last_login(ghost3)
    assert next(u for u in client.get("/api/users", headers=admin_headers).json() if u["id"] == ghost3)["inactive"] is False

    admin_id = client.get("/api/me", headers=admin_headers).json()["id"]
    db._execute("UPDATE users SET created_at = datetime('now', '-12 days'), last_login_at = NULL WHERE id = ?", (admin_id,))
    assert next(u for u in client.get("/api/users", headers=admin_headers).json() if u["id"] == admin_id)["inactive"] is False

    assert client.put(
        "/api/admin/inactive-users-policy",
        headers=admin_headers,
        json={"inactive_after_days": 0, "inactive_purge_after_days": 5},
    ).json()["inactive_after_days"] == 0
    assert next(u for u in client.get("/api/users", headers=admin_headers).json() if u["id"] == ghost)["inactive"] is False
```

`days_until_purge == 3` 依赖整天计算：若实现用 `CAST(julianday(...) )` 可能是 2 或 3。实现后若差 1 天，把断言改成 `assert rows[ghost]["days_until_purge"] in (2, 3)` 或改用固定公式并在测试里断言同一公式。优先实现：

```python
def days_until_purge(created_at: str, n: int, m: int) -> int | None:
    if n <= 0 or m <= 0 or not created_at:
        return None
    # created_at 为 UTC naive 'YYYY-MM-DD HH:MM:SS'
    from datetime import datetime, timezone, timedelta
    created = datetime.strptime(created_at[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    deadline = created + timedelta(days=n + m)
    now = datetime.now(timezone.utc)
    sec = (deadline - now).total_seconds()
    return max(0, int(-(-sec // 86400)))  # ceil, min 0
```

测试里对 ghost（12 天前、N=10、M=5）deadline=17 天，剩余约 5 天不是 3。**纠正：** days_until_purge 是距离**删除日**（created+N+M），12 天前 + 15 天窗口 → 约 3 天。10+5=15，15-12=3。对。

- [ ] **Step 2:** pytest 该测试 → FAIL

- [ ] **Step 3: db 方法**

```python
INACTIVE_AFTER_KEY = "inactive_after_days"
INACTIVE_PURGE_KEY = "inactive_purge_after_days"

def _clamp_inactive_days(value, default: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(n, 3650))

def get_inactive_policy(self) -> tuple[int, int]:
    n = _clamp_inactive_days(self.get_setting(INACTIVE_AFTER_KEY), 90)
    m = _clamp_inactive_days(self.get_setting(INACTIVE_PURGE_KEY), 30)
    return n, m

def set_inactive_policy(self, after_days: int, purge_after_days: int) -> tuple[int, int]:
    n = _clamp_inactive_days(after_days, 90)
    m = _clamp_inactive_days(purge_after_days, 30)
    # 不要在非法时静默改成 90；API 层先校验再 set
    self.set_setting(INACTIVE_AFTER_KEY, str(after_days))
    self.set_setting(INACTIVE_PURGE_KEY, str(purge_after_days))
    return after_days, purge_after_days
```

API 校验 0–3650，拒绝非整数 → 400。db 的 set 只存已校验的 int。

```python
    def list_inactive_user_rows(self, after_days: int) -> list[dict]:
        if after_days <= 0:
            return []
        return self._rows(
            "SELECT * FROM users WHERE is_admin = 0 AND last_login_at IS NULL "
            f"AND created_at <= datetime('now', ?) AND NOT {_user_has_channel_sql()} "
            "AND NOT EXISTS (SELECT 1 FROM push_logs p WHERE p.user_id = users.id)",
            (f"-{int(after_days)} days",),
        )

    def list_inactive_purge_ids(self, after_days: int, purge_after_days: int) -> list[int]:
        if after_days <= 0 or purge_after_days <= 0:
            return []
        total = int(after_days) + int(purge_after_days)
        return [
            r["id"]
            for r in self._rows(
                "SELECT id FROM users WHERE is_admin = 0 AND last_login_at IS NULL "
                f"AND created_at <= datetime('now', ?) AND NOT {_user_has_channel_sql()} "
                "AND NOT EXISTS (SELECT 1 FROM push_logs p WHERE p.user_id = users.id)",
                (f"-{total} days",),
            )
        ]
```

`admin_user_summary` 增加可选 `inactive=False, days_until_purge=None`。`list_users` 里算 policy、inactive id 集合、再填字段。

Policy 路由放在 `GET /users` 附近。Pydantic：

```python
class InactiveUsersPolicyIn(BaseModel):
    inactive_after_days: int
    inactive_purge_after_days: int
```

- [ ] **Step 4:** 测试 PASS。若 `days_until_purge` 差 1，用 `>= 2 and <= 4` 或对齐公式后改断言。

- [ ] **Step 5: Commit** `feat(admin): 非活跃用户判定与天数设置接口`

---

### Task 3: 每天清理

**Files:** `app/db.py`（`purge_inactive_users`）、`app/scheduler.py`、`tests/test_scheduler.py`

- [ ] **Step 1: 测试**

在 `tests/test_scheduler.py` 追加（沿用该文件已有的 db/scheduler fixture 风格；若没有轻量 fixture，直接 `DB(tmp_path/"t.db")`）：

看文件顶部如何建 Scheduler。若过重，只测 `db.purge_inactive_users`：

```python
def test_purge_inactive_users_deletes_old_ghosts(tmp_path):
    db = DB(tmp_path / "p.db")
    db.set_inactive_policy(10, 5)
    keep = db.add_user("keepg", "h")
    gone = db.add_user("goneg", "h")
    db._execute("UPDATE users SET created_at = datetime('now', '-12 days') WHERE id = ?", (keep,))
    db._execute("UPDATE users SET created_at = datetime('now', '-16 days') WHERE id = ?", (gone,))
    n = db.purge_inactive_users()
    assert n == 1
    assert db.get_user(keep) is not None
    assert db.get_user(gone) is None
```

调度器：用 monkeypatch 把 `inactive_users_last_purge_at` 设为 25 小时前，调用 `_maybe_purge_inactive_users`（新建的方法），断言被调用。也可以只测 db，scheduler 里 10 行调用 + 测「距上次不足 24h 则 skip」：

```python
def test_purge_inactive_skips_within_24h(tmp_path):
    db = DB(tmp_path / "p.db")
    db.set_setting("inactive_users_last_purge_at", str(int(time.time())))
    gone = db.add_user("goneg2", "h")
    db.set_inactive_policy(1, 1)
    db._execute("UPDATE users SET created_at = datetime('now', '-10 days') WHERE id = ?", (gone,))
    assert db.purge_inactive_users_if_due() == 0
    assert db.get_user(gone) is not None
    db.set_setting("inactive_users_last_purge_at", str(int(time.time()) - 25 * 3600))
    assert db.purge_inactive_users_if_due() == 1
    assert db.get_user(gone) is None
```

把 due 判断放进 db 更易测。Scheduler 每圈调用 `purge_inactive_users_if_due()`，包在 try/except 打 log。

```python
    def purge_inactive_users_if_due(self, now_ts: int | None = None) -> int:
        now_ts = int(now_ts or time.time())
        raw = self.get_setting("inactive_users_last_purge_at") or "0"
        try:
            last = int(float(raw))
        except (TypeError, ValueError):
            last = 0
        if last and now_ts - last < 24 * 3600:
            return 0
        n = self.purge_inactive_users()
        self.set_setting("inactive_users_last_purge_at", str(now_ts))
        return n

    def purge_inactive_users(self) -> int:
        n_days, m_days = self.get_inactive_policy()
        ids = self.list_inactive_purge_ids(n_days, m_days)
        for uid in ids:
            self.delete_user(uid)
        return len(ids)
```

注意：due 检查即使 N=0 也应更新 last_purge 以免空转？N=0 时 `list_inactive_purge_ids` 返回 []，仍更新 last 时间即可。

- [ ] **Step 2–4:** TDD 后在 scheduler 主循环（`_last_cleanup` 块**之外**，每轮都调用，内部自己节流）加上：

```python
            try:
                removed_users = self.db.purge_inactive_users_if_due()
                if removed_users:
                    logger.info("清理非活跃用户 %d 人", removed_users)
            except Exception:
                logger.exception("非活跃用户清理失败")
```

- [ ] **Step 5: Commit** `feat(admin): 每天清理到期的非活跃用户`

`purge` 要写 admin_logs。db 层 `log_admin_action(None, "purge_inactive_user", str(uid), username)` 在 delete 前读 username。

---

### Task 4: 用户页 UI

**Files:** `app/static/app.js`, `app/static/style.css`, `tests/test_frontend_interactions.py`

- [ ] **Step 1: 测试**

```python
def test_admin_users_page_has_inactive_policy():
    render = _fn_body("renderAdminUsers")
    assert "非活跃" in render
    assert "inactive_after_days" in render or "au-inactive-n" in render
    assert "au-inactive-n" in render
    assert "au-inactive-m" in render
    assert "adminSaveInactivePolicy" in APP_JS.read_text()
    assert "/api/admin/inactive-users-policy" in _fn_body("adminSaveInactivePolicy")
    filt = _fn_body("adminUsersFiltered")
    assert "inactive" in filt
```

- [ ] **Step 2:** FAIL

- [ ] **Step 3:**

`loadAdminUsers` 同时拉 `/api/users` 与 `/api/admin/inactive-users-policy`，存 `state.inactivePolicy`。

`adminUsersFiltered`：`if (filter === "inactive" && !u.inactive) return false;`

counts 加 `inactive: users.filter((u) => u.inactive).length`

meta 加 `· ${counts.inactive} 非活跃`

Tab：`${tab("inactive", "非活跃")}`

状态列：若 `u.inactive`，显示 `非活跃` 或 `非活跃 · ${u.days_until_purge} 天后删除`（M>0 且 days_until_purge !== null）。否则保持原来的推送开/关。

设置行插在 `settings-tabs` **之前**（规格：搜索与 Tab 之间）：

```javascript
      <div class="au-inactive-policy">
        <label>满 <input id="au-inactive-n" class="form-control" type="number" min="0" max="3650" value="${n}"> 天列为非活跃</label>
        <label>再 <input id="au-inactive-m" class="form-control" type="number" min="0" max="3650" value="${m}"> 天自动删除</label>
        <button type="button" class="btn-sm" onclick="adminSaveInactivePolicy()">保存</button>
        <span class="muted">每天扫一次 · 0 为关闭</span>
      </div>
```

n/m 来自 `state.inactivePolicy`，缺省 90/30。

```javascript
async function adminSaveInactivePolicy() {
  const n = Number($("#au-inactive-n").value);
  const m = Number($("#au-inactive-m").value);
  try {
    state.inactivePolicy = await api("/api/admin/inactive-users-policy", {
      method: "PUT",
      body: JSON.stringify({ inactive_after_days: n, inactive_purge_after_days: m }),
    });
    flash("已保存非活跃规则");
    loadAdminUsers();
  } catch (err) {
    flash(err.message, "error");
  }
}
```

CSS：`.au-inactive-policy { display:flex; flex-wrap:wrap; gap:12px; align-items:center; margin: 0 0 12px; }` 输入宽约 88px。手机 44px min-height。

不要用 prompt。天数是 number，onclick 只有函数名。

- [ ] **Step 4:** 该测试 + `test_admin_users_page_has_batch_bar` + xss PASS

- [ ] **Step 5: Commit** `feat(admin): 用户页非活跃筛选与天数设置`

---

### Task 5: 缓存与回归

读取当前 `index.html` 的 `?v=` 和 `sw.js` 的 `CACHE`，各 +1。不改版本号。

Run:

`.venv/bin/python -m pytest tests/test_api.py::test_login_sets_last_login_at_register_does_not tests/test_api.py::test_inactive_user_policy_and_list_flags tests/test_scheduler.py::test_purge_inactive_users_deletes_old_ghosts tests/test_scheduler.py::test_purge_inactive_skips_within_24h tests/test_frontend_interactions.py tests/test_frontend_xss.py -q`

（测试函数名以实际为准。）

Commit `chore(web): 非活跃用户功能后刷新静态缓存`

---

## 规格对照

| 规格 | 任务 |
|---|---|
| last_login 仅登录/微信，注册不算 | 1 |
| 判定五条件、N=0 | 2 |
| policy GET/PUT、list 字段 | 2 |
| N+M 删除、M=0 不删、24h | 3 |
| 用户页设置+Tab+状态文案 | 4 |
| 缓存 | 5 |
