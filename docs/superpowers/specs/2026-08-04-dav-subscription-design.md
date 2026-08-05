# 大V订阅自托管版（dav-subscription）设计文档

日期：2026-08-04
状态：已确认（用户已批准方案 B）

## 1. 背景与目标

用户解包了一个微信小程序「大V订阅」（appid `wx7e101c7ccf632b4a`），其核心功能是聚合订阅雪球、微博、股吧、推特等平台的财经大V动态，并实时推送到微信。但该小程序只是客户端，数据与会员权限均由其私有后端（`fusion-prod.vdingyue.online`）控制，无法通过改客户端实现"无限制"。

本项目目标：**自托管一个 Docker 服务，复刻核心价值——盯大V公开动态、新帖推送，无会员/次数/名额限制**，推送渠道为飞书和 Telegram，并提供 Web 管理界面。

数据源（用户已确认）：**雪球、微博、X（Twitter）**。

## 2. 范围

### 做
- 定时轮询雪球 / 微博 / X（RSS）的大V公开动态
- 新帖去重后推送飞书（群机器人 webhook）和 Telegram（Bot API）
- Web 管理界面：订阅管理（增删改/启停大V）、帖子列表、推送记录
- Docker 一键部署，SQLite 持久化

### 明确不做（首版）
- 不做会员/付费内容（私有后端内容拿不到）
- 不接 X 官方 API（需付费订阅），X 走 RSS 源
- 不做多用户/账号体系（单用户自托管）
- 不做小程序前端
- 不做微博/雪球的私信、评论互动

## 3. 总体架构

单容器 Python 服务，包含四部分：

```
docker-compose up -d
└── app (python:3.12-slim, 单容器)
    ├── scheduler   每 N 秒轮询各平台 → 新帖去重 → 推送
    ├── fetchers    雪球 / 微博 / X(RSS)
    ├── notifiers   飞书 webhook + Telegram bot
    ├── api         FastAPI: /api/kols /api/posts /api/push-logs /healthz
    └── web         静态页面 (无构建步骤的原生 HTML/JS)
        ├── 订阅管理  增删改大V、启停、按平台筛选
        ├── 帖子列表  浏览抓到的动态，点链接跳原文
        └── 推送记录  每次推送的状态和错误
```

单一进程内由 asyncio 任务同时承担轮询调度与 API 服务（FastAPI 本身是异步的）。SQLite 使用 WAL 模式，允许并发读写。

## 4. 数据模型（SQLite）

### kols（订阅的大V）
- `id` INTEGER PRIMARY KEY
- `platform` TEXT：`xueqiu` / `weibo` / `twitter`
- `name` TEXT：昵称
- `external_id` TEXT：雪球 user_id / 微博 uid / X 的 RSS 地址
- `enabled` INTEGER：是否启用（0/1）
- `created_at` TEXT

### posts（抓到的动态）
- `id` INTEGER PRIMARY KEY
- `platform` TEXT
- `kol_id` INTEGER（外键）
- `external_id` TEXT：平台侧帖子 ID
- `title` TEXT
- `content` TEXT：正文摘要
- `url` TEXT：原文链接
- `published_at` TEXT：发布时间
- `fetched_at` TEXT
- 唯一约束 `(platform, external_id)` 用于去重

### push_logs（推送记录）
- `id` INTEGER PRIMARY KEY
- `post_id` INTEGER（外键）
- `channel` TEXT：`feishu` / `telegram`
- `status` TEXT：`success` / `failed`
- `error` TEXT
- `created_at` TEXT

## 5. 配置

全局配置放 `config.yaml`（可用环境变量覆盖），KOL 通过网页增删，不进配置文件。

```yaml
notifiers:
  feishu:
    webhook_url: ""      # 飞书群自定义机器人 webhook
  telegram:
    bot_token: ""        # @BotFather 获取
    chat_id: ""          # 接收消息的会话 ID

sources:
  xueqiu:
    cookie: ""           # 可选；不配可抓但更易被限流
  weibo:
    cookie: ""           # 建议配置，微博接口需要登录态

polling:
  interval_seconds: 180  # 轮询间隔
  jitter_seconds: 30     # 随机抖动，避免固定节奏被限流
  notify_on_start: true  # 服务启动时向渠道发一条上线消息

web:
  password: ""           # 可选，Basic Auth 保护管理界面
```

## 6. 抓取器

每个抓取器实现统一接口：`fetch(kol) -> list[Post]`（只返回该大V最近一页动态，由调度器负责去重入库）。

### 雪球（xueqiu.py）
- 接口：`GET https://xueqiu.com/statuses/original/timeline.json?user_id={id}&page=1`
- cookie 可选（`xq_a_token`），带 cookie 成功率更高
- 解析字段：`id`、`title`、`description`、`target`（原文链接）、`timeBefore` / `created_at`

### 微博（weibo.py）
- 接口：`GET https://m.weibo.cn/api/container/getIndex?type=uid&value={uid}&containerid=107603{uid}`
- 需要登录 cookie（`SUB` 等）与 token，从配置读取
- 解析 cards 中的 `mblog`：`id`、`text`、`created_at`、分享链接

### X（rss.py）
- 每个大V的 `external_id` 为 RSS 地址（RSSHub 或 nitter）
- 使用 feedparser 解析：条目 `id`/`link`、`title`、`summary`、`published`

### 异常隔离
- 每个源独立 try/except，单个失败只记录日志，不影响其他源
- 失败按指数退避重试（如 30s/60s/120s，封顶 10 分钟），连续成功后退回正常间隔

## 7. 通知器

统一接口：`notify(post) -> None`，失败抛异常由调度器记录并重试一次。

### 飞书（feishu.py）
- `POST {webhook_url}`，交互式卡片：作者、平台、正文摘要、发布时间 + 「查看原文」按钮（`open_url`）

### Telegram（telegram.py）
- `POST https://api.telegram.org/bot{token}/sendMessage`
- HTML 格式：标题（带原文链接）、摘要、来源，`disable_web_page_preview` 视情况关闭

## 8. 调度与可靠性

- asyncio 循环，按 `interval_seconds ± jitter` 轮询所有启用的 KOL
- 启动时可选向两个渠道发「服务上线」消息（配置 `notify_on_start: true`）
- 推送失败记录到 `push_logs` 并重试一次，仍失败标记 `failed` 并保留错误
- `/healthz` 返回 200，供 Docker healthcheck

## 9. 安全

- `web.password` 非空时，管理 API 与静态页启用 Basic Auth
- README 建议仅内网部署；如需公网，置于反向代理后

## 10. Docker 部署

- `python:3.12-slim` 基础镜像，`requirements.txt` 安装依赖
- `docker-compose.yml`：`restart: unless-stopped`，挂载 `./data:/data`（SQLite），`TZ=Asia/Shanghai`，暴露 8000 端口
- healthcheck：`curl -f http://localhost:8000/healthz`

## 11. 测试

- 去重逻辑（同一帖子只入库一次）
- 消息格式化（飞书卡片 / Telegram HTML）
- 通知器（mock HTTP，成功/失败路径）
- 抓取器（使用录制样例 JSON，不依赖网络）
- 用 pytest 运行：`python -m pytest`

## 12. 目录结构

```
dav-subscription/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── config.example.yaml
├── .env.example
├── README.md
├── app/
│   ├── __init__.py
│   ├── main.py            # 入口：FastAPI + 调度器启动
│   ├── config.py          # 加载 YAML + 环境变量
│   ├── db.py              # SQLite 连接与建表
│   ├── scheduler.py       # 轮询循环、去重、推送、重试
│   ├── api.py             # REST API
│   ├── fetchers/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── xueqiu.py
│   │   ├── weibo.py
│   │   └── rss.py
│   ├── notifiers/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── feishu.py
│   │   └── telegram.py
│   └── static/
│       ├── index.html
│       ├── app.js
│       └── style.css
└── tests/
    ├── test_dedup.py
    ├── test_format.py
    ├── test_notifiers.py
    └── fixtures/
        ├── xueqiu_sample.json
        └── weibo_sample.json
```

## 13. 风险与注意事项

- 微博接口依赖登录 cookie，cookie 过期需手动更新（README 写获取方法）
- 雪球不配 cookie 可能被限流，建议配置
- X 依赖第三方 RSS 源（RSSHub/nitter），源不稳定时该平台会暂时抓不到；README 提供自建 RSSHub 选项
- 目标平台接口变动可能导致抓取失败，属正常维护事项
- 仅抓取公开动态，不涉及任何账号登录后的私有内容
