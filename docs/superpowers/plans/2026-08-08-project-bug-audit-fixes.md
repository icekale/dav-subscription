# 项目 Bug 修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 修复全量审计发现的凭证泄露、PWA 私有内容缓存、SPA 异步竞态、分页边界、推送丢失和认证一致性问题，并用回归测试覆盖每个缺陷。

**Architecture:** 保持现有 FastAPI + SQLite + 单文件 SPA 架构，不引入新依赖。后端通过区分“当前用户完整资料”和“管理员用户摘要”控制敏感字段暴露；前端通过路由渲染 token 和路由感知的刷新函数阻止旧页面更新当前 DOM；推送失败复用现有 `PushRetryQueue`，不重建推送系统。

**Tech Stack:** Python 3.14、FastAPI、SQLite、pytest、原生 JavaScript、Service Worker。

---

## 审计结论与范围

已确认的问题：

- `GET /api/users` 和管理员更新用户响应泄露 `feed_token`、`bark_key`、`wecom_webhook`、`llm_api_key`。
- Service Worker 缓存 `/feed/{token}.xml` 私有 RSS 响应。
- `kolCard` 在搜索页、我的订阅页、组合订阅页、KOL 详情页复用 `toggleSubscribe()`，成功后无条件调用首页专用的 `renderHomeList()`。
- SPA 路由切换后，旧的异步渲染可能覆盖新路由或写入不存在的 DOM。
- 多个分页接口接受负数 `limit`；SQLite 的 `LIMIT -1` 表示不限制。
- 每日精选没有 Bark 查询和发送分支。
- 免打扰汇总发送失败后先删除缓冲，失败内容不会进入重试队列。
- 同平台并发抓取在锁外写入数据源健康状态，结果顺序不确定。
- 注册用户名用 `COLLATE NOCASE` 判重，登录却使用大小写敏感查询。
- 登录限流字典的过期记录清理不完整，存在可持续增长风险。

不纳入错误修复：

- `source_event_stats()` 当前对带 `ok_count/fail_count` 的正常事件实测返回 `ok=5, fail=1` 正确；追加旧版事件和混合事件回归测试即可。
- 当前全量测试最终结果为 `350 passed`；首次运行出现的 3 个雪球测试失败未能复现，需要在验证阶段重复运行并记录结果。

---

### Task 1: 隔离用户敏感字段

**Files:**
- Modify: `app/api.py:200-222, 1332-1334, 1476`
- Test: `tests/test_api.py`

- [x] **Step 1: 写失败测试，验证管理员用户列表不返回凭证原文**

新增 API 测试：创建两个用户，为第二个用户写入 `feed_token`、`bark_key`、`wecom_webhook`、`llm_api_key`，管理员请求 `GET /api/users`，断言每条结果不包含这些字段，或只包含明确的布尔绑定状态字段。

同时断言当前用户的 `GET /api/me` 仍能得到设置页面必需的自身字段，避免误删正常设置功能。

- [x] **Step 2: 运行测试确认当前实现失败**

Run:

```bash
.venv/bin/python -m pytest tests/test_api.py -k "users and secret or public_user" -q
```

Expected: 当前实现会在管理员列表响应中发现 `feed_token`、`bark_key`、`wecom_webhook` 或 `llm_api_key`。

- [x] **Step 3: 增加管理员摘要 DTO**

在 `app/api.py` 增加只返回管理用户列表所需字段的函数，例如：

```python
def admin_user_summary(user: dict) -> dict:
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
```

让 `GET /api/users` 和管理员 `PUT /api/users/{user_id}` 使用摘要函数；登录、注册、微信登录和 `/api/me` 继续使用当前用户自己的完整设置响应。

- [x] **Step 4: 运行 API 回归测试**

```bash
.venv/bin/python -m pytest tests/test_api.py -q
```

Expected: API 测试通过，敏感字段不出现在管理员列表响应中。

- [x] **Step 5: Commit**

```bash
git add app/api.py tests/test_api.py
git commit -m "fix(security): stop exposing user credentials in admin listing"
```

---

### Task 2: 阻止 PWA 缓存私有 RSS

**Files:**
- Create: `tests/test_frontend_pwa.py`
- Modify: `app/static/sw.js:30-39`
- Test: `tests/test_frontend_pwa.py`

- [x] **Step 1: 写静态回归测试**

读取 `app/static/sw.js`，断言 fetch handler 明确排除 `/feed/`，并断言 manifest、图标和 Service Worker 注册仍存在。测试不运行浏览器，只保护安全边界不会被后续改动移除。

- [x] **Step 2: 运行测试确认当前实现缺少排除**

```bash
.venv/bin/python -m pytest tests/test_frontend_pwa.py -q
```

Expected: 当前版本因没有 `/feed/` 排除而失败。

- [x] **Step 3: 修改 Service Worker 路由排除**

将判断改为：

```javascript
if (
  e.request.method !== "GET" ||
  url.origin !== self.location.origin ||
  url.pathname.startsWith("/api/") ||
  url.pathname.startsWith("/feed/")
) return;
```

保留现有静态资源 network-first 和离线 fallback 策略。

- [x] **Step 4: 验证 PWA 静态资源**

```bash
node --check app/static/sw.js
.venv/bin/python -m pytest tests/test_frontend_pwa.py -q
```

Expected: 语法和静态安全测试通过。

- [x] **Step 5: Commit**

```bash
git add app/static/sw.js tests/test_frontend_pwa.py
git commit -m "fix(pwa): never cache private RSS feeds"
```

---

### Task 3: 修复订阅卡片跨页面操作回归

**Files:**
- Modify: `app/static/app.js:408-474, 420-436`
- Create: `tests/test_frontend_interactions.py`
- Test: `tests/test_frontend_interactions.py` 或现有前端静态测试

- [x] **Step 1: 写回归测试/静态断言**

覆盖以下场景的路由分发：

- 首页成功后刷新首页列表
- 我的订阅页成功后刷新我的订阅列表
- 组合订阅页成功后刷新组合列表
- 搜索页成功后重新执行当前搜索
- KOL 详情页成功后刷新详情页

断言 `toggleSubscribe()` 不再无条件调用 `renderHomeList()`。

- [x] **Step 2: 运行测试确认当前实现存在首页 DOM 假设**

```bash
.venv/bin/python -m pytest tests/test_frontend_interactions.py -q
```

Expected: 当前实现能被静态检查发现调用首页专用刷新函数，或浏览器模拟会在非首页找不到 `#kol-list`。

- [x] **Step 3: 恢复路由感知刷新**

保留成功后更新 `state.catalog` 的本地状态，但将刷新分发集中到 `refreshKolsView()`。扩展该函数处理搜索页：

```javascript
function refreshKolsView() {
  const hash = location.hash;
  if (hash.startsWith("#/home")) renderHomeList();
  else if (hash.startsWith("#/combinations")) renderCombinations();
  else if (hash.startsWith("#/mysubs")) renderMySubs();
  else if (hash.startsWith("#/kol/")) renderKolPage(Number(hash.split("/")[2] || 0));
  else if (hash.startsWith("#/search")) doSearch();
}
```

`toggleSubscribe()` 成功后调用 `refreshKolsView()`，并在刷新前确认当前路由仍然有效。若后续发现完整重载过重，再把各页面改为局部更新，但本任务优先修复错误 DOM 写入。

- [x] **Step 4: 运行前端语法和回归测试**

```bash
node --check app/static/app.js
.venv/bin/python -m pytest tests/test_frontend_interactions.py tests/test_frontend_xss.py -q
```

- [x] **Step 5: Commit**

```bash
git add app/static/app.js tests/test_frontend_interactions.py
 git commit -m "fix(web): refresh subscription cards according to current route"
```

---

### Task 4: 给 SPA 异步渲染增加路由令牌

**Files:**
- Modify: `app/static/app.js:230-298, 518-603, 622-760, 979-1005, 3042-3091`
- Test: `tests/test_frontend_interactions.py`

- [x] **Step 1: 写异步导航回归测试**

使用可控 Promise/最小 DOM 模拟以下场景：

1. 启动 `renderHome()` 并暂停 `/api/recommendations`
2. 切换 hash 到 `#/timeline`
3. 释放旧请求
4. 断言旧 home 渲染不会写入当前 `#main`，也不会访问不存在的 `#kol-list`

对 `renderMySubs()`、`renderCombinations()` 和 `renderKolPage()` 至少各覆盖一个旧响应不覆盖新页面的断言。

- [x] **Step 2: 增加 render token**

在 router 入口为每次 hashchange 生成递增 token：

```javascript
let routeRenderSeq = 0;

async function router() {
  const renderSeq = ++routeRenderSeq;
  const route = location.hash;
  // ...
}
```

将 token 传给需要等待接口的 render 函数，所有 `await` 后在写 DOM 前检查：

```javascript
function routeStillActive(seq, hash) {
  return seq === routeRenderSeq && location.hash === hash;
}
```

任何检查失败都直接 return。catch 分支也必须先检查再写错误状态。对不能立即改签名的局部刷新函数，至少增加 `document.querySelector()` 守卫，避免 null 解引用。

- [x] **Step 3: 处理全局状态写入**

旧请求返回时不得覆盖当前页面使用的 `state.catalog`、`state.user` 或当前页面筛选状态；只允许当前 route token 持有者更新这些状态。

- [x] **Step 4: 运行验证**

```bash
node --check app/static/app.js
.venv/bin/python -m pytest tests/test_frontend_interactions.py tests/test_frontend_xss.py -q
```

手工验证：Chrome DevTools Network throttling 下快速切换首页、我的订阅、组合订阅、动态和 KOL 详情页，旧页面不得覆盖新页面。

- [x] **Step 5: Commit**

```bash
git add app/static/app.js tests/test_frontend_interactions.py
 git commit -m "fix(web): ignore stale async route renders"
```

---

### Task 5: 统一限制 API 分页参数

**Files:**
- Modify: `app/api.py:769-813, 1314-1330`
- Test: `tests/test_api.py`

- [x] **Step 1: 写边界测试**

为以下接口分别请求 `limit=-1`、`limit=0` 和 `limit=501`：

- `/api/my/feed`
- `/api/kols/{kol_id}/posts`
- `/api/posts`
- `/api/push-logs`
- `/api/admin/logs`

断言负数和 0 不会变成 SQLite 的无限制查询，正数最大仍为 500。

- [x] **Step 2: 增加统一 helper**

在 `app/api.py` 使用统一函数：

```python
def bounded_limit(value: int, default: int = 100) -> int:
    return max(1, min(value, 500))
```

将所有分页接口的 `min(limit, 500)` 替换为 `bounded_limit(limit)`；offset 继续使用 `max(offset, 0)`。

- [x] **Step 3: 运行 API 测试**

```bash
.venv/bin/python -m pytest tests/test_api.py -q
```

Expected: 所有分页边界通过，返回量不会超过 500。

- [x] **Step 4: Commit**

```bash
git add app/api.py tests/test_api.py
git commit -m "fix(api): reject negative pagination limits"
```

---

### Task 6: 修复 Bark 每日精选

**Files:**
- Modify: `app/db.py:1243-1249`
- Modify: `app/scheduler.py:1769-1872`
- Test: `tests/test_scheduler.py`

- [x] **Step 1: 写失败测试**

创建一个只绑定 Bark、开启 `daily_report=1` 和通知开关的用户，断言 `daily_report_users()` 返回该用户；再用 Fake Bark notifier 验证 `_send_daily_report()` 调用 `send_daily(posts)` 并写入 `push_logs`。

- [x] **Step 2: 增加 Bark 资格条件**

在 SQL 绑定条件中加入：

```sql
OR bark_key != ''
```

- [x] **Step 3: 增加 Bark 每日发送分支**

在每日精选发送流程中复用 `BarkNotifier` 和现有 `_channel_enabled()` 逻辑，检查 `bark_key` 后发送，成功按 `channel='bark'` 写推送日志，异常设置 `failed=True` 并触发已有告警函数。

- [x] **Step 4: 运行测试**

```bash
.venv/bin/python -m pytest tests/test_scheduler.py -q
```

- [x] **Step 5: Commit**

```bash
git add app/db.py app/scheduler.py tests/test_scheduler.py
git commit -m "fix(push): include Bark in daily reports"
```

---

### Task 7: 让免打扰汇总失败可重试

**Files:**
- Modify: `app/scheduler.py:1656-1724`
- Test: `tests/test_scheduler.py`

- [x] **Step 1: 写失败测试**

构造用户免打扰缓冲，令唯一渠道第一次发送抛异常，断言：

- `_dnd_buffer` 不会静默丢失所有帖子，或失败帖子进入 `retry_queue`
- 发送恢复后，下一轮能完成推送
- 已成功的渠道不会重复发送

- [x] **Step 2: 设计最小重试路径**

在 `_send_dnd_summary()` 每个渠道失败时，为该渠道的每条 Post 写失败日志并调用现有 `retry_queue.add(post, channel, user_id)`；在调用前为 Post 保留当前已入库的 external id，确保 `_retry_push()` 可以重新找到 post_id。

`_flush_dnd_buffers()` 只在发送完成或所有失败渠道已经入队后清理内存缓冲；失败渠道的重试不再依赖内存中的摘要文本。重试会按单帖发送，优先保证不丢失；成功渠道继续保持摘要发送，不重复补发。

- [x] **Step 3: 运行测试**

```bash
.venv/bin/python -m pytest tests/test_scheduler.py -q
```

- [x] **Step 4: Commit**

```bash
git add app/scheduler.py tests/test_scheduler.py
git commit -m "fix(push): retry failed do-not-disturb summaries"
```

---

### Task 8: 串行化数据源健康状态更新

**Files:**
- Modify: `app/scheduler.py:631-717`
- Test: `tests/test_scheduler.py`

- [x] **Step 1: 写并发回归测试**

让同一平台的两个 fetcher 并发执行，一个成功、一个失败，断言最终状态同时反映该轮混合结果：

- `source_err_*` 不会被成功 worker 随机清空
- `source_fails_*` 不会因任一成功 worker 随机归零
- 事件计数仍为成功 1、失败 1

- [x] **Step 2: 收集本轮结果后单线程落库**

保留 worker 内的锁保护 `round_stats`，但删除 worker 内对 `SOURCE_OK_KEY`、`SOURCE_ERR_KEY`、`SOURCE_FAILS_KEY` 和 `source_next_retry_at` 的最终状态写入；由 `poll_once()` 在 `ex.map()` 完成后根据 `round_stats` 一次性写入：

```python
for platform, st in round_stats.items():
    if st["fail"]:
        db.set_setting(SOURCE_ERR_KEY.format(platform=platform), st["err"][:300])
        db.set_setting(SOURCE_FAILS_KEY.format(platform=platform), str(st["fail"]))
    elif st["ok"]:
        db.set_setting(SOURCE_OK_KEY.format(platform=platform), str(int(time.time())))
        db.set_setting(SOURCE_ERR_KEY.format(platform=platform), "")
        db.set_setting(SOURCE_FAILS_KEY.format(platform=platform), "0")
```

保留“整轮无失败才清 retry 时间”的策略，并使连续失败计数以平台/轮次聚合，而不是由最后完成的 worker 决定。

- [x] **Step 3: 运行调度器测试**

```bash
.venv/bin/python -m pytest tests/test_scheduler.py -q
```

- [x] **Step 4: Commit**

```bash
git add app/scheduler.py tests/test_scheduler.py
git commit -m "fix(scheduler): make source health updates deterministic"
```

---

### Task 9: 统一用户名大小写规则

**Files:**
- Modify: `app/db.py:570-580` 或 `app/api.py:464`
- Test: `tests/test_api.py`

- [x] **Step 1: 写失败测试**

注册 `Yansy102` 后，使用 `yansy102` 登录，断言登录成功；同时断言现有用户名重复注册仍被拒绝。

- [x] **Step 2: 登录改用大小写不敏感查询**

把登录处：

```python
user = db.get_user_by_username(username)
```

改成：

```python
user = db.get_user_by_username_ci(username)
```

保持 token 中使用数据库中保存的原始用户名。

- [x] **Step 3: 运行认证测试**

```bash
.venv/bin/python -m pytest tests/test_api.py -k "login or register" -q
```

- [x] **Step 4: Commit**

```bash
git add app/api.py tests/test_api.py
 git commit -m "fix(auth): make username lookup case-insensitive"
```

---

### Task 10: 修复登录限流内存清理

**Files:**
- Modify: `app/api.py:265-310`
- Test: `tests/test_api.py`

- [x] **Step 1: 写清理行为测试**

使用可控时间或 monkeypatch `time.time()`，创建大量不同用户名失败记录，推进时间超过窗口，再触发一次清理，断言过期用户名记录从 `account_failures` 删除；对 `login_attempts` 同样断言过期 IP 记录被删除。

- [x] **Step 2: 清理所有过期值而非只清理空列表**

将两个清理逻辑统一为在每次登录尝试时按当前时间过滤所有字典项，并在超出上限时删除最旧或已过期条目。不要仅判断 `if not v`，因为过期时间戳列表本身非空。

- [x] **Step 3: 运行限流测试**

```bash
.venv/bin/python -m pytest tests/test_api.py -k "login_limit or account_lock" -q
```

- [x] **Step 4: Commit**

```bash
git add app/api.py tests/test_api.py
git commit -m "fix(auth): bound login rate-limit memory"
```

---

### Task 11: 保护数据源统计回归并完成验证

**Files:**
- Test: `tests/test_api.py`
- Test: `tests/test_scheduler.py`

- [x] **Step 1: 增加事件统计边界测试**

覆盖以下三类事件：

```python
db.add_source_event("xueqiu", "ok", ok_count=5)
db.add_source_event("xueqiu", "fail", fail_count=1)
assert db.source_event_stats("xueqiu") == {"ok": 5, "fail": 1, "warn": 0}
```

同时保留旧版 `ok_count=0/fail_count=0` 事件，验证升级后的兼容口径。

- [x] **Step 2: 完成静态检查**

```bash
node --check app/static/app.js
node --check app/static/sw.js
.venv/bin/ruff check app tests
.venv/bin/python -m pytest tests/ -q
```

Expected: 全量测试稳定通过，且连续两次运行结果一致；Ruff 不再报告新增改动中的错误。

- [x] **Step 3: 浏览器手工回归**

在 Chrome DevTools Network throttling 下验证：

- 首页、我的订阅、组合订阅、搜索、KOL 详情之间快速切换不被旧响应覆盖
- 非首页卡片订阅/退订后不出现“操作失败”假错误
- PWA Service Worker 不缓存 `/feed/{token}.xml`
- 负数分页请求被拒绝或被安全钳制

- [x] **Step 4: 最终审计与部署前检查**

```bash
git diff --check
git status --short
git log --oneline -5
```

确认没有未审查的工作区改动后，再由用户决定是否提交和部署。
