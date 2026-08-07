<div align="center">

# 大V订阅 DaV Subscription

自托管的社交大V动态聚合订阅系统：抓取 **雪球 / 微博 / X(Twitter)** 大V公开动态（含雪球组合调仓），新帖实时推送到 **Telegram / 飞书 / 企业微信**。支持多用户注册，每个用户自选订阅的大V与推送渠道，管理员在网页后台统一管理。

[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ed.svg?logo=docker&logoColor=white)](Dockerfile)
[![Docker Hub](https://img.shields.io/docker/v/icekale/dav-subscription?logo=docker&label=Docker%20Hub)](https://hub.docker.com/r/icekale/dav-subscription)
[![GHCR](https://img.shields.io/badge/GHCR-镜像-2496ed.svg?logo=github&logoColor=white)](https://github.com/icekale/dav-subscription/pkgs/container/dav-subscription)
[![Platform](https://img.shields.io/badge/Platform-amd64%20%7C%20arm64-blue.svg)]()

</div>

> 仅抓取公开可见的动态，不含任何平台会员/付费内容；自托管无订阅名额与推送次数限制。

## 产品截图

<div align="center">

| | |
| --- | --- |
| <img src="docs/screenshots/home.png" width="420"><br>订阅广场 · 平台筛选与分类目录 | <img src="docs/screenshots/settings.png" width="420"><br>推送设置 · 多渠道状态与通道选择 |
| <img src="docs/screenshots/mysubs.png" width="420"><br>我的订阅 · 帖子/回复分订 | <img src="docs/screenshots/combinations.png" width="420"><br>组合订阅 · 雪球模拟仓调仓 |
| <img src="docs/screenshots/login.png" width="420"><br>登录注册 · 注册码邀请 | <img src="docs/screenshots/admin-stats.png" width="420"><br>管理后台 · 数据源与抓取状态 |

</div>

## 功能

- **多源聚合**：雪球帖子/回复、雪球组合调仓、微博、X，自动去重、按发布时间顺序推送；带图动态文字+图片同卡送达（TG 相册 / 飞书卡片插图）
- **多用户**：注册码注册，用户自助订阅/退订，各自独立的动态流与推送
- **多通道推送**：Telegram（官方共享机器人或用户自建机器人）、飞书私聊/群、企业微信群机器人、Bark（iOS 自托管通知）；绑定多个渠道时可自选接收通道
- **关键词提醒**：设置关键词后，命中关键词的动态带 🔑 标记、并在免打扰时段实时穿透推送（适合只关心某个大V聊的特定话题）
- **RSS 订阅源**：每个用户一个私有 RSS 地址（含订阅凭证），加进任意 RSS 阅读器即可直接收关注动态，无需登录
- **特别关注**：把订阅的大V标星 ⭐，推送消息带星标标识、每日精选置顶；可在免打扰时段内选择「特别关注穿透」实时提醒
- **午夜免打扰**：设置免打扰时段（支持跨午夜），时段内不打扰，结束后一次性补一条汇总，不错过任何动态（可选配置 OpenAI 兼容 LLM 后，汇总自动生成 AI 要点）
- **数据源稳定性监控**：后台实时展示各数据源抓取状态与健康探测，支持在线调整抓取频率与策略，数据源连续失败自动向管理员告警
- **系统日志增强**：网页端实时查看系统日志，支持级别与关键词过滤；日志默认落盘持久化（滚动 5MB×3），重启不丢，便于排查与 AI Agent 分析
- **网页后台**：大V目录、分类、优先级抓取、注册码、用户与管理员、推送记录、操作日志与系统日志（网页实时查看）、数据源状态
- **抓取策略**：优先大V短间隔（默认 60s）+ 普通大V全局间隔（默认 180s），随机抖动与失败退避；雪球/微博 cookie 自动续期保活
- **本地头像缓存**：第三方图床头像自动缓存到服务器本地，解决签名过期/外链失效
- **长文完整推送**：单条推送上限 2000 字符并智能断句，不再拦腰截断
- **X 翻译**：配置 X 登录 Cookie 后走官方翻译接口（同网页版），内容自动翻译成中文
- **微信小程序**（可选）：`miniprogram/` 提供微信登录的客户端，可后接

## 快速 Docker 部署

### 0. 用 AI Agent 部署（可选，推荐）

本项目从部署、配置到日常运维都可以交给 AI Agent（如 Codex、Claude Code、Cursor 等）直接完成。克隆仓库后，把目标交给 AI Agent，它会自行阅读本 README 与部署文档、准备配置、执行命令并做健康检查：

```bash
git clone https://github.com/icekale/dav-subscription.git
```

> 示例指令（按你的环境替换部署目标与推送渠道）：
>
> ```
> 阅读这个仓库的 README 和部署文档，用 Docker Compose 帮我部署 dav-subscription：
> 1. 配置 Telegram / 飞书 / 企业微信推送渠道，并创建 admin 管理员账号
> 2. 构建并启动容器，部署完成后检查健康接口和 Web 后台可访问
> 3. 告诉我登录地址、管理员账号，以及查看日志排障的方法
> ```

AI Agent 可以完成的典型工作：

- **部署**：自动准备 `.env`、构建并启动容器、验证 `/healthz` 与 Web 后台
- **升级**：`git pull` 后重建容器，保留 `./data/dav.db` 数据不丢失
- **排障**：查看容器日志、检查数据源抓取状态、定位推送失败原因
- **日常运维**：数据备份、清理过期帖子、调整抓取频率与抓取策略

> 提示：重要生产环境建议在让 AI Agent 操作前先备份 `./data/` 目录，并保留系统快照。

### 1. 前置要求

- Docker 20.10+ 与 Docker Compose v2（`docker compose version` 可验证）
- 一个可访问的服务器（NAS / VPS / 群晖 / Unraid 均可），推荐 2 核 1G 以上
- 想收推送至少需要一个渠道的凭据：Telegram Bot Token、飞书应用或企业微信群机器人 webhook

### 2. 获取代码并准备配置

```bash
git clone https://github.com/icekale/dav-subscription.git
cd dav-subscription
cp .env.example .env
```

编辑 `.env`，把下面的关键项填上（其余可留空，不影响启动）：

| 环境变量 | 必填 | 说明 |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | 推荐 | Telegram 机器人 token，[BotFather](https://t.me/BotFather) 创建 |
| `TELEGRAM_CHAT_ID` | 推荐 | 管理员接收系统告警的会话 ID（可用 [@userinfobot](https://t.me/userinfobot) 查询） |
| `TELEGRAM_BOT_USERNAME` | 推荐 | 机器人 @username，用于推送设置页的一键绑定链接 |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 可选 | 飞书自建应用凭据（用于机器人命令与私聊推送），配置见下文 |
| `FEISHU_WEBHOOK_URL` | 可选 | 飞书群机器人 webhook（系统告警用，用户可自行在网页绑定各自的群机器人） |
| `WECOM_WEBHOOK_URL` | 可选 | 企业微信群机器人 webhook（系统告警用） |
| `BARK_SERVER` | 可选 | Bark 服务器地址，默认官方 `https://api.day.app`；自建实例时填 `https://bark.example.com` |
| `BARK_KEY` | 可选 | 系统级默认 Bark key（配置后系统告警也发 Bark）；用户可各自在网页绑定自己的 key |
| `LLM_API_BASE` / `LLM_API_KEY` / `LLM_MODEL` | 可选 | OpenAI 兼容 LLM（OpenAI / DeepSeek / 本地 Ollama、vLLM 均可）。配置 `LLM_API_KEY` 后，免打扰时段汇总自动生成 AI 要点；未配置则用普通列表汇总，推送管线零变化 |
| `WEB_ADMIN_PASSWORD` | 推荐 | 启动时创建 `admin` 管理员账号，登录后台管理 |
| `WEB_ALLOW_REGISTER` | 可选 | 是否允许注册（`false` 时关闭注册入口）；注册始终需要邀请码，邀请码由管理员在后台生成 |
| `XUEQIU_COOKIE` | 可选 | 浏览器登录 xueqiu.com 后复制的 Cookie，用于保持登录态、提升抓取稳定性 |
| `WEIBO_COOKIE` | 可选 | 浏览器登录微博后复制的 Cookie，可后台扫码登录替代 |
| `TWITTER_COOKIE` | 可选 | 浏览器登录 x.com 后复制的完整 Cookie（直抓 X + 自动翻译中文） |
| `LOG_LEVEL` | 可选 | 日志级别 `INFO`/`DEBUG`（DEBUG 记录每次 API 请求与慢请求告警，便于排查） |
| `LOG_FILE` | 可选 | 日志文件，默认 `/data/logs/app.log`（随数据卷持久化，滚动 5MB×3，重启不丢） |

也可以用 YAML 配置：复制 `config.example.yaml` 为 `config.yaml` 后修改（环境变量优先级更高）。

### 3. 启动

```bash
docker compose up -d --build
```

> 国内网络构建较慢时，可在 compose 的 `build.args.PIP_INDEX_URL` 指定清华镜像（Unraid 模板已默认配置）。

启动后访问：

- Web 后台：<http://localhost:8000> （首次用 `admin` + `WEB_ADMIN_PASSWORD` 登录）
- Telegram / 飞书里给机器人发 `/list` 即可开始订阅大V

数据保存在 `./data/dav.db`（SQLite），重启不丢；升级只需 `git pull && docker compose up -d --build`。

不想本地构建？直接用现成镜像（Docker Hub / GHCR 均发布，amd64 + arm64）：

```bash
docker run -d --name dav-subscription --restart unless-stopped \
  -p 8000:8000 -v "$PWD/data:/data" \
  -e WEB_ADMIN_PASSWORD=你的管理员密码 \
  -e TELEGRAM_BOT_TOKEN=你的token \
  icekale/dav-subscription:latest
```

或在 compose 里用 `image: icekale/dav-subscription:latest` 替代 `build: .`。不想 git clone，直接新建一个 `docker-compose.yml` 用现成镜像部署：

```yaml
services:
  dav-subscription:
    # Docker Hub 与 GHCR 双端发布，amd64 + arm64；国内网络可换 ghcr.io/icekale/dav-subscription:latest
    image: icekale/dav-subscription:latest
    container_name: dav-subscription
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      - TZ=Asia/Shanghai
      - DB_PATH=/data/dav.db
    # 推送渠道凭据、管理员密码等全部从同目录 .env 读取（变量见上方表格）
    env_file:
      - .env
    volumes:
      - ./data:/data
```

同目录准备 `.env`（从仓库复制 `.env.example`，按上方变量表填好）后启动：

```bash
docker compose up -d        # 首次拉镜像启动
# 升级：docker compose pull && docker compose up -d
```

- 数据保存在 `./data/dav.db`（SQLite），重启、升级不丢
- 镜像自带健康检查（`/healthz`），`docker ps` 可看到 `(healthy)`
- 访问 <http://localhost:8000> ，用 `admin` + `WEB_ADMIN_PASSWORD` 登录

## 生产部署（HTTPS）

仓库提供了带 Caddy 自动 HTTPS 的完整编排 `docker-compose.prod.yml`：

```bash
cp .env.example .env
# 编辑 .env，至少设置：DOMAIN=your.domain.com、WEB_ADMIN_PASSWORD、推送渠道凭据
docker compose -f docker-compose.prod.yml up -d --build
```

Caddy 会自动申请并续期 Let's Encrypt 证书，无需额外配置。需要把域名 A 记录指向服务器，并开放 80/443 端口。

## Unraid 部署

在 Unraid 的「Apps」里添加自定义 Compose 栈，或直接使用 `docker-compose.unraid.yml`：

```bash
cp docker-compose.unraid.yml /mnt/user/appdata/dav-subscription/docker-compose.yml
cd /mnt/user/appdata/dav-subscription
# 在同目录创建 .env（内容同 .env.example）并填写凭据
docker compose up -d --build
```

默认对外端口 **18084**（宿主机 8000 常被占用）：访问 `http://<NAS IP>:18084`。数据目录为 `./data`。

## 推送渠道配置

### Telegram

1. 找 [@BotFather](https://t.me/BotFather) 发 `/newbot`，拿到 token 与 @username
2. 填入 `.env`：`TELEGRAM_BOT_TOKEN`、`TELEGRAM_BOT_USERNAME`、`TELEGRAM_CHAT_ID`
3. 用户加机器人后发 `/start`，再发 `/list` 浏览订阅

用户也可以在网页「推送设置」里粘贴自己的 Bot Token，用自己的机器人收推送（不受共享机器人广播限速影响）。

### 飞书

用户需要飞书应用机器人用于私聊命令与推送，配置一次即可所有用户共用：

1. 打开[飞书开放平台](https://open.feishu.cn)，创建「企业自建应用」
2. 应用能力 → 开启「机器人」；权限管理 → 开通：`im:message`、`im:message:send_as_bot`、`im:chat`（读会话）、`contact:user.base:readonly` 等
3. 事件与回调 → 订阅方式选「长连接」，添加事件 `接收消息 im.message.receive_v1`
4. 发布版本并等待审核通过
5. 把 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_BOT_NAME` 填入 `.env`

> 关键：用户必须在机器人的**私聊**会话里发消息/命令，群聊不会收到新帖推送；网页「推送设置」里有分步引导。

### 企业微信

企业微信任意群里添加「群机器人」，复制 webhook 粘贴到网页推送设置即可（用户各自绑定，互不影响）。

## 数据源配置

- **雪球**：后台「数据源」页可直接粘贴 Cookie；配置 `WEIBO_USERNAME/PASSWORD` 可自动登录续期微博 Cookie，微博也支持网页扫码登录
- **X**：配置 `TWITTER_COOKIE` 后直抓 X 官方接口并把内容翻译成中文；直抓失败会自动降级自建 RSSHub 备用通道（compose 已内置，默认指向 `http://rsshub:1200`，不依赖外部公共实例）
- **抓取频率**：后台「数据源」页可实时调整轮询间隔、优先大V间隔、合并推送周期等，即时生效

## 微信小程序（可选）

`miniprogram/` 是微信小程序客户端。用微信开发者工具打开，把 `miniprogram/config.js` 的 `BASE_URL` 改为后端地址，并在微信公众平台配置 `WECHAT_APP_ID` / `WECHAT_APP_SECRET` 即可；未配置微信凭据时登录页自动降级为账号密码登录。

## 备份与运维

- 数据库为单文件 `data/dav.db`，直接复制即备份
- `scripts/backup.py` 提供带保留周期的备份脚本；`scripts/backup_unraid.sh` 为 Unraid 定时任务示例
- 推送失败会自动重试（1m/5m/15m），数据源连续失败会通过系统渠道向管理员告警

## 开发

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml   # 填入本地配置
uvicorn app.main:app --reload
```

测试：`python -m pytest -q`

## 常见问题

- **收不到推送？** 先到网页「推送设置」确认状态为已绑定；飞书必须是私聊会话；Telegram 先给机器人发 `/start`
- **绑定了多个渠道只收到一部分？** 在「推送设置 → 推送通道选择」勾选想接收的渠道
- **雪球抓取失败？** 后台「数据源」更新雪球 Cookie
- **X 抓不到？** 后台开启「X 内容自动翻译」并配置 `TWITTER_COOKIE`

## License

MIT
