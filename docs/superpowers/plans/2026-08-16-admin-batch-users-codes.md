# 用户与注册码批量管理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 管理后台用户页和注册码页加上与大V列表相同的勾选 + 表上方操作条，并用两个批量接口一次完成开关推送/删用户、复制/作废/清废码。

**Architecture:** 后端仿 `POST /api/admin/kols/batch`，新增 `POST /api/admin/users/batch` 与 `POST /api/admin/register-codes/batch`。前端用 `Set` 保存勾选（`_adminUsersSelected` / `_adminCodesSelected`），筛选后保留，成功后清空。复制只走剪贴板。物理删除注册码是新 DB 方法，禁止复用现有的 `delete_register_code`（它只是作废）。

**Tech Stack:** FastAPI + Pydantic、SQLite/`app/db.py`、vanilla `app/static/app.js` + `style.css`、pytest（`.venv/bin/python -m pytest`）。

---

## 交接须知（给执行 agent）

- **规格（唯一真相）：** `docs/superpowers/specs/2026-08-16-admin-batch-users-codes-design.md`
- **仓库：** `icekale/vpush`，本地路径含 `dav-subscription`。当前实现应做在 `main`。规格提交若还在本地：`e287cd4 docs: 用户与注册码批量管理规格`。
- **不要提交：** `DESIGN.md`、`.impeccable/`、`.env`、`data/`。
- **不要混进无关改动：** 工作区可能已有 iOS 滚动相关的 `style.css` / `index.html?v=140` / `sw.js` v17。若那些 diff 不是本功能，先 `git checkout -- app/static/index.html app/static/style.css app/static/sw.js` 再开始（或 stash）。缓存版本从你开始编辑时文件里的数字 +1。HEAD 上已提交的是 `app.js?v=139`、`style.css?v=102`、`CACHE = "dav-shell-v16"`。
- **XSS 硬约束：** `tests/test_frontend_xss.py` 禁止在 `onclick="...${...}"` 里插 `.code` / `.note` / `.username`。勾选必须用 `onchange="adminXxxToggle(this)"` + `data-id` / `data-code="${escapeHtml(c.code)}"`，与大V的 `.kol-check` 相同。
- **不要改：** 单人 `PUT /api/users/{id}` 的 `UserUpdate`、用户「管理」弹窗、注册码生成栏、按批次「复制未用 / 作废未用」、单行备注。不要改产品版本号 `1.12.9`。
- **不要推送、不要部署**，除非交接人明确要求。
- **验证命令：** `.venv/bin/python -m pytest tests/test_api.py tests/test_frontend_interactions.py tests/test_frontend_xss.py -q`

## 文件地图

| 文件 | 职责 |
|---|---|
| `app/api.py` | `UserBatchAction` / `RegisterCodeBatchAction`；两个 POST 批量路由 |
| `app/db.py` | `set_users_notify`；`purge_register_codes`（真 DELETE） |
| `app/static/app.js` | 用户/注册码勾选、操作条、批量请求 |
| `app/static/style.css` | 操作条、勾选列、手机 44px |
| `app/static/index.html` | `app.js` / `style.css` 的 `?v=` +1 |
| `app/static/sw.js` | `CACHE` 名 +1 |
| `tests/test_api.py` | 批量接口 |
| `tests/test_frontend_interactions.py` | 两页 markup 约定 |

对照实现：`app/static/app.js` 里 `_adminKolsSelected`、`#ak-batch-bar`、`adminKolToggleSelect`（约 3239–3453 行）；`app/api.py` 的 `KolBatchAction` 与 `kol_batch_action`。

---

### Task 1: 用户批量接口

**Files:**
- Modify: `tests/test_api.py`（文件末尾追加）
- Modify: `app/api.py`（`KolBatchAction` 旁加模型；`GET /users` 附近加路由）
- Modify: `app/db.py`（`update_user` 附近加 `set_users_notify`）

- [ ] **Step 1: 写失败测试**

在 `tests/test_api.py` 末尾追加：

```python
def test_admin_users_batch_notify_and_delete():
    client = make_client()
    admin_headers = auth_headers(client)
    admin = client.get("/api/me", headers=admin_headers).json()
    a_headers = user_headers(client, "batchu_a")
    b_headers = user_headers(client, "batchu_b")
    users = client.get("/api/users", headers=admin_headers).json()
    uid_a = next(u["id"] for u in users if u["username"] == "batchu_a")
    uid_b = next(u["id"] for u in users if u["username"] == "batchu_b")

    def batch(ids, action):
        return client.post(
            "/api/admin/users/batch",
            headers=admin_headers,
            json={"ids": ids, "action": action},
        )

    assert batch([], "disable_notify").status_code == 400
    assert batch([uid_a], "nope").status_code == 400
    assert batch([uid_a, uid_b], "disable_notify").status_code == 200
    rows = {u["id"]: u for u in client.get("/api/users", headers=admin_headers).json()}
    assert rows[uid_a]["notify_enabled"] is False
    assert rows[uid_b]["notify_enabled"] is False
    assert batch([uid_a], "enable_notify").json()["count"] == 1
    assert next(u for u in client.get("/api/users", headers=admin_headers).json() if u["id"] == uid_a)["notify_enabled"] is True

    deleted = batch([admin["id"], uid_a, 999999], "delete")
    assert deleted.status_code == 200
    body = deleted.json()
    assert body["count"] == 1 and body["skipped"] == 2
    names = {u["username"] for u in client.get("/api/users", headers=admin_headers).json()}
    assert "batchu_a" not in names
    assert "batchu_b" in names
    assert admin["username"] in names
    assert client.get("/api/me", headers=a_headers).status_code in (401, 403)

    uh = user_headers(client, "batchu_norm")
    assert client.post(
        "/api/admin/users/batch",
        headers=uh,
        json={"ids": [uid_b], "action": "disable_notify"},
    ).status_code == 403
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `.venv/bin/python -m pytest tests/test_api.py::test_admin_users_batch_notify_and_delete -q`

Expected: FAIL（404 或路由不存在）

- [ ] **Step 3: 最小实现**

`app/api.py` 在 `KolBatchAction` 后增加：

```python
class UserBatchAction(BaseModel):
    ids: list[int]
    action: str  # enable_notify|disable_notify|delete
```

`app/db.py` 在 `update_user` 后增加：

```python
    def set_users_notify(self, ids: list[int], enabled: bool) -> int:
        ids = [int(i) for i in ids]
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE users SET notify_enabled = ? WHERE id IN ({placeholders})",
                (1 if enabled else 0, *ids),
            )
            self._conn.commit()
            return cur.rowcount
```

`app/api.py` 在 `list_users`（`@router.get("/users")`）之后增加：

```python
    @router.post("/admin/users/batch", dependencies=[Depends(require_admin)])
    def users_batch_action(body: UserBatchAction, admin: dict = Depends(require_admin)):
        if not body.ids:
            raise HTTPException(status_code=400, detail="请先选择用户")
        action = body.action
        if action in ("enable_notify", "disable_notify"):
            n = db.set_users_notify(body.ids, action == "enable_notify")
            skipped = max(0, len(body.ids) - n)
            _audit(admin, f"batch_{action}", str(n), f"ids={body.ids[:20]}")
            return {"ok": True, "count": n, "skipped": skipped}
        if action == "delete":
            count = 0
            skipped = 0
            for uid in body.ids:
                if uid == admin["id"] or db.get_user(uid) is None:
                    skipped += 1
                    continue
                db.delete_user(uid)
                count += 1
            _audit(admin, "batch_delete_users", str(count), f"ids={body.ids[:20]} skipped={skipped}")
            return {"ok": True, "count": count, "skipped": skipped}
        raise HTTPException(status_code=400, detail=f"不支持的操作: {action}")
```

删除必须调用现有 `db.delete_user`（会清订阅/推送日志/ACL），不要自己写 DELETE FROM users。

- [ ] **Step 4: 跑测试，确认通过**

Run: `.venv/bin/python -m pytest tests/test_api.py::test_admin_users_batch_notify_and_delete -q`

Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add tests/test_api.py app/api.py app/db.py
git commit -m "$(cat <<'EOF'
feat(admin): 用户批量开关推送与删除接口

管理员一次处理多人，删除自动跳过本人和不存在的 id。
EOF
)"
```

---

### Task 2: 注册码批量接口

**Files:**
- Modify: `tests/test_api.py`（再追加）
- Modify: `app/db.py`（`revoke_unused_in_batch` 附近）
- Modify: `app/api.py`（注册码路由附近）

- [ ] **Step 1: 写失败测试**

```python
def test_admin_register_codes_batch_revoke_and_purge():
    client = make_client()
    admin_headers = auth_headers(client)
    db = client.app.state.db
    gen = client.post(
        "/api/admin/register-codes",
        headers=admin_headers,
        json={"count": 4, "note": "batch-rc"},
    ).json()
    available, to_use, to_revoke, to_expire = gen["codes"]
    register(client, "rc_used_user", code=to_use)
    assert client.post(
        f"/api/admin/register-codes/{to_revoke}/revoke", headers=admin_headers
    ).status_code == 200
    db._execute(
        "UPDATE register_codes SET expires_at = datetime('now', '-2 days') WHERE code = ?",
        (to_expire,),
    )

    def batch(codes, action):
        return client.post(
            "/api/admin/register-codes/batch",
            headers=admin_headers,
            json={"codes": codes, "action": action},
        )

    assert batch([], "revoke").status_code == 400
    assert batch([available], "nope").status_code == 400
    # 混选：只作废未用未废的；已用/已作废跳过
    mixed_revoke = batch([available, to_use, to_revoke], "revoke")
    assert mixed_revoke.status_code == 200
    assert mixed_revoke.json()["count"] == 1
    rows = {r["code"]: r for r in client.get("/api/admin/register-codes", headers=admin_headers).json()}
    assert rows[available]["revoked_at"]
    assert rows[to_use]["used_by"]
    # 可用码不能物理删除 → 全部不合法则 400
    fresh = client.post(
        "/api/admin/register-codes",
        headers=admin_headers,
        json={"count": 1, "note": "keep"},
    ).json()["codes"][0]
    assert batch([fresh], "delete").status_code == 400
    # 清废码：已用/已作废/已过期；混进可用则跳过
    purged = batch([to_use, to_revoke, to_expire, fresh], "delete")
    assert purged.status_code == 200
    assert purged.json()["count"] == 3
    left = {r["code"] for r in client.get("/api/admin/register-codes", headers=admin_headers).json()}
    assert to_use not in left and to_revoke not in left and to_expire not in left
    assert fresh in left
    invitee = next(u for u in client.get("/api/users", headers=admin_headers).json() if u["username"] == "rc_used_user")
    assert invitee["register_code"] == ""
    assert invitee["register_note"] == ""

    uh = user_headers(client, "rc_batch_norm")
    assert client.post(
        "/api/admin/register-codes/batch",
        headers=uh,
        json={"codes": [fresh], "action": "revoke"},
    ).status_code == 403
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `.venv/bin/python -m pytest tests/test_api.py::test_admin_register_codes_batch_revoke_and_purge -q`

Expected: FAIL（404）

- [ ] **Step 3: 最小实现**

`app/api.py` 在 `UserBatchAction` 旁增加：

```python
class RegisterCodeBatchAction(BaseModel):
    codes: list[str]
    action: str  # revoke|delete
```

`app/db.py` 在 `revoke_unused_in_batch` 后增加。**不要改** `delete_register_code`（旧名仍是软作废）：

```python
    def purge_register_codes(self, codes: list[str]) -> int:
        codes = [str(c).strip().upper() for c in codes if str(c).strip()]
        if not codes:
            return 0
        placeholders = ",".join("?" * len(codes))
        with self._lock:
            cur = self._conn.execute(
                f"DELETE FROM register_codes WHERE code IN ({placeholders}) AND ("
                "used_by IS NOT NULL OR revoked_at IS NOT NULL OR "
                "(expires_at IS NOT NULL AND expires_at <= datetime('now')))",
                codes,
            )
            self._conn.commit()
            return cur.rowcount
```

`app/api.py` 放在 `revoke_unused_register_codes` 附近：

```python
    @router.post("/admin/register-codes/batch", dependencies=[Depends(require_admin)])
    def register_codes_batch_action(body: RegisterCodeBatchAction, admin: dict = Depends(require_admin)):
        codes = [c.strip().upper() for c in body.codes if c and str(c).strip()]
        if not codes:
            raise HTTPException(status_code=400, detail="请先选择注册码")
        if body.action == "revoke":
            count = sum(1 for c in codes if db.revoke_register_code(c))
            skipped = len(codes) - count
            if count == 0:
                raise HTTPException(status_code=400, detail="没有可作废的注册码")
            _audit(admin, "batch_revoke_register_codes", str(count), f"skipped={skipped}")
            return {"ok": True, "count": count, "skipped": skipped}
        if body.action == "delete":
            count = db.purge_register_codes(codes)
            skipped = len(codes) - count
            if count == 0:
                raise HTTPException(status_code=400, detail="没有可删除的注册码")
            _audit(admin, "batch_delete_register_codes", str(count), f"skipped={skipped}")
            return {"ok": True, "count": count, "skipped": skipped}
        raise HTTPException(status_code=400, detail=f"不支持的操作: {body.action}")
```

过期判定必须用 SQLite `datetime('now')`，与库内 `expires_at` 格式一致。不要在 Python 里自己 parse 再删，以免时区不一致漏删。

- [ ] **Step 4: 跑测试，确认通过**

Run: `.venv/bin/python -m pytest tests/test_api.py::test_admin_users_batch_notify_and_delete tests/test_api.py::test_admin_register_codes_batch_revoke_and_purge -q`

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add tests/test_api.py app/api.py app/db.py
git commit -m "$(cat <<'EOF'
feat(admin): 注册码批量作废与清废码接口

混选只处理合法项；物理删除已用码后用户来源为空。
EOF
)"
```

---

### Task 3: 用户页勾选与操作条

**Files:**
- Modify: `tests/test_frontend_interactions.py`
- Modify: `app/static/app.js`（`loadAdminUsers` / `renderAdminUsers` 一段，约 4760–4873）

- [ ] **Step 1: 写失败测试**

在 `tests/test_frontend_interactions.py` 的 `test_admin_users_page_uses_modal_not_prompt` 后追加：

```python
def test_admin_users_page_has_batch_bar():
    """用户管理：勾选列 + 表上方批量条（开/关推送/删除）。"""
    render = _fn_body("renderAdminUsers")
    assert 'id="au-batch-bar"' in render
    assert 'id="au-checkall"' in render
    assert "au-check" in render
    assert "adminUserToggleSelect" in render
    assert "开启推送" in render
    assert "关闭推送" in render
    assert "adminUsersBatch(" in render
    assert "/api/admin/users/batch" in _fn_body("adminUsersBatch")
    src = APP_JS.read_text()
    assert "let _adminUsersSelected" in src
    delete_fn = _fn_body("adminUsersBatch")
    assert "confirm(" in delete_fn
    assert "enable_notify" in delete_fn
    assert "disable_notify" in delete_fn
    assert "delete" in delete_fn
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `.venv/bin/python -m pytest tests/test_frontend_interactions.py::test_admin_users_page_has_batch_bar -q`

Expected: FAIL（找不到函数或 markup）

- [ ] **Step 3: 实现前端**

在 `app/static/app.js` 里 `async function loadAdminUsers` **之前**加：

```javascript
let _adminUsersSelected = new Set();

function adminUsersSyncBar() {
  const bar = $("#au-batch-bar");
  if (!bar) return;
  bar.style.display = _adminUsersSelected.size ? "flex" : "none";
  const strong = bar.querySelector("strong");
  if (strong) strong.textContent = `已选 ${_adminUsersSelected.size} 人`;
}

function adminUserToggleSelect(el) {
  const id = Number(el.dataset.id);
  if (el.checked) _adminUsersSelected.add(id);
  else _adminUsersSelected.delete(id);
  adminUsersSyncBar();
  const checkall = $("#au-checkall");
  const boxes = [...document.querySelectorAll(".au-check")];
  if (checkall) {
    checkall.checked = boxes.length > 0 && boxes.every((c) => c.checked);
    checkall.indeterminate = boxes.some((c) => c.checked) && !checkall.checked;
  }
}

function adminUserTogglePage(el) {
  document.querySelectorAll(".au-check").forEach((c) => {
    c.checked = el.checked;
    const id = Number(c.dataset.id);
    if (el.checked) _adminUsersSelected.add(id);
    else _adminUsersSelected.delete(id);
  });
  el.indeterminate = false;
  adminUsersSyncBar();
}

function adminUserClearSelect() {
  _adminUsersSelected.clear();
  document.querySelectorAll(".au-check").forEach((c) => { c.checked = false; });
  const checkall = $("#au-checkall");
  if (checkall) {
    checkall.checked = false;
    checkall.indeterminate = false;
  }
  adminUsersSyncBar();
}

async function adminUsersBatch(action) {
  const ids = [..._adminUsersSelected];
  if (!ids.length) return;
  if (action === "delete" && !confirm(`确认删除选中的 ${ids.length} 个用户？其订阅关系将一并删除，不可恢复。`)) return;
  try {
    const data = await api("/api/admin/users/batch", {
      method: "POST",
      body: JSON.stringify({ ids, action }),
    });
    const n = data.count || 0;
    const skipped = data.skipped || 0;
    if (action === "delete") {
      flash(skipped ? `已删除 ${n} 人，跳过本人` : `已删除 ${n} 人`);
    } else if (action === "enable_notify") {
      flash(`已开启 ${n} 人推送`);
    } else {
      flash(`已关闭 ${n} 人推送`);
    }
    _adminUsersSelected.clear();
    loadAdminUsers();
  } catch (err) {
    flash(err.message, "error");
  }
}
```

改 `renderAdminUsers` 的行和表：

1. 每个 `<tr>` 最前加（`u.id` 是数字，可以进 onclick 的 dataset，不要把 `u.username` 插进 handler）：

```javascript
      <td><input type="checkbox" class="au-check" data-id="${u.id}" ${_adminUsersSelected.has(u.id) ? "checked" : ""} onchange="adminUserToggleSelect(this)" aria-label="选择用户"></td>
```

2. `<thead>` 第一列：

```html
<th scope="col" style="width:32px"><input type="checkbox" id="au-checkall" onchange="adminUserTogglePage(this)" aria-label="全选当前筛选"></th>
```

3. 空行 `colspan` 从 7 改为 8。

4. 在 `settings-tabs` **之后**、`table-wrap` **之前**插入（无选中时 `display:none`）：

```javascript
      <div class="toolbar admin-batch-bar" id="au-batch-bar" style="margin-top:10px;display:${_adminUsersSelected.size ? "flex" : "none"};align-items:center;gap:8px;flex-wrap:wrap">
        <strong>已选 ${_adminUsersSelected.size} 人</strong>
        <button type="button" class="btn-sm" onclick="adminUsersBatch('enable_notify')">开启推送</button>
        <button type="button" class="btn-sm" onclick="adminUsersBatch('disable_notify')">关闭推送</button>
        <button type="button" class="btn-sm danger" onclick="adminUsersBatch('delete')">删除</button>
        <button type="button" class="btn-sm" onclick="adminUserClearSelect()">取消选择</button>
      </div>
```

5. `renderAdminUsers` 末尾、回填 `#au-q` 之后：

```javascript
  const checkall = $("#au-checkall");
  const boxes = [...document.querySelectorAll(".au-check")];
  if (checkall) {
    checkall.checked = boxes.length > 0 && boxes.every((c) => _adminUsersSelected.has(Number(c.dataset.id)));
    checkall.indeterminate = boxes.some((c) => c.checked) && !checkall.checked;
  }
```

行上「管理 / 测试推送」和 `adminOpenUser` 不要动。

- [ ] **Step 4: 跑测试，确认通过**

Run: `.venv/bin/python -m pytest tests/test_frontend_interactions.py::test_admin_users_page_has_batch_bar tests/test_frontend_interactions.py::test_admin_users_page_uses_modal_not_prompt tests/test_frontend_xss.py -q`

Expected: 全部 PASS。若 XSS 失败，把 handler 改成只引用 `this` / `u.id`。

- [ ] **Step 5: Commit**

```bash
git add tests/test_frontend_interactions.py app/static/app.js
git commit -m "$(cat <<'EOF'
feat(admin): 用户列表勾选与批量操作条

筛选下表格上出现开/关推送和删除，勾选在筛选切换后保留。
EOF
)"
```

---

### Task 4: 注册码页勾选与操作条

**Files:**
- Modify: `tests/test_frontend_interactions.py`
- Modify: `app/static/app.js`（`loadAdminCodes` / `renderCodeGroups` / `renderCodeRow`）
- Modify: `app/static/style.css`

- [ ] **Step 1: 写失败测试**

```python
def test_admin_codes_page_has_batch_bar():
    """注册码：列表上方批量条 + 行勾选 + 批次标题全选。"""
    load = _fn_body("loadAdminCodes")
    assert 'id="rc-batch-bar"' in load
    assert "复制" in load
    assert "作废未用" in load
    assert "清掉废码" in load
    groups = _fn_body("renderCodeGroups")
    assert "rc-batch-check" in groups
    assert "adminCodesToggleBatch" in groups
    row = _fn_body("renderCodeRow")
    assert "rc-check" in row
    assert "adminCodesToggle(this)" in row
    assert "adminCodesBatch" in APP_JS.read_text()
    batch = _fn_body("adminCodesBatch")
    assert "/api/admin/register-codes/batch" in batch
    assert "confirm(" in batch
    assert "copyText(" in _fn_body("adminCodesCopySelected")
    css = STYLE_CSS.read_text()
    assert ".admin-batch-bar" in css
    assert ".rc-check" in css
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `.venv/bin/python -m pytest tests/test_frontend_interactions.py::test_admin_codes_page_has_batch_bar -q`

Expected: FAIL

- [ ] **Step 3: 实现前端与样式**

在 `saveCodesForm` 附近增加状态与函数。`_adminCodesSelected` 存**码号字符串**：

```javascript
let _adminCodesSelected = new Set();

function codeCanRevoke(c) {
  return c && !c.used_by && !c.revoked_at;
}

function codeCanPurge(c) {
  const st = codeStatus(c);
  return st === "used" || st === "revoked" || st === "expired";
}

function adminCodesSelectedRows() {
  const all = state.adminCodes || [];
  return all.filter((c) => _adminCodesSelected.has(c.code));
}

function adminCodesSyncBar() {
  const bar = $("#rc-batch-bar");
  if (!bar) return;
  const selected = adminCodesSelectedRows();
  bar.style.display = _adminCodesSelected.size ? "flex" : "none";
  const strong = bar.querySelector("strong");
  if (strong) strong.textContent = `已选 ${_adminCodesSelected.size} 个`;
  const revokeBtn = $("#rc-batch-revoke");
  const purgeBtn = $("#rc-batch-purge");
  if (revokeBtn) revokeBtn.disabled = !selected.some(codeCanRevoke);
  if (purgeBtn) purgeBtn.disabled = !selected.some(codeCanPurge);
}

function adminCodesToggle(el) {
  const code = el.dataset.code;
  if (!code) return;
  if (el.checked) _adminCodesSelected.add(code);
  else _adminCodesSelected.delete(code);
  adminCodesSyncBar();
  adminCodesSyncBatchChecks();
}

function adminCodesToggleBatch(el) {
  const batchId = el.dataset.batch;
  document.querySelectorAll(`.rc-check[data-batch="${batchId}"]`).forEach((c) => {
    c.checked = el.checked;
    if (el.checked) _adminCodesSelected.add(c.dataset.code);
    else _adminCodesSelected.delete(c.dataset.code);
  });
  el.indeterminate = false;
  adminCodesSyncBar();
}

function adminCodesSyncBatchChecks() {
  document.querySelectorAll(".rc-batch-check").forEach((el) => {
    const boxes = [...document.querySelectorAll(`.rc-check[data-batch="${el.dataset.batch}"]`)];
    el.checked = boxes.length > 0 && boxes.every((c) => c.checked);
    el.indeterminate = boxes.some((c) => c.checked) && !el.checked;
  });
}

function adminCodesClearSelect() {
  _adminCodesSelected.clear();
  document.querySelectorAll(".rc-check").forEach((c) => { c.checked = false; });
  document.querySelectorAll(".rc-batch-check").forEach((c) => {
    c.checked = false;
    c.indeterminate = false;
  });
  adminCodesSyncBar();
}

function adminCodesCopySelected() {
  const codes = [..._adminCodesSelected];
  if (!codes.length) return;
  copyText(codes.join("\n"), `已复制 ${codes.length} 个邀请码`);
}

async function adminCodesBatch(action) {
  const selected = adminCodesSelectedRows();
  const codes = action === "revoke"
    ? selected.filter(codeCanRevoke).map((c) => c.code)
    : selected.filter(codeCanPurge).map((c) => c.code);
  if (!codes.length) return;
  const ok = action === "revoke"
    ? confirm(`将作废选中的 ${codes.length} 个未使用邀请码，确认？`)
    : confirm(`将从列表删除选中的 ${codes.length} 个已用/已作废/已过期邀请码，不可恢复。确认？`);
  if (!ok) return;
  try {
    const data = await api("/api/admin/register-codes/batch", {
      method: "POST",
      body: JSON.stringify({ codes, action }),
    });
    flash(action === "revoke" ? `已作废 ${data.count} 个邀请码` : `已删除 ${data.count} 个邀请码`);
    _adminCodesSelected.clear();
    loadAdminCodes();
  } catch (err) {
    flash(err.message, "error");
  }
}
```

`loadAdminCodes` 里，在 `settings-tabs` 之后、`<div id="rc-list">` 之前插入：

```javascript
      <div class="toolbar admin-batch-bar" id="rc-batch-bar" style="margin-top:10px;display:${_adminCodesSelected.size ? "flex" : "none"};align-items:center;gap:8px;flex-wrap:wrap">
        <strong>已选 ${_adminCodesSelected.size} 个</strong>
        <button type="button" class="btn-sm" onclick="adminCodesCopySelected()">复制</button>
        <button type="button" class="btn-sm" id="rc-batch-revoke" onclick="adminCodesBatch('revoke')">作废未用</button>
        <button type="button" class="btn-sm danger" id="rc-batch-purge" onclick="adminCodesBatch('delete')">清掉废码</button>
        <button type="button" class="btn-sm" onclick="adminCodesClearSelect()">取消选择</button>
      </div>
```

`loadAdminCodes` 末尾 `renderCodesList()` 之后调用 `adminCodesSyncBar()`。

`renderCodeGroups` 的批次标题里，在 `<strong>` 前加（`g.id` 来自 `batch_id`，用 `escapeHtml` 进 data 属性；onclick 只传 `this`）：

```javascript
            <input type="checkbox" class="rc-batch-check" data-batch="${escapeHtml(g.id)}" onchange="adminCodesToggleBatch(this)" aria-label="全选本批可见">
```

`renderCodeRow` 的邀请码单元格改成（`data-code` / `data-batch` 都经 `escapeHtml`；**禁止** `onclick="...('${c.code}')"`）：

```javascript
    <td data-label="邀请码"><span class="rc-code"><input type="checkbox" class="rc-check" data-code="${escapeHtml(c.code)}" data-batch="${escapeHtml(c.batch_id || c.code)}" ${_adminCodesSelected.has(c.code) ? "checked" : ""} onchange="adminCodesToggle(this)" aria-label="选择邀请码"><code>${escapeHtml(c.code)}</code><button class="btn-sm" data-code="${escapeHtml(c.code)}" onclick="copyText(this.dataset.code, '已复制')">复制</button></span></td>
```

`renderCodesList` 末尾加 `adminCodesSyncBatchChecks(); adminCodesSyncBar();`。

`style.css` 在 `.rc-counts` 规则后增加：

```css
.admin-batch-bar { align-items: center; }
.rc-code .rc-check, .rc-batch-title .rc-batch-check {
  width: 16px;
  height: 16px;
  margin: 0;
  flex-shrink: 0;
}
.rc-batch-title { align-items: center; }
```

在 `@media (max-width: 768px)` 里注册码那段增加：

```css
  .admin-batch-bar .btn-sm { min-height: 44px; }
  .rc-code .rc-check, .rc-batch-title .rc-batch-check { width: 20px; height: 20px; }
```

批次上原有「复制未用 / 作废未用」按钮不要删。生成栏不要动。

- [ ] **Step 4: 跑测试，确认通过**

Run: `.venv/bin/python -m pytest tests/test_frontend_interactions.py::test_admin_codes_page_has_batch_bar tests/test_frontend_interactions.py::test_register_codes_desktop_controls_share_one_grid tests/test_frontend_interactions.py::test_register_codes_mobile_has_field_labels_and_compact_grid tests/test_frontend_xss.py -q`

Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_frontend_interactions.py app/static/app.js app/static/style.css
git commit -m "$(cat <<'EOF'
feat(admin): 注册码列表勾选与批量作废清理

跨批次勾选后可复制、作废未用、清掉已用/已作废/已过期。
EOF
)"
```

---

### Task 5: 缓存版本与全量回归

**Files:**
- Modify: `app/static/index.html`（`style.css?v=` 与 `app.js?v=` 各 +1）
- Modify: `app/static/sw.js`（`CACHE` 字符串 +1，例如 `dav-shell-v16` → `dav-shell-v17`）

- [ ] **Step 1: 读取当前数字再 +1**

打开 `index.html` / `sw.js`，在**你编辑时文件里已有的数字**上加一。不要假设一定是 139/102/v16。不要改 `app/version.py` 或 `APP_VERSION`。

- [ ] **Step 2: 跑本功能相关测试**

Run: `.venv/bin/python -m pytest tests/test_api.py::test_admin_users_batch_notify_and_delete tests/test_api.py::test_admin_register_codes_batch_revoke_and_purge tests/test_frontend_interactions.py tests/test_frontend_xss.py -q`

Expected: 全部 PASS（interactions 文件里原有用例也必须过）

- [ ] **Step 3: Commit**

```bash
git add app/static/index.html app/static/sw.js
git commit -m "$(cat <<'EOF'
chore(web): 用户与注册码批量管理后刷新静态缓存

避免旧 service worker 继续提供没有勾选条的外壳。
EOF
)"
```

若 Step 1 改动已和 Task 4 的 `style.css` 叠在一起且尚未提交，可以把 html/sw 并进 Task 4 的 commit，**不要**再单独空 commit。

---

## 规格对照

| 规格条目 | 任务 |
|---|---|
| 用户批量 enable/disable notify / delete，跳过本人 | Task 1 |
| 不改单人 PUT UserUpdate | Task 1（只加新路由） |
| 注册码 batch revoke/delete，混选部分成功，可用码不能删 | Task 2 |
| 新物理删除，不复用 `delete_register_code` | Task 2 |
| 删已用码后用户来源为空 | Task 2 测试断言 |
| 用户勾选 + 表上方条 + confirm 删除 | Task 3 |
| 注册码勾选 + 批次标题 indeterminate + 复制不打接口 | Task 4 |
| 作废/清废按钮按选中内容禁用 | Task 4 `adminCodesSyncBar` |
| 保留单人管理、生成栏、批次复制/作废未用、单行备注 | Task 3–4 不改那些入口 |
| XSS：不把 code/note 插进 onclick | Task 3–4 + xss 测试 |
| 缓存 +1，不改版本号 | Task 5 |
| 普通用户 403 | Task 1–2 |

## 不做（执行时若想加，停下来问）

批量改备注、批量设管理员、批量测试推送、底部固定条、前端循环打单条 API、把邀请来源写进用户表、推送/部署。
