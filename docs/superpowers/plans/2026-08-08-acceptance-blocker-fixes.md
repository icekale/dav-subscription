# 验收阻断问题修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复验收阶段发现的私有内容越权、账号锁定绕过、SPA 异步竞态、每日精选重复发送和标签/综述边界问题，使版本达到可发布状态。

**Architecture:** 保持现有 FastAPI + SQLite + 原生 JavaScript SPA + pytest 架构，不引入新依赖。后端统一从“用户当前可见的大V集合”推导内容读取和订阅权限；每日精选增加按用户、日期、渠道的持久化成功标记；前端要求所有跨 `await` 的路由渲染和局部刷新携带当前路由令牌。

**Tech Stack:** Python 3.14、FastAPI、SQLite、pytest、Ruff、原生 JavaScript、Node `--check`。

---

## 文件范围

- Modify: `app/db.py`，集中提供可见订阅集合、未打标帖子查询、标签精确匹配和每日精选渠道状态存取。
- Modify: `app/api.py`，修复动态/RSS权限、Telegram 订阅权限复用以及标签回填查询。
- Modify: `app/telegram_bot.py`，拒绝已无权访问的私有大V订阅回调。
- Modify: `app/scheduler.py`，限制每日精选内容范围并按渠道幂等重试。
- Modify: `app/llm.py`，解析层强制每日综述最多三条。
- Modify: `app/static/app.js`，补全路由令牌传递和管理员卡片刷新分发。
- Modify: `docs/管理员手册.md`，同步每日综述实际输出格式。
- Create or modify: `tests/test_api.py`、`tests/test_db.py`、`tests/test_scheduler.py`、`tests/test_llm.py`、`tests/test_telegram_bot.py`、`tests/test_frontend_interactions.py`。

---

## Task 1: 收紧私有大V内容和订阅权限

**Files:**

- Modify: `app/db.py:517-523, 921-923`
- Modify: `app/api.py:571, 790-800, 830-852`
- Modify: `app/scheduler.py:1839`
- Modify: `app/telegram_bot.py:184-196`
- Test: `tests/test_api.py`, `tests/test_db.py`, `tests/test_scheduler.py`, `tests/test_telegram_bot.py`

- [ ] **Step 1: 写权限撤销失败测试**

创建公开大V、用户订阅、插入帖子；随后将大V改为私有并清空 ACL。断言普通用户访问 `/api/my/feed` 不返回该帖子，使用用户 `feed_token` 的 RSS 也不返回该帖子，每日精选不向该用户生成该大V内容。

同时为数据库权限辅助方法增加单元测试，确认普通用户只获得公开大V和 ACL 中私有大V，管理员保留现有管理访问语义。

同时增加 Telegram `sub:<kol_id>` 回调测试：当大V已私有且 Telegram 用户不在 ACL 时，不能创建订阅，并返回明确的不可见提示。

- [ ] **Step 2: 运行失败测试**

```bash
.venv/bin/python -m pytest tests/test_api.py tests/test_scheduler.py tests/test_telegram_bot.py -k "private or acl or feed or daily_report" -q
```

Expected：当前实现仍能从动态或 RSS 读到帖子，或 Telegram 回调直接创建订阅。

- [ ] **Step 3: 增加统一权限边界**

在 `app/db.py` 增加一个只做集合运算的辅助方法，普通用户返回：

```python
readable = db.subscribed_kol_ids(user_id) & db.visible_kol_ids(user_id)
```

管理员继续保留对已订阅私有大V的管理访问能力。将 `/api/my/feed`、RSS 和每日精选都改用该集合。不要只在前端隐藏卡片，权限判断必须在后端完成。

Telegram 回调订阅前复用同一权限判断；私有大V只有管理员或 ACL 用户可以订阅。普通公开大V保持现有行为。

- [ ] **Step 4: 运行权限回归测试**

```bash
.venv/bin/python -m pytest tests/test_api.py tests/test_scheduler.py tests/test_telegram_bot.py -k "private or acl or feed or daily_report" -q
```

Expected：公开转私有并撤销 ACL 后，API、RSS、每日精选和 Telegram 订阅入口都拒绝访问；公开大V和 ACL 用户行为不变。

- [ ] **Step 5: Commit**

```bash
git add app/db.py app/api.py app/scheduler.py app/telegram_bot.py tests/test_api.py tests/test_scheduler.py tests/test_telegram_bot.py
git commit -m "fix(auth): enforce private KOL visibility on all access paths"
```

## Task 2: 统一账号锁定的用户名键

**Files:**

- Modify: `app/api.py:338-358, 511-525`
- Test: `tests/test_api.py`

- [ ] **Step 1: 写大小写绕过测试**

对同一管理员账号使用不同大小写的用户名提交达到锁定阈值的错误密码，然后使用正确密码登录。断言正确密码仍被 `429` 拒绝；等待时间通过 monkeypatch 控制，不使用真实等待。

- [ ] **Step 2: 运行失败测试**

```bash
.venv/bin/python -m pytest tests/test_api.py -k "login and lock" -q
```

Expected：当前实现会因不同大小写使用不同字典键而允许正确密码登录。

- [ ] **Step 3: 规范化所有账号锁定键**

增加单一规范化函数：

```python
def _account_key(username: str) -> str:
    return username.strip().casefold()
```

`_account_lock_seconds_left()`、`_record_account_failure()`、成功登录清理和锁定字典访问全部使用该键。未知用户也必须使用同一规则，避免通过大小写拆分失败计数。

- [ ] **Step 4: 运行认证回归测试**

```bash
.venv/bin/python -m pytest tests/test_api.py -k "login or account_lock" -q
```

Expected：大小写变体共享失败次数和锁定状态；正常大小写不敏感登录仍成功；IP 限流行为不变。

- [ ] **Step 5: Commit**

```bash
git add app/api.py tests/test_api.py
git commit -m "fix(auth): canonicalize account lock keys"
```

## Task 3: 补全 SPA 路由令牌和异步写入保护

**Files:**

- Modify: `app/static/app.js:230-298, 350-500, 518-625, 650-860, 1865-1881, 3240-3298`
- Create or modify: `tests/test_frontend_interactions.py`

- [ ] **Step 1: 写 controlled-Promise 导航测试**

使用最小 DOM 和可控 Promise 覆盖：

1. 首页推荐请求挂起后切换到动态页，释放请求后旧首页不能写入 `#main`。
2. 订阅刷新请求挂起后离开当前页面，释放请求后不能更新新页面 DOM 或旧页面全局状态。
3. `/api/me` 请求挂起后切换路由，旧响应不能覆盖新路由的 `state.user`。
4. 管理后台 loader 请求挂起后切换路由，旧响应不能写入 `#admin-body`。

- [ ] **Step 2: 运行失败测试**

```bash
.venv/bin/python -m pytest tests/test_frontend_interactions.py -k "route or stale or navigation" -q
```

Expected：当前实现至少在局部刷新、`/api/me` 或管理后台场景中出现旧响应写入。

- [ ] **Step 3: 让路由令牌成为必需输入**

路由级渲染函数统一接收 `renderSeq`，所有 `await` 后执行：

```javascript
function routeStillActive(seq) {
  return Number.isInteger(seq) && seq === routeRenderSeq;
}
```

局部事件处理器在发起请求前捕获当前 `routeRenderSeq`，请求完成后使用该值校验。删除“未传 token 视为活跃”的兼容分支。`router()` 在 `/api/me` 返回后和每个 loader 写 DOM 前都检查令牌。

`refreshKolsView()`、平台筛选、收藏、订阅、管理员删除和动态分页不得启动无令牌异步刷新。页面刷新函数应将令牌继续传给对应 renderer，而不是重新调用首页专用函数。

- [ ] **Step 4: 修复通用大V卡片删除刷新**

将 `adminDeleteKolFromHome()` 改为按当前路由调用统一刷新，或将删除处理拆成当前页面无关的 `adminDeleteKol()`。确保首页、组合订阅、我的订阅、搜索和KOL详情页删除成功后都清除已删除卡片，不触发“操作失败”误报。

- [ ] **Step 5: 运行前端验证**

```bash
node --check app/static/app.js
.venv/bin/python -m pytest tests/test_frontend_interactions.py -q
```

Expected：controlled-Promise 测试通过，旧路由不能写新 DOM，旧 `/api/me` 不能覆盖当前用户状态。

- [ ] **Step 6: Commit**

```bash
git add app/static/app.js tests/test_frontend_interactions.py
git commit -m "fix(web): reject stale route render responses"
```

## Task 4: 为每日精选增加按渠道幂等重试

**Files:**

- Modify: `app/db.py:132-160, 300-350`
- Modify: `app/scheduler.py:1825-1975`
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: 写部分渠道失败测试**

构造同一用户同时绑定 Telegram 和企业微信，令 Telegram 第一次成功、企业微信失败。连续调用两次 `_send_daily_report()`，断言第二次只重试企业微信，Telegram 发送次数仍为一次。

增加进程重启语义测试：写入成功状态后重新创建 `Database`/scheduler，成功渠道仍不能重复发送。

- [ ] **Step 2: 运行失败测试**

```bash
.venv/bin/python -m pytest tests/test_scheduler.py -k "daily_report and retry" -q
```

Expected：当前实现第二次会重复发送所有已成功渠道。

- [ ] **Step 3: 增加持久化渠道状态**

在 SQLite 增加每日精选投递状态表，唯一键为 `(user_id, report_date, channel)`，至少保存 `status` 和时间戳：

```sql
CREATE TABLE IF NOT EXISTS daily_report_deliveries (
    user_id INTEGER NOT NULL,
    report_date TEXT NOT NULL,
    channel TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, report_date, channel)
)
```

在 `app/db.py` 提供查询、成功标记和失败标记方法。发送前跳过当天已成功渠道；发送成功后立即标记该渠道，异常只标记该渠道失败。

- [ ] **Step 4: 保持整体完成状态语义**

`_send_daily_report()` 只有在所有应发送渠道都成功或没有待发送内容时返回 `True`。部分失败返回 `False`，让调度器继续重试，但下一轮只处理失败渠道。清理任务同时删除过期投递状态，避免表无限增长。

- [ ] **Step 5: 运行测试**

```bash
.venv/bin/python -m pytest tests/test_scheduler.py -k "daily_report" -q
```

Expected：部分失败可重试，成功渠道不重复；重复调用和进程重启都保持幂等。

- [ ] **Step 6: Commit**

```bash
git add app/db.py app/scheduler.py tests/test_scheduler.py
git commit -m "fix(push): make daily reports channel-idempotent"
```

## Task 5: 修复标签回填和标签精确筛选

**Files:**

- Modify: `app/db.py:1144-1174, 1247-1251`
- Modify: `app/api.py:1405-1442`
- Test: `tests/test_api.py`

- [ ] **Step 1: 写两个失败测试**

测试一：最新两条帖子已有标签，第三条帖子没有标签；调用 `/api/tags/backfill` `limit=1`，断言第三条被处理。

测试二：创建标签 `宏观` 和 `宏观经济`，筛选 `tag=宏观` 时只返回包含完整标签 `宏观` 的帖子。

- [ ] **Step 2: 运行失败测试**

```bash
.venv/bin/python -m pytest tests/test_api.py -k "tag and (backfill or filter)" -q
```

Expected：当前回填返回 `processed=0`，或标签筛选发生前缀误匹配。

- [ ] **Step 3: 让数据库直接查询未打标帖子**

为 `list_posts()` 增加 `untagged_only` 参数，或新增专用 `list_untagged_posts(limit)`，在 SQL 的 `WHERE` 中加入：

```sql
(p.tags IS NULL OR p.tags = '')
```

回填接口直接调用该查询，不再先取已打标帖子再在 Python 中过滤。

- [ ] **Step 4: 使用 JSON 元素边界匹配标签**

标签写入继续使用 `json.dumps()`。查询时对用户输入完成 LIKE 通配符转义，并匹配 JSON 字符串元素边界，例如目标模式为：

```text
%\"宏观\"%
```

确保 `宏观` 不命中 `宏观经济`。若标签允许双引号或反斜杠，使用 JSON 编码后的值生成查询片段，不使用字符拼接绕过编码。

- [ ] **Step 5: 运行标签回归测试**

```bash
.venv/bin/python -m pytest tests/test_api.py -k "tag" -q
```

Expected：回填数量按未打标帖子计算，标签筛选只匹配完整元素，原有词表和回填鉴权测试继续通过。

- [ ] **Step 6: Commit**

```bash
git add app/db.py app/api.py tests/test_api.py
 git commit -m "fix(tags): backfill pending posts and match exact labels"
```

## Task 6: 强制每日综述最多三条并同步文档

**Files:**

- Modify: `app/llm.py:339-390`
- Modify: `docs/管理员手册.md:48`
- Test: `tests/test_llm.py`

- [ ] **Step 1: 写超量输出失败测试**

构造包含五个列表项的模型响应，调用 `_parse_daily_summary()` 或 `summarize_daily()`，断言返回的 `points` 长度最多为 3，且保留前三条顺序和引用序号。

- [ ] **Step 2: 运行失败测试**

```bash
.venv/bin/python -m pytest tests/test_llm.py -k "daily and max" -q
```

Expected：当前实现返回五条。

- [ ] **Step 3: 在解析层强制上限**

解析器完成列表项识别后只保留前三条：

```python
points = points[:3]
```

保留现有无要点降级、帖子序号越界丢弃和原始列表 fallback 行为。限制必须在服务端解析/渲染层执行，不能只依赖 Prompt。

- [ ] **Step 4: 同步管理员手册**

将“每条要点带原文链接”的描述改为当前真实行为：综述要点为纯文本；若产品决定恢复链接，则同时修改 renderer 和测试，不保留文档与实现不一致的状态。本次计划采用纯文本描述，避免扩大功能范围。

- [ ] **Step 5: 运行 LLM 测试**

```bash
.venv/bin/python -m pytest tests/test_llm.py -q
```

Expected：每日综述上限、降级和已有摘要测试全部通过。

- [ ] **Step 6: Commit**

```bash
git add app/llm.py docs/管理员手册.md tests/test_llm.py
git commit -m "fix(daily): enforce summary point limit and align docs"
```

## Task 7: 全量验证和发布前人工验收

**Files:**

- No business-code changes expected.
- Test: all affected test files and full suite.

- [ ] **Step 1: 运行专项测试**

```bash
.venv/bin/python -m pytest tests/test_api.py tests/test_db.py tests/test_scheduler.py tests/test_llm.py tests/test_telegram_bot.py tests/test_frontend_interactions.py -q
```

Expected：专项测试全部通过。

- [ ] **Step 2: 运行全量验证**

```bash
.venv/bin/python -m pytest tests/ -q
ruff check app tests
node --check app/static/app.js
node --check app/static/sw.js
git diff --check
```

Expected：全量 pytest 通过，Ruff 和 Node 语法检查无错误，Git 空白检查通过。

- [ ] **Step 3: 完成浏览器手工验证**

在本地启动现有开发服务，至少验证以下路径：

- 首页、动态、搜索、我的订阅、组合订阅和KOL详情之间快速切换。
- 订阅、退订、收藏和管理员删除操作在请求未完成时切换路由。
- 管理后台各 tab 快速切换，确认旧 loader 不覆盖当前 tab。
- 私有大V公开转私有并移除 ACL 后，动态、RSS、每日精选和 Telegram 订阅均被拒绝。
- 每日精选 Telegram 成功、企业微信失败后再次运行，只重试企业微信。

- [ ] **Step 4: 记录发布门槛结果**

只有 P0/P1/P2 专项测试和全量验证均通过，且人工验收没有旧响应覆盖新页面的问题，才进入提交、推送和 Unraid 部署流程。部署步骤不属于本计划的执行范围，需单独获得发布授权。
