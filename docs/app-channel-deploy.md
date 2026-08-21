# 知识星球 App 通道（模拟安卓客户端）部署与配置

> 目的：以「知识星球 Android App 原生协议」的服务端复刻作为抓取通道，在 web 通道受限时兜底。
> 边界：仅本人账号、已授权星球；沿用 1059 随机反爬重试与延时；不绕过登录/付费/访问控制；账号级日限（13607）与通道无关，不做规避；低频抓取。

## 一、已落地组件（静态复原 + 服务端移植）

| 文件 | 内容 | 状态 |
|---|---|---|
| `app/fetchers/zsxq.py` | app 通道请求头（UA/X-Request-Id/X-Version/Cookie）、GET/下载走 `_api_headers` | 探针已实测通过 |
| `app/fetchers/zsxq_crypto.py` | G3 混合加密：AES-128-CBC/PKCS7（随机 key/iv）+ RSA/ECB/PKCS1Padding 包裹 AES key | 单测通过（登录/POST 用） |
| `app/fetchers/zsxq_ws.py` | G5 App WS 协议层：握手三头、`req_data` 信封、WSResp 解析分发、resp_id 去重、心跳 | 单测通过；`python -m app.fetchers.zsxq_ws --url … --group …` 可独立跑 |
| `scripts/zsxq_app_channel_smoke.py` | 真实账号冒烟：强制 App 通道拉一个星球，结果留档 `work/zsxq_app_smoke-*.json` | 操作者执行 |

## 二、配置项（后台设置 / 环境变量二选一）

| 键 | 环境变量 | 默认 | 说明 |
|---|---|---|---|
| `zsxq_cookie` | `ZSXQ_COOKIE` | 空 | `zsxq_access_token=…` 完整串，web 与 App 通道共用 |
| `zsxq_app_channel` | `ZSXQ_APP_CHANNEL` | `0` | `1` = 请求头切换为 xiaomiquan App 配方 |
| `zsxq_app_device` | `ZSXQ_APP_DEVICE` | `16 OnePlus_PJD110` | UA 设备串（空格压 `_`） |
| `zsxq_ws_enabled` | `ZSXQ_WS_ENABLED` | `0` | `1` = 启用 App 原生 WS 长连 |
| `zsxq_ws_address` | `ZSXQ_WS_ADDRESS` | 空 | ws:// 或 wss:// 地址（见第三节） |

后台：`/admin` 拉取设置页直接改；环境变量用于 docker-compose 部署（已透传）。

## 三、wsAddress 获取（当前唯一残余未知项）

wsAddress 由登录响应写入 App 内 `Session.getWsAddress()`，改 MMKV（加密）不可直接注入。可行获取：

1. **LSPosed 管理器 UI 正常启用钩子模块**（推荐，无需碰网络）：钩 `rb/a.k()` / `ws/d.j()` 打印 URL，作用域 `com.unnoo.quan`，用管理器面板启用（勿直接改 `modules_config.db` 绕过 UI——daemon 有 `no such table: configs` 的既有问题）。
2. **后续抓包**：登录态下抓 WS 握手（需解决 App OkHttp 不走系统代理的问题——透明重定向在 macOS 上无法解码 TLS，理论上需 Linux 透明代理主机）。
3. 手动从已抓取的任何 WS 地址填入配置。

未拿到前：WS 长连默认关闭，抓取仍走轮询 App 通道，不影响部署。

## 四、冒烟与部署

```bash
# 冒烟（服务器或本机，留档到 work/）
ZSXQ_COOKIE='zsxq_access_token=...' GROUP_ID=28888112822211 \
.venv/bin/python scripts/zsxq_app_channel_smoke.py

# 部署（docker-compose.prod.yml 已透传 ZSXQ_*）
export ZSXQ_COOKIE='...'
export ZSXQ_APP_CHANNEL=1
docker compose -f docker-compose.prod.yml up -d

# WS 长连本体自检
.venv/bin/python -m app.fetchers.zsxq_ws --url wss://... --group 28888112822211 --timeout 30
```

## 五、风险与限流边界（保持既有行为）

- 1059 随机反爬：沿用 fetcher 6 次重试 + 延时，不缩短。
- 13607/20601 附件额度/日限：账号级，App 通道同样受限（实测两通道同墙）；命中即抛错交调度退避，不重试硬刚。
- 单账号、本人星球、低频；不做批量并发。