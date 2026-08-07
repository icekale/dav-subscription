# Web 前端手机端用户体验优化 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让普通用户在手机浏览器上方便操作：底部标签栏导航 + 各用户页面移动端布局与触控优化。

**Architecture:** 纯前端改动（`app/static/` 的 index.html / app.js / style.css）。移动端（≤768px）隐藏侧边栏、显示固定底部标签栏（5 个用户标签 + 管理员「更多」）；复用现有 hash 路由；桌面端（>768px）行为完全不变。无后端改动。

**Tech Stack:** 原生 HTML/CSS/JS（无框架）。前端无自动化测试框架：验证用 `node --check`（JS 语法）＋ 浏览器响应式手工走查；GitHub CI 已有 `node --check app/static/app.js` 步骤。

**约定：** 项目根 `dav-subscription/`（当前本地仓库已是根目录布局、与 GitHub 同构）。前端改动无需 pytest。每个任务结束 `node --check` + 提交。执行应在 feature 分支上进行。

**Spec:** `docs/superpowers/specs/2026-08-06-mobile-web-ux-design.md`

---

## Task 1: 底部标签栏结构（index.html + app.js）

**Files:**
- Modify: `app/static/index.html`（`#app-view` 内新增 `.bottom-nav` 容器）
- Modify: `app/static/app.js`（新增 `renderBottomNav`、`renderMore`、路由接入、高亮逻辑）
- 验证：`node --check`

**背景：** 手机端用固定底部标签栏替代图标侧边栏。5 个用户标签 + 管理员「更多」。管理员「更多」页列出后台 9 个页面入口（现有 `NAV[1].items`）。

- [ ] **Step 1: `index.html` 加入底部栏容器**

`app/static/index.html` 中 `#app-view`（`<div id="app-view" class="app-view hidden">`）内，在 `.main-col` 的 `</div>`（`<main id="main" class="page-main"></main>` 之后的闭合）之后、`#app-view` 闭合前，插入：

```html
    <nav id="bottom-nav" class="bottom-nav"></nav>
```

即结构变为：

```html
    <div class="main-col">
      <header class="topbar">...</header>
      <main id="main" class="page-main"></main>
    </div>
    <nav id="bottom-nav" class="bottom-nav"></nav>
```

- [ ] **Step 2: `app.js` 新增移动端导航常量与 `renderBottomNav`**

`app/static/app.js` 在 `function renderSidebar(user) {...}` 结束（`checkUpdate();` 之后的 `}` 处）后，新增：

```js
const MOBILE_NAV = [
  { route: "home", icon: "◎", label: "广场" },
  { route: "combinations", icon: "◈", label: "组合" },
  { route: "mysubs", icon: "▤", label: "订阅" },
  { route: "timeline", icon: "☰", label: "动态" },
  { route: "settings", icon: "⚙", label: "设置" },
];

function renderBottomNav(user) {
  const tabs = [...MOBILE_NAV];
  if (user.is_admin) tabs.push({ route: "more", icon: "✚", label: "更多" });
  $("#bottom-nav").innerHTML = tabs.map((t) => `
    <button class="bnav-item" data-route="${t.route}" onclick="location.hash='#/${t.route}'">
      <span class="bnav-icon">${t.icon}</span>
      <span class="bnav-label">${t.label}</span>
    </button>`).join("");
}
```

- [ ] **Step 3: `app.js` 新增「更多」页 `renderMore`**

在 `renderBottomNav` 定义之后新增：

```js
async function renderMore() {
  if (!state.user.is_admin) { location.hash = "#/home"; return; }
  setPageTitle("更多");
  const adminGroup = NAV.find((g) => g.admin) || { items: [] };
  $("#main").innerHTML = `
    ${heroPanel("More", "更多", "管理后台入口。")}
    <section class="section-panel">
      <div class="more-grid">
        ${adminGroup.items.map((item) => `
          <button class="more-item" onclick="location.hash='#/${item.route}'">
            <span class="more-icon">${item.icon}</span>
            <span class="more-label">${escapeHtml(item.label)}</span>
          </button>`).join("")}
      </div>
    </section>`;
}
```

- [ ] **Step 4: 路由接入 + 底部栏渲染 + 高亮**

`app/static/app.js` 的 `async function router()` 中，找到以下代码段：

```js
  renderSidebar(state.user);
  renderTopbar(state.user);
  document.querySelectorAll(".nav-item").forEach((b) =>
    b.classList.toggle("active", b.dataset.route === page || b.dataset.route === `${page}/${param}`)
  );
```

替换为：

```js
  renderSidebar(state.user);
  renderTopbar(state.user);
  renderBottomNav(state.user);
  document.querySelectorAll(".nav-item").forEach((b) =>
    b.classList.toggle("active", b.dataset.route === page || b.dataset.route === `${page}/${param}`)
  );
  // 底部栏高亮：管理员进后台页时高亮「更多」
  const activeBottom = page === "admin" ? "more" : page;
  document.querySelectorAll(".bnav-item").forEach((b) =>
    b.classList.toggle("active", b.dataset.route === activeBottom)
  );
```

在 `router()` 的分发链中（`else if (page === "search") await renderSearch();` 之前）新增：

```js
    else if (page === "more") await renderMore();
```

- [ ] **Step 5: 语法校验 + 提交**

Run: `node --check app/static/app.js`
Expected: 无输出（语法 OK）。

```bash
git add app/static/index.html app/static/app.js
git commit -m "feat: 移动端底部标签栏与管理员「更多」页"
```

---

## Task 2: 移动端壳层 CSS（底部栏 + 隐藏侧边栏）

**Files:**
- Modify: `app/static/style.css`（末尾追加）
- 验证：浏览器响应式手工核对

**背景：** ≤768px 隐藏侧边栏、显示底部栏；底部栏固定 + 安全区；主内容底部留白避免被遮挡。

- [ ] **Step 1: 追加底部栏基础样式与移动端壳层规则**

在 `app/static/style.css` 文件末尾追加：

```css
/* ---------- 移动端底部标签栏 ---------- */
.bottom-nav {
  display: none;
  position: fixed;
  left: 0; right: 0; bottom: 0;
  z-index: 50;
  background: var(--color-surface-soft);
  backdrop-filter: blur(var(--blur-nav)) saturate(160%);
  border-top: var(--border-default);
  padding: 6px 4px calc(6px + env(safe-area-inset-bottom));
  justify-content: space-around;
}
.bnav-item {
  flex: 1;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 2px;
  border: none; background: transparent;
  color: var(--color-text-muted);
  font-size: 11px;
  min-height: 48px;
  border-radius: var(--radius-control);
}
.bnav-item .bnav-icon { font-size: 18px; line-height: 1; }
.bnav-item.active { color: var(--color-accent-strong); font-weight: var(--font-weight-semibold); }

/* 「更多」页网格 */
.more-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-top: 12px; }
.more-item {
  display: flex; align-items: center; gap: 10px;
  min-height: 52px;
  border: var(--border-strong); border-radius: var(--radius-control);
  background: var(--color-surface);
  color: var(--color-text);
  font-size: var(--text-md);
  padding: 0 14px;
}
.more-item .more-icon { font-size: 16px; width: 20px; text-align: center; }

/* ---------- 手机端（≤768px）壳层 ---------- */
@media (max-width: 768px) {
  .sidebar { display: none; }
  .bottom-nav { display: flex; }
  .main-col { min-height: 100vh; }
  .topbar { padding: 0 12px; }
  .page-main { padding: 16px 14px calc(74px + env(safe-area-inset-bottom)); }
}
```

- [ ] **Step 2: 手工核对**

开发者工具响应式模式：
- 375px：侧边栏消失、底部栏出现且 5 个标签（管理员 6 个）可点击、内容底部不被遮挡
- 1024px：底部栏消失、侧边栏恢复（此步可随 Task 6 一并走查）

```bash
git add app/static/style.css
git commit -m "feat: 移动端底部栏与壳层样式（隐藏侧边栏、安全区留白）"
```

---

## Task 3: 订阅广场手机布局（平台筛选 chips + KOL 卡片）

**Files:**
- Modify: `app/static/app.js`（`platformTabHTML` 加文字标签）
- Modify: `app/static/style.css`（`.pt-label` 隐藏规则 + 移动端 chips/卡片规则）
- 验证：`node --check` + 手工

**背景：** 平台筛选当前只显示图标；手机端改为带文字的可横滑 chips。KOL 卡片单列、订阅按钮通栏 ≥44px。

- [ ] **Step 1: `platformTabHTML` 增加文字标签**

`app/static/app.js` 的 `function platformTabHTML(p, current, handler)` 整体替换为：

```js
function platformTabHTML(p, current, handler) {
  const label = p ? PLATFORM_LABELS[p] : "全部";
  return `<button class="platform-tab ${p === current ? "selected" : ""}" data-platform="${p || "all"}"
    title="${label}" aria-label="${label}"
    onclick="${handler}('${p}')">${PLATFORM_ICONS[p || ""]}<span class="pt-label">${label}</span></button>`;
}
```

（`mysubs` 页 `renderMySubsTabs` 复用了 `platformTabHTML`，自动获得文字标签。）

- [ ] **Step 2: CSS——桌面隐藏 `.pt-label` + 移动端 chips/KOL 卡片**

`app/static/style.css` 在 `.platform-tab.selected .pt-icon` 规则（约 374 行）后新增：

```css
.pt-label { display: none; }
```

在 Task 2 追加的 `@media (max-width: 768px)` 块内（`}` 前）追加：

```css
  .platform-tabs { flex-wrap: nowrap; overflow-x: auto; -webkit-overflow-scrolling: touch; padding-bottom: 4px; }
  .platform-tab { width: auto; height: auto; min-height: 38px; padding: 0 14px; gap: 6px; border-radius: var(--radius-pill); }
  .platform-tab .pt-label { display: inline; font-size: var(--text-sm); }
  .kol-item { flex-wrap: wrap; }
  .kol-item .btn-sub { width: 100%; min-height: 44px; }
  .search-bar { height: var(--control-height-xl); }
```

- [ ] **Step 3: 校验 + 提交**

Run: `node --check app/static/app.js`
Expected: 无输出。

```bash
git add app/static/app.js app/static/style.css
git commit -m "feat: 平台筛选手机端带文字 chips，KOL 卡片单列订阅按钮通栏"
```

---

## Task 4: 我的订阅 / 动态 / 组合 手机布局

**Files:**
- Modify: `app/static/style.css`（移动端规则）
- 验证：手工走查

**背景：** 我的订阅/动态的切换、类型选择、收藏、链接等控件在手机上要 ≥44px、便于点按。

- [ ] **Step 1: 在 `@media (max-width: 768px)` 块内追加规则**

在 Task 3 追加内容之后的 `@media (max-width: 768px)` 块内追加：

```css
  .toolbar { flex-wrap: wrap; }
  .fav-toggle { min-height: 44px; }
  .sub-type-switches { gap: 8px; }
  .sub-type-switch { min-height: 44px; }
  .post-item { padding: 14px 4px; }
  .post-item a { min-height: 40px; display: inline-flex; align-items: center; }
  .btn-normal, .btn-ghost { min-height: 44px; }
  .btn-add { min-height: 44px; }
  .hero-panel { padding: 16px; }
```

- [ ] **Step 2: 手工走查**

- 我的订阅：顶部平台 chips 可横滑；每项类型切换（帖子/回复/帖子+回复）、⭐ 特别关注、取消订阅均可点
- 动态：帖子卡片正文与原文链接可点，不拥挤
- 组合订阅：卡片信息完整

```bash
git add app/static/style.css
git commit -m "feat: 我的订阅/动态/组合移动端触控优化"
```

---

## Task 5: 推送设置手机布局

**Files:**
- Modify: `app/static/style.css`（移动端规则）
- 验证：手工走查

**背景：** 推送设置的表单控件、绑定码按钮在手机上要醒目、易点。

- [ ] **Step 1: 在 `@media (max-width: 768px)` 块内追加规则**

在 Task 4 追加内容之后的 `@media (max-width: 768px)` 块内追加：

```css
  .form-control { min-height: 44px; }
  .section-panel .toolbar .btn-normal { min-height: 44px; }
```

- [ ] **Step 2: 手工走查**

- 推送设置各输入框/下拉 ≥44px；「生成绑定码」按钮通栏可点；渠道绑定/解绑按钮可点

```bash
git add app/static/style.css
git commit -m "feat: 推送设置移动端控件放大"
```

---

## Task 6: 收尾验收与部署

**Files:**
- 验证：全量语法检查 + 响应式走查清单
- 部署：推送 GitHub + 同步 unraid 重建

- [ ] **Step 1: 全量语法检查**

Run: `node --check app/static/app.js && node --check miniprogram/utils/api.js && node --check miniprogram/pages/settings/settings.js`
Expected: 无输出。

Run: `git diff --check`
Expected: 无输出。

- [ ] **Step 2: 响应式走查清单（375/390px + 桌面）**

在本地起服务（`uvicorn app.main:app` 或部署后 unraid）逐项核对：

1. 手机尺寸：侧边栏隐藏、底部栏出现，5 标签可切换且当前高亮；管理员见「更多」可进 9 个后台页并可返回；普通用户无「更多」
2. 平台 chips 可横滑、带文字、筛选生效（订阅广场 & 我的订阅）
3. KOL 卡片单列，订阅/取消按钮 ≥44px 可点
4. 我的订阅：分段切换、订阅类型、⭐、取消订阅可点
5. 动态：正文与原文链接可点
6. 推送设置：控件 ≥44px、绑定码按钮通栏
7. 模拟 iPhone 底部安全区不遮挡
8. 桌面宽度恢复侧边栏，现有功能不回归（含管理后台、搜索、大V详情）

- [ ] **Step 3: 合并与发布**

确认 `git status` 只有本次前 5 个任务涉及的 `app/static/*` 改动（未跟踪的 `docs/superpowers/plans/`、`uv.lock` 一律不提交）。然后：

```bash
git add app/static/index.html app/static/app.js app/static/style.css
git status --short            # 确认只暂存这三个文件
git commit -m "feat: Web 前端手机端用户体验优化"   # 若前序任务已各自提交，此步可跳过
git push origin main
```

- [ ] **Step 4: 同步 unraid 并重建 + 验证**

```bash
rsync -az --exclude='data/' --exclude='.env' --exclude='config.yaml' --exclude='.pytest_cache' --exclude='.ruff_cache' --exclude='__pycache__' --exclude='.venv' --exclude='.git' --exclude='backups/' --exclude='.DS_Store' \
  "$(pwd)/" root@192.168.5.28:/mnt/user/appdata/dav-subscription/
ssh root@192.168.5.28 "cd /mnt/user/appdata/dav-subscription && docker compose -f docker-compose.unraid.yml up -d --build dav-subscription"
ssh root@192.168.5.28 "curl -sS -m 8 http://127.0.0.1:18084/healthz; docker ps --format '{{.Names}} {{.Status}}' | grep dav-subscription"
```

Expected: `HTTP 200` + `dav-subscription Up ... (healthy)`。

然后手机浏览器打开 `http://192.168.5.28:18084` 强刷，按 Step 2 清单走查。

---

## 自审清单

- **Spec 覆盖**：导航（Task 1/2）、订阅广场（Task 3）、我的订阅/组合/动态（Task 4）、推送设置（Task 5）、验收与部署（Task 6）——设计文档第 1-4 节全部有对应任务。
- **占位符扫描**：全部步骤含精确代码；无 TBD/TODO。
- **类型/命名一致**：`renderBottomNav`/`renderMore`/`MOBILE_NAV`/`.bnav-item`/`.pt-label`/`.more-grid` 在各任务间一致；`platformTabHTML` 签名不变（复用方 `renderPlatformTabs`/`renderMySubsTabs` 不受影响）；`router()` 中 `activeBottom` 逻辑单一出处。
- **不做**：后台页重设计、深色模式、PWA、后端改动（见 spec「不做」）。
