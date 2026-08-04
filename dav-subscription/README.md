# 大V订阅（自托管版）

聚合订阅雪球 / 微博 / X(Twitter) 大V公开动态，新帖实时推送到**飞书**与**Telegram**。

架构：

- **微信小程序**（`miniprogram/`）：客户前端——微信登录，首页广场发现大V并自助订阅、动态时间线、我的订阅、推送绑定
- **Docker 服务**：后端 API + 网页后台管理（大V目录、分类、推送记录、用户与管理员指定）
- **推送**：飞书（群 webhook + 自建应用直聊）与 Telegram bot 双通道，按订阅关系逐人推送

## 文档

- [用户指南](docs/用户指南.md)：在 Telegram / 飞书里怎么订阅大V、怎么绑定账号
- [管理员手册](docs/管理员手册.md)：部署、大V/用户管理、配置项、常见问题

## Telegram bot 订阅命令

配置 `notifiers.telegram.bot_token` 后，用户可直接在 Telegram 里给机器人发命令订阅大V（首次使用自动创建账号并绑定 chat_id）：

- `/list` — 查看可订阅的大V（含 ID 与订阅状态，`/list 2` 翻页）
- `/sub 1` / `/sub https://xueqiu.com/8790885129` / `/sub 8790885129` — 订阅（支持按 ID、雪球主页链接或 UID）
- `/unsub 1` / `/unsub https://xueqiu.com/8790885129` / `/unsub 8790885129` — 取消订阅
- `/mysubs` — 我的订阅
- `/help` — 帮助

> 说明：本项目为自托管替代方案，仅抓取公开可见的动态，不包含任何平台会员/付费内容；无订阅名额与推送次数限制。

## 功能

- 订阅管理：网页增删改大V、启停（雪球 user_id / 微博 uid / X RSS 地址）
- 多用户：注册/登录，客户自助订阅自己喜欢的大V，各看各的动态流
- 逐人推送：新帖按订阅关系推送给每个用户绑定的 Telegram / 飞书
- 大V分类：分类管理、按分类筛选、推送消息带分类标签
- 定时轮询：默认 180s，带随机抖动与失败退避
- 优先抓取：把重点大V标记为「优先」后按 `polling.priority_interval_seconds`（默认 60s）抓取，其余保持全局间隔，兼顾时效与风控
- 消息推送：新帖去重后推送飞书（卡片）与 Telegram（HTML 消息）
- 帖子历史与推送记录：Web 页面可浏览
- Docker 一键部署，SQLite 持久化

## 快速开始

```bash
cp config.example.yaml config.yaml
# 编辑 config.yaml，填入飞书/Telegram 配置
docker compose up -d --build
```

打开 http://localhost:8000 进入网页后台。**管理员只能通过后台指定**：注册用户一律是普通用户；启动时配置 `web.admin_password` 会创建 `admin` 管理员账号，管理员登录后可在「管理后台 → 用户」里把其他用户设为/取消管理员。数据保存在 `./data/dav.db`，重启不丢。

## 微信小程序

小程序代码在 `miniprogram/`，用微信开发者工具打开即可预览：

1. 在 [微信公众平台](https://mp.weixin.qq.com) 注册小程序，拿到 `appid`/`appsecret`，填入 `wechat.app_id` / `wechat.app_secret`
2. 修改 `miniprogram/utils/api.js` 里的 `BASE_URL` 为后端地址；本地开发勾选开发者工具「不校验合法域名」
3. 首次使用走 `wx.login` 自动登录（未配置微信凭据时登录页会降级为账号密码登录）

上线前需要把后端部署到 HTTPS 域名，并在小程序后台配置 request 合法域名。

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
| `notifiers.feishu.webhook_url` | 飞书群机器人 webhook（全局推送） |
| `notifiers.feishu.app_id` / `app_secret` | 飞书自建应用凭据（逐人直聊推送需要，未配置则跳过） |
| `notifiers.telegram.bot_token` | Telegram Bot token |
| `notifiers.telegram.chat_id` | 接收消息的会话 ID |
| `notifiers.telegram.proxy` | 可选：Telegram API 代理地址（如 `http://127.0.0.1:7890`，被墙网络建议配置） |
| `sources.xueqiu.cookie` | 可选，雪球 Cookie 初始值；过期后需手动更新（自动续期会尝试，但受 WAF 限制通常需要浏览器） |
| `sources.weibo.cookie` | 可选，微博 Cookie 初始值（未配置账号密码时的兜底） |
| `sources.weibo.token` | 可选，x-xsrf-token |
| `sources.weibo.username` | 可选，微博账号；配置后自动登录并自动续期 cookie |
| `sources.weibo.password` | 可选，微博密码 |
| `polling.interval_seconds` | 轮询间隔（默认 180） |
| `polling.jitter_seconds` | 随机抖动（默认 30） |
| `polling.notify_on_start` | 启动时发上线消息（默认 true） |
| `web.allow_register` | 是否开放自助注册（默认 true） |
| `web.admin_password` | 可选，启动时创建 `admin` 管理员账号（密码） |
| `web.token_secret` | 可选，token 签名密钥，留空自动生成并持久化 |
| `wechat.app_id` / `app_secret` | 微信小程序登录凭据（小程序端用） |

所有配置项均可通过环境变量覆盖（见 `.env.example`）。注意 `.env` 文件本身不会被程序自动读取，环境变量需由运行环境注入（Docker compose 已处理，直接 `python app/main.py` 本地运行不会读取 `.env`）。

## Cookie 获取与自动续期

- **雪球**：抓取走 `user_timeline.json` JSON 接口，普通 HTTP 请求即可，不受 WAF 挑战影响。Cookie 约 30 天有效；过期后服务会尝试自动续期，但雪球首页受阿里云 WAF 保护（需要浏览器执行 JS 验证），自动续期通常无法成功，此时会清晰报错，请手动更新 `sources.xueqiu.cookie`。
- **微博**：推荐配置 `sources.weibo.username/password`，服务会自动走 weibo.cn 登录流程获取 cookie 并续期（可能偶尔遇到验证码导致登录失败，失败时会推送告警并在次日重试）。不想用账号密码时，也可手动填 cookie：浏览器登录 weibo.cn → 开发者工具 → Network → 复制请求头里的 `Cookie` 整串。

手动 cookie 过期后重新复制即可，无需重启容器（改 `config.yaml` 后 `docker compose restart`）。

## 用户与订阅

- 管理员只能在网页后台指定（`web.admin_password` 引导 + 后台用户页设置），注册/小程序登录用户一律为普通用户
- 管理员在「我的 → 管理后台」维护大V目录、分类、查看推送记录、指定管理员
- 普通用户在首页/搜索中浏览大V并点击「订阅」，动态页只显示自己订阅的大V的新帖
- 「我的 → 推送设置」绑定 Telegram chat_id / 飞书 open_id 并开启推送，新帖会按订阅关系逐人推送

## 配置校验

程序启动时会校验配置：数字/布尔字段会自动归一化类型（如引号包裹的 `"60"`），类型错误或取值非法会直接启动报错并指明具体配置项；环境变量解析失败也会提示变量名。

## X (Twitter) 订阅

X 官方 API 需付费，本项目通过 RSS 源订阅。每个 X 大V 在「订阅管理」中添加时，外部 ID 填 RSS 地址，例如：

- RSSHub 公共实例：`https://rsshub.app/twitter/user/elonmusk`
- 自建 RSSHub：`http://<你的地址>/twitter/user/elonmusk`
- 其他兼容 RSS 2.0 的源亦可

RSS 源不稳定时该平台会暂时抓不到，建议自建 RSSHub 保证可用性。

## 生产部署（HTTPS + 正式域名）

1. 复制环境变量模板并填好密钥（域名、bot token、飞书/微信凭据、管理员密码等）：

   ```bash
   cp .env.example .env.prod
   # 编辑 .env.prod：DOMAIN、TELEGRAM_BOT_TOKEN、FEISHU_APP_ID/SECRET、
   # WECHAT_APP_ID/SECRET、WEB_ADMIN_PASSWORD、WEB_TOKEN_SECRET、XUEQIU_COOKIE
   ```

2. 用生产 compose 启动（Caddy 自动申请/续期 HTTPS 证书）：

   ```bash
   set -a; source .env.prod; set +a
   docker compose -f docker-compose.prod.yml up -d --build
   ```

3. 数据备份（SQLite 在线备份，WAL 安全）：

   ```bash
   python3 scripts/backup.py data/dav.db backups 14
   ```

   可加入 crontab 每天自动备份：`0 3 * * * cd /path/to/project && python3 scripts/backup.py data/dav.db backups 14`

4. 小程序上线：把小程序 `miniprogram/utils/api.js` 的 `BASE_URL` 改为 `https://你的域名`，在微信公众平台配置 request 合法域名后提审。

## Unraid 部署

把整个项目目录放到 Unraid 的 appdata 下，例如 `/mnt/user/appdata/dav-subscription`，然后：

1. 在 Unraid 里装好 Docker Compose（或使用 Docker Compose Manager 插件），添加项目 `/mnt/user/appdata/dav-subscription/docker-compose.unraid.yml`
2. 在 compose 的「环境变量」里填好密钥：`FEISHU_APP_ID/SECRET`、`TELEGRAM_BOT_TOKEN`、`WECHAT_APP_ID/SECRET`（暂无微信可留空）、`XUEQIU_COOKIE`、`WEB_ADMIN_PASSWORD`、`WEB_TOKEN_SECRET`；或在该目录建一个 `.env` 文件
3. 启动后访问 `http://<Unraid IP>:18084`（宿主机 8000 常被占用，Unraid 用 18084 对外）
4. 数据保存在 `/mnt/user/appdata/dav-subscription/data/dav.db`，备份用 `python3 scripts/backup.py`（或在 Unraid 上定期复制该目录）

> 局域网 HTTP 部署即可，不需要 HTTPS；如要对外提供小程序服务再走生产 compose（Caddy + 域名）。

## 数据保留

帖子与推送记录默认保留 30 天（`polling.posts_retention_days`，0 表示永久保留），调度器每 6 小时自动清理超期数据，避免 SQLite 无限膨胀。

## 安全提示

默认监听所有网卡。建议：

- 仅在内网使用，或置于反向代理后
- 如暴露公网，务必通过生产 compose（HTTPS）部署，并设置 `WEB_ADMIN_PASSWORD`、`WEB_TOKEN_SECRET`

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
