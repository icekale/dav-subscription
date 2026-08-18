# 动态广场宽屏右侧栏 — 收尾计划

> 不居中整页。不新做推荐算法或热搜。不改手机时间线、不改 75ch。

**Goal:** 把已落地的宽屏右侧栏收成可提交的一档：搜索手感对齐 X 的「栏顶独立搜索」，布局决策写进 spec，窄屏行为不变。

**Architecture:** `isWideTimeline()`（≥1280px）+ `1fr / 300px` 网格。主列和右栏各用 64px 顶部槽位，搜索独立在栏顶；推荐仍走 `GET /api/recommendations?unsubscribed=1`，标签仍走 `dynamic_tags` + `tlPickTag`。

**Tech Stack:** FastAPI、`app/static/app.js` + `style.css`、pytest 静态测试。

---

## 已锁定（不做）

- 整页或三列居中（`DESIGN.md`：主列铺满，不靠缩小外壳换可读性）。
- 新推荐接口、热搜新闻、右侧再加一套发现体系。
- 时间线按分类筛选。
- 宽屏顶栏「筛选」大面板。
- 改 768px 底栏时间线、改正文 75ch。

## 已经落地

- 宽屏 `#tl-rail`：特别关注 / 次要大V、未订阅推荐（最多 4）、热门标签（最多 8）。
- 主列铺满到栏，两列顶边对齐；跨 1280px 重排开关，保证主列至少约 680px。
- 宽屏无「筛选」按钮；关键词在右侧；分类入口已删。
- 窄屏：开关和「筛选」仍在顶栏（搜索 + 标签，无分类）。
- 测试：`test_recommendations_unsubscribed_only`、`test_timeline_wide_rail_markup`、`test_timeline_rail_fills_main_and_survives_resize`。

---

### Task 1: 搜索独立在栏顶

现在搜索和特别关注塞在同一张卡里，栏显得挤，也不像 X 那种栏顶搜索。

**Files:**
- Modify: `app/static/app.js`（`renderTimeline` 里 `#tl-rail`）
- Modify: `app/static/style.css`（`.tl-rail-search` 单独一行，不要 `.tl-rail-card` 包一层）
- Test: `tests/test_frontend_interactions.py`

- [x] **Step 1: 失败测试**

`test_timeline_rail_fills_main_and_survives_resize` 追加：宽屏轨道里 `tlSearchBarHtml()` 在 `tl-rail-view` **之外**；CSS 有 `.tl-rail > .search-bar` 或等价选择器，且 `.tl-rail-view` 不再当搜索容器。

- [x] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_frontend_interactions.py::test_timeline_rail_fills_main_and_survives_resize -q`

- [x] **Step 3: 实现**

```html
<aside class="tl-rail">
  <div class="tl-rail-head">${tlSearchBarHtml()}</div>
  <div class="tl-rail-body">
    <div class="tl-rail-card tl-rail-view">${tlViewTogglesHtml()}</div>
    <div id="tl-rail-recs"></div>
    <div id="tl-rail-tags"></div>
  </div>
</aside>
```

搜索沿用现成 `.search-bar`（胶囊、focus 环）。仍 `#tl-q` + 回车 `tlApplyRailSearch`。不要做成即时 `oninput`（时间线是请求，不是首页本地滤）。

- [x] **Step 4: 缓存加一档**

`style.css`、`app.js`、`sw.js` 各 +1。

- [x] **Step 5: 跑相关测试**

Run: `.venv/bin/python -m pytest tests/test_frontend_interactions.py -q`

---

### Task 2: 把「不居中」写回 spec

**Files:**
- Modify: `docs/specs/2026-08-18-timeline-right-rail-design.md`

- [x] **Step 1:** 反目标补一句：不把时间线改成 X 式三列居中；空画布用右侧栏填，不用左右留白。
- [x] **Step 2:** 卡片顺序改成：栏顶搜索 → 特别关注 / 次要大V → 推荐关注 → 热门标签。

---

### Task 3: 核对窄屏 + 提交（等人说）

- [x] **Step 1:** 预览：≥1280px 搜索在栏顶；Feed 与右栏首卡同顶；&lt;1280px 无栏，顶栏仍有筛选 + 两个开关。
- [x] **Step 2:** `.venv/bin/python -m pytest tests/test_frontend_interactions.py tests/test_api.py::test_recommendations_unsubscribed_only -q`
- [ ] **Step 3:** 用户明确说提交后再 commit。不推、不上 VPS、不 bump `APP_VERSION`。

---

说「开始」就按 Task 1 → 2 → 3 做。不要顺手改订阅广场或其他页。
