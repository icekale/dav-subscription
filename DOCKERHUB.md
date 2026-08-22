# V Push

**自托管的社交大V动态聚合订阅系统**：抓取 **雪球 / 微博 / X (Twitter)** 大V的公开动态（含雪球组合调仓），新帖按订阅关系**实时推送到 Telegram / 飞书 / 企业微信**。多用户自助订阅，每个用户自选关注的大V与接收渠道；管理员在网页后台统一管理大V目录、数据源与用户。

> 仅抓取公开可见的动态，不含任何平台会员/付费内容；**自托管，无订阅名额与推送次数限制**，数据全部保存在你自己的服务器。

| | |
| --- | --- |
| 平台 | linux/amd64 · linux/arm64（Docker Hub / GHCR 双端发布） |
| 镜像 | `icekale/vpush:latest` |
| 许可 | MIT |

## ✨ 功能特性

- **多源聚合**：雪球帖子/回复、雪球组合调仓、微博、X，自动去重、按发布时间顺序推送；带图动态文字+图片同卡送达（TG 相册 / 飞书卡片插图）
- **多用户**：注册码邀请注册，用户自助订阅/退订，各自独立的动态流与推送
- **多通道推送**：Telegram、飞书私聊/群、企业微信群机器人、Bark、浏览器通知（Chrome / Edge）；绑定多个渠道时可自选接收通道
- **关键词提醒**：命中关键词的动态实时穿透推送（🔑 标记），适合只关心特定话题
- **特别关注 ⭐**：标星大V的推送带星标、每日精选置顶，可在免打扰时段实时穿透
- **午夜免打扰**：时段内不打扰，结束后一次性补一条汇总（可选配置 LLM 后自动生成 AI 要点）
- **数据源稳定性监控**：后台实时展示抓取状态与健康探测，在线调整抓取频率，连续失败自动向管理员告警
- **网页后台**：大V目录、分类、注册码、用户管理、推送记录、实时系统日志、数据源状态
- **X 自动翻译**：配置登录 Cookie 后走 X 官方翻译接口，内容自动翻译成中文
- **微信小程序**（可选）：附带小程序客户端，微信登录使用

## 🚀 快速开始

要求：Docker 20.10+ 与 Docker Compose v2（或直接 `docker run`）、一台可访问的服务器（NAS / VPS / 群晖 / Unraid 均可，推荐 2 核 1G 以上）。

### 方式一：docker run（最快体验）

```bash
docker run -d --name vpush --restart unless-stopped \
  -p 8000:8000 \
  -v "$PWD/data:/data" \
  -e WEB_ADMIN_PASSWORD=你的管理员密码 \
  -e TELEGRAM_BOT_TOKEN=你的Telegram机器人token \
  -e TELEGRAM_CHAT_ID=你的会话ID \
  icekale/vpush:latest
```

### 方式二：Docker Compose（推荐）

新建 `docker-compose.yml`：

```yaml
services:
  vpush:
    image: icekale/vpush:latest
    container_name: vpush
    restart: unless-stopped
    ports:
      - "8000:8000"
    env_file:
      - .env
    volumes:
      - ./data:/data
```

同目录新建 `.env`（按需填写，核心项见下方表格）：

```bash
# 首次启动创建 admin 管理员账号（必填，至少 6 位）
WEB_ADMIN_PASSWORD=你的管理员密码
# Telegram 推送渠道（@BotFather 创建机器人）
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=123456789
TELEGRAM_BOT_USERNAME=your_bot
# 雪球 Cookie（浏览器登录 xueqiu.com 后复制，抓雪球必需）
XUEQIU_COOKIE=...
# 微博（可选，也可后台扫码登录）
WEIBO_COOKIE=...
# X 直抓 + 自动翻译（可选）
TWITTER_COOKIE=...
```

启动：

```bash
docker compose up -d
```

打开浏览器访问 **<http://localhost:8000**，用> `admin` + `WEB_ADMIN_PASSWORD` 登录后台。

> 国内网络拉取慢，可改用 GHCR 镜像：`ghcr.io/icekale/vpush:latest`

## 📱 如何使用

### Web 后台

- **订阅广场**：浏览大V目录，按平台/分类筛选，一键订阅/退订
- **动态**：已订阅大V的最新帖时间流
- **我的订阅**：管理订阅，标星特别关注 ⭐
- **推送设置**：绑定 Telegram / 飞书 / 企业微信 / Bark / 浏览器通知，生成绑定码把机器人会话合并到网页账号，自选接收通道
- **管理后台**（管理员）：大V管理、批量导入、分类、注册码、用户、推送记录、数据源状态、系统日志

### Telegram / 飞书机器人

给机器人发消息即可开始：

| 命令 | 说明 |
| --- | --- |
| `/list` | 查看可订阅的大V（`/list 2` 翻页） |
| `/sub 1` 或 `/sub 链接` | 订阅大V |
| `/unsub 1` | 取消订阅 |
| `/mysubs` | 我的订阅 |
| `/bind 6位码` | 把机器人会话合并到网页账号 |
| `/help` | 帮助 |

飞书机器人会发带按钮的交互卡片，点「订阅」即可；企业微信群机器人通过 webhook 接收推送（订阅请在网页完成）。

## ⚙️ 核心环境变量

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `WEB_ADMIN_PASSWORD` | 是 | 首次启动创建 admin 账号的密码 |
| `XUEQIU_COOKIE` | 推荐 | 雪球登录 Cookie（抓雪球必需，失效时后台告警需手动更新） |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | 推荐 | Telegram 推送渠道 |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 否 | 飞书自建应用凭据（机器人订阅+私聊推送） |
| `WECOM_WEBHOOK_URL` | 否 | 企业微信群机器人 webhook（系统告警；用户可各自绑定） |
| `BARK_SERVER` / `BARK_KEY` | 否 | Bark iOS 通知 |
| `VAPID_PRIVATE_KEY` / `VAPID_PUBLIC_KEY` | 否 | 浏览器 Web Push；留空则首次使用时自动生成 |
| `LLM_API_BASE` / `LLM_API_KEY` / `LLM_MODEL` | 否 | OpenAI 兼容 LLM，免打扰汇总生成 AI 要点 |
| `WEIBO_COOKIE` 或 `WEIBO_USERNAME/PASSWORD` | 否 | 微博渠道 |
| `TWITTER_COOKIE` | 否 | X 直抓 + 自动翻译 |
| `POLLING_POSTS_RETENTION_DAYS` | 否 | 帖子/推送记录保留天数（默认 30，0 永久） |
| `TZ` | 否 | 时区，默认 Asia/Shanghai |

完整变量清单见仓库 [.env.example](https://github.com/icekale/vpush/blob/main/.env.example)。

## 🔒 生产部署（HTTPS）

仓库提供带 Caddy 自动 HTTPS 的完整编排：

```bash
git clone https://github.com/icekale/vpush.git
cd vpush
cp .env.example .env    # 设置 DOMAIN、WEB_ADMIN_PASSWORD、推送凭据
docker compose -f docker-compose.prod.yml up -d --build
```

Caddy 自动申请/续期 Let's Encrypt 证书，把域名 A 记录指向服务器、开放 80/443 即可。

## 💾 备份与升级

- 数据是单文件 SQLite：`data/dav.db`，直接复制即备份
- 升级：`docker compose pull && docker compose up -d`，数据不丢
- 推送失败自动重试（1m/5m/15m）；数据源连续失败自动向管理员告警

## ❓ 常见问题

- **收不到推送？** 网页「推送设置」确认渠道已绑定；飞书必须是私聊会话；Telegram 先给机器人发 `/start`
- **雪球抓取失败？** 后台「数据源」页更新雪球 Cookie（首页续期已被反爬接管，需手动更新）
- **X 抓不到？** 配置 `TWITTER_COOKIE`；直抓失败会告警并放慢采集，请检查 Cookie 或升级代码
- **绑定了多渠道只收到一部分？** 「推送设置 → 推送通道选择」勾选想接收的渠道

## 🔗 相关链接

- GitHub 仓库与完整文档：<https://github.com/icekale/vpush>
- 微信小程序客户端与更多配置见仓库 README
