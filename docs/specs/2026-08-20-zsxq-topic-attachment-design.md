# 知识星球 vpush 接入（主题正文 + 图片 + 附件）规格 v2

日期：2026-08-20
状态：已确认
前提：`2026-08-19-zsxq-multi-account-design.md`（账号/会员/路由/后台）已确认，本文只定
抓取、附件、推送与配置项。两文不冲突。

## 0. 原则

- 复用现有 `Fetcher → 去重 → 推送` 管线，不新建「星球管理」模块。
- 星球 = 私有数据源，`kols.platform=zsxq`、`external_id=group_id`。
- web API（`api.zsxq.com/v2`）用 Cookie，无 RSA、无证书钉扎、无签名 header。
- 采集相关的保守限制做成配置项且**默认放宽**，只保留两条硬线：1059 退避、权限白名单。

## 1. 抓取

每星球独立拉取（账号路由见多账号规格）：
- 列表：`GET /v2/groups/{group_id}/topics?scope=all&count=20`，`next_end_time` 分页。
- 新主题：有 `talk.article`（长文）或需完整正文时，补 `GET /v2/topics/{topic_id}` 详情。
- 图片：`collect_images` 已有，走现有推送卡。
- 附件：对本轮新主题解析 `collect_files`，对每个 `file_id` 调
  `GET /v2/files/{file_id}/download_url` 取下载 URL；URL 存 `post.detail["files"]`，格式：
  ```json
  [{"file_id": "...", "name": "a.pdf", "size": 123, "url": "https://..."}]
  ```
- 附件不落库永久保存；抓到当轮推走。缓存「已解析的 file_id → url」避免重复请求。

### 配置项（后台 + 环境变量，默认放宽）

| key | 默认 | 说明 |
|---|---|---|
| `zsxq_fetch_delay_seconds` | 1.0 | 请求间隔（非附件请求） |
| `zsxq_file_delay_seconds` | 1.0 | 附件 download_url 请求间隔 |
| `zsxq_max_pages` | 3 | 每周球单轮最大翻页 |
| `zsxq_backfill_days` | 0 | 新建/启用源时回填历史主题天数；0=不回填，默认增量 |
| `zsxq_allow_public` | 0 | 是否允许星球设为公开条目（默认私有） |

账号并发：沿用多账号规格「每账号并发 1，多账号并行」；附件请求在本账号内串行。

## 2. Post 结构

`platform="zsxq"`，`external_id=str(topic_id)`（用于去重），`kol_name=星球名`。
正文 = talk/question+answer 文本（`strip_html` 清洗，把 `<e type=.../>` 内嵌标签清除仅留可见文本）。
`detail` 保留原始映射 + `files` 列表。图片进 `post.images`。

## 3. 附件推送

- Telegram：内容「📎 文件名」+ 下载。URL 可 GET 且 ≤20MB → `sendDocument`；否则发链接文本。
  下载失败降级为发链接。
- 飞书 / 企业微信 / Bark：第一版发「📎 文件名 + 下载链接」文本，不做上传。
- RSS：附件附在主题内容下方并标注「(链接可能过期)」，不冒充永久。

## 4. 后端 / db

- `ALLOWED_PLATFORMS` 加 `"zsxq"`；`PLATFORM_LABELS` 加 `{"zsxq": "知识星球"}`。
- `zsxq_accounts`、`zsxq_memberships` 表按多账号规格建，Fetcher 依赖它选账号。
- Cookie 后台在现有 `_cookie_status` 侧新增「知识星球账号」列表（多账号规格已定，本文不重复）。

## 5. 调度集成

`build_fetchers` 注册 `ZsxqFetcher`。调度器对 `platform=zsxq` 的 kol：
- 普通星球按 `PollingConfig.interval_seconds` 档（可配）。
- 1059：冻结该账号（见多账号规格的退避），不影响其他账号/星球。
- 附件日限 20601 出现 → 该账号退避并告警，明日自动恢复。

## 6. 不做 / 硬线

- 不做评论抓取（保留扩展位）。
- 不做本地 PDF 持久化归档（只下载推送，临时缓存 GC）。
- 不伪造 RSA 签名、不绕证书钉扎（web 通道本不需要）。
- 1059 / 20601 / 登录失效：服务端强控，只能退避 + 告警，不硬顶。
- 只在白名单授权星球上拉取。

## 7. 测试

- 已有 `test_zsxq_inspect.py`（解析器）保留。
- 新增：
  - `ZsxqFetcher`：topic → Post（正文/图片/files detail）、详情补全（`tests/test_zsxq_fetcher.py`）
  - 附件 URL 解析与重复缓存
  - 1059 → 账号退避；20601 → 账号退避
  - `ALLOWED_PLATFORMS` / `build_fetchers` 注册
  - 去重 external_id=topic_id
  - 附件渲染（`tests/test_zsxq_attachments.py`）

## 8. 执行状态（2026-08-20）

已完成：
- `ZsxqFetcher`（`app/fetchers/zsxq.py`）：列表抓取、详情补全、图片、附件 download_url + 会话缓存、1059 异常带 code
- `build_fetchers` 注册 `zsxq`；`ALLOWED_PLATFORMS` / `PLATFORM_LABELS` 更新
- 附件渲染接入 Telegram / 飞书 / 企业微信 / Bark（📎 文件名 + 下载链接，标注「链接可能过期」）
- Cookie 后台：`GET/POST /admin/zsxq-cookie`（沿用 existing `_cookie_status` 模式，key `zsxq_cookie`）
- 测试：`test_zsxq_fetcher.py`(8) + `test_zsxq_attachments.py`(3) + 既有 inspect 测试全绿

后续（非本版阻塞）：
- Telegram 附件 sendDocument（≤20MB 下载后上传）；当前跨端统一发链接，避免新增下载/上传管线
- `zsxq_accounts` / `zsxq_memberships` 多账号表 + 路由（沿用 2026-08-19 规格，本轮 Fetcher 用单 Cookie）
- 评论抓取
- 后台前端「知识星球账号列表」UI（当前仅 API 就绪）
