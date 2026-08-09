# 飞书个人机器人扫码绑定设计

**日期：** 2026-08-09<br>
**状态：** 已确认设计，待编写实施计划

## 1. 目标

为来自不同飞书企业/租户的用户提供类似 ZCode 的扫码绑定体验：用户扫码后，飞书在其所属租户中自动创建一个属于用户自己的机器人应用，用户在新机器人私聊窗口发送一次性 `/bind` 绑定码，系统完成绑定并使用该应用发送后续推送。

个人应用只承担推送职责。订阅、退订和其他设置继续在网页端完成；个人机器人不提供 `/list`、`/sub`、卡片回调等常驻命令能力。

已有共享飞书机器人绑定必须保持可用。个人机器人是用户主动选择的新增路由，验证成功前及失效后均可回退到共享机器人。

## 2. 非目标

- 不迁移、覆盖或清空现有 `users.feishu_open_id` 和 `users.feishu_chat_id`。
- 不为每个个人应用建立常驻 WebSocket。
- 不在第一期实现个人机器人上的订阅命令、卡片交互或事件广播。
- 不把 `app_secret` 暴露给浏览器、日志、管理员用户列表或 API 响应。
- 不用一个个人应用跨用户或跨租户复用。

## 3. 现有系统约束

- 当前共享机器人使用全局 `FEISHU_APP_ID/FEISHU_APP_SECRET`，由 `FeishuBot` 通过长连接接收命令。
- 当前用户表中的飞书身份属于共享应用域，不能直接拿给新个人应用使用；个人应用必须保存自己的应用域身份。
- `FeishuNotifier` 已负责卡片构造、图片上传和消息发送，个人路由应复用这些消息格式和推送日志机制。
- 服务以单个 Uvicorn 进程运行，SQLite 是持久化存储；新增迁移必须是加法式且可重复执行。

## 4. 用户体验与状态流

### 4.1 新用户

新注册用户进入推送设置时，首要操作是“扫码创建个人机器人”，同时保留“使用共享机器人”入口。个人机器人不是强制项；如果服务端未配置 `FEISHU_CREDENTIAL_KEY`，个人入口显示为不可用，共享机器人照常可绑定。

### 4.2 已有用户

已有共享机器人绑定的用户继续看到原有绑定状态和操作，系统不自动切换路由。页面可以提供低干扰的“可选升级个人机器人”入口；用户未主动开始注册时，数据库和推送行为不变。

### 4.3 扫码与绑定

1. 用户点击个人机器人绑定，后端创建一个只属于当前登录用户的注册会话。
2. 后端调用飞书官方应用注册协议，浏览器只得到 `session_id`、二维码地址和会话过期时间。
3. 用户扫码，飞书在用户所属租户创建 `PersonalAgent` 应用。
4. 后端轮询注册结果。得到凭据后将候选应用凭据加密暂存到注册会话，生成服务端随机六位十六进制绑定码，例如 `406d93`，并进入 `awaiting_bind`。
5. 网页显示 `/bind 406d93` 和 60 秒倒计时，提示用户打开刚创建的机器人私聊窗口发送该指令。
6. 服务端为该注册会话启动一个临时消息监听，只接收 `im.message.receive_v1` 的私聊事件。监听器校验会话、应用、发送者和绑定码后，原子消费绑定码并保存个人应用域的 `open_id` 与 `chat_id`。
7. 系统向该 `chat_id` 发送测试消息。测试成功后将个人机器人标记为 `active`，关闭临时监听并刷新网页状态。
8. 绑定码过期后立即失效。只要底层扫码注册会话仍未过期，用户可以申请新的 60 秒绑定码；新码会使旧码立即失效。注册会话整体过期后必须重新扫码。

临时监听期间除 `/bind` 外的消息全部忽略，不创建飞书用户，也不执行订阅操作。

### 4.4 状态定义

注册会话状态：

- `pending`：等待扫码，持续轮询注册协议。
- `credentials_created`：已取得个人应用凭据，已生成绑定码。
- `awaiting_bind`：临时监听已启动，等待正确私聊指令。
- `testing`：已收到绑定码，正在发送测试消息。
- `active`：测试成功，个人应用可用于推送。
- `degraded`：凭据存在但绑定或测试/后续发送失败，继续使用共享回退。
- `expired`：二维码或绑定会话过期。
- `cancelled`：用户主动取消或开始了新的替代注册。

个人机器人记录只使用 `active`、`degraded`、`disabled` 三类运行状态；新应用必须先通过 `testing` 才能进入 `active`。

### 4.5 API 契约

所有端点都位于当前认证用户的作用域内：

- `POST /api/me/feishu-personal/register`：取消该用户尚未结束的旧注册会话后，创建新会话，返回 `session_id`、`verification_uri`、`session_expires_at` 和安全状态。
- `GET /api/me/feishu-personal/register/{session_id}`：返回二维码/绑定流程需要的安全字段，包括 `status`、`verification_uri`、`bind_command`、`bind_code_expires_at`、`session_expires_at`、展示用错误和个人机器人运行状态。会话不属于当前用户时返回 404。
- `POST /api/me/feishu-personal/register/{session_id}/refresh-code`：仅在 `awaiting_bind` 且注册会话未过期时可调用，作废旧码并返回新的一分钟 `bind_command`。
- `POST /api/me/feishu-personal/register/{session_id}/cancel`：取消会话并关闭其临时监听器。
- `DELETE /api/me/feishu-personal`：禁用个人路由并擦除个人凭据；共享飞书字段和共享机器人绑定保持不变。
- `GET /api/me`：只增加个人机器人是否可用、运行状态和脱敏应用标识等展示字段，不返回任何密钥、设备码或绑定码。

浏览器仅在注册会话未结束时轮询状态；二维码、绑定码和错误文案都由上述状态接口提供。测试消息由服务端在收到正确绑定码后自动发送，不提供由浏览器传入凭据的测试接口。

## 5. 飞书注册协议

### 5.1 端点与请求

飞书中国租户使用：

```text
POST https://accounts.feishu.cn/oauth/v1/app/registration
Content-Type: application/x-www-form-urlencoded
```

国际 Lark 租户使用同一路径的 `https://accounts.larksuite.com` 域名。默认先使用飞书域名；轮询结果的 `user_info.tenant_brand` 明确为 `lark` 时，后续轮询切换到 Lark 域名。

请求顺序：

```text
action=init
```

确认服务支持 `client_secret` 后：

```text
action=begin
archetype=PersonalAgent
auth_method=client_secret
request_user_info=open_id
```

二维码地址可追加 `createOnly=true`，避免用户误更新已有应用。平台模板默认能力由飞书返回；实现不得假定未验证的权限一定可用，最终以测试发送为准。

### 5.2 轮询处理

```text
action=poll
device_code=<服务端保存的值>
```

所有响应先解析 JSON，再根据业务字段判断状态；HTTP 400 也可能只是正常等待。处理规则：

- `authorization_pending`：保持当前间隔。
- `slow_down`：在当前间隔上增加 5 秒。
- `access_denied`：会话转为 `cancelled`。
- `expired_token`：会话转为 `expired`。
- 返回 `client_id` 与 `client_secret`：保存加密凭据并进入绑定阶段。
- 其他错误：记录脱敏错误，转为 `degraded` 或 `expired`，不影响共享路径。

有效期优先读取 `expires_in`，兼容平台或客户端可能返回的 `expire_in`。`user_info` 或其中的 `open_id` 缺失时不得启用个人路由；网页提示重新扫码或稍后重试。

## 6. 数据模型

新增 `feishu_personal_bots` 表，至少包含：

```text
id                     INTEGER PRIMARY KEY
user_id                INTEGER UNIQUE NOT NULL
app_id                 TEXT UNIQUE NOT NULL
app_secret_ciphertext  TEXT NOT NULL
open_id                TEXT NOT NULL DEFAULT ''
chat_id                TEXT NOT NULL DEFAULT ''
tenant_brand           TEXT NOT NULL DEFAULT 'feishu'
status                 TEXT NOT NULL
last_error             TEXT NOT NULL DEFAULT ''
verified_at            TEXT
last_success_at        TEXT
created_at             TEXT NOT NULL
updated_at             TEXT NOT NULL
```

新增 `feishu_registration_sessions` 表，至少包含：

```text
session_id             TEXT PRIMARY KEY
user_id                INTEGER NOT NULL
device_code_ciphertext TEXT NOT NULL
registration_base_url  TEXT NOT NULL
verification_uri       TEXT NOT NULL
candidate_app_id       TEXT NOT NULL DEFAULT ''
candidate_app_secret_ciphertext TEXT NOT NULL DEFAULT ''
candidate_tenant_brand TEXT NOT NULL DEFAULT 'feishu'
expected_open_id       TEXT NOT NULL DEFAULT ''
bind_code_hash         TEXT NOT NULL DEFAULT ''
bind_code_expires_at   INTEGER
session_expires_at     INTEGER NOT NULL
poll_interval          INTEGER NOT NULL
status                 TEXT NOT NULL
last_error             TEXT NOT NULL DEFAULT ''
created_at             TEXT NOT NULL
updated_at             TEXT NOT NULL
```

约束：

- 同一用户同时只有一个未结束注册会话；开始新会话时旧会话转为 `cancelled`。
- 轮询得到的新凭据只暂存在注册会话中；测试成功后用单个事务更新或创建个人机器人记录，因此旧的 `active` 记录在新应用可用前始终保留。
- `app_id` 在个人机器人表中唯一；`open_id/chat_id` 不做全局唯一约束，因为它们属于不同应用域。
- 现有 `users` 飞书字段不增加个人凭据列，也不执行批量清洗。

## 7. 临时监听器

临时监听器由独立的会话管理器创建，每个注册会话最多一条连接，职责只有：接收事件、快速确认、把最小事件数据交回主服务。事件处理必须在飞书要求的 3 秒内完成。

监听器只接受：

- `chat_type` 为私聊的消息。
- 文本符合 `/bind <code>`（大小写不敏感、允许多余空白）。
- 发送者与注册返回的 `expected_open_id` 一致；平台未返回预期身份时，使用一次性会话码和当前应用绑定双重限制。

监听器在绑定成功、绑定码过期、会话取消或应用凭据失效时立即停止。当前 Python SDK 没有稳定的公开关闭接口，连接生命周期应封装在适配器中，并使用隔离的短生命周期 worker/强制回收兜底，禁止把个人监听器加入常驻共享 `FeishuBot`。

## 8. 推送路由与回退

新增个人路由解析层，但保留现有共享 `FeishuNotifier` 行为：

1. 用户个人记录为 `active` 且存在 `chat_id`：使用个人 `app_id/app_secret` 获取该应用的 `tenant_access_token`，复用现有卡片和图片发送逻辑。
2. 个人记录不存在、处于 `degraded/disabled` 或缺少验证身份：使用全局共享应用，行为与当前版本一致。
3. 个人发送返回明确的凭据、权限、应用停用错误：标记 `degraded`，当前消息在存在旧共享绑定时走共享回退。
4. 网络超时、连接重置等结果不明确的错误：不立即双发，进入现有重试队列；重试仍失败后再标记 `degraded`。
5. 推送日志的渠道名继续使用 `feishu`，并在内部错误/诊断字段记录个人或共享来源。

解绑个人机器人时擦除密文、身份和绑定状态；旧共享字段保持原值。重新绑定个人机器人时，只有新应用测试成功才替换旧个人记录。

## 9. 安全与配置

新增环境变量：

```text
FEISHU_CREDENTIAL_KEY=<Fernet 兼容的 32 字节 Base64 密钥>
```

该密钥只从运行环境读取，不写入 SQLite。`app_secret` 与临时 `device_code` 使用认证加密保存；绑定码使用服务端密钥计算不可逆哈希。所有日志对 `app_secret`、`device_code`、绑定码和完整应用身份做脱敏。

缺少密钥、密钥格式错误或解密失败时：个人功能显示不可用并记录管理员诊断信息，既有共享机器人和已有共享绑定继续工作。第一期不做自动密钥轮换；更换密钥需按运维文档重新绑定个人机器人。

注册、刷新绑定码和解绑接口都要求当前网页登录态；状态查询只能读取当前用户自己的 `session_id`。接口应限制同一用户的并发注册会话和绑定码刷新频率，防止资源滥用。

## 10. 测试与验收

### 自动化测试

- 注册协议：`init/begin/poll` 成功、等待、`slow_down`、HTTP 400 JSON、拒绝、过期、Lark 域切换和缺失 `open_id`。
- 绑定码：随机生成、哈希校验、大小写处理、60 秒过期、单次消费、跨用户/跨会话拒绝、刷新后旧码失效。
- 临时监听：只接受私聊 `/bind`，成功/超时/取消后连接回收，不处理其他命令。
- 数据库：旧数据库迁移不改变原用户行；新表唯一约束和并发状态转换正确。
- 安全：API 和管理员列表不返回密钥，数据库只存密文；无 `FEISHU_CREDENTIAL_KEY` 时共享路径回归通过。
- 推送：个人 `active` 优先、明确错误共享回退、模糊网络错误不双发、重试后降级。
- 前端：新用户引导、旧用户原状态、二维码轮询、60 秒倒计时、重新生成绑定码、成功/失败/回退文案。

### 手工验收

1. 使用两个不同飞书企业的账号分别扫码，确认生成的 `app_id` 不同且消息互不串线。
2. 在新机器人私聊发送正确 `/bind`，确认网页变为已绑定并收到测试消息。
3. 发送错误码、群聊发送、超过 60 秒发送，确认均不能绑定。
4. 已有共享绑定用户升级失败时，确认旧共享推送仍可收到且原绑定字段未变。
5. 个人应用被撤销或测试发送失败时，确认进入共享回退并在日志中可诊断。

## 11. 成功标准

- 新用户无需手动填写 App ID/Secret，能通过扫码和一次 `/bind` 完成个人机器人绑定。
- 个人机器人验证成功后，推送不再依赖共享应用的应用级配额。
- 任何注册、绑定或个人应用故障都不会破坏已有共享绑定和推送。
- 密钥、设备码和绑定码不出后端，且临时监听不会变成常驻连接。
