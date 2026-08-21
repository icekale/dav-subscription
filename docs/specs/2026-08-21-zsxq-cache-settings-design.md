# 知识星球缓存 / 抓取设置（Web UI）

日期：2026-08-21
状态：已确认

## 放哪

管理后台 → 数据源 → 抓取设置，在「X 通道」旁加一组「知识星球」。
保存走现有 `PUT /api/admin/polling-config`，即时生效。不新开页，不进用户设置。

## 设什么

| 项 | settings key | 默认 | 范围 | 作用 |
|---|---|---|---|---|
| 单轮翻页 | `zsxq_max_pages` | 3 | 1–20 | 每星球每轮最多翻几页（每页 20 条） |
| 请求间隔 | `zsxq_fetch_delay_seconds` | 1.0 | 0.2–10 | 列表/详情请求间隔 |
| 附件间隔 | `zsxq_file_delay_seconds` | 1.0 | 0.2–10 | `download_url` 间隔 |
| 附件预缓存 | `zsxq_prefetch_files` | 关（`0`） | 开关 | 抓到新帖时把附件落到 `data/zsxq_files`；默认关，点开再下 |

未写入时 GET 返回与 Fetcher 相同的默认（含环境变量覆盖）。
预缓存只落盘，不改 `files[].url`（推送仍用签名 URL）。磁盘已有文件时抓取跳过 `download_url`。

## 缓存运维

`GET /api/stats` 增加 `zsxq_cache: {files, bytes}`（只统计 `zsxq_files`，不含图片）。
`POST /api/admin/zsxq-cache/purge`：删除当前帖子已不引用的附件文件，返回 `{deleted, files, bytes}`。
界面只读展示「附件缓存 xx / n 个文件」+「清理未引用」。无全清按钮。

## 不做

缓存总开关、TTL/容量/LRU、每星球单独一套、回填天数、公开条目、清理图片。
