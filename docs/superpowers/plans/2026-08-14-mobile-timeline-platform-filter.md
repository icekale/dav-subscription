# Mobile Timeline Platform Badge Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the heavy mobile timeline filter form with one row of five existing platform icon buttons that apply immediately, while leaving the desktop filter unchanged.

**Architecture:** Render one of two filter-panel bodies at `renderTimeline()` time using a shared `matchMedia("(max-width: 768px)")` helper. Mobile gets icon-only buttons backed by the existing `TL_PLATFORMS` and `PLATFORM_ICONS`; desktop keeps the existing keyword/select/action controls verbatim. Mobile opening clears hidden keyword/category/tag state, synchronizes visible active chips, and platform selection immediately reloads and closes the panel.

**Tech Stack:** Vanilla JavaScript template rendering, CSS Grid, existing design tokens/SVG icons, pytest static frontend regression tests, Chrome device emulation.

**Approved Spec:** `docs/superpowers/specs/2026-08-14-mobile-timeline-platform-filter-design.md`

---

## File Map

- Modify `app/static/app.js`: responsive panel rendering, mobile platform-button HTML, mobile state clearing, immediate platform selection, active-chip synchronization.
- Modify `app/static/style.css`: five-column icon grid, 44px touch targets, selected and platform-color states.
- Modify `tests/test_frontend_interactions.py`: static regression coverage for mobile-only markup, hidden-filter clearing, immediate close/apply behavior, desktop preservation, and CSS touch geometry.
- Modify `app/static/index.html`: increment `style.css` and `app.js` query versions so installed PWA clients request the changed assets.
- Modify `app/static/sw.js`: increment the shell cache name so old cached assets are removed on activation.

No new dependency, icon file, component abstraction, API endpoint, or backend change is required.

---

### Task 1: Lock the Mobile Interaction Contract With Failing Tests

**Files:**
- Modify: `tests/test_frontend_interactions.py`
- Test: `tests/test_frontend_interactions.py`

- [ ] **Step 1: Add the stylesheet path and mobile filter tests**

Add this constant below `APP_JS`:

```python
STYLE_CSS = APP_JS.with_name("style.css")
```

Append these tests after `test_post_tags_filter_timeline_without_inline_user_string`:

```python
def test_mobile_timeline_filter_renders_existing_platform_icons_only():
    """移动筛选只渲染现有平台图标；桌面完整表单仍保留。"""
    render = _fn_body("renderTimeline")
    mobile_html = _fn_body("tlMobilePlatformsHtml")

    assert "isMobileTimelineFilter()" in render
    assert 'id="tl-mobile-platforms"' in render
    assert "PLATFORM_ICONS[p]" in mobile_html
    assert 'aria-label="平台：${label}"' in mobile_html
    assert 'aria-pressed="${state.timelinePlatform === p}"' in mobile_html
    assert "tlPickMobilePlatform('${p}')" in mobile_html
    assert "<span>${label}</span>" not in mobile_html

    # desktop branch must remain feature-complete
    for marker in ('id="tl-q"', 'id="tl-platform"', 'id="tl-category"',
                   'id="tl-tag"', "tlApplyFilter()"):
        assert marker in render


def test_mobile_platform_filter_clears_hidden_state_and_applies_immediately():
    """移动端不允许不可见的关键词/分类/标签继续影响结果。"""
    clear_hidden = _fn_body("tlClearMobileHiddenFilters")
    pick_mobile = _fn_body("tlPickMobilePlatform")
    toggle_panel = _fn_body("tlFilterPanel")

    for assignment in (
        'state.timelineQ = ""',
        'state.timelineCategory = ""',
        'state.timelineTag = ""',
    ):
        assert assignment in clear_hidden
    assert "tlClearMobileHiddenFilters()" in toggle_panel
    assert "isMobileTimelineFilter()" in toggle_panel
    assert "state.timelinePlatform = p" in pick_mobile
    assert 'classList.remove("open")' in pick_mobile
    assert 'setAttribute("aria-expanded", "false")' in pick_mobile
    assert "tlSyncActiveChips()" in pick_mobile
    assert "loadTimeline(true, routeRenderSeq)" in pick_mobile


def test_mobile_platform_filter_is_five_equal_44px_targets():
    """390px 移动端必须容纳五个等宽、至少 44px 的平台角标。"""
    css = STYLE_CSS.read_text()
    grid = re.search(r"\.tl-mobile-platforms\s*\{([^}]*)\}", css, re.DOTALL)
    button = re.search(r"\.tl-mobile-platform\s*\{([^}]*)\}", css, re.DOTALL)
    assert grid and "repeat(5, minmax(0, 1fr))" in grid.group(1)
    assert button and ("height: 44px" in button.group(1) or "min-height: 44px" in button.group(1))
    assert "width: 100%" in button.group(1)
    assert ".tl-mobile-platform.selected" in css
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_frontend_interactions.py::test_mobile_timeline_filter_renders_existing_platform_icons_only \
  tests/test_frontend_interactions.py::test_mobile_platform_filter_clears_hidden_state_and_applies_immediately \
  tests/test_frontend_interactions.py::test_mobile_platform_filter_is_five_equal_44px_targets -q
```

Expected: all three fail because `tlMobilePlatformsHtml`, `tlPickMobilePlatform`, `tlClearMobileHiddenFilters`, and `.tl-mobile-platforms` do not exist yet.

Do not weaken assertions to make current code pass.

---

### Task 2: Implement the Mobile-Only Platform Panel

**Files:**
- Modify: `app/static/app.js:823-913`
- Modify: `app/static/app.js:1038-1088`
- Test: `tests/test_frontend_interactions.py`

- [ ] **Step 1: Add the viewport helper and mobile platform renderer**

Immediately after `TL_PLATFORMS`, add:

```javascript
function isMobileTimelineFilter() {
  return window.matchMedia("(max-width: 768px)").matches;
}

function tlMobilePlatformsHtml() {
  return TL_PLATFORMS.map(([p, label]) => `
    <button class="tl-mobile-platform ${state.timelinePlatform === p ? "selected" : ""}"
      data-platform="${p}"
      aria-label="平台：${label}"
      title="${label}"
      aria-pressed="${state.timelinePlatform === p}"
      onclick="tlPickMobilePlatform('${p}')">
      ${PLATFORM_ICONS[p] || ""}
    </button>`).join("");
}
```

Use the existing constant data only. Do not duplicate SVG markup or add visible text inside these buttons.

- [ ] **Step 2: Render mutually exclusive mobile and desktop panel bodies**

At the start of `renderTimeline(seq)`, after `setPageTitle("最新动态")`, add:

```javascript
const mobileFilter = isMobileTimelineFilter();
```

Replace the existing `tl-filter-panel` body with this conditional template. Keep the desktop markup byte-for-byte equivalent in behavior:

```javascript
<div class="tl-filter-panel" id="tl-filter-panel">
  ${mobileFilter ? `
    <div class="tl-mobile-platforms" id="tl-mobile-platforms">
      ${tlMobilePlatformsHtml()}
    </div>` : `
    <input id="tl-q" class="form-control" placeholder="搜索标题/内容关键词" value="${escapeHtml(state.timelineQ || "")}" onkeydown="if(event.key==='Enter')tlApplyFilter()">
    <div class="tl-filter-row">
      <select id="tl-platform" class="form-control" onchange="tlApplyFilter()">${tlPlatformOptions()}</select>
      <select id="tl-category" class="form-control" onchange="tlApplyFilter()"><option value="">全部分类</option></select>
      <select id="tl-tag" class="form-control" onchange="tlApplyFilter()"><option value="">全部标签</option></select>
    </div>
    <div class="tl-filter-actions">
      <button class="btn-ghost" onclick="tlResetFilters()">清除筛选</button>
      <button class="btn-normal" onclick="tlApplyFilter()">完成</button>
    </div>`}
</div>
```

Replace the active-chip insertion:

```javascript
${tlActiveChipsHtml()}
```

with a stable synchronization target:

```javascript
<div id="tl-active-chips-wrap">${tlActiveChipsHtml()}</div>
```

- [ ] **Step 3: Avoid unnecessary mobile category/tag requests**

In the `try` block near the end of `renderTimeline`, wrap category/tag loading in the already-computed `mobileFilter` branch:

```javascript
if (!mobileFilter) {
  await loadTimelineCategories().catch(() => { _tlCategories = []; });
  await loadTimelineTags().catch(() => { _tlTags = []; });
}
await loadTimeline(true, seq);
```

This is not a backend behavior change. It only removes API work for controls that are absent on mobile.

- [ ] **Step 4: Add focused state/UI synchronization helpers**

Place these functions immediately before `tlFilterPanel()`:

```javascript
function tlSyncActiveChips() {
  const wrap = $("#tl-active-chips-wrap");
  if (wrap) wrap.innerHTML = tlActiveChipsHtml();
}

function tlClearMobileHiddenFilters() {
  const changed = !!(state.timelineQ || state.timelineCategory || state.timelineTag);
  state.timelineQ = "";
  state.timelineCategory = "";
  state.timelineTag = "";
  return changed;
}

function tlPickMobilePlatform(p) {
  tlClearMobileHiddenFilters();
  state.timelinePlatform = p;
  const platforms = $("#tl-mobile-platforms");
  if (platforms) platforms.innerHTML = tlMobilePlatformsHtml();
  const bar = $("#tl-filterbar");
  if (bar) bar.classList.remove("open");
  const btn = $("#tl-filter-toggle");
  if (btn) {
    btn.classList.toggle("has-filter", !!p);
    btn.setAttribute("aria-expanded", "false");
  }
  tlSyncActiveChips();
  loadTimeline(true, routeRenderSeq);
}
```

Do not reuse `tlApplyFilter()` here: it dereferences desktop-only form controls and is intentionally unavailable in mobile markup.

- [ ] **Step 5: Make panel opening clear invisible conditions and avoid focusing an absent input**

Replace `tlFilterPanel()` with:

```javascript
function tlFilterPanel() {
  const bar = $("#tl-filterbar");
  if (!bar) return;
  const opening = !bar.classList.contains("open");
  const mobile = isMobileTimelineFilter();
  if (opening && mobile) {
    const hiddenChanged = tlClearMobileHiddenFilters();
    const platforms = $("#tl-mobile-platforms");
    if (platforms) platforms.innerHTML = tlMobilePlatformsHtml();
    const btn = $("#tl-filter-toggle");
    if (btn) btn.classList.toggle("has-filter", !!state.timelinePlatform);
    tlSyncActiveChips();
    if (hiddenChanged) loadTimeline(true, routeRenderSeq);
  }
  const open = bar.classList.toggle("open");
  const btn = $("#tl-filter-toggle");
  if (btn) btn.setAttribute("aria-expanded", String(open));
  if (open && !mobile) $("#tl-q")?.focus();
}
```

The optional focus is required because `#tl-q` does not exist in mobile markup.

- [ ] **Step 6: Run focused interaction tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_frontend_interactions.py -q
node --check app/static/app.js
```

Expected: all tests in `test_frontend_interactions.py` pass; Node exits 0.

Do not commit yet; Task 3 supplies the required CSS for the third new test.

---

### Task 3: Style the Five Existing Icons as Lightweight Badges

**Files:**
- Modify: `app/static/style.css:1191-1232`
- Test: `tests/test_frontend_interactions.py`

- [ ] **Step 1: Add the mobile icon grid inside the existing `@media (max-width: 768px)` block**

Place these rules after `.tl-pills { display: none; }`:

```css
  .tl-mobile-platforms {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 8px;
    width: 100%;
  }
  .tl-mobile-platform {
    width: 100%;
    min-width: 0;
    height: 44px;
    padding: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: var(--border-strong);
    border-radius: var(--radius-control);
    background: var(--color-surface);
    color: var(--color-text-muted);
  }
  .tl-mobile-platform .pt-icon { width: 20px; height: 20px; }
  .tl-mobile-platform[data-platform="xueqiu"]:not(.selected) { color: var(--color-brand-xueqiu); }
  .tl-mobile-platform[data-platform="combination"]:not(.selected) { color: var(--color-accent-text); }
  .tl-mobile-platform[data-platform="weibo"]:not(.selected) { color: var(--color-brand-weibo); }
  .tl-mobile-platform[data-platform="twitter"]:not(.selected) { color: var(--color-brand-twitter); }
  .tl-mobile-platform.selected {
    border-color: var(--color-accent);
    background: var(--color-accent);
    color: var(--color-white);
  }
  .tl-mobile-platform:focus-visible {
    outline: var(--outline-focus);
    outline-offset: 2px;
  }
```

Use a 12px control radius, not a circular/pill shape: five equal icon controls should read as one compact tool row, and the system may already render circular platform badges inside post metadata.

Do not add labels, shadows, gradients, or another container/card.

- [ ] **Step 2: Update the stale mobile comment**

Replace the comment on `.tl-pills { display: none; }` with:

```css
  .tl-pills { display: none; } /* 桌面平台胶囊隐藏；移动端平台角标在轻量筛选面板中按需展开 */
```

- [ ] **Step 3: Run focused tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_frontend_interactions.py -q
node --check app/static/app.js
git diff --check
```

Expected: all frontend interaction tests pass, Node exits 0, and `git diff --check` prints nothing.

- [ ] **Step 4: Commit the behavior and styling together**

```bash
git add app/static/app.js app/static/style.css tests/test_frontend_interactions.py
git commit -m "feat(web): 移动端筛选改为平台角标" -- \
  app/static/app.js app/static/style.css tests/test_frontend_interactions.py
```

Expected: one commit containing only these three files.

---

### Task 4: Bust the Installed PWA Shell Cache

**Files:**
- Modify: `app/static/index.html:27,123`
- Modify: `app/static/sw.js:2`
- Test: `tests/test_frontend_pwa.py`

- [ ] **Step 1: Increment static asset query versions**

In `app/static/index.html`, change:

```html
<link rel="stylesheet" href="/style.css?v=90">
<script src="/app.js?v=128"></script>
```

to:

```html
<link rel="stylesheet" href="/style.css?v=91">
<script src="/app.js?v=129"></script>
```

- [ ] **Step 2: Increment the Service Worker shell cache**

In `app/static/sw.js`, change:

```javascript
const CACHE = "dav-shell-v6";
```

to:

```javascript
const CACHE = "dav-shell-v7";
```

Do not alter the network-first strategy or API/feed exclusions.

- [ ] **Step 3: Run PWA regression tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_frontend_pwa.py -q
node --check app/static/sw.js
git diff --check
```

Expected: PWA tests pass, Node exits 0, and diff check is clean.

- [ ] **Step 4: Commit cache-busting changes**

```bash
git add app/static/index.html app/static/sw.js
git commit -m "chore(web): 刷新移动筛选静态缓存" -- \
  app/static/index.html app/static/sw.js
```

Do not change `APP_VERSION` in this implementation task. Version bump/tag/release is a separate user decision.

---

### Task 5: Full Verification and Responsive Acceptance

**Files:**
- Verify only; no production file should change.

- [ ] **Step 1: Run CI-equivalent checks**

```bash
.venv/bin/python -m pytest -q
node --check app/static/app.js
node --check miniprogram/utils/api.js
for f in miniprogram/pages/*/*.js; do node --check "$f" || exit 1; done
(cd waf-bot && npm ci --ignore-scripts && npm test)
git diff --check
```

Expected:
- pytest exits 0 with no failures;
- all Node syntax checks exit 0;
- WAF solver reports 5 passing tests;
- `git diff --check` prints nothing.

Warnings from FastAPI/Starlette on local Python 3.14 do not fail the run; record them as existing dependency warnings, not feature regressions.

- [ ] **Step 2: Verify exact 390px mobile geometry in Chrome device emulation**

Open the timeline at a 390×844 emulated viewport, click “筛选”, and run in DevTools Console:

```javascript
({
  viewport: document.documentElement.clientWidth,
  scrollWidth: document.documentElement.scrollWidth,
  panelOpen: document.querySelector("#tl-filterbar")?.classList.contains("open"),
  buttons: [...document.querySelectorAll(".tl-mobile-platform")].map((el) => {
    const r = el.getBoundingClientRect();
    return {
      label: el.getAttribute("aria-label"),
      width: Math.round(r.width),
      height: Math.round(r.height),
      right: Math.round(r.right),
      pressed: el.getAttribute("aria-pressed"),
    };
  }),
})
```

Expected:
- `viewport === 390` and `scrollWidth === 390`;
- `panelOpen === true`;
- exactly five buttons;
- every height is at least 44;
- every right edge is at most 376 (14px page inset);
- exactly one button has `pressed: "true"`.

- [ ] **Step 3: Verify immediate mobile behavior**

With mobile emulation still active:

1. Seed a non-platform filter using Console:
   ```javascript
   state.timelineQ = "测试";
   state.timelineCategory = "1";
   state.timelineTag = "宏观";
   ```
2. Close and reopen “筛选”.
3. Confirm:
   ```javascript
   [state.timelineQ, state.timelineCategory, state.timelineTag]
   ```
   Expected: `["", "", ""]`.
4. Click the Weibo icon.
5. Confirm:
   ```javascript
   ({
     platform: state.timelinePlatform,
     open: document.querySelector("#tl-filterbar").classList.contains("open"),
     pressed: document.querySelector('.tl-mobile-platform[data-platform="weibo"]')?.getAttribute("aria-pressed"),
   })
   ```
   Expected: `{ platform: "weibo", open: false, pressed: "true" }`.
6. Reopen and select “全部”. Expected: `state.timelinePlatform === ""`, panel closes, and the filter button loses `has-filter`.

- [ ] **Step 4: Verify desktop preservation at 1280px**

At a 1280×800 viewport, click “筛选” and confirm:

```javascript
({
  mobileButtons: document.querySelectorAll(".tl-mobile-platform").length,
  q: !!document.querySelector("#tl-q"),
  platform: !!document.querySelector("#tl-platform"),
  category: !!document.querySelector("#tl-category"),
  tag: !!document.querySelector("#tl-tag"),
  done: [...document.querySelectorAll("#tl-filter-panel button")].some((b) => b.textContent.trim() === "完成"),
})
```

Expected:

```javascript
{ mobileButtons: 0, q: true, platform: true, category: true, tag: true, done: true }
```

Apply one desktop keyword/category/tag combination and confirm the existing complete filter still reloads correctly.

- [ ] **Step 5: Review final repository state**

```bash
git status --short --branch
git log -4 --oneline --decorate
git diff HEAD~2..HEAD --stat
```

Expected:
- only pre-existing untracked `.impeccable/` and `DESIGN.md` may remain;
- two implementation commits follow the approved design-spec commit;
- no unrelated files are staged or modified.

Stop here for user review. Do not push, tag, publish, or deploy unless explicitly requested.
