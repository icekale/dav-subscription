# 次要大V（Secondary KOL）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增「次要大V」档位——降低采集频率（15min 基础 + 1h 封顶）+ 进入长周期合并推送（1h 摘要），与「优先大V」互斥。

**Architecture:** `kols` 表新增 `secondary` 布尔列（启动时 ALTER TABLE 迁移）。调度层 `_effective_interval` 增加次要档分支，`poll_once` 新帖分派新增 `_secondary_digest` 缓冲，主循环新增第二个 flush 计时器。API/前端增加 toggle 与互斥逻辑。

**Tech Stack:** Python 3.12 + FastAPI + SQLite + 原生 JS 前端 + pytest

**Spec:** `docs/superpowers/specs/2026-08-10-secondary-kol-design.md`

---

### Task 1: DB 层 secondary 列与迁移

**Files:**

- Modify: `app/db.py`（迁移 330 行附近、`add_kol` 444 行、`update_kol` 528 行）
- Test: `tests/test_db.py`

- [ ] **Step 1: 写失败测试**——迁移补列、add_kol 带 secondary、update_kol 设置 secondary、互斥（设 secondary 清 priority）

```python
# tests/test_db.py 末尾追加
def test_db_migrates_secondary_column(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    cols = {r["name"] for r in db._rows("PRAGMA table_info(kols)")}
    assert "secondary" in cols
    assert db._rows("PRAGMA table_info(kols)")[0]["name"] == "id"  # 原有列不动


def test_add_kol_with_secondary(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    kid = db.add_kol("xueqiu", "测试", "999", priority=False, secondary=True)
    kol = db.get_kol(kid)
    assert kol["secondary"] == 1
    assert kol["priority"] == 0


def test_update_kol_secondary_and_mutex(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    kid = db.add_kol("xueqiu", "测试", "999", priority=True)
    # 设 secondary 必须自动清 priority（互斥在 db 层兜底）
    db.update_kol(kid, secondary=True)
    kol = db.get_kol(kid)
    assert kol["secondary"] == 1 and kol["priority"] == 0
    # 设 priority 必须自动清 secondary
    db.update_kol(kid, priority=True)
    kol = db.get_kol(kid)
    assert kol["priority"] == 1 and kol["secondary"] == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/kale/Documents/微信小程序大 v 订阅/dav-subscription && .venv/bin/python -m pytest tests/test_db.py -q`
Expected: FAIL（`add_kol` 无 `secondary` 参数）

- [ ] **Step 3: 实现 db.py 改动**

```python
# 1) 迁移块（330 行 cols 检查后追加）
if "secondary" not in cols:
    self._conn.execute("ALTER TABLE kols ADD COLUMN secondary INTEGER NOT NULL DEFAULT 0")

# 2) add_kol 签名与 INSERT（444 行）
    def add_kol(
        self,
        platform: str,
        name: str,
        external_id: str,
        category_id: int | None = None,
        priority: bool = False,
        secondary: bool = False,
        original_only: bool = False,
    ) -> int:
        ...
        return self._execute(
            "INSERT INTO kols (platform, name, external_id, category_id, priority, secondary, original_only) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (platform, name, external_id, category_id, 1 if priority else 0, 1 if secondary else 0, 1 if original_only else 0),
        )

# 3) update_kol 签名与互斥逻辑（528 行）
    def update_kol(
        self,
        kol_id: int,
        name=None,
        external_id=None,
        enabled=None,
        original_only=_UNSET,
        category_id=_UNSET,
        priority=_UNSET,
        secondary=_UNSET,
        is_private=_UNSET,
    ):
        sets, params = [], []
        ...
        if priority is not _UNSET:
            sets.append("priority = ?")
            params.append(1 if priority else 0)
            if priority:
                sets.append("secondary = 0")  # 互斥
        if secondary is not _UNSET:
            sets.append("secondary = ?")
            params.append(1 if secondary else 0)
            if secondary:
                sets.append("priority = 0")  # 互斥
        ...
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /Users/kale/Documents/微信小程序大 v 订阅/dav-subscription && .venv/bin/python -m pytest tests/test_db.py -q`
Expected: PASS（含新 3 个测试）

- [ ] **Step 5: 提交**

```bash
cd /Users/kale/Documents/微信小程序大 v 订阅/dav-subscription
git add app/db.py tests/test_db.py
git commit -m "feat(db): add secondary flag to kols with priority mutex"
```

---

### Task 2: 配置层三档参数

**Files:**

- Modify: `app/config.py`（PollingConfig 101 行附近）
- Modify: `app/main.py`（79-89 行附近）
- Modify: `app/scheduler.py`（常量 98-102 行附近）
- Test: `tests/test_api.py`（stats 端点）、`tests/test_scheduler.py`

- [ ] **Step 1: 写失败测试**——配置读取与 stats 端点返回新参数

```python
# tests/test_scheduler.py 追加
def test_secondary_frequency_settings_loaded(monkeypatch):
    from app.scheduler import SECONDARY_BASE_SECONDS, SECONDARY_IDLE_CAP_SECONDS, SECONDARY_DIGEST_INTERVAL_SECONDS
    assert SECONDARY_BASE_SECONDS == 900
    assert SECONDARY_IDLE_CAP_SECONDS == 3600
    assert SECONDARY_DIGEST_INTERVAL_SECONDS == 3600
```

```python
# tests/test_api.py 追加（找现有 stats 测试模式复制）
def test_stats_include_secondary_frequency(monkeypatch, client):
    r = client.get("/api/admin/stats")
    assert r.status_code == 200
    data = r.json()
    freq = data.get("frequency_config") or data.get("polling_config") or {}
    assert "secondary_interval_seconds" in freq
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/kale/Documents/微信小程序大 v 订阅/dav-subscription && .venv/bin/python -m pytest tests/test_scheduler.py::test_secondary_frequency_settings_loaded tests/test_api.py::test_stats_include_secondary_frequency -q`
Expected: FAIL（常量/字段不存在）

- [ ] **Step 3: 实现配置改动**

```python
# app/config.py PollingConfig 追加
    secondary_interval_seconds: int = 900
    secondary_idle_cap_seconds: int = 3600
    secondary_digest_interval_seconds: int = 3600

# app/config.py ENV 映射追加（158 行附近）
    "POLLING_SECONDARY_INTERVAL_SECONDS": ("polling", "secondary_interval_seconds"),
    "POLLING_SECONDARY_IDLE_CAP_SECONDS": ("polling", "secondary_idle_cap_seconds"),
    "POLLING_SECONDARY_DIGEST_INTERVAL_SECONDS": ("polling", "secondary_digest_interval_seconds"),

# app/scheduler.py 常量（98 行附近）
SECONDARY_BASE_SECONDS = 900
SECONDARY_IDLE_CAP_SECONDS = 3600
SECONDARY_DIGEST_INTERVAL_SECONDS = 3600

# app/main.py（79-89 行 pattern 复制）写入 db settings
    db.set_setting("config_secondary_base_seconds", str(config.polling.secondary_interval_seconds))
    db.set_setting("config_secondary_idle_cap_seconds", str(config.polling.secondary_idle_cap_seconds))
    db.set_setting("config_secondary_digest_interval_seconds", str(config.polling.secondary_digest_interval_seconds))
```

同时把 `app/main.py` 的 `config_sync_items` 列表（85-89 行）加上三对：`("config_secondary_base_seconds", SECONDARY_BASE_SECONDS)`、`("config_secondary_idle_cap_seconds", SECONDARY_IDLE_CAP_SECONDS)`、`("config_secondary_digest_interval_seconds", SECONDARY_DIGEST_INTERVAL_SECONDS)`。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /Users/kale/Documents/微信小程序大 v 订阅/dav-subscription && .venv/bin/python -m pytest tests/test_scheduler.py tests/test_api.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd /Users/kale/Documents/微信小程序大 v 订阅/dav-subscription
git add app/config.py app/main.py app/scheduler.py tests/test_scheduler.py tests/test_api.py
git commit -m "feat(config): secondary KOL frequency and digest settings"
```

---

### Task 3: 调度层——间隔计算与新帖分派

**Files:**

- Modify: `app/scheduler.py`（`_effective_interval` 140 行附近、`poll_once` 971 行附近、`__init__` 1535 行附近、主循环 1685 行附近）
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_scheduler.py 追加
def test_effective_interval_secondary_tier(monkeypatch):
    from app.scheduler import _effective_interval, SECONDARY_BASE_SECONDS, SECONDARY_IDLE_CAP_SECONDS
    state = SimpleNamespace(empty_rounds={})
    kol = {"id": 1, "priority": 0, "secondary": 1, "platform": "xueqiu"}
    # 空轮 0 → 基础间隔
    iv = _effective_interval(None, kol, state, 180, 60)
    assert iv == SECONDARY_BASE_SECONDS
    # 空轮 6 → 封顶
    state.empty_rounds[1] = 6
    iv = _effective_interval(None, kol, state, 180, 60)
    assert iv == SECONDARY_IDLE_CAP_SECONDS
    # secondary 与 priority 同时存在时 priority 优先
    kol2 = {"id": 2, "priority": 1, "secondary": 1, "platform": "xueqiu"}
    iv = _effective_interval(None, kol2, state, 180, 60)
    assert iv == 60
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/kale/Documents/微信小程序大 v 订阅/dav-subscription && .venv/bin/python -m pytest tests/test_scheduler.py::test_effective_interval_secondary_tier -q`
Expected: FAIL（secondary 分支未实现，返回 180）

- [ ] **Step 3: 实现 `_effective_interval` 次要分支**

```python
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
```

- [ ] **Step 4: 新帖分派测试**（`poll_once` 用现有 mock 模式）

```python
# tests/test_scheduler.py 追加
def test_secondary_kol_goes_to_secondary_digest(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "S", "1", secondary=True)  # 次要大V
    uid = db.add_user("u", "h", telegram_chat_id="111")
    db.add_subscription(uid, kid)
    digest: dict[int, list] = {}
    secondary_digest: dict[int, list] = {}
    posts = [make_post(kid)]
    sent = []

    class FakeTG:
        def __init__(self, config, chat_id=None, client=None, **kwargs):
            self.client = SimpleNamespace(close=lambda: None)

        def send_digest(self, posts, kol_name, platform):
            sent.append((len(posts), kol_name))

    monkeypatch.setattr("app.notifiers.telegram.TelegramNotifier", FakeTG)
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="t", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
    )
    poll_once(
        db,
        {"xueqiu": FakeFetcher(posts)},
        [],
        interval_seconds=0,
        digest=digest,
        secondary_digest=secondary_digest,
        notifiers_config=ncfg,
    )
    # 次要大V不实时推送、不进普通 digest，进长摘要缓冲
    assert sent == []
    assert digest == {}
    assert len(secondary_digest.get(kid, [])) == 1

    # 长摘要 flush 用现有 flush_digest
    flush_digest(db, secondary_digest, [], ncfg)
    assert sent == [(1, "S")]
    assert secondary_digest == {}
```

- [ ] **Step 5: 实现 `poll_once` 分派 + `__init__` 缓冲 + 主循环双 flush**

```python
# __init__（1535 行附近）
        self._digest: dict[int, list[Post]] = {}
        self._secondary_digest: dict[int, list[Post]] = {}
        self._last_digest_flush = time.monotonic()
        self._last_secondary_digest_flush = time.monotonic()

# poll_once 签名加参数（719 行附近）
    digest: dict[int, list[Post]] | None = None,
    secondary_digest: dict[int, list[Post]] | None = None,

# poll_once 分派（971 行附近）——注意：次要大V在长摘要禁用（secondary_digest=None）时实时推送
        if not kol.get("priority") and kol["platform"] != "combination":
            if kol.get("secondary"):
                if secondary_digest is not None:
                    secondary_digest.setdefault(kol["id"], []).append(post)
                else:
                    notify_subscribers(...)  # 长摘要禁用时实时推送
            elif digest is not None:
                digest.setdefault(kol["id"], []).append(post)
            else:
                notify_subscribers(...)
        else:
            notify_subscribers(...)

# poll_once 调用处传入 secondary_digest（1657 行附近）
                    self._digest if digest_interval > 0 else None,
                    self._secondary_digest if secondary_digest_interval > 0 else None,

# 主循环 digest flush 之后（1689 行附近）
            if (
                secondary_digest_interval > 0
                and self._secondary_digest
                and now_mono - self._last_secondary_digest_flush >= secondary_digest_interval
            ):
                self._last_secondary_digest_flush = now_mono
                try:
                    await asyncio.to_thread(
                        flush_digest,
                        self.db,
                        self._secondary_digest,
                        self.notifiers,
                        self.notifiers_config,
                        self.retry_queue,
                        self._dnd_buffer,
                        self.llm_config,
                    )
                except Exception as exc:  # noqa: BLE001 - 摘要推送失败下轮重试
                    logger.warning("次要大V摘要推送失败 err=%s", exc)

# 读取配置（1644 行附近）
            secondary_digest_interval = _polling_setting(
                self.db, "config_secondary_digest_interval_seconds", self.polling_config.secondary_digest_interval_seconds
            )
```

注意：`poll_once` 的 `digest` 参数签名需加 `secondary_digest` 参数（默认 None），调用处（1550 行附近）同步传入。

- [ ] **Step 6: 运行调度测试确认通过**

Run: `cd /Users/kale/Documents/微信小程序大 v 订阅/dav-subscription && .venv/bin/python -m pytest tests/test_scheduler.py -q`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
cd /Users/kale/Documents/微信小程序大 v 订阅/dav-subscription
git add app/scheduler.py tests/test_scheduler.py
git commit -m "feat(scheduler): secondary KOL slower cadence and long digest"
```

---

### Task 4: API 层 secondary 字段与互斥

**Files:**

- Modify: `app/api.py`（KolIn 135 行、KolBatchIn 143 行、KolUpdate 147 行、add_kol 1322 行、update_kol 1484 行）
- Test: `tests/test_api.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_api.py 追加（参考现有 admin 大V测试的 client fixture）
def test_admin_toggle_secondary(admin_client):
    # 建一个测试大V
    r = admin_client.post("/api/admin/kols", json={"platform": "xueqiu", "name": "次要大V", "external_id": "999999"})
    kid = r.json()["id"]
    # 设 secondary
    r = admin_client.put(f"/api/admin/kols/{kid}", json={"secondary": True})
    assert r.status_code == 200
    kol = r.json()
    assert kol["secondary"] == 1 and kol["priority"] == 0
    # 设 priority 应清 secondary（互斥）
    r = admin_client.put(f"/api/admin/kols/{kid}", json={"priority": True})
    kol = r.json()
    assert kol["priority"] == 1 and kol["secondary"] == 0


def test_add_kol_with_secondary(admin_client):
    r = admin_client.post("/api/admin/kols", json={
        "platform": "xueqiu", "name": "次要", "external_id": "888888", "secondary": True,
    })
    assert r.status_code == 200
    assert r.json()["secondary"] == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/kale/Documents/微信小程序大 v 订阅/dav-subscription && .venv/bin/python -m pytest tests/test_api.py::test_admin_toggle_secondary tests/test_api.py::test_add_kol_with_secondary -q`
Expected: FAIL（`secondary` 不在 schema / 返回 422）

- [ ] **Step 3: 实现 API 改动**

```python
# KolIn / KolBatchIn 加字段
    secondary: bool = False

# KolUpdate 加字段
    secondary: bool | None = None

# add_kol 调用处传 secondary
        kid = db.add_kol(
            body.platform,
            name,
            external_id,
            category_id=body.category_id,
            priority=body.priority,
            secondary=body.secondary,
            original_only=body.original_only,
        )

# update_kol 调用处（1484 行）——互斥在 db.update_kol 内部处理，这里传值
        db.update_kol(
            kol_id,
            name=name,
            external_id=external_id,
            enabled=body.enabled,
            category_id=body.category_id if "category_id" in body.model_fields_set else None,
            priority=body.priority if "priority" in body.model_fields_set else None,
            secondary=body.secondary if "secondary" in body.model_fields_set else None,
        )
        # 更新后返回最新 kol（现有代码可能已 return db.get_kol(kol_id)）
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /Users/kale/Documents/微信小程序大 v 订阅/dav-subscription && .venv/bin/python -m pytest tests/test_api.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd /Users/kale/Documents/微信小程序大 v 订阅/dav-subscription
git add app/api.py tests/test_api.py
git commit -m "feat(api): secondary KOL flag with priority mutex"
```

---

### Task 5: 前端次要开关与参数表单

**Files:**

- Modify: `app/static/app.js`（大V表格 2781 行、toggle 函数 2867 行附近、统计卡片 2398 行、抓取设置表单 2263 行附近、保存逻辑 2493 行附近）
- Modify: `app/static/style.css`（如需）

- [ ] **Step 1: 大V表格加「次要」列与按钮**——复制 priority 列模式

```javascript
// 表头（2781 行附近 thead）
<th scope="col">优先</th><th scope="col">次要</th><th scope="col">原创</th>

// 行渲染
<td>${k.priority ? '<span class="status-ok">是</span>' : "否"}</td>
<td>${k.secondary ? '<span class="status-ok">是</span>' : "否"}</td>

// 操作按钮（priority 按钮后追加）
<button class="btn-sm" onclick="adminToggleSecondary(${k.id}, ${!k.secondary})">${k.secondary ? "取消次要" : "设为次要"}</button>
```

- [ ] **Step 2: toggle 函数**

```javascript
async function adminToggleSecondary(id, secondary) {
  const kol = state.adminKols.find((k) => k.id === id);
  try {
    await api(`/api/kols/${id}`, { method: "PUT", body: JSON.stringify({ secondary: !!secondary }) });
    flash(`已${secondary ? "设为次要" : "取消次要"}「${kol ? kol.name : "该大V"}」`);
    loadAdminKols();
  } catch (err) {
    alert("操作失败: " + err.message);
  }
}
```

- [ ] **Step 3: 统计卡片**（2398 行附近）

```javascript
${statCard("次要大V", s.secondary_kols)}
```

- [ ] **Step 4: 抓取设置表单三项输入**（2263 行附近 pattern 复制）

```html
<input id="pc-secondary-interval" type="number" class="form-control" style="margin:0;width:110px" min="60" max="86400" value="${s.polling_config.secondary_interval_seconds}">
<input id="pc-secondary-cap" type="number" class="form-control" style="margin:0;width:110px" min="60" max="86400" value="${s.polling_config.secondary_idle_cap_seconds}">
<input id="pc-secondary-digest" type="number" class="form-control" style="margin:0;width:110px" min="0" max="86400" value="${s.polling_config.secondary_digest_interval_seconds}">
```

- [ ] **Step 5: 保存逻辑**（2493 行附近）加三个字段

```javascript
    secondary_interval_seconds: Number($("#pc-secondary-interval").value),
    secondary_idle_cap_seconds: Number($("#pc-secondary-cap").value),
    secondary_digest_interval_seconds: Number($("#pc-secondary-digest").value),
```

- [ ] **Step 6: API stats 端点返回新字段**（app/api.py stats 450 行附近）

```python
            "secondary_interval_seconds",
            "config_secondary_base_seconds",
            "config_secondary_idle_cap_seconds",
            "config_secondary_digest_interval_seconds",
```

- [ ] **Step 7: 手工验证**——浏览器打开后台，确认次要开关、统计卡、参数表单渲染正常

- [ ] **Step 8: 提交**

```bash
cd /Users/kale/Documents/微信小程序大 v 订阅/dav-subscription
git add app/static/app.js app/api.py
git commit -m "feat(admin): secondary KOL toggle and frequency settings UI"
```

---

### Task 6: 完整验证

- [ ] **Step 1: 全量测试**

Run: `cd /Users/kale/Documents/微信小程序大 v 订阅/dav-subscription && .venv/bin/python -m pytest -q`
Expected: 全部通过（原 503 + 新增约 10）

- [ ] **Step 2: Ruff + diff 检查**

Run: `cd /Users/kale/Documents/微信小程序大 v 订阅/dav-subscription && .venv/bin/ruff check app/ tests/ && git diff --check`
Expected: 全部通过

- [ ] **Step 3: 运行冒烟**——启动服务，后台设置一个次要大V，确认 stats 计数与配置生效

- [ ] **Step 4: 汇总提交**

```bash
cd /Users/kale/Documents/微信小程序大 v 订阅/dav-subscription
git log --oneline -8
git status --short
```
