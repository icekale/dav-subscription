# 普通用户个人次要大V（个人推送降频）设计

2026-08-10

## 背景与目标

现有「次要大V」是**全局属性**（`kols.secondary`，管理员设置）：采集降频 + 1h 长摘要。用户希望**普通用户**也能把自己订阅的大V标为「次要」——**个人维度**：该用户自己的推送降频（新帖合并进摘要、不实时打扰），不影响采集频率（采集是全局的，无法按用户分开），也不影响其他用户。

**入口**：订阅卡片上一个按钮即可（与现有「特别关注 ⭐」并列的「次要」按钮），无任何配置项。

## 设计决策

- 数据模型：`subscriptions` 表新增 `secondary` 列（默认 0），**个人维度**，与 `favorite` 并列。
- 推送行为：`notify_subscribers` 里，对该大V标了「个人次要」的用户，新帖不实时推送，进入**用户级延迟缓冲**，每 `config_digest_interval_seconds`（默认 10 分钟）批量推给该用户。
- **不新增配置项**：延迟周期复用现有 digest 周期，普通用户零配置。
- 全局次要（`kols.secondary`）与个人次要独立：全局次要影响所有人（采集+长摘要），个人次要只影响自己（延迟推送）。
- 优先/特别关注（favorite）穿透优先：用户既标 favorite 又标 secondary 时，favorite 生效（实时推送）——favorite 是用户显式"想要"的信号。

## 组件改动

### 1. DB 层（app/db.py）

- 迁移：`subscriptions` 表缺 `secondary` 列则 `ALTER TABLE ... ADD COLUMN secondary INTEGER NOT NULL DEFAULT 0`（跟随现有 favorite 迁移模式，约 328 行）。
- `subscribers_of_kol` 的 SELECT 加 `s.secondary AS secondary`。
- 新增 `set_subscription_secondary(user_id, kol_id, secondary) -> bool`（复制 `set_subscription_favorite` 模式）。
- 新增 `subscribed_secondary_ids(user_id) -> set[int]`（复制 `subscribed_favorite_ids` 模式，供目录接口返回）。

### 2. API 层（app/api.py）

- `SubscriptionFavoriteIn` 模式复制一个 `SubscriptionSecondaryIn { secondary: bool }`。
- 新增 `PUT /api/subscriptions/{kol_id}/secondary`（复制 favorite 端点模式，约 1030 行）。
- 目录接口（约 980 行，返回 `favorite` 的地方）加 `secondary` 字段：`"secondary": kol["id"] in secondary_ids`。

### 3. 调度层（app/scheduler.py）

- `notify_subscribers` 增加 `secondary_buffer: dict[int, list[Post]] | None = None` 参数。
- 遍历订阅用户时：`secondary = bool(user.get("secondary"))`，若 `secondary and not favorite and secondary_buffer is not None` → `secondary_buffer.setdefault(user["id"], []).append(post)` 并 `continue`（不实时推）；favorite 用户仍实时。
- `__init__` 加 `self._secondary_buffer: dict[int, list[Post]] = {}`。
- `poll_once` 透传 `secondary_buffer`（现有调用链加参数，位置参数注意顺序）。
- 主循环新增 flush：每 `config_digest_interval_seconds` 周期，把 `_secondary_buffer` 里每个用户的帖子**以摘要样式**推给他们（复用 `_send_dnd_summary` 或 `notify_digest_subscribers` 的 per-user 逻辑——先看哪个复用成本最低，`_send_dnd_summary(user, posts)` 是 per-user 的，直接复用）。

### 4. 前端（app/static/app.js）

- 大V目录卡片：`favorite` 按钮旁加一个「次要」按钮（`kol.secondary` 状态，点击 `PUT /api/subscriptions/{kol_id}/secondary`）。仅已订阅显示（与 favorite 一致）。
- 我的订阅页（mysubs）：如列表项有 favorite 切换，同样加 secondary 切换；若无，只加目录卡片入口。
- 样式：复用 fav-btn 风格，图标用简单文本或现有 SVG 变体（如 🔇 或静音图标）。

### 5. 测试

- DB：迁移补列、set_subscription_secondary、subscribers_of_kol 返回 secondary。
- API：PUT secondary 端点、目录接口返回 secondary 字段。
- Scheduler：个人次要用户进 secondary_buffer 不实时推；favorite+secondary 时实时推（favorite 优先）；flush 后推送给该用户。

## 边界与行为

- 个人次要只影响该用户自己，不改变全局采集频率与全局次要行为。
- 用户可同时标 favorite 和 secondary（不互斥），favorite 优先（实时）。
- 延迟周期 = 全局 digest 周期，后台「抓取设置」的合并推送周期可整体调。
- 免打扰（dnd）逻辑优先：dnd 窗口内仍进 dnd_buffer（现有逻辑不变），次要缓冲只在非 dnd 时生效。
- 取消订阅自动失去个人次要（随 subscriptions 行删除）。

## 非目标

- 不做个人次要的独立周期配置（用户要求零配置）。
- 不做个人次要的采集频率调整（全局约束）。
- 不改全局次要（kols.secondary）语义。
