# 非活跃用户标记与自动清理

日期：2026-08-16  
范围：管理后台 `#/admin/users`；登录接口；调度器

## 目标

把「领了邀请码注册后就消失」的账号自动列为非活跃，并在宽限期后物理删除，避免用户表堆积。天数在用户页上改。

## 不做

- 停用/冻结代替删除
- `inactive_at` 等粘性标记（每次按规则现算）
- 管理员进入此规则
- 把设置放进系统设置页
- 注册发 token 算登录
- 用 RSS/feed 访问当作登录
- 6 小时清理频率

## 判定（同时满足才是非活跃）

1. `is_admin = 0`
2. 设置 N > 0，且 `created_at <= datetime('now', '-' || N || ' days')`
3. `last_login_at` 为空（从未真正登录）
4. 当前未绑定任何推送渠道：无 `telegram_chat_id`、无飞书（`feishu_open_id` / `feishu_chat_id` / 个人飞书机器人 active）、无 `wecom_webhook`、无 `bark_key`。与列表「未绑定」同一套口径
5. `push_logs` 中不存在该 `user_id` 的行

N = 0：不标记任何人，也不删除。

## 删除

仍满足上面全部条件，且设置 M > 0，且 `created_at <= now - (N+M) days`。

- 调用现有 `db.delete_user`（订阅、推送日志、ACL、bind_codes 一并清）
- 写 audit：`purge_inactive_user`，target=user_id，detail=username
- M = 0：只标记，不自动删
- 不能删到自己（调度器无「当前管理员」会话；名单本就不含管理员）

登录后 `last_login_at` 有值，立即不再非活跃，也不会被删。

时间轴（默认 N=90、M=30）：注册第 90 天出现在「非活跃」；第 120 天删除。

## 数据

- `users.last_login_at TEXT NULL`。仅 `POST /api/auth/login` 与微信登录成功时写入 `datetime('now')`。注册、改密、刷新页面不写
- 存量用户：`last_login_at` 保持 NULL。已在用的人只要再登录一次就会被排除；从未回来的邀请号会按 `created_at` 进入规则。这是有意行为，与「注册后没再登录」一致
- 设置键（`settings` 表）：
  - `inactive_after_days` 默认 `"90"`
  - `inactive_purge_after_days` 默认 `"30"`
  - 合法范围 0–3650 的整数；非法值回退默认

## 调度

独立于帖子/推送日志的 6 小时清理。上次成功时间存在 `inactive_users_last_purge_at`（unix 秒或 SQLite datetime）。距上次 ≥ 24 小时才跑一轮：列出应删 id，逐个 `delete_user`，打日志「清理非活跃用户 n 人」。失败不阻断调度主循环。

## 用户页

- 搜索与筛选 Tab 之间：一行「满 N 天列为非活跃」「再 M 天自动删除」「保存」，旁注「每天扫一次 · 0 为关闭」
- Tab 增加「非活跃」，人数现算
- 非活跃行状态列：`非活跃 · x 天后删除`；M=0 时只显示「非活跃」
- 勾选批量删除保留；自动删除不走批量条
- 「管理」弹窗不改

## 接口

`GET /api/users` 每条增加：

- `inactive`: bool
- `days_until_purge`: int | null（非活跃且 M>0 时为剩余整天数，最小 0；否则 null）

`GET /api/admin/inactive-users-policy`（管理员）：`{ inactive_after_days, inactive_purge_after_days }`

`PUT /api/admin/inactive-users-policy`（管理员）：同上字段，校验 0–3650，audit `update_inactive_users_policy`。

不把这两项塞进 `PUT /api/users/{id}`。

## 前端缓存

改 `app.js` / `style.css` 时 `?v=` +1，`sw.js` 的 `CACHE` +1。不改产品版本号。

## 测试

- 登录写入 `last_login_at`；注册不写
- 满 N 天、无登录、无渠道、无推送日志 → `inactive` true；管理员 false；有登录 false；有渠道 false；有推送日志 false
- N=0 时无人 inactive
- 满 N+M 天且仍满足 → 调度删除；M=0 不删
- 登录后不再 inactive、不会被删
- 普通用户不能改 policy（403）
- 前端：用户页有非活跃 Tab、两天数字段和保存

XSS：天数是数字，不要把用户名插进 `onclick`。
