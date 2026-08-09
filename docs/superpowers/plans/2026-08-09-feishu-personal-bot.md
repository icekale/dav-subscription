# 飞书个人机器人扫码绑定——实施计划

**日期：** 2026-08-09
**来源 spec：** docs/superpowers/specs/2026-08-09-feishu-personal-bot-registration-design.md
**协议验证：** ✅ init/begin/poll 已实测通过（accounts.feishu.cn/oauth/v1/app/registration，
begin 返回 device_code/user_code/verification_uri/interval=5；未扫码 poll 返回 400 authorization_pending=20094）

## 设计要点（来自 spec，实施须遵守）

- 个人机器人**纯推送**：不提供 /list /sub /bind 常驻命令、无卡片回调、无常驻 WebSocket。
- **不迁移/清空** users.feishu_open_id / feishu_chat_id；共享绑定全程保留。
- 个人 `active` 才用个人应用推送；degraded/disabled/缺失 → 共享回退。
- app_secret/device_code 认证加密（Fernet）存库；bind_code 服务端哈希；日志脱敏。
- 无 FEISHU_CREDENTIAL_KEY → 个人功能不可用，共享照常。
- 临时监听器只收 p2p `/bind <code>`，3 秒内处理，单次消费。

## 文件改动

| 文件 | 改动 |
|---|---|
| `requirements.txt` | +`cryptography`（Fernet） |
| `app/config.py` | FeishuConfig + `credential_key`（env FEISHU_CREDENTIAL_KEY），不写库 |
| `app/feishu_personal.py`（新） | 注册协议客户端 + 会话管理器 + 绑定码 + 临时监听器 + 推送路由决策 |
| `app/db.py` | 两张新表 + CRUD + 迁移；启动把非终态会话置 expired |
| `app/notifiers/feishu.py` | FeishuNotifier 支持 app_id/app_secret 覆盖（供个人应用复用卡片/图片/发送） |
| `app/channels.py` / `scheduler.py` | feishu 分支优先个人 active；degraded 走共享 |
| `app/api.py` | 5 个新端点 + GET /api/me 脱敏展示字段 |
| `app/main.py` | 启动清理过期会话 |
| `app/static/app.js` | 个人机器人扫码绑定区块 + 轮询 + 60s 倒计时 |
| `tests/test_feishu_personal.py`（新） | 协议/绑定码/监听/路由/安全/API 测试 |

## 实施顺序

1. 依赖 + config（FEISHU_CREDENTIAL_KEY）
2. db 迁移 + 表 + 方法
3. feishu_personal.py：加密助手 → 注册客户端（init/begin/poll + lark 切换）→ 会话管理器 → 绑定码 → 临时监听器 → 推送路由
4. FeishuNotifier 凭据覆盖 + channels/scheduler 路由
5. api.py 端点
6. main.py 启动清理
7. 前端 app.js
8. 测试 + 全量 pytest

## 关键实现决策

- **临时监听器**：lark-oapi `ws.Client` 跑独立 daemon 线程，只注册 `im.message.receive_v1`；
  收到正确 `/bind` 后置 `_done` flag（后续事件直接 return）。SDK 无公开 stop API，
  daemon 线程随进程回收（`ponytail:` 上限 = 同时进行中的注册会话数，天然受限）。
  会话终态（active/expired/cancelled）后监听器不再处理事件。
- **会话唯一**：同用户开始新注册 → 旧会话 cancelled；进程重启 → 非终态会话置 expired。
- **推送路由**：`feishu_personal_bots` 有 `active` 记录且 chat_id 非空 → 个人凭据发；
  明确错误（凭据/权限/停用，如 230101/91002/99991670）→ degraded + 当前消息共享回退；
  网络类模糊错误 → 重试队列，重试失败再 degraded。
- **轮询调度**：每用户注册会话一个后台轮询协程/线程，按 interval（默认 5s，slow_down +5s），
  会话过期自动停；浏览器只轮询 GET 状态接口，不直接打飞书。
