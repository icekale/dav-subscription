# 项目验收评估报告

> 评估基线：`main` 分支，HEAD `461f94c`。本报告用于向本次开发负责人反馈验收结果，不包含代码修改、提交或部署操作。

## 一、验收结论

**当前版本验收不通过，暂不建议推送生产或重建 Unraid 服务。**

本次改动的基础质量较好：全量测试、Ruff、Node 语法检查和 Git 空白检查均通过；原审计计划中的多项问题也已经修复。但验收仍发现一个权限漏洞、两个高风险一致性问题，以及多个新功能边界问题。其中私有大V权限撤销后仍能读取内容属于发布阻断项，必须优先修复并完成回归验证。

## 二、验证结果

已执行或确认的验证结果：

- `.venv/bin/python -m pytest tests/ -q`：`407 passed`
- `ruff check app tests`：通过
- `node --check app/static/app.js`：通过
- `node --check app/static/sw.js`：通过
- 小程序 JavaScript 语法检查：通过
- `git diff --check`：通过
- 工作区：干净

上述结果说明当前版本没有明显的语法、静态检查或已有测试回归，但不能替代权限撤销、异步竞态和多渠道重试场景的专项验收。

## 三、验收发现

### P0：私有大V权限撤销后仍可读取内容

涉及位置：

- [app/api.py:841](/Users/kale/Documents/微信小程序大%20v%20订阅/dav-subscription/app/api.py:841)
- [app/api.py:571](/Users/kale/Documents/微信小程序大%20v%20订阅/dav-subscription/app/api.py:571)
- [app/scheduler.py:1839](/Users/kale/Documents/微信小程序大%20v%20订阅/dav-subscription/app/scheduler.py:1839)
- [app/telegram_bot.py:184](/Users/kale/Documents/微信小程序大%20v%20订阅/dav-subscription/app/telegram_bot.py:184)

`/api/my/feed`、RSS 和每日精选都根据用户历史订阅直接取得大V ID，没有与当前的 `visible_kol_ids()` 求交集。

复现方式：

1. 大V处于公开状态时，用户完成订阅。
2. 管理员将大V改为私有，并从 ACL 中移除该用户。
3. 用户继续请求动态接口或 RSS，仍能读取该大V的新帖子；每日精选也会继续取数。
4. Telegram 搜索结果的 `sub:` 回调还会直接创建订阅，未重新校验私有大V可见性。

影响：ACL 撤销不能立即撤销内容访问权限，属于权限边界失效。修复前不得部署。

### P1：账号锁定可通过用户名大小写绕过

涉及位置：

- [app/api.py:511](/Users/kale/Documents/微信小程序大%20v%20订阅/dav-subscription/app/api.py:511)
- [app/api.py:512](/Users/kale/Documents/微信小程序大%20v%20订阅/dav-subscription/app/api.py:512)
- [app/api.py:525](/Users/kale/Documents/微信小程序大%20v%20订阅/dav-subscription/app/api.py:525)

登录查询已经大小写不敏感，但 `account_failures` 和 `account_locked_until` 仍使用用户提交的原始用户名作为键。对同一账号使用不同大小写提交失败密码，可以拆散失败计数，绕过账号级锁定阈值。

影响：账号级暴力破解防护不符合设计预期。登录查找、失败记录、锁定检查和清理必须使用同一个规范化用户名。

### P1：SPA 路由令牌保护不完整

涉及位置：

- [app/static/app.js:3240](/Users/kale/Documents/微信小程序大%20v%20订阅/dav-subscription/app/static/app.js:3240)
- [app/static/app.js:488](/Users/kale/Documents/微信小程序大%20v%20订阅/dav-subscription/app/static/app.js:488)
- [app/static/app.js:3266](/Users/kale/Documents/微信小程序大%20v%20订阅/dav-subscription/app/static/app.js:3266)
- [app/static/app.js:1865](/Users/kale/Documents/微信小程序大%20v%20订阅/dav-subscription/app/static/app.js:1865)

`routeStillActive(undefined)` 被视为活跃，因此部分局部刷新仍然绕过路由保护。`refreshKolsView()` 调用异步渲染器时没有传递令牌；`router()` 在等待 `/api/me` 后也没有再次检查当前路由；管理后台 loader 直接写入 `#admin-body`，没有路由失效保护。

复现方式：触发订阅操作后，在刷新请求完成前切换路由，再释放旧请求。旧响应可能修改全局状态或覆盖当前页面 DOM。现有测试主要是静态断言，未覆盖 controlled-Promise 导航场景。

### P2：每日精选部分渠道失败会重复发送成功渠道

涉及位置：[app/scheduler.py:1583](/Users/kale/Documents/微信小程序大%20v%20订阅/dav-subscription/app/scheduler.py:1583) 及每日精选各渠道发送分支。

当前只有全部渠道成功时才写入当天完成标记。如果 Telegram 成功而企业微信失败，下一轮会重新发送 Telegram，造成重复通知。需要按用户和渠道记录每日精选发送成功状态，重试时只发送失败或未完成的渠道。

### P2：标签回填的 `limit` 没有按“未打标帖子”计算

涉及位置：[app/api.py:1415](/Users/kale/Documents/微信小程序大%20v%20订阅/dav-subscription/app/api.py:1415)。

接口先取最新 `limit` 条帖子，再过滤空标签。如果最新帖子已经打过标签，较旧的未打标帖子就不会被处理。复现时存在一条旧的待处理帖子和两条较新的已打标帖子，调用 `limit=2` 返回 `processed=0`，待处理帖子仍然存在。

### P2：每日综述“最多三条”只有 Prompt 约束

涉及位置：[app/llm.py:316](/Users/kale/Documents/微信小程序大%20v%20订阅/dav-subscription/app/llm.py:316)、[_parse_daily_summary()](/Users/kale/Documents/微信小程序大%20v%20订阅/dav-subscription/app/llm.py:339)、[render_daily_summary()](/Users/kale/Documents/微信小程序大%20v%20订阅/dav-subscription/app/llm.py:386)。

模型被要求最多输出三条，但解析器会接受所有列表项，渲染器也会全部发送。模型返回五条时，用户会收到五条，违反当前产品约定。应在解析层强制截断到前三条，并补充测试。

### P2：标签筛选没有实现完整标签匹配

涉及位置：[app/db.py:1248](/Users/kale/Documents/微信小程序大%20v%20订阅/dav-subscription/app/db.py:1248)、[app/db.py:1251](/Users/kale/Documents/微信小程序大%20v%20订阅/dav-subscription/app/db.py:1251)。

代码注释说明要匹配 JSON 数组中的完整元素，但当前 SQL 参数实际生成的是 `%宏观%`，没有包含 JSON 元素边界。筛选 `宏观` 可能误命中 `宏观经济`。现有测试没有覆盖标签前缀冲突。

### P2：管理员删除大V在非首页可能不刷新当前页面

通用 `kolCard()` 在多个页面复用，但删除按钮统一调用首页专用的 `adminDeleteKolFromHome()`。在组合订阅、我的订阅、搜索或KOL详情页删除后，当前页面可能保留已删除的卡片，直到下一次完整路由刷新。

### 文档一致性问题

[docs/管理员手册.md:48](/Users/kale/Documents/微信小程序大%20v%20订阅/dav-subscription/docs/管理员手册.md:48) 仍说明每日综述要点带原文链接，但当前渲染器已经不再输出链接。修复功能后应同步更新手册，避免运维和用户预期不一致。

## 四、已确认通过的项目

以下原审计项目已实现并有测试保护：

- 管理员用户列表不再返回 RSS token、Bark key、企业微信 webhook 和 LLM API key 原文。
- Service Worker 已排除 `/api/` 和 `/feed/` 私有路径。
- 分页参数已限制正数范围，避免 `LIMIT -1` 绕过上限。
- Bark 已纳入每日精选资格和发送流程。
- 免打扰汇总发送失败后会进入现有重试队列。
- 并发数据源事件已在轮询轮次结束后统一归并。
- 用户名登录查询已改为大小写不敏感。
- `source_event_stats()` 当前混合事件统计结果正确，并已有回归测试。
- LLM 标签、Telegram 搜索与订阅类型、每日综述降级、无障碍修复和管理后台骨架屏均已具备基础测试覆盖。

## 五、发布门槛

完成以下事项并重新验证前，不建议推送 `main`、同步 `192.168.5.28` 或重建 Docker Compose 服务：

1. P0 权限问题全部修复，并通过公开转私有、ACL 移除后的 API、RSS、每日精选和 Telegram 回调测试。
2. P1 账号锁定和 SPA 路由竞态修复，并通过运行时异步测试。
3. P2 每日精选幂等、标签回填、标签精确筛选和综述数量上限测试通过。
4. 全量 `pytest`、Ruff、Node 语法检查、`git diff --check` 重新通过。
5. 完成浏览器手工验证：快速切换首页、动态、搜索、我的订阅、组合订阅、KOL详情和管理后台，确认旧响应不覆盖当前页面。
6. 更新管理员手册后，再进行提交、推送和 Unraid 部署验收。
