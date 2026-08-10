# 雪球 WAF 无 Chromium 求解器设计

## 背景

`feat/xueqiu-waf-pure-python` 原探索使用 jsdom 执行从挑战页提取的 `renderData` 和主脚本，但手工重建了精简 DOM。该签名请求返回 400，因而错误推断服务端将签名绑定到真实浏览器环境。

重新验证表明，挑战脚本会读取完整页面 DOM。将服务端返回的完整 HTML 原样交给同一版本的 jsdom 后，可以生成有效的 `md5__1038` URL，签名请求返回雪球首页，并下发 `xq_a_token`、`xqat`、`xq_id_token` 等会话 Cookie；同一 HTTP Session 随后请求项目实际使用的 `statuses/user_timeline.json` 返回 200 JSON。

因此本次工作的根因修复是保留完整挑战 HTML，不再依赖 Chromium 执行页面。

## 目标

- 用轻量 jsdom 求解器替换 waf-bot 中的 Playwright 和 Chromium。
- 保持主服务与 waf-bot 之间现有 `/data/waf_cookies.json` 协议不变。
- 保留 `WAF_SEED_COOKIE` 登录态注入能力。
- 只有经过真实雪球时间线 API 验证的 Cookie 才允许覆盖现有文件。
- 单次失败保留上一份有效 Cookie，并由 watchdog 下一周期重试。

## 非目标

- 本次不实现严格的 QuickJS 纯 Python 求解器。QuickJS 当前会触发挑战脚本的 `type__0` 反分析分支。
- 不实现通用多站点 WAF 框架。
- 不递归求解多层挑战。雪球首页当前一层完整 HTML 挑战即可建立有效会话。
- 不改变主服务的雪球抓取、组合抓取或 Cookie 文件读取逻辑。

## 方案选择

### 采用：Python watchdog + Node/jsdom

保留 Python 负责 HTTP 会话、Cookie jar、周期调度、错误处理和原子文件写入；新增一个只负责执行完整挑战 HTML 的 Node/jsdom 求解器。

该方案改动面最小，已通过在线雪球请求验证，并移除资源占用最大的 Chromium。

### 不采用：Node-only sidecar

Node-only 实现需要重新实现 Cookie jar、Seed Cookie、HTTP 指纹模拟和原子写文件，并引入更多依赖。它没有明显优于保留现有 Python watchdog。

### 不采用：QuickJS 严格纯 Python

QuickJS 已可执行完整脚本，但运行时能力检测仍产生无效 `type__0` 参数。继续逆向不属于本次可用替代方案的最短路径。

## 组件

### `waf-bot/solver.js`

职责单一：

1. 从 stdin 读取 JSON：完整 HTML、页面 URL、User-Agent。
2. 在加载 jsdom 前拦截其导航实现，捕获挑战脚本写入的目标 URL。
3. 使用 jsdom 29.1.1 执行完整 HTML，并使用直接依赖 whatwg-url 16.0.1 序列化导航 URL。
4. 最多等待 5 秒，随后输出 `{"signed_url": "..."}`。
5. 无签名、输入无效或执行异常时写 stderr 并非零退出；Python subprocess 总超时为 10 秒。

求解器不发网络请求、不保存 Cookie，也不了解项目配置。

### `waf-bot/watchdog.py`

职责：

1. 使用 `curl_cffi.Session` 和 Chrome impersonation 创建同一条浏览器指纹 HTTP 会话。
2. 将 `WAF_SEED_COOKIE` 逐项注入 `.xueqiu.com` Cookie jar。
3. 请求雪球首页。
4. 若响应包含 `renderData`，将完整 HTML 交给 `solver.js`，并在同一 Session 请求返回的签名 URL。
5. 若签名响应仍包含挑战页，判定本轮失败。
6. 请求公开用户 `1247347556` 的时间线探测接口，要求状态码 200、JSON 对象且包含 `statuses`。
7. 验证成功后，将 Session 中完整 Cookie 集合原子写入共享文件。

watchdog 继续按 `WAF_REFRESH_INTERVAL` 周期运行。

### Docker 镜像

- 保留 Python 3.12 slim 基础镜像和 watchdog 入口。
- 删除 Playwright 安装、Chromium 下载及浏览器系统依赖。
- 安装 Node.js 22、jsdom 29.1.1、whatwg-url 16.0.1 和 `curl_cffi` 0.16.0。
- 提交 npm lockfile，避免 jsdom 私有导航接口因浮动版本变化。

## 数据流

1. watchdog 创建 Session 并注入可选 Seed Cookie。
2. `GET https://xueqiu.com/`。
3. 未出现挑战：直接执行时间线探测。
4. 出现挑战：完整 HTML 经 stdin 传给 solver。
5. solver 返回绝对或相对签名 URL。
6. watchdog 使用 `urljoin` 归一化 URL，在原 Session 内携带 Referer 请求签名 URL。
7. 签名响应必须不再含 `renderData`。
8. watchdog 调用 `statuses/user_timeline.json` 探测。
9. 探测成功后原子覆盖 Cookie 文件。

## 错误处理

以下情况均判定本轮失败，并保留旧 Cookie 文件：

- 首页请求失败或超时。
- 挑战 HTML 缺失求解所需内容。
- Node 求解器超时、非零退出或未返回签名 URL。
- 签名响应仍是挑战页。
- 探测接口非 200、非 JSON、JSON 结构不含 `statuses`。
- Cookie jar 为空。
- 临时文件写入或原子替换失败。

日志不得输出 Cookie 值或完整签名 URL，只记录阶段、状态码和简短错误。

## 安全边界

- solver 容器不挂载 Docker socket、宿主目录或额外凭据，只挂载现有 `/data` 共享目录。
- Seed Cookie 只进入 Python HTTP Session，不传给 Node solver；solver 输入仅包含公开挑战 HTML、URL 和 UA。
- jsdom 页面脚本不启用 Node `require`、网络资源加载或文件访问能力。
- subprocess 使用固定可执行文件和参数数组，不经过 shell。
- 求解成功前不写共享 Cookie 文件。

## 测试策略

### Python 单元测试

- 完整 HTML 原样传给 solver 调用层，不只传 `renderData` 或脚本片段。
- 无挑战首页跳过 solver 并执行探测。
- 有效签名、有效探测后写出 Cookie 文件。
- solver 无签名、签名响应仍是挑战页时不覆盖旧文件。
- 探测非 200、非 JSON 或缺少 `statuses` 时不覆盖旧文件。
- Seed Cookie 正确进入 Session Cookie jar。

网络边界通过注入 Session/solver runner 测试；不在 CI 请求真实雪球。

### Node 求解器测试

使用合成 HTML，其中内联脚本执行 `location.href = '/signed?md5__1038=test'`。测试 solver 返回归一化前的捕获 URL，并验证完整 HTML 中的额外 DOM 内容可被脚本读取。

### 手工冒烟测试

构建 waf-bot 镜像后执行一次刷新，并验证：

1. 日志报告刷新成功。
2. Cookie 文件包含雪球会话 Cookie。
3. 主服务使用该文件请求公开时间线返回 200 JSON。
4. 镜像中不存在 Chromium/Playwright 浏览器文件。

## 兼容与迁移

- `WAF_COOKIE_FILE`、`WAF_REFRESH_INTERVAL`、`WAF_SEED_COOKIE` 环境变量保持不变。
- Cookie 文件继续使用 `{"fetched_at": ..., "cookies": [{"name": ..., "value": ...}]}`。
- 主服务无需迁移。
- 部署只需重建 waf-bot 镜像；旧有效 Cookie 在第一次新流程刷新成功前继续保留。
