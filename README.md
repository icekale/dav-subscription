<div align="center">

# V Push

自托管的社交大V动态聚合订阅系统：抓取 **雪球 / 微博 / X(Twitter)** 大V公开动态（含雪球组合调仓），新帖实时推送到 **Telegram / 飞书 / 企业微信**。支持多用户注册，每个用户自选订阅的大V与推送渠道，管理员在网页后台统一管理。

[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ed.svg?logo=docker&logoColor=white)](Dockerfile)
[![Docker Hub](https://img.shields.io/docker/v/icekale/vpush?logo=docker&label=Docker%20Hub)](https://hub.docker.com/r/icekale/vpush)
[![GHCR](https://img.shields.io/badge/GHCR-镜像-2496ed.svg?logo=github&logoColor=white)](https://github.com/icekale/vpush/pkgs/container/vpush)
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

- **多源聚合**：雪球帖子/回复、雪球组合调仓、微博、X、**ima 知识库**，自动去重、按发布时间顺序推送；带图动态文字+图片同卡送达（TG 相册 / 飞书卡片插图）；组合详情页提供实时净值/今日涨跌、当前持仓（权重条）与净值曲线（调仓卡自动附当日涨跌）
- **多用户**：注册码注册，用户自助订阅/退订，各自独立的动态流与推送
- **多通道推送**：Telegram（官方共享机器人或用户自建机器人）、飞书私聊/群、企业微信群机器人、Bark（iOS 自托管通知）、浏览器通知（Chrome / Edge Web Push，关掉标签页也能弹）；绑定多个渠道时可自选接收通道
- **关键词提醒**：设置关键词后，命中关键词的动态带 🔑 标记、并在免打扰时段实时穿透推送（适合只关心某个大V聊的特定话题）
- **特别关注**：把订阅的大V标星 ⭐，推送消息带星标标识、每日精选置顶；可在免打扰时段内选择「特别关注穿透」实时提醒
- **午夜免打扰**：设置免打扰时段（支持跨午夜），时段内不打扰，结束后一次性补一条汇总，不错过任何动态（可选配置 OpenAI 兼容 LLM 后，汇总自动生成 AI 要点）
- **数据源稳定性监控**：后台实时展示各数据源抓取状态与健康探测，支持在线调整抓取频率与策略，数据源连续失败自动向管理员告警
- **系统日志增强**：网页端实时查看系统日志，支持级别与关键词过滤；日志默认落盘持久化（滚动 5MB×3），重启不丢，便于排查与 AI Agent 分析
- **网页后台**：大V目录、分类、优先级/次要抓取、注册码、用户与管理员、推送记录、操作日志与系统日志（网页实时查看）、数据源状态
- **抓取策略**：**雪球组合最高频（30s，空轮封顶 2min）** + 优先大V短间隔（默认 60s）+ 普通大V全局间隔（默认 180s）+ **次要大V低频（默认 15min，空轮封顶 1h）**，随机抖动与失败退避；**无新帖自动降频**（空轮间隔 2 倍步进，有新帖立即恢复），轮内随机错峰打破固定节律，X 直抓失败期间限速；组合调仓**实时推送**（不走合并摘要）；**优先大V实时推送、普通大V 10min 合并摘要、次要大V 1h 长摘要合并推送**（次要/优先互斥，后台可调）；微博 cookie 自动续期保活（登录失败 30 分钟冷却），雪球 cookie 定时探测失效并告警（雪球首页续期已被反爬接管，需手动更新 cookie）
- **本地头像缓存**：第三方图床头像自动缓存到服务器本地，解决签名过期/外链失效
- **长文完整推送**：单条推送上限 2000 字符并智能断句，不再拦腰截断
- **X 翻译**：配置 X 登录 Cookie 后走官方翻译接口（同网页版），内容自动翻译成中文
- **微信小程序**（可选）：`miniprogram/` 提供微信登录的客户端，可后接

## 快速 Docker 部署

### 0. 用 AI Agent 部署（可选，推荐）

本项目从部署、配置到日常运维都可以交给 AI Agent（如 Codex、Claude Code、Cursor 等）直接完成。克隆仓库后，把目标交给 AI Agent，它会自行阅读本 README 与部署文档、准备配置、执行命令并做健康检查：

```bash
git clone https://github.com/icekale/vpush.git
```

> 示例指令（按你的环境替换部署目标与推送渠道）：
>
> ```
> 阅读这个仓库的 README 和部署文档，用 Docker Compose 帮我部署 vpush：
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
git clone https://github.com/icekale/vpush.git
cd vpush
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
| `VAPID_PRIVATE_KEY` / `VAPID_PUBLIC_KEY` | 可选 | 浏览器 Web Push 的 VAPID 密钥（PEM + 公钥）。留空则首次使用时自动生成并写入数据库 |
| `VAPID_MAILTO` | 可选 | VAPID 联系邮箱，默认 `mailto:admin@localhost` |
| `LLM_API_BASE` / `LLM_API_KEY` / `LLM_MODEL` | 可选 | OpenAI 兼容 LLM（OpenAI / DeepSeek / 本地 Ollama、vLLM 均可）。配置 `LLM_API_KEY` 后，免打扰时段汇总自动生成 AI 要点；未配置则用普通列表汇总，推送管线零变化 |
| `WEB_ADMIN_PASSWORD` | 推荐 | 启动时创建 `admin` 管理员账号，登录后台管理 |
| `WEB_ALLOW_REGISTER` | 可选 | 是否允许注册（`false` 时关闭注册入口）；注册始终需要邀请码，邀请码由管理员在后台生成 |
| `XUEQIU_COOKIE` | **必需** | 浏览器登录 xueqiu.com 后复制的 Cookie。雪球抓取接口必须有登录态，无/失效 cookie 会返回 400；首页续期通道已被反爬接管无法自动续期，后台「数据源 → Cookie 管理」粘贴新串即可，不用重启 |
| `WEIBO_COOKIE` | 可选 | 浏览器登录微博后复制的 Cookie，可后台扫码登录替代 |
| `TWITTER_COOKIE` | 可选 | 浏览器登录 x.com 后复制的完整 Cookie（直抓 X + 自动翻译中文）；也可在后台「数据源 → Cookie 管理」覆盖，无需重启 |
| `IMA_COOKIE` | 可选 | ima 网页登录 Cookie（请求头 `x-ima-cookie`），抓列表/标题/时间/摘要/封面；可用 `scripts/ima_qr_login.py` 扫码自动捕获 |
| `IMA_OPENAPI_CLIENTID` / `IMA_OPENAPI_APIKEY` | 可选 | ima OpenAPI 凭证（登录 https://ima.qq.com/agent-interface 生成），官方通道，**取全文必须**；对订阅的知识库原文仍受客户端限制，自动降级为摘要 |
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
docker run -d --name vpush --restart unless-stopped \
  -p 8000:8000 -v "$PWD/data:/data" \
  -e WEB_ADMIN_PASSWORD=你的管理员密码 \
  -e TELEGRAM_BOT_TOKEN=你的token \
  icekale/vpush:latest
```

或在 compose 里用 `image: icekale/vpush:latest` 替代 `build: .`。不想 git clone，直接新建一个 `docker-compose.yml` 用现成镜像部署：

```yaml
services:
  vpush:
    # Docker Hub 与 GHCR 双端发布，amd64 + arm64；国内网络可换 ghcr.io/icekale/vpush:latest
    image: icekale/vpush:latest
    container_name: vpush
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
cp docker-compose.unraid.yml /mnt/user/appdata/vpush/docker-compose.yml
cd /mnt/user/appdata/vpush
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

### 飞书个人机器人（可选，免共享限频）

共享机器人所有用户共用一个应用配额（`im/v1/messages` 整体约 1000 次/分钟），用户多时可能触发频控。可配置 `FEISHU_CREDENTIAL_KEY` 开启**个人机器人**：用户在网页点「扫码创建个人机器人」，飞书会在其租户自动创建属于他自己的应用，用户只需在私聊窗口发一次 `/bind 6位码` 即可完成绑定。之后该用户的推送走自己的应用，配额独立。

- `FEISHU_CREDENTIAL_KEY`：Fernet 兼容的 32 字节 Base64 密钥，只从环境变量读取。生成：`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- 个人应用凭据用该密钥**加密存库**，浏览器/日志/API 一律脱敏；绑定码只存服务端哈希
- 个人机器人只做推送：无 `/list`/`/sub` 命令、无卡片交互；订阅管理仍在网页
- 个人机器人**失效自动回退共享机器人**，不破坏既有共享绑定；解绑只擦个人凭据，共享字段不变
- 未配置密钥时个人入口显示不可用，共享机器人完全不受影响

### 企业微信

企业微信任意群里添加「群机器人」，复制 webhook 粘贴到网页推送设置即可（用户各自绑定，互不影响）。

## 数据源配置

- **雪球**：后台「数据源 → Cookie 管理」粘贴 Cookie，保存即时生效；配置 `WEIBO_USERNAME/PASSWORD` 可自动登录续期微博 Cookie，微博也支持网页扫码登录
- **X**：配置 `TWITTER_COOKIE` 或在「数据源 → Cookie 管理」粘贴后直抓 X 官方接口并把内容翻译成中文；直抓失败会告警并放慢采集，不再走备用内容通道
- **ima**：知识库条目在后台按平台 `ima` 添加，`external_id` 填知识库 ID（OpenAPI 模式）或 wiki URL 的 `knowledgeBaseId`（Cookie 模式）；Cookie 用 `scripts/ima_qr_login.py` 扫码捕获；OpenAPI 凭证取全文，订阅库全文受 ima 客户端限制时自动降级为摘要（`detail.full_text` 标记是否拿到全文）
- **反爬绕过**：X 与雪球均对裸 HTTP 客户端设了反爬（Cloudflare / 阿里云 WAF JS 挑战），本仓库已内置对应绕过——X 直抓用 curl_cffi 模拟 Chrome 指纹（`impersonate=chrome124`）；雪球 `waf-bot` sidecar 默认使用 curl_cffi + jsdom 求解器，不包含浏览器运行时，并在发布 cookie 前校验真实接口（配置了登录 cookie 时验证组合调仓接口确认登录态有效）。挑战脚本受 Node 文件系统与进程权限限制，容器同时启用只读根文件系统、仅保留数据写入所需的 `DAC_OVERRIDE` 能力和禁止提权。详见下方「常见问题」
- **抓取频率**：后台「数据源」页可实时调整轮询间隔、优先大V间隔、次要大V间隔/封顶/推送周期/**合并推送最低条数**（积压不足此条数不推送、继续攒，够数才发）、合并推送周期等，即时生效

## 微信小程序（可选）

`miniprogram/` 是微信小程序客户端。用微信开发者工具打开，把 `miniprogram/config.js` 的 `BASE_URL` 改为后端地址，并在微信公众平台配置 `WECHAT_APP_ID` / `WECHAT_APP_SECRET` 即可；未配置微信凭据时登录页自动降级为账号密码登录。

## 备份与运维

- 数据库为单文件 `data/dav.db`，直接复制即备份
- `scripts/backup.py` 提供带保留周期的备份脚本；`scripts/backup_unraid.sh` 为 Unraid 定时任务示例
- 推送失败会自动重试（1m/5m/15m），数据源连续失败会通过系统渠道向管理员告警

## 开发

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
cp config.example.yaml config.yaml   # 填入本地配置
uvicorn app.main:app --reload
```

测试：`python -m pytest -q`

## 常见问题

- **登录被锁定 / 提示尝试次数过多？** 同一 IP 连续失败 8 次会临时限流（5 分钟）；账号连续失败（管理员 3 次、普通用户 10 次，1 小时内）会触发账号级临时锁定（15–30 分钟自动解锁），锁定期内即使密码正确也拒绝。锁定事件会在管理后台「操作日志」中留痕，方便排查是否被爆破。
- **收不到推送？** 先到网页「推送设置」确认状态为已绑定；飞书必须是私聊会话；Telegram 先给机器人发 `/start`
- **绑定了多个渠道只收到一部分？** 在「推送设置 → 推送通道选择」勾选想接收的渠道
- **雪球抓取失败？** 后台「数据源」更新雪球 Cookie。若接口直接返回 400（`error_code 400016`），是雪球升级了阿里云 WAF JS 挑战——先确认 `waf-bot` 容器在运行（`docker ps | grep waf-bot`）且 `data/waf_cookies.json` 文件在持续刷新（改时间戳为最近几分钟）；若接口校验失败（游客：公开时间线；登录：组合调仓接口报 `10022` 表示登录失效），`waf-bot` 不会覆盖旧 cookie 文件，主容器会继续使用上次验证成功的版本。若「组合」大V报 `10022`，说明雪球登录 Cookie 已失效，需重新登录；后台「数据源」更新 Cookie 会自动同步给 waf-bot，无需重建 sidecar。只有通过 `.env` 或 `config.yaml` 变更 Cookie 时才需要重启主服务使配置生效
- **X 抓不到？** 后台开启「X 内容自动翻译」，并在「数据源 → Cookie 管理」更新 Cookie（或设 `TWITTER_COOKIE`）。若报 `X GraphQL ... 403` 且响应体含 `Just a moment`，是 X 的 Cloudflare 挑战——直抓已内置 curl_cffi 指纹绕过（无需换 Cookie，通常是临时风控，等数小时自动解除）；若 403 是 code 89/353 则是 Cookie 失效或 X 接口规则变更

## License

MIT
