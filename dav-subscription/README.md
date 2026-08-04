# 大V订阅（自托管版）

聚合订阅雪球 / 微博 / X(Twitter) 大V公开动态，新帖实时推送到**飞书**与**Telegram**，并带一个简单的 Web 管理界面。

> 说明：本项目为自托管替代方案，仅抓取公开可见的动态，不包含任何平台会员/付费内容；无订阅名额与推送次数限制。

## 功能

- 订阅管理：网页增删改大V、启停（雪球 user_id / 微博 uid / X RSS 地址）
- 定时轮询：默认 180s，带随机抖动与失败退避
- 消息推送：新帖去重后推送飞书（卡片）与 Telegram（HTML 消息）
- 帖子历史与推送记录：Web 页面可浏览
- Docker 一键部署，SQLite 持久化

## 快速开始

```bash
cp config.example.yaml config.yaml
# 编辑 config.yaml，填入飞书/Telegram 配置
docker compose up -d --build
```

打开 http://localhost:8000 管理订阅。数据保存在 `./data/dav.db`，重启不丢。

## 飞书机器人（申请 webhook）

1. 打开目标飞书群 → 设置 → 群机器人 → 添加机器人 → 自定义机器人
2. 复制 Webhook 地址，填入 `notifiers.feishu.webhook_url`

## Telegram 机器人（申请 token 与 chat_id）

1. 与 [@BotFather](https://t.me/BotFather) 对话：`/newbot`，按提示创建，拿到 `bot_token`
2. 把 bot 拉进目标会话，发一条消息
3. 访问 `https://api.telegram.org/bot<你的token>/getUpdates`，在返回的 JSON 里找 `chat.id`，填入 `notifiers.telegram.chat_id`

## 配置说明

| 配置项 | 说明 |
| --- | --- |
| `notifiers.feishu.webhook_url` | 飞书群机器人 webhook |
| `notifiers.telegram.bot_token` | Telegram Bot token |
| `notifiers.telegram.chat_id` | 接收消息的会话 ID |
| `sources.xueqiu.cookie` | 可选，雪球 Cookie 初始值；过期后需手动更新（自动续期会尝试，但受 WAF 限制通常需要浏览器） |
| `sources.weibo.cookie` | 可选，微博 Cookie 初始值（未配置账号密码时的兜底） |
| `sources.weibo.token` | 可选，x-xsrf-token |
| `sources.weibo.username` | 可选，微博账号；配置后自动登录并自动续期 cookie |
| `sources.weibo.password` | 可选，微博密码 |
| `polling.interval_seconds` | 轮询间隔（默认 180） |
| `polling.jitter_seconds` | 随机抖动（默认 30） |
| `polling.notify_on_start` | 启动时发上线消息（默认 true） |
| `web.password` | 管理界面访问密码（Basic Auth，留空不启用） |

所有配置项均可通过环境变量覆盖（见 `.env.example`）。注意 `.env` 文件本身不会被程序自动读取，环境变量需由运行环境注入（Docker compose 已处理，直接 `python app/main.py` 本地运行不会读取 `.env`）。

## Cookie 获取与自动续期

- **雪球**：抓取走 `user_timeline.json` JSON 接口，普通 HTTP 请求即可，不受 WAF 挑战影响。Cookie 约 30 天有效；过期后服务会尝试自动续期，但雪球首页受阿里云 WAF 保护（需要浏览器执行 JS 验证），自动续期通常无法成功，此时会清晰报错，请手动更新 `sources.xueqiu.cookie`。
- **微博**：推荐配置 `sources.weibo.username/password`，服务会自动走 weibo.cn 登录流程获取 cookie 并续期（可能偶尔遇到验证码导致登录失败，失败时会推送告警并在次日重试）。不想用账号密码时，也可手动填 cookie：浏览器登录 weibo.cn → 开发者工具 → Network → 复制请求头里的 `Cookie` 整串。

手动 cookie 过期后重新复制即可，无需重启容器（改 `config.yaml` 后 `docker compose restart`）。

## 配置校验

程序启动时会校验配置：数字/布尔字段会自动归一化类型（如引号包裹的 `"60"`），类型错误或取值非法会直接启动报错并指明具体配置项；环境变量解析失败也会提示变量名。

## X (Twitter) 订阅

X 官方 API 需付费，本项目通过 RSS 源订阅。每个 X 大V 在「订阅管理」中添加时，外部 ID 填 RSS 地址，例如：

- RSSHub 公共实例：`https://rsshub.app/twitter/user/elonmusk`
- 自建 RSSHub：`http://<你的地址>/twitter/user/elonmusk`
- 其他兼容 RSS 2.0 的源亦可

RSS 源不稳定时该平台会暂时抓不到，建议自建 RSSHub 保证可用性。

## 安全提示

默认监听所有网卡。建议：

- 仅在内网使用，或置于反向代理后
- 如暴露公网，务必设置 `web.password`

## 开发与测试

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest
```

## 常见问题

**微博抓不到内容？** 检查是否配置了 `sources.weibo.username/password`；如未配置，手动更新 `sources.weibo.cookie`。自动登录失败时飞书/Telegram 会收到告警。

**飞书收不到推送？** 确认 webhook 正确且机器人未被移出群。

**Telegram 收不到推送？** 确认 bot 已拉入会话、`chat_id` 正确。

**推送记录里大量 failed？** 查看该条目的错误信息，通常是渠道配置问题。
