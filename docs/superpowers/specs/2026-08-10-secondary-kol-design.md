# 次要大V：降频采集 + 长周期合并推送 设计

2026-08-10

## 背景与目标

现有大V采集有三档节奏：

| 档位 | 基础间隔 | 空轮封顶 | 推送方式 |
| --- | --- | --- | --- |
| 优先大V（`priority=1`） | 60s | 180s | 实时推送 |
| 普通大V | 180s | 900s | 合并摘要（10min） |
| 雪球组合 | 30s | 120s | 实时推送 |

用户希望新增「次要大V」档：**降低采集频率 + 适度合并推送**，用于关注度低、不想被频繁打扰的大V。与「优先大V」互斥，不可同时勾选。

## 设计决策

- `kols` 表新增 `secondary` 布尔列（默认 0），与 `priority` 正交但**互斥**（设置一个自动清除另一个）。
- 次要大V独立三档参数（后台可调）：
  - `secondary_interval_seconds` 基础间隔，默认 **900s（15min）**
  - `secondary_idle_cap_seconds` 空轮拉伸封顶，默认 **3600s（1h）**
  - `secondary_digest_interval_seconds` 长摘要周期，默认 **3600s（1h）**
- **双摘要缓冲**：现有 `_digest`（普通/10min）保留，新增 `_secondary_digest`（长周期）。次要大V的新帖进入长摘要，到点统一推送。
- 优先级判定顺序：`combination` > `priority` > `secondary` > 普通。

## 数据模型

```sql
ALTER TABLE kols ADD COLUMN secondary INTEGER NOT NULL DEFAULT 0;
```

互斥约束在应用层实施（API 设置 `secondary=1` 时同写 `priority=0`，反之亦然），不引入 SQL CHECK（SQLite 旧库 ALTER 不便加约束）。

## 组件改动

### 1. DB 层（app/db.py）

- `add_kol` / `update_kol` 接受 `secondary: bool = False`。
- `list_kols` 返回 `secondary` 字段。
- 启动时迁移：`PRAGMA table_info(kols)` 无 `secondary` 列则 `ALTER TABLE` 补列。

### 2. 配置层（app/config.py、app/main.py、app/scheduler.py 常量）

- `PollingConfig` 新增 `secondary_interval_seconds: int = 900`、`secondary_idle_cap_seconds: int = 3600`、`secondary_digest_interval_seconds: int = 3600`。
- 环境变量映射：`POLLING_SECONDARY_INTERVAL_SECONDS`、`POLLING_SECONDARY_IDLE_CAP_SECONDS`、`POLLING_SECONDARY_DIGEST_INTERVAL_SECONDS`。
- scheduler 常量 `SECONDARY_BASE_SECONDS = 900`、`SECONDARY_IDLE_CAP_SECONDS = 3600`、`SECONDARY_DIGEST_INTERVAL_SECONDS = 3600`。
- `main.py` 把三个新配置写入 db settings（`config_secondary_*`），供后台展示与运行时读取。

### 3. 调度层（app/scheduler.py）

**间隔计算** `_effective_interval`：

```python
if kol["platform"] == "combination":
    ...（不变）
elif kol.get("priority"):
    ...（不变）
elif kol.get("secondary"):
    base = _frequency_setting(db, "config_secondary_base_seconds", SECONDARY_BASE_SECONDS)
    cap = _frequency_setting(db, "config_secondary_idle_cap_seconds", SECONDARY_IDLE_CAP_SECONDS)
else:
    ...（不变）
```

**新帖分派**（`poll_once` 内）：

```python
if digest is not None and not kol.get("priority") and kol["platform"] != "combination":
    if kol.get("secondary"):
        secondary_digest.setdefault(kol["id"], []).append(post)
    else:
        digest.setdefault(kol["id"], []).append(post)
else:
    notify_subscribers(...)
```

**双 flush 计时**：`__init__` 增加 `self._secondary_digest: dict = {}`、`self._last_secondary_digest_flush = time.monotonic()`。主循环现有 digest flush 之后追加：

```python
if (
    secondary_digest_interval > 0
    and self._secondary_digest
    and now_mono - self._last_secondary_digest_flush >= secondary_digest_interval
):
    self._last_secondary_digest_flush = now_mono
    await asyncio.to_thread(flush_digest, self.db, self._secondary_digest, ...)
```

`flush_digest` 无需改动（接收 digest 字典即可），通知文案无需区分普通/次要——摘要本身就是"合并推送"。

**主循环节奏** `_scheduler_loop_delay`：不变（取最短间隔，次要间隔更长不影响）。

### 4. API 层（app/api.py）

- `KolIn` / `KolBatchIn` / `KolUpdate` 增加 `secondary: bool = False` / `secondary: bool | None = None`。
- 设置/更新大V时实施互斥：`secondary=True` → `priority=False`；`priority=True` → `secondary=False`。
- 新增 `adminToggleSecondary(id, secondary)` 端点（或复用现有 toggle 模式）。

### 5. 前端（app/static/app.js、style.css）

- 大V表格新增「次要」列（与「优先」列并列）。
- 次要大V行显示"是"（绿色）或"否"，按钮 `设为次要/取消次要`。
- toggle 时若对方已勾选优先，前端提示并自动取消优先。
- 数据源页统计卡片新增「次要大V」计数。
- 抓取设置表单新增三项参数输入（次要间隔/封顶/长摘要周期）。

### 6. 测试

- `test_db.py`：迁移补列、add_kol 带 secondary、互斥（设置 secondary 清 priority）。
- `test_scheduler.py`：
  - `_effective_interval`：secondary 档基础间隔/封顶正确。
  - 新帖分派：secondary 大V进 `_secondary_digest`，priority 实时，普通进 `_digest`。
  - 双 flush：长摘要到点推送、未到点保留、普通 digest 不受影响。
  - 主循环配置读取。
- `test_api.py`：toggle secondary、互斥、统计计数。

## 边界与行为

- 次要大V与优先大V**互斥**，通过 API 强制（前端同步提示）。
- 组合大V**允许设置次要标记但忽略效果**：`combination` 档优先判定，设为次要不改变其 30s 高频 + 实时推送行为（保持语义简单，不引入拒绝分支）。
- `secondary_digest_interval_seconds` 配置为 0 → 次要大V退化为实时推送（与普通 digest 的 0 语义一致）。
- 次要大V的帖子仍入库、去重、可被搜索——只影响抓取频率与推送节奏。
- 空轮拉伸逻辑复用（2 倍步进封顶），次要大V封顶更高（1h）即"不怕错过"。

## 非目标

- 不做按用户维度的次要设置（次要大V是全局属性，所有订阅者一视同仁）。
- 不改变现有 digest 通知文案格式。
- 不做次要大V的失败告警（与「必要大V」概念无关，后续如有需要单独立项）。

## 数据流

1. 管理员在后台把某大V设为「次要」→ API 写 `kols.secondary=1`（并清 `priority`）。
2. scheduler `_effective_interval` 对该大V返回 900s 基础间隔、空轮 2 倍步进、1h 封顶。
3. 新帖入库后按 `secondary` 分派进 `_secondary_digest` 缓冲。
4. 每 3600s（默认）主循环 flush 长摘要，合并推送所有订阅者。
