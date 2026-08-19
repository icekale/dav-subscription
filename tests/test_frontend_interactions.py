"""前端交互静态回归测试：订阅卡片操作必须按当前路由刷新。

背景：kolCard 的「订阅」按钮在首页、我的订阅、组合订阅、搜索、KOL 详情
多个页面复用 toggleSubscribe()。曾出现成功后无条件调用首页专用的
renderHomeList()，在非首页会因找不到 #kol-list 抛异常并落入 catch 弹出
「操作失败」假错误。本测试静态固化两条约定：
  1. toggleSubscribe 成功后调用路由感知的 refreshKolsView()
  2. refreshKolsView 覆盖所有会出现订阅卡片的页面路由
"""
import re
from pathlib import Path

APP_JS = Path(__file__).parent.parent / "app" / "static" / "app.js"
STYLE_CSS = APP_JS.with_name("style.css")


def _fn_body(name: str) -> str:
    """提取指定函数（或变量=函数）的函数体。"""
    src = APP_JS.read_text()
    m = re.search(rf"async\s+function\s+{name}\b|function\s+{name}\b", src)
    assert m, f"未找到函数 {name}"
    start = src.index("{", m.end())
    depth, i = 1, start + 1
    while depth:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    return src[start:i]


def _media_block(css: str, query: str) -> str:
    idx = css.find(query)
    assert idx != -1, f"缺少 {query}"
    start = css.find("{", idx)
    depth, i = 1, start + 1
    while depth and i < len(css):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
        i += 1
    return css[start:i]


def test_toggle_subscribe_refreshes_by_route_not_home():
    """toggleSubscribe 成功后必须调用 refreshKolsView，不得无条件 renderHomeList。"""
    body = _fn_body("toggleSubscribe")
    assert "refreshKolsView()" in body, "toggleSubscribe 应通过 refreshKolsView 刷新当前路由"
    # 首页专用刷新不能出现在 toggleSubscribe 成功路径（无条件调用是跨页假错误的根因）
    assert "renderHomeList();" not in body.replace("refreshKolsView();", "")


def test_refresh_kols_view_covers_all_card_routes():
    """refreshKolsView 必须覆盖所有出现订阅卡片的页面。"""
    body = _fn_body("refreshKolsView")
    for route_call in (
        'startsWith("#/home")',
        'startsWith("#/combinations")',
        'startsWith("#/mysubs")',
        'startsWith("#/kol/")',
        'startsWith("#/search")',
    ):
        assert route_call in body, f"refreshKolsView 缺少 {route_call} 路由分支"
    assert "loadHomeKols" in body
    assert "renderCombinations" in body
    assert "renderMySubs" in body
    assert "renderKolPage" in body
    assert "doSearch" in body


def test_search_page_lists_only_unsubscribed_kols_without_query():
    """显示更多进入搜索页后立即列出未订阅大V，交互搜索也必须携带当前路由令牌。"""
    render = _fn_body("renderSearch")
    search = _fn_body("doSearch")

    assert "await doSearch(seq)" in render
    assert render.count("doSearch(routeRenderSeq)") == 2
    assert "if (!keyword) return" not in search
    assert "kols.filter((k) => !k.subscribed)" in search
    assert re.search(r"keyword\s*\?\s*available\.filter", search)
    assert "所有大V都已订阅" in search
    assert "没有匹配的未订阅大V" in search


def test_kol_detail_page_subscribes_via_toggle_subscribe():
    """KOL 详情页的订阅按钮必须复用 toggleSubscribe（从而获得路由感知刷新）。"""
    src = APP_JS.read_text()
    assert "toggleKolPageSubscribe" in src
    m = re.search(r"async function toggleKolPageSubscribe.*?\n}", src, re.DOTALL)
    assert m, "未找到 toggleKolPageSubscribe"
    assert "toggleSubscribe(" in m.group(0)


# ---- 异步路由竞态：旧路由的渲染不得覆盖新路由 ----

def test_router_emits_route_token():
    """router 每次路由切换必须递增 routeRenderSeq 并把 token 传给渲染函数。"""
    body = _fn_body("router")
    assert "const renderSeq = ++routeRenderSeq;" in body
    for call in ("renderHome(renderSeq)", "renderMySubs(renderSeq)", "renderCombinations(renderSeq)",
                 "renderTimeline(renderSeq)", "renderKolPage(Number(param), renderSeq)",
                 "renderSearch(renderSeq)", "renderSettings(renderSeq)"):
        assert call in body, f"router 未把 token 传给 {call}"
    # 错误状态也不能被过期路由写入
    assert "routeStillActive(renderSeq)" in body


def test_renderers_check_route_token_after_await():
    """各异步渲染函数在 await 之后、写 DOM 之前必须检查 routeStillActive。"""
    for name in ("renderHome", "renderMySubs", "renderCombinations", "renderTimeline", "renderKolPage", "renderSettings"):
        body = _fn_body(name)
        assert "routeStillActive(" in body, f"{name} 缺少路由令牌检查"
    # doSearch / loadHomeKols / loadTimeline / loadMyAsks 是局部刷新入口，同样要检查
    for name in ("doSearch", "loadHomeKols", "loadTimeline", "loadMyAsks"):
        body = _fn_body(name)
        assert "routeStillActive(" in body, f"{name} 缺少路由令牌检查"
    # renderHomeList 不得在没有 #kol-list 时解引用（旧响应落入非首页）
    assert 'if (!target) return' in _fn_body("renderHomeList")


def test_route_token_guard_checks_latest_seq():
    """routeStillActive 必须与全局 routeRenderSeq 比较，未传 token 视为过期（局部刷新必须带令牌）。"""
    src = APP_JS.read_text()
    m = re.search(r"function routeStillActive\(seq\)\s*\{[^}]*\}", src)
    assert m, "未找到 routeStillActive"
    assert "routeRenderSeq" in m.group(0)
    # 严格令牌：已删除「未传 token 视为活跃」的兼容分支
    assert "undefined" not in m.group(0)


def test_post_tags_filter_timeline_without_inline_user_string():
    """时间线帖子标签必须是可点击按钮：data-tag 传值 + tlPickTag 复用 state.timelineTag。

    约束：onclick 不得把标签文本插进 JS 字符串（XSS 注入面），必须走 this.dataset.tag。
    """
    post_card = _fn_body("postCard")
    pick_tag = _fn_body("tlPickTag")

    assert 'data-tag="${escapeHtml(t)}"' in post_card
    assert "tlPickTag(this.dataset.tag)" in post_card
    assert "state.timelineTag = tag" in pick_tag
    assert "loadTimeline(true, routeRenderSeq)" in pick_tag


def test_mobile_timeline_filter_keeps_pills_out_of_panel():
    """手机端平台条留在吸顶栏；筛选面板是搜索、视图开关和标签。"""
    render = _fn_body("renderTimeline")
    src = APP_JS.read_text()

    assert 'id="tl-pills"' in render
    assert "tlPillsHtml()" in render
    assert 'id="tl-mobile-platforms"' not in render
    assert "function tlMobilePlatformsHtml" not in src
    assert "function tlPickMobilePlatform" not in src
    assert "function tlPlatformOptions" not in src
    assert 'role="radiogroup"' in render
    actions = render.split("tl-actions")[1].split("tl-filter-panel")[0]
    assert "tlViewTogglesHtml" not in actions
    assert "tlViewTogglesHtml()" in render.split('id="tl-filter-panel"')[1]

    assert "tlSearchBarHtml()" in render
    assert 'id="tl-q"' in _fn_body("tlSearchBarHtml")
    assert 'id="tl-tag"' in render
    assert "tlApplyFilter()" in render
    assert 'id="tl-category"' not in render
    assert "tlApplyRailSearch" in src


def test_timeline_pills_always_show_short_labels():
    """平台条一律图标+短字，选中只换底色；全称留在 aria-label。"""
    pills = _fn_body("tlPillsHtml")
    src = APP_JS.read_text()
    css = STYLE_CSS.read_text()
    assert "tl-pill-icon" not in pills
    assert "iconOnly" not in pills
    assert "platformShortLabel(p)" in pills
    assert "PLATFORM_ICONS[p || \"\"]" in pills
    assert "<span>${short}</span>" in pills
    assert 'aria-label="${label}"' in pills
    assert 'title="${label}"' in pills
    assert 'role="radio"' in pills
    assert "aria-checked" in pills
    assert 'combination: "组合"' in src
    assert ".tl-pill-icon" not in css
    assert ".tl-pills { display: none" not in css
    assert "flex-wrap: wrap" in css
    assert 'data-platform="xueqiu"]' in css and "margin-inline-end" in css
    pill = re.search(r"\.tl-pill\s*\{([^}]*)\}", css)
    assert pill and "44px" in pill.group(1)
    assert ".tl-pill:focus-visible" in css


def test_timeline_filter_status_is_pills_only():
    """平台只由胶囊表达；筛选高亮和生效芯片只服务搜索/标签。"""
    chips = _fn_body("tlActiveChips")
    pick = _fn_body("tlPickPlatform")
    apply_f = _fn_body("tlApplyFilter")
    render = _fn_body("renderTimeline")
    assert 'key: "platform"' not in chips
    assert "平台：" not in chips
    assert "timelinePlatform || state.timelineTag" not in pick
    assert "timelinePlatform || state.timelineTag" not in apply_f
    assert "state.timelineQ || state.timelinePlatform || state.timelineTag" not in render
    assert "tlPanelFilterOn()" in pick or "state.timelineQ || state.timelineTag" in pick


def test_timeline_platform_switch_reverts_on_failure():
    """点平台先出骨架；失败退回上一选中，条上能重试。"""
    load = _fn_body("loadTimeline")
    pick = _fn_body("tlPickPlatform")
    assert "TL_SKELETON" in load
    assert "catch" in load
    assert "加载失败" in load
    assert "revertPlatform" in pick or "prev" in pick
    assert "aria-busy" in load or "aria-busy" in pick


def test_mobile_platform_filter_keeps_hidden_state_and_applies_immediately():
    """打开筛选或点平台不改关键词/标签；只有清除筛选才重置。"""
    src = APP_JS.read_text()
    pick = _fn_body("tlPickPlatform")
    toggle_panel = _fn_body("tlFilterPanel")
    reset = _fn_body("tlResetFilters")

    assert "function tlClearMobileHiddenFilters" not in src
    assert "tlClearMobileHiddenFilters" not in toggle_panel
    assert "isMobileTimelineFilter()" not in toggle_panel
    assert 'state.timelineQ = ""' not in pick
    assert 'state.timelineTag = ""' not in pick
    assert "state.timelinePlatform = p" in pick
    assert "loadTimeline(true, routeRenderSeq" in pick
    for assignment in (
        'state.timelineQ = ""',
        'state.timelineCategory = ""',
        'state.timelineTag = ""',
    ):
        assert assignment in reset


def test_mobile_platform_filter_is_five_equal_44px_targets():
    """旧图标宫格已删；时间线胶囊桌面带短字 44px。"""
    css = STYLE_CSS.read_text()
    assert ".tl-mobile-platform" not in css
    pill = re.search(r"\.tl-pill\s*\{([^}]*)\}", css)
    assert pill and "44px" in pill.group(1)


def test_timeline_polish_matches_chip_row_and_browser_surfaces():
    """筛选钮与胶囊同高；组合图标走雪球色；空态留空；选区/光标跟品牌走。"""
    css = STYLE_CSS.read_text()
    feed = _fn_body("renderTimelineFeed")
    pick = _fn_body("tlPickPlatform")
    remove = _fn_body("tlRemoveFilter")
    assert "::selection" in css
    assert "caret-color" in css
    bar = re.search(r"\.tl-filterbar \.fav-toggle\s*\{([^}]*)\}", css)
    assert bar and "44px" in bar.group(1)
    assert 'data-platform="combination"]:not(.selected) .pt-icon { color: var(--color-brand-xueqiu)' in css
    empty = re.search(r"^\.empty\s*>\s*div\s*\{([^}]*)\}", css, re.M)
    assert empty and "18px" in empty.group(1)
    assert "#tl-platform" not in pick
    assert "#tl-platform" not in remove
    assert "tl-feed-more" in feed
    assert "tl-feed-end" in feed
    assert 'style="margin-top:14px' not in feed


def test_mobile_mysubs_filter_renders_icon_badges_keeps_desktop_toolbar():
    """订阅页移动端：平台+特别关注全部变为一行角标；桌面保留文字胶囊+按钮。"""
    render = _fn_body("renderMySubs")
    tabs = _fn_body("renderMySubsTabs")
    mobile_html = _fn_body("mysubsMobileFiltersHtml")

    assert "isMobileTimelineFilter()" in render
    assert 'id="mysubs-tabs"' in render
    # 桌面分支必须保留完整工具栏
    assert 'id="mysubs-fav-toggle"' in render
    assert '"platform-tabs"' in render
    assert "platformShortLabel(p)" in mobile_html
    assert "switchMySubsPlatform('${p}')" in mobile_html
    assert "toggleMySubsFav()" in mobile_html
    assert "STAR_SVG" in mobile_html
    assert "特别关注" in mobile_html
    assert "<span>${short}</span>" in mobile_html
    # 星标点击后需重绘角标选中态
    assert "renderMySubsTabs()" in _fn_body("toggleMySubsFav")
    # 双分支渲染：移动角标 / 桌面文字胶囊
    assert "mysubsMobileFiltersHtml()" in tabs
    assert 'platformTabHTML(p, state.mysubsPlatform' in tabs


def test_platform_tabs_always_show_short_labels():
    """订阅广场/我的订阅桌面平台条与时间线同一套：图标+短字，组合不写全称。"""
    tab = _fn_body("platformTabHTML")
    src = APP_JS.read_text()
    css = STYLE_CSS.read_text()
    assert "platformShortLabel(p)" in tab
    assert 'class="pt-label">${short}</span>' in tab
    assert "function platformShortLabel" in src
    assert "display: none" not in re.search(r"\.pt-label\s*\{([^}]*)\}", css).group(1)
    base = re.search(r"\.platform-tab\s*\{([^}]*)\}", css)
    assert base and "36px" not in base.group(1)
    assert ".platform-tab:focus-visible" in css


def test_mobile_mysubs_filter_is_six_equal_44px_targets():
    """订阅/动态移动端：5 平台 + 星标/筛选共 6 等宽 44px 角标，文字仅 aria。"""
    css = STYLE_CSS.read_text()
    pill = re.search(r"\.tl-pill\s*\{([^}]*)\}", css)
    assert pill and "44px" in pill.group(1)
    assert "特别关注" in _fn_body("mysubsMobileFiltersHtml")
    assert 'aria-label="特别关注"' in _fn_body("mysubsMobileFiltersHtml")
    assert 'aria-label="筛选"' in _fn_body("renderTimeline")
    assert ".icon-badge-bar .tl-pill span" in css and "display: none" in css
    assert ".icon-badge-bar > .fav-toggle" in css and "font-size: 0" in css
    assert 'class="icon-badge-bar"' in _fn_body("renderHome")
    assert 'class="tl-filterbar-top icon-badge-bar"' in _fn_body("renderTimeline")
    # 不再把筛选条竖着堆成两行
    mobile = re.search(r"@media \(max-width: 768px\) \{(.*)\}\s*/\* ----------", css, re.DOTALL)
    body = mobile.group(1) if mobile else css
    assert ".tl-filterbar-top { flex-direction: column" not in body.replace(" ", "")
    av = re.search(r"\.tl-badge-avatars > \*\s*\{([^}]*)\}", css)
    assert av and "52px" in av.group(1)


# ---- 订阅广场移动端头部密度 ----

def test_mobile_home_filter_reuses_native_and_shared_controls():
    """广场移动端与订阅/动态同一行角标；搜索分类收进漏斗。"""
    render = _fn_body("renderHome")
    mobile_platforms = _fn_body("homeMobilePlatformsHtml")
    pick = _fn_body("homePickMobilePlatform")
    toggle = _fn_body("homeToggleFilter")

    for marker in ('class="icon-badge-bar"', 'id="home-filter-toggle"',
                   'id="home-search"', 'id="platform-tabs"', 'id="home-cats"',
                   'id="home-filter-panel"'):
        assert marker in render
    assert "<details" not in render
    assert "platformShortLabel(p)" in mobile_platforms
    assert "<span>${short}</span>" in mobile_platforms
    assert "homePickMobilePlatform('${p}')" in mobile_platforms
    assert "state.platform = platform" in pick
    assert "homeToggleFilter()" in render
    assert 'toggleAttribute("hidden"' in toggle
    assert "loadHomeKols(routeRenderSeq)" in pick
    assert "state.homeQ || state.homeCategory" in _fn_body("homeHasFilters")
    assert "state.platform" not in _fn_body("homeHasFilters")


# ---- 设置页保存按钮对齐 ----

def test_dnd_save_button_aligns_left_with_other_settings_buttons():
    """免打扰保存按钮必须左对齐（与关键词提醒等模块一致），不得右对齐错开。"""
    css = STYLE_CSS.read_text()
    actions = re.search(r"\.dnd-actions\s*\{([^}]*)\}", css)
    assert actions, "缺少 .dnd-actions 样式"
    assert "justify-content: flex-end" not in actions.group(1), (
        "免打扰保存按钮右对齐会与左侧表单项、下方模块错开"
    )
    settings = APP_JS.read_text()
    dnd_block = settings[settings.index('class="dnd-actions"'):]
    assert "saveDnd()" in dnd_block
    assert "dnd-result" not in dnd_block[:400], "保存反馈应走 toast，不要在按钮旁放结果 span"


def test_success_toast_uses_accent_not_green():
    """日常成功 toast 走克制蓝，不占成功绿。"""
    css = STYLE_CSS.read_text()
    block = re.search(r"\.toast\.success\s*\{([^}]*)\}", css)
    assert block, "未找到 .toast.success"
    assert "color-accent" in block.group(1)
    assert "color-success" not in block.group(1)


def test_submit_ask_requires_category():
    """申请表有分类框，提交必须带 category_id。"""
    body = _fn_body("submitAsk")
    assert "ask-category" in body
    assert "category_id" in body
    assert "请选择分类" in body
    render = _fn_body("renderSearch")
    assert "ask-category" in render


def test_settings_save_feedback_uses_flash():
    """推送设置保存/失败统一走 flash toast，不再用 alert 或行内「已保存 ✅」。"""
    src = APP_JS.read_text()
    start = src.index("// ---------- 推送设置 ----------")
    end = src.index("// ---------- 管理后台")
    settings = src[start:end]
    assert "已保存 ✅" not in settings
    assert "alert(" not in settings
    for span_id in ("dnd-result", "keywords-result", "push-channels-result", "llm-result", "custom-tg-result"):
        assert span_id not in settings
    for name in (
        "saveNotify", "saveDailyReport", "saveDnd", "saveKeywords",
        "savePushChannels", "saveLlm", "savePassword", "saveCustomTgBot",
        "saveWecomWebhook", "saveBarkKey",
    ):
        body = _fn_body(name)
        assert "flash(" in body, f"{name} 应使用 flash toast"
        assert "alert(" not in body, f"{name} 不应再用 alert"
    assert "flash(" in _fn_body("savePollingConfig")
    assert "alert(" not in _fn_body("savePollingConfig")
    assert "alert(" not in _fn_body("saveXueqiuCookie")
    assert "alert(" not in _fn_body("saveTwitterCookie")
    assert "flash(" in _fn_body("saveTwitterCookie")
    assert "flash(" in _fn_body("pasteCookieField")


def test_kol_image_settings_is_fourth_push_section_and_loads_independently():
    """动态图片卡片位于关键词后，并在设置页初始化完成后独立加载。"""
    body = _fn_body("renderSettings")
    push = body[body.index('id="st-push"'):body.index('id="st-bind"')]

    assert push.count('<section class="section-panel">') == 4
    assert push.index("关键词提醒") < push.index("动态图片")
    for copy in ("网页", "推送", "私有 RSS", "头像仍会显示", "仅影响当前账号"):
        assert copy in push
    assert 'id="kol-images-settings"' in push
    assert "正在加载已订阅大V" in push and 'class="muted' in push

    restore = body.rindex('switchSettingsTab(state.settingsTab || "push")')
    dnd = body.rindex("toggleDnd()")
    loader = body.rindex("loadKolImageSettings(seq);")
    assert restore < dnd < loader
    assert "await loadKolImageSettings" not in body


def test_kol_image_loader_is_route_guarded_local_and_retryable():
    """订阅加载失败只替换动态图片卡片，且可用当前路由令牌重试。"""
    load = _fn_body("loadKolImageSettings")
    render = _fn_body("renderKolImageSettings")

    assert 'api("/api/my/subscriptions")' in load
    assert load.count("routeStillActive(seq)") >= 2
    assert '$("#kol-images-settings")' in load
    assert '$("#main").innerHTML' not in load
    assert "加载失败:" in load
    assert "重试" in load
    assert "loadKolImageSettings(routeRenderSeq)" in load
    assert "正在加载已订阅大V" in load

    assert "emptyState(" in render
    assert "还没有订阅大V" in render
    assert "#/home" in render


def test_kol_image_loader_latest_generation_and_revision_win():
    """同路由并发 GET 只允许最新且未跨 mutation 的响应或错误落地。"""
    src = APP_JS.read_text()
    load = _fn_body("loadKolImageSettings")
    error = load[load.index("catch"):]

    for declaration in (
        "let _kolImageLoadGeneration = 0",
        "let _kolImageDataRevision = 0",
        "let _kolImageReloadNeeded = false",
    ):
        assert declaration in src
    assert "const loadGeneration = ++_kolImageLoadGeneration" in load
    assert "const loadRevision = _kolImageDataRevision" in load
    assert load.count("loadGeneration !== _kolImageLoadGeneration") >= 2
    assert load.count("loadRevision !== _kolImageDataRevision") >= 2
    assert load.count("_kolImagePendingIds.size") >= 2
    assert load.count("routeStillActive(seq)") >= 2
    assert load.index("loadGeneration !== _kolImageLoadGeneration") < load.index(
        "_kolImageSubscriptions = subscriptions"
    )
    assert load.index("loadRevision !== _kolImageDataRevision") < load.index(
        "_kolImageSubscriptions = subscriptions"
    )
    assert "_kolImageReloadNeeded = true" in load
    assert "reloadKolImageSettingsIfNeeded()" in load
    for guard in (
        "loadGeneration !== _kolImageLoadGeneration",
        "loadRevision !== _kolImageDataRevision",
        "_kolImagePendingIds.size",
        "routeStillActive(seq)",
    ):
        assert error.index(guard) < error.index("current.innerHTML")


def test_kol_image_rows_reuse_avatar_platform_and_accessible_switch():
    """紧凑行复用头像和开关，并以 !hide_images 映射可见状态。"""
    row = _fn_body("kolImageSettingsRowHtml")

    assert "kolCard" not in row
    assert "avatarHtml(kol.name, kol.avatar_url)" in row
    assert "escapeHtml(kol.name)" in row
    assert "PLATFORM_LABELS[kol.platform]" in row
    assert re.search(r"!\s*kol\.hide_images\s*\?\s*\"checked\"", row)
    assert 'class="switch kol-images-switch"' in row
    assert 'data-kol-id="${kol.id}"' in row
    assert 'aria-label="显示${escapeHtml(kol.name)}（${escapeHtml(platform)}）的动态图片"' in row
    assert "<span>显示</span>" in row
    assert 'onchange="toggleKolImages(${kol.id}, this)"' in row
    assert re.search(r"_kolImagePendingIds\.has\(kol\.id\)\s*\?\s*\"disabled\"", row)


def test_kol_image_search_threshold_fields_and_local_results():
    """十二个起显示搜索；过滤只重绘列表并覆盖名称、ID、平台。"""
    render = _fn_body("renderKolImageSettings")
    filter_body = _fn_body("filterKolImageSettings")

    assert re.search(r"_kolImageSubscriptions\.length\s*>=\s*12", render)
    assert 'placeholder="搜索已订阅大V"' in render
    assert 'oninput="filterKolImageSettings()"' in render
    assert 'id="kol-images-list"' in render
    assert 'role="region"' in render
    assert 'aria-label="已订阅大V的动态图片"' in render
    assert 'id="kol-images-more"' in render

    assert "kol.name" in filter_body
    assert "kol.external_id" in filter_body
    assert "PLATFORM_LABELS[kol.platform]" in filter_body
    assert ".toLowerCase()" in filter_body
    assert ".includes(query)" in filter_body
    assert "没有匹配的已订阅大V" in filter_body
    assert '$("#kol-images-list")' in filter_body
    assert '$("#kol-images-more")' in filter_body
    assert "filtered.length - 5" in filter_body
    assert "还有 ${" in filter_body
    assert "hidden" in filter_body
    assert '$("#kol-images-settings")' not in filter_body


def test_kol_image_toggle_is_inverse_guarded_and_rolls_back():
    """切换即时保存反向 hide_images，进行中禁用，失败回滚并走 toast。"""
    src = APP_JS.read_text()
    body = _fn_body("toggleKolImages")

    assert "const _kolImagePendingIds = new Set()" in src
    assert "if (!input || input.disabled || _kolImagePendingIds.has(kolId)) return" in body
    assert "const seq = routeRenderSeq" in body
    assert "input.disabled = true" in body
    assert "/api/subscriptions/${kolId}/hide-images" in body
    assert re.search(r'method:\s*"PUT"', body)
    assert "hide_images: !show" in body
    assert body.count("routeStillActive(seq)") >= 2
    assert "_kolImageSubscriptions.find" in body
    assert "const previousHideImages = kol.hide_images" in body
    assert "kol.hide_images = !show" in body
    assert body.index("kol.hide_images = !show") < body.index("await api")
    assert "kol.hide_images = previousHideImages" in body
    assert "input.checked = !previousHideImages" in body
    assert "mountedInput.disabled = false" in body
    assert "_kolImagePendingIds.delete(kolId)" in body
    assert body.index("_kolImagePendingIds.delete(kolId)") < body.rindex("routeStillActive(seq)")
    assert 'flash(`${show ? "已显示" : "已隐藏"}' in body
    assert 'flash("保存失败: " + err.message, "error")' in body
    assert "alert(" not in body


def test_kol_image_toggle_syncs_mounted_input_without_losing_keyboard_focus():
    """普通 toggle 收尾原地同步当前行；仅键盘焦点仍在可见行时恢复。"""
    body = _fn_body("toggleKolImages")
    cleanup = body[body.index("finally"):]

    focus_capture = (
        'const restoreFocus = document.activeElement === input '
        '&& input.matches(":focus-visible")'
    )
    assert focus_capture in body
    assert body.index(focus_capture) < body.index("input.disabled = true")
    assert 'document.querySelector(`#kol-images-list input[data-kol-id="${kolId}"]`)' in cleanup
    assert "mountedInput.checked = !kol.hide_images" in cleanup
    assert "mountedInput.disabled = false" in cleanup
    focus_guard = (
        "if (restoreFocus && (document.activeElement === input "
        "|| document.activeElement === document.body))"
    )
    assert focus_guard in cleanup
    assert "mountedInput.focus({ preventScroll: true })" in cleanup
    assert "mountedInput.focus()" not in cleanup
    assert "filterKolImageSettings()" not in cleanup


def test_kol_image_toggle_recovers_stale_route_after_returning_to_settings():
    """旧路由请求收尾时若已回到设置页，必须重拉服务端真值并解除新行禁用。"""
    body = _fn_body("toggleKolImages")
    reload_if_needed = _fn_body("reloadKolImageSettingsIfNeeded")
    cleanup = body[body.index("finally"):]

    assert "_kolImagePendingIds.delete(kolId)" in cleanup
    assert 'location.hash.replace(/^#\\/?/, "").split("?")[0] === "settings"' in cleanup
    assert "if (routeStillActive(seq))" in cleanup
    assert "_kolImageReloadNeeded = true" in cleanup
    assert "reloadKolImageSettingsIfNeeded()" in cleanup
    assert cleanup.index("_kolImagePendingIds.delete(kolId)") < cleanup.index(
        "reloadKolImageSettingsIfNeeded()"
    )
    assert "renderKolImageSettings()" not in cleanup
    assert "loadKolImageSettings(routeRenderSeq)" in reload_if_needed


def test_kol_image_same_route_pending_load_reloads_after_last_toggle():
    """pending 期间作废 GET；最后一个 toggle 收尾时重拉，普通路径只同步当前行。"""
    body = _fn_body("toggleKolImages")
    cleanup = body[body.index("finally"):]
    reload_if_needed = _fn_body("reloadKolImageSettingsIfNeeded")

    assert body.count("_kolImageDataRevision += 1") >= 2
    assert body.index("_kolImageDataRevision += 1") < body.index("await api")
    assert "_kolImagePendingIds.size === 0 && _kolImageReloadNeeded" in cleanup
    assert "reloadKolImageSettingsIfNeeded()" in cleanup
    assert "else if (routeStillActive(seq))" in cleanup
    assert "mountedInput.disabled = false" in cleanup
    assert "filterKolImageSettings()" not in cleanup
    assert "renderKolImageSettings()" not in cleanup

    assert "if (!_kolImageReloadNeeded || _kolImagePendingIds.size)" in reload_if_needed
    assert 'location.hash.replace(/^#\\/?/, "").split("?")[0] !== "settings"' in reload_if_needed
    assert "_kolImageReloadNeeded = false" in reload_if_needed
    assert "loadKolImageSettings(routeRenderSeq)" in reload_if_needed
    assert reload_if_needed.index("_kolImageReloadNeeded = false") < reload_if_needed.index(
        "loadKolImageSettings(routeRenderSeq)"
    )


def test_kol_image_css_is_compact_truncating_and_touchable():
    """动态图片行保持 36px 头像、长名省略、至少 44px 开关，且名单卡片内滚动。"""
    css = STYLE_CSS.read_text()
    container = re.search(r"#kol-images-settings\s*\{([^}]*)\}", css)
    row = re.search(r"\.kol-images-row\s*\{([^}]*)\}", css)
    avatar = re.search(r"\.kol-images-row \.kol-avatar\s*\{([^}]*)\}", css)
    info = re.search(r"\.kol-images-info\s*\{([^}]*)\}", css)
    name = re.search(r"\.kol-images-name\s*\{([^}]*)\}", css)
    switch = re.search(r"\.kol-images-switch\s*\{([^}]*)\}", css)
    empty = re.search(
        r"#kol-images-settings > \.empty,\s*\.kol-images-list > \.empty\s*\{([^}]*)\}",
        css,
    )
    empty_cta = re.search(
        r"#kol-images-settings > \.empty \.btn-add,\s*"
        r"\.kol-images-list > \.empty \.btn-add\s*\{([^}]*)\}",
        css,
    )

    assert ".switch {" in css
    assert container and "width: 100%" in container.group(1) and "max-width: 640px" in container.group(1)
    assert "border:" not in container.group(1) and "box-shadow:" not in container.group(1)
    assert row and "display: flex" in row.group(1) and "min-height: 44px" in row.group(1)
    assert avatar and "width: 36px" in avatar.group(1) and "height: 36px" in avatar.group(1)
    assert info and "min-width: 0" in info.group(1)
    assert name and "overflow: hidden" in name.group(1)
    assert "text-overflow: ellipsis" in name.group(1)
    assert "white-space: nowrap" in name.group(1)
    assert switch and "min-height: 44px" in switch.group(1)
    assert re.search(r"\.kol-images-switch input:disabled\s*~\s*span\s*\{[^}]*opacity:", css)
    assert empty and "padding: 24px" in empty.group(1)
    assert empty_cta and "margin-top: 12px" in empty_cta.group(1)
    list_rule = re.search(r"\.kol-images-list\s*\{([^}]*)\}", css)
    assert list_rule and "max-height: 260px" in list_rule.group(1)
    assert "overflow-y: auto" in list_rule.group(1)
    assert "overscroll-behavior: contain" in list_rule.group(1)
    assert "padding-right: 12px" in list_rule.group(1)
    more = re.search(r"#kol-images-more\s*\{([^}]*)\}", css)
    assert more and "margin-top: 8px" in more.group(1)


def test_stats_proxies_tab():
    src = APP_JS.read_text()
    assert 'data-tab="proxies"' in src
    assert "function loadProxyAdmin" in src
    assert 'STATS_TABS.includes(tab)' in _fn_body("statsTabFromHash")
    assert '"proxies"' in APP_JS.read_text()
    assert "loadProxyAdmin()" in _fn_body("switchStatsTab")
    assert "/api/admin/proxy-routes" in src
    assert "/api/admin/proxy-pools" in src


def test_stats_tabs_expose_tab_aria():
    """数据源分段导航与注册码页同一套 tab 语义。"""
    src = APP_JS.read_text()
    assert 'role="tab" id="tab-overview" aria-selected="true" aria-controls="st-overview"' in src
    assert 'aria-controls="st-proxies"' in src
    assert 'role="tabpanel" aria-labelledby="tab-proxies"' in src
    switch = _fn_body("switchStatsTab")
    assert 'setAttribute("aria-selected"' in switch


def test_proxy_admin_labels_and_mobile_table():
    """出口下拉各有标签；导入有可见 label；节点表走大V表的手机卡片约定。"""
    render = _fn_body("renderProxyAdmin")
    assert "代理池" in render
    assert "指定代理" in render
    assert "导入节点" in render
    assert "<th>操作</th>" in render
    assert 'class="ak-table proxy-nodes"' in render
    assert 'data-label="地址"' in render
    assert 'class="ak-actions"' in render
    assert 'class="btn-sm"' in render
    assert "ak-hide-mobile" in render
    assert 'class="ak-empty"' in render
    assert "还没有节点，先导入或提取。" in render
    css = STYLE_CSS.read_text()
    assert ".ak-table td::before" in css
    wide = _media_block(css, "@media (max-width: 1280px)")
    assert ".ak-table.proxy-nodes thead" in wide
    assert ".proxy-route" in wide


def test_proxy_admin_hardens_write_paths():
    """探测后回写列表、写操作防连点，空池不能存指定池，删节点要确认。"""
    test_fn = _fn_body("testProxyNode")
    assert "loadProxyAdmin()" in test_fn
    assert "btn.disabled" in test_fn
    save = _fn_body("saveProxyRoutes")
    assert "请先创建代理池" in save
    assert "请先导入或提取代理" in save
    delete_node = _fn_body("deleteProxyNode")
    assert "confirm(" in delete_node
    create = _fn_body("createProxyPool")
    assert "请填写代理池名称" in create
    load = _fn_body("loadProxyAdmin")
    assert "textarea[id^='pp-import-']" in load


def test_stats_cookie_repair_deep_link():
    """Cookie 失效要从总览一键进 Cookie 管理，并吃 #/admin/stats?tab=cookies。"""
    src = APP_JS.read_text()
    assert "function cookieRepairItems" in src
    assert "function cookieRepairBanner" in src
    assert "function statsTabFromHash" in src
    assert "#/admin/stats?tab=" in _fn_body("switchStatsTab")
    assert "statsTabFromHash()" in _fn_body("loadAdminStats")
    assert "saveTwitterCookie()" in _fn_body("loadAdminStats")
    assert "pasteCookieField('xq-cookie')" in _fn_body("loadAdminStats")
    banner = _fn_body("cookieRepairBanner")
    assert "switchStatsTab('cookies')" in banner
    assert "Cookie 需要更新" in banner
    repair = _fn_body("cookieRepairItems")
    assert "xueqiu_probe_alert_at" not in repair
    assert "src.xueqiu && !src.xueqiu.ok" in repair


def test_post_header_does_not_clip_platform_or_time():
    """卡片头「名字 · 平台 · 时间」同行时，名字省略不得裁掉平台图标和时间。

    回归：.p-name-line overflow:hidden + .p-name flex:1 会让短名也把
    后面的平台圆标和发布时间裁出可视区（VPS 手机端时间线「时间消失」）。
    """
    css = STYLE_CSS.read_text()
    name_line = re.search(r"\.post-item \.p-name-line\s*\{([^}]*)\}", css)
    name = re.search(r"\.post-item \.p-name\s*\{([^}]*)\}", css)
    time = re.search(r"\.post-item \.p-time\s*\{([^}]*)\}", css)
    platform = re.search(r"\.post-item \.p-name-line \.p-platform\s*\{([^}]*)\}", css)
    assert name_line, "缺少 .p-name-line 规则"
    assert name, "缺少 .p-name 规则"
    assert time, "缺少 .p-time 规则"
    assert platform, "缺少 .p-platform 规则"
    assert "overflow: hidden" not in name_line.group(1)
    assert re.search(r"flex:\s*1(?!\s*1\s*0)", name.group(1)) is None
    assert "flex-shrink: 0" in time.group(1)
    assert "flex-shrink: 0" in platform.group(1)

    post_card = _fn_body("postCard")
    assert 'class="p-time"' in post_card
    assert "fmtPublished(post.published_at)" in post_card
    assert 'class="p-platform"' in post_card


def test_mobile_post_name_aligns_with_platform_badge():
    """移动端名字与平台角标必须同一中线：不能只用 min-height 把名字撑高却让文字贴顶。"""
    css = STYLE_CSS.read_text()
    mobile = re.search(
        r"@media \(max-width: 768px\) \{.*?\.post-item a\.p-name\s*\{([^}]*)\}",
        css,
        re.DOTALL,
    )
    assert mobile, "缺少移动端 .post-item a.p-name 规则"
    body = mobile.group(1)
    assert "display: block" in body
    assert "line-height: 44px" in body
    assert "height: 44px" in body


def test_timeline_type_roles_follow_four_step_ramp():
    """时间线字号只走四档：头像字形 20、分组标签淡灰 400 + 等宽数字。"""
    css = STYLE_CSS.read_text()
    avatar = re.search(r"\.post-item \.p-header \.kol-avatar\s*\{([^}]*)\}", css)
    group = re.search(r"^\.tl-group-head\s*\{([^}]*)\}", css, re.M)
    badge = re.search(r"^\.tl-badge-avatars \.ph\s*\{([^}]*)\}", css, re.M)
    assert avatar, "缺少帖子头像字号"
    assert "var(--text-icon)" in avatar.group(1)
    assert group, "缺少日期分组标签"
    assert "var(--text-xs)" in group.group(1)
    assert "font-weight: 400" in group.group(1)
    assert "var(--color-text-faint)" in group.group(1)
    assert "tabular-nums" in group.group(1)
    assert badge, "缺少新帖胶囊头像字母"
    assert "var(--text-icon)" in badge.group(1)


def test_timeline_new_badge_pins_to_sticky_filterbar():
    """新帖胶囊挂在吸顶筛选条上，往下滚仍能点，不能跟着时间线一起滑走。"""
    render = _fn_body("renderTimeline")
    html = re.search(r'\$\("#main"\)\.innerHTML = `(.*?)`;', render, re.S)
    assert html, "renderTimeline 未写入主栏 HTML"
    chunk = html.group(1)
    feed = re.search(r'<section class="section-panel tl-feed-panel".*?</section>', chunk, re.S)
    assert feed, "缺少时间线面板"
    assert 'id="tl-new-badge"' not in feed.group(0)
    assert chunk.index('id="tl-filterbar"') < chunk.index('id="tl-new-badge"') < chunk.index('id="tl-feed-panel"')
    css = STYLE_CSS.read_text()
    bar = re.search(r"^\.tl-filterbar\s*\{([^}]*)\}", css, re.M)
    assert bar and "position: sticky" in bar.group(1)
    badge = re.search(r"^\.tl-new-badge\s*\{([^}]*)\}", css, re.M)
    assert badge, "缺少 .tl-new-badge"
    assert "position: absolute" in badge.group(1)
    assert "top: 100%" in badge.group(1)


def test_timeline_filterbar_stays_in_main_column():
    """筛选条只占主列，不横跨右侧栏留下空走廊；不居中、不收窄整页。"""
    render = _fn_body("renderTimeline")
    html = re.search(r'\$\("#main"\)\.innerHTML = `(.*?)`;', render, re.S)
    assert html, "renderTimeline 未写入主栏 HTML"
    chunk = html.group(1)
    assert chunk.index('class="tl-layout"') < chunk.index('id="tl-filterbar"')
    assert 'class="tl-main"' in chunk
    assert chunk.index('class="tl-main"') < chunk.index('id="tl-filterbar"') < chunk.index('id="tl-feed-panel"')
    assert chunk.index('id="tl-feed-panel"') < chunk.index('id="tl-rail"')
    css = STYLE_CSS.read_text()
    assert re.search(r"\.tl-main\s*\{[^}]*min-width:\s*0", css)
    assert "top: 128px" not in css
    assert ".tl-layout { margin: 0 auto" not in css.replace("\n", " ")
    wide = re.search(r"@media \(min-width:\s*1280px\)\s*\{([\s\S]*?)\n\}", css)
    assert wide, "缺少宽屏布局块"
    assert re.search(
        r"\.tl-filterbar\s*\{[^}]*height:\s*64px[^}]*display:\s*flex[^}]*align-items:\s*center",
        wide.group(1),
    )
    assert re.search(
        r"\.tl-rail-head\s*\{[^}]*height:\s*64px[^}]*display:\s*flex[^}]*align-items:\s*center",
        wide.group(1),
    )


def test_timeline_wide_rail_markup():
    """宽屏动态页有右侧栏：开关可搬家，推荐未订阅，标签走 tlPickTag。"""
    render = _fn_body("renderTimeline")
    assert "isWideTimeline()" in render
    assert 'id="tl-rail"' in render
    assert "loadTimelineRail" in render
    assert "tlViewTogglesHtml" in render
    assert "recommendations?unsubscribed=1" in _fn_body("loadTimelineRail")
    assert "railFailHtml" in _fn_body("loadTimelineRail")
    assert "重试" in _fn_body("railFailHtml")
    assert "tlPickTag" in _fn_body("renderRailTags")
    css = STYLE_CSS.read_text()
    assert ".tl-rail" in css
    assert "min-width: 1280px" in css or "min-width:1280px" in css
    assert "max-width: 1279px" in css or "max-width:1279px" in css


def test_timeline_rail_subscription_button_toggles_in_place():
    """推荐按钮用自身状态在 POST/DELETE 间切换，不确认、不刷新推荐列表。"""
    render = _fn_body("renderRailRecs")
    assert 'data-subscribed="0"' in render
    assert "railToggleSubscribe" in render
    assert "tl-rail-subscribe-state" in render
    assert "tl-rail-subscribe-action" in render

    toggle = _fn_body("railToggleSubscribe")
    assert 'method: "POST"' in toggle
    assert 'method: "DELETE"' in toggle
    assert "/api/subscriptions/${kolId}" in toggle
    assert "confirm(" not in toggle
    assert "btn.disabled = true" in toggle
    assert 'setAttribute("aria-busy", "true")' in toggle
    assert "btn.disabled = false" in toggle
    assert 'removeAttribute("aria-busy")' in toggle
    assert 'classList.toggle("subscribed", nextSubscribed)' in toggle
    assert "renderRailRecs(" not in toggle
    assert (
        'flash(`${subscribed ? "退订" : "订阅"}「${name}」失败: ${err.message}`, "error")'
        in toggle
    )


def test_timeline_rail_subscription_button_restores_keyboard_focus_safely():
    """原生 disabled 后仅在键盘焦点掉到 body 时恢复，不抢走用户的新焦点。"""
    toggle = _fn_body("railToggleSubscribe")
    focus_capture = (
        'const restoreFocus = document.activeElement === btn '
        '&& btn.matches(":focus-visible")'
    )
    assert "if (!btn || btn.disabled) return" in toggle
    assert focus_capture in toggle
    assert toggle.index(focus_capture) < toggle.index("btn.disabled = true")

    cleanup = toggle[toggle.index("finally"):]
    focus_guard = (
        "if (restoreFocus && btn.isConnected "
        "&& document.activeElement === document.body)"
    )
    assert "btn.disabled = false" in cleanup
    assert focus_guard in cleanup
    assert cleanup.index("btn.disabled = false") < cleanup.index(focus_guard)
    assert "btn.focus({ preventScroll: true })" in cleanup
    assert "btn.focus()" not in cleanup


def test_timeline_rail_subscription_button_has_quiet_fixed_states():
    """推荐按钮固定宽度；已订阅用现有淡蓝令牌，悬停和键盘聚焦显示退订。"""
    css = STYLE_CSS.read_text()
    rule = re.search(r"\.tl-rail-subscribe\s*\{([^}]*)\}", css)
    assert rule and "width: 72px" in rule.group(1)
    missing_label_layout = [
        declaration
        for declaration in ("padding: 0 6px", "white-space: nowrap")
        if declaration not in rule.group(1)
    ]
    assert not missing_label_layout
    subscribed = re.search(r"\.tl-rail-subscribe\.subscribed\s*\{([^}]*)\}", css)
    assert subscribed and "background: var(--color-accent-soft)" in subscribed.group(1)
    assert "color: var(--color-text-strong)" in subscribed.group(1)
    assert "color: var(--color-accent-text)" not in subscribed.group(1)
    assert ".tl-rail-subscribe.subscribed:hover .tl-rail-subscribe-action" in css
    assert ".tl-rail-subscribe.subscribed:focus-visible .tl-rail-subscribe-action" in css
    assert ".tl-rail-subscribe.subscribed:hover .tl-rail-subscribe-state" in css
    assert ".tl-rail-subscribe.subscribed:focus-visible .tl-rail-subscribe-state" in css
    state_swap = re.search(
        r"\.tl-rail-subscribe\.subscribed:hover \.tl-rail-subscribe-state,\s*"
        r"\.tl-rail-subscribe\.subscribed:focus-visible \.tl-rail-subscribe-state\s*\{([^}]*)\}",
        css,
    )
    action_swap = re.search(
        r"\.tl-rail-subscribe\.subscribed:hover \.tl-rail-subscribe-action,\s*"
        r"\.tl-rail-subscribe\.subscribed:focus-visible \.tl-rail-subscribe-action\s*\{([^}]*)\}",
        css,
    )
    assert state_swap and "display: none" in state_swap.group(1)
    assert action_swap and "display: inline" in action_swap.group(1)


def test_timeline_rail_fills_main_and_survives_resize():
    """主列铺满、右侧 300px；75ch 只限正文；跨 1280px 重排开关。"""
    css = STYLE_CSS.read_text()
    assert "minmax(680px, 1fr) 300px" in css
    assert ".tl-filterbar-top,\n  .tl-layout" not in css and ".tl-filterbar-top,.tl-layout" not in css.replace(" ", "")
    assert re.search(r"\.tl-layout \.tl-feed-panel\s*\{[^}]*flex:\s*1", css)
    render = _fn_body("renderTimeline")
    assert "tlSearchBarHtml()" in render
    assert "tlApplyRailSearch" in APP_JS.read_text()
    assert 'id="tl-category"' not in render
    rail = render[render.index('id="tl-rail"'):]
    assert rail.index("tlSearchBarHtml()") < rail.index("tl-rail-view")
    assert "${tlSearchBarHtml()}${tlViewTogglesHtml()}" not in render
    assert 'class="tl-rail-head"' in rail
    assert 'class="tl-rail-body"' in rail
    assert ".tl-rail-head > .tl-rail-search" in css
    assert re.search(r"\.tl-rail-body\s*\{[^}]*margin-top:\s*16px", css)
    assert re.search(
        r"\.tl-rail-view\s*\{[^}]*display:\s*grid[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)",
        css,
    )
    assert not re.search(r"\.tl-rail-search\s*\{[^}]*radius-card", css)
    assert re.search(r"\.tl-layout \.tl-feed-panel\s*\{[^}]*margin-top:\s*16px", css)
    assert re.search(r"@media \(min-width:\s*1280px\)[\s\S]*?\.tl-rail\s*\{[^}]*top:\s*56px", css)
    assert "calc(75ch + 2 * var(--section-padding-lg-x))" not in css
    assert ".post-item .p-content" in css and "max-width: 75ch" in css
    assert ".tl-rail-rec .btn-ghost" in css
    assert ".tl-rail-rec-meta" in css and "text-overflow: ellipsis" in css
    src = APP_JS.read_text()
    assert "ensureWideTimelineWatch" in src
    assert "ensureWideTimelineWatch()" in _fn_body("renderTimeline")
    watch = _fn_body("ensureWideTimelineWatch")
    assert "min-width: 1280px" in watch
    assert 'addEventListener("change"' in watch
    assert "renderTimeline(" in watch
    assert "tlSyncActiveChips()" in _fn_body("tlPickTag")
    assert "renderRailTags" in _fn_body("tlRemoveFilter")


def test_timeline_new_badge_shows_posted_not_count():
    """新帖胶囊跟 X：可见文案是「已发布」，不画 +N，条数只在 aria-label。"""
    src = APP_JS.read_text()
    render = _fn_body("renderTimeline")
    assert "已发布" in render
    assert 'id="tl-new-count"' not in src
    assert "tl-badge-more" not in _fn_body("tlBadgeAvatarsHtml")
    assert "条新动态，点击查看" in _fn_body("pollNewPosts")
    assert ".tl-badge-more" not in STYLE_CSS.read_text()


def test_push_channels_html_treats_personal_feishu_as_bound():
    """渠道勾选不能只看 users.feishu_*，否则个人机器人用户会看到「还没有绑定」。"""
    assert "feishu_personal" in _fn_body("feishuChannelBound")
    assert "feishuChannelBound(user)" in _fn_body("pushChannelsHtml")


def test_admin_backup_page_three_panels_download_skips_webdav():
    """备份页：侧栏入口、三块标题；本机下载不得走 WebDAV 上传。"""
    src = APP_JS.read_text()
    assert 'route: "admin/backup"' in src
    body = _fn_body("loadAdminBackup")
    assert "本机备份" in body
    assert "WebDAV 定时" in body
    assert "恢复" in body
    download = _fn_body("backupDownload")
    assert "/api/admin/backup/download" in download
    assert "/api/admin/backup/webdav" not in download
    assert "restore" not in download
    restore = _fn_body("backupRestoreWebDAV")
    assert "confirm(" in restore
    assert "/api/admin/backup/restore/webdav" in restore
    assert "cfg-unit" not in body
    assert "backup-grid" in body
    assert 'class="backup-file-input"' in body


def test_admin_users_page_uses_modal_not_prompt():
    """用户管理：搜索/筛选/管理面板，不再用 prompt/alert 改名、重置密码、测试推送。"""
    src = APP_JS.read_text()
    start = src.index("async function loadAdminUsers")
    end = src.index("// ---------- 主题")
    body = src[start:end]
    assert "prompt(" not in body
    assert "alert(" not in body
    assert "adminOpenUser" in body
    assert "renderAdminUsers" in body
    assert "adminUsersApplyFilter" in body
    assert "userChannelIconsHtml" in body
    open_user = _fn_body("adminOpenUser")
    assert "modal-mask" in open_user
    assert "um-name" in open_user
    assert "um-pass" in open_user
    assert "um-push-msg" in open_user
    for name in ("adminSaveUsername", "adminSavePassword", "adminSendTestPush", "adminDeleteUser", "adminToggleAdmin"):
        fn = _fn_body(name)
        assert "flash(" in fn, f"{name} 应使用 flash toast"
        assert "prompt(" not in fn
        assert "alert(" not in fn


def test_admin_users_page_has_batch_bar():
    """用户管理：勾选列 + 表上方批量条（开/关推送/删除）。"""
    render = _fn_body("renderAdminUsers")
    assert 'id="au-batch-bar"' in render
    assert 'id="au-checkall"' in render
    assert "au-check" in render
    assert "adminUserToggleSelect" in render
    assert "开启推送" in render
    assert "关闭推送" in render
    assert "adminUsersBatch(" in render
    assert "/api/admin/users/batch" in _fn_body("adminUsersBatch")
    src = APP_JS.read_text()
    assert "let _adminUsersSelected" in src
    delete_fn = _fn_body("adminUsersBatch")
    assert "confirm(" in delete_fn
    assert "enable_notify" in delete_fn
    assert "disable_notify" in delete_fn
    assert "delete" in delete_fn


def test_admin_users_page_has_inactive_policy():
    """用户管理：非活跃天数设置 + 筛选 Tab + 状态列文案。"""
    render = _fn_body("renderAdminUsers")
    assert "非活跃" in render
    assert 'id="au-inactive-n"' in render
    assert 'id="au-inactive-m"' in render
    assert 'id="au-inactive-save"' in render
    assert "rc-field" in render
    assert "rc-generate" in render
    assert "列为非活跃" in render
    assert "之后删除" in render
    assert "adminSaveInactivePolicy" in render
    assert "btn-normal" in render
    src = APP_JS.read_text()
    assert "adminSaveInactivePolicy" in src
    assert "adminInactivePolicySyncSave" in src
    assert "每天扫一次" in _fn_body("inactivePolicyHint")
    assert "/api/admin/inactive-users-policy" in _fn_body("adminSaveInactivePolicy")
    assert "/api/admin/inactive-users-policy" in _fn_body("loadAdminUsers")
    filt = _fn_body("adminUsersFiltered")
    assert "inactive" in filt
    assert "days_until_purge" in render
    assert "status-warn" in render


def test_admin_codes_page_has_batch_bar():
    """注册码：列表上方批量条 + 行勾选 + 批次标题全选 + 全选当前筛选。"""
    load = _fn_body("loadAdminCodes")
    assert 'id="rc-batch-bar"' in load
    assert "复制" in load
    assert "作废未用" in load
    assert "清掉废码" in load
    assert 'id="rc-checkall"' in load
    assert "adminCodesTogglePage" in load
    assert "全选当前筛选" in load
    groups = _fn_body("renderCodeGroups")
    assert "rc-batch-check" in groups
    assert "adminCodesToggleBatch" in groups
    row = _fn_body("renderCodeRow")
    assert "rc-check" in row
    assert "adminCodesToggle(this)" in row
    assert "adminCodesBatch" in APP_JS.read_text()
    batch = _fn_body("adminCodesBatch")
    assert "/api/admin/register-codes/batch" in batch
    assert "confirm(" in batch
    assert "copyText(" in _fn_body("adminCodesCopySelected")
    src = APP_JS.read_text()
    assert "adminCodesTogglePage" in src
    assert "adminCodesSyncPageCheck" in src
    assert "adminSaveCodeNote" not in src
    css = STYLE_CSS.read_text()
    assert ".admin-batch-bar" in css
    assert ".rc-check" in css
    assert ".rc-checkall" in css


def test_register_codes_mobile_has_field_labels_and_compact_grid():
    """注册码页移动端：每格带 data-label 字段名、备注独占整行、批次操作两列等宽。"""
    row = _fn_body("renderCodeRow")
    batch = _fn_body("renderCodeGroups")
    css = STYLE_CSS.read_text()

    for label in ("邀请码", "备注", "状态", "使用者", "时间", "操作"):
        assert f'data-label="{label}"' in row
    assert "rc-note-cell" in row
    assert "rc-note-input" not in row
    assert "adminSaveCodeNote" not in row
    assert "rc-counts" in batch  # 可用/已用独立元素，不再混在长行里断行
    assert ".rc-table td::before" in css
    assert 'content: attr(data-label)' in css
    assert "rc-note-cell" in css
    assert "grid-column: 1 / -1" in css
    assert "repeat(2, minmax(0, 1fr))" in css  # 批次操作与表格均为两列等宽网格
    assert ".settings-tabs" in css and "flex-wrap: nowrap" in css  # 筛选一行横向滚动
    hide = re.search(r"([^{}]+)\{[^}]*scrollbar-width:\s*none", css)
    assert hide and ".settings-tabs" in hide.group(1)  # 横向滑动时隐藏滚动条，避免移动端滑动框


def test_register_codes_desktop_controls_share_one_grid():
    """注册码页桌面：生成栏用标签网格对齐，搜索不再套一层 form-control。"""
    body = _fn_body("loadAdminCodes")
    css = STYLE_CSS.read_text()
    assert 'class="rc-generate"' in body
    assert "rc-field-note" in body
    assert "rc-preset" in body
    assert "常用" in body
    assert "cat-chip" not in body
    assert 'class="form-control"' not in body.split('id="rc-q"')[1][:80]
    assert "rc-list-head" in body
    assert "search-bar rc-search" in body
    assert "max-width: 860px" in css
    assert ".rc-preset" in css
    assert "height: var(--control-height-2xl)" in css
    groups = _fn_body("renderCodeGroups")
    assert "rc-batch-title" in groups
    assert "rc-batch-meta" in groups


def test_logout_clears_timeline_and_bind_cache():
    """登出必须清掉动态缓存和绑定码，避免下一账号看到上一账号的数据。"""
    body = _fn_body("logout")
    assert "clearSessionCaches()" in body
    clear = _fn_body("clearSessionCaches")
    assert "_tlPosts.length = 0" in clear
    assert "_tlLoadedFilter = null" in clear
    assert "pendingBind = null" in clear
    assert "state.timelineFavorite = false" in clear
    assert "state.timelineSecondary = false" in clear


def test_sticky_chrome_is_opaque_canvas_not_glass():
    """壳层（顶栏/筛选条/侧栏/底栏）用不透明画布色，禁止半透明+saturate 放大色块。"""
    tokens = (APP_JS.parent / "vendor" / "design-tokens.css").read_text()
    css = STYLE_CSS.read_text()
    assert "rgba(15, 17, 21, 0.82)" not in tokens
    assert "rgba(245, 245, 247, 0.78)" not in tokens
    body = re.search(r"^body\s*\{([^}]*)\}", css, re.M)
    assert body and "gradient-page-admin-wide" not in body.group(1)
    topbar = re.search(r"^\.topbar\s*\{([^}]*)\}", css, re.M)
    assert topbar and "backdrop-filter" not in topbar.group(1)
    assert "background: var(--color-bg)" in topbar.group(1)
    bar = re.search(r"^\.tl-filterbar\s*\{([^}]*)\}", css, re.M)
    assert bar and "backdrop-filter" not in bar.group(1)
    assert "calc(-1 * var(--page-pad-x))" in bar.group(1)
    assert css.count("--page-pad-x:") >= 3
    sidebar = re.search(r"^\.sidebar\s*\{([^}]*)\}", css, re.M)
    assert sidebar and "backdrop-filter" not in sidebar.group(1)
    assert "background: var(--color-bg)" in sidebar.group(1)
    bottom = re.search(r"^\.bottom-nav\s*\{([^}]*)\}", css, re.M)
    assert bottom and "backdrop-filter" not in bottom.group(1)
    assert "background: var(--color-bg)" in bottom.group(1)
    assert "backdrop-filter" not in css


def test_admin_kols_keeps_selection_against_filter_ids():
    """跨页勾选按筛选全集清理，不得按当前页 id 丢掉选中项。"""
    body = _fn_body("loadAdminKols")
    assert "state.adminKols = kols" in body
    assert "data.ids" in body
    assert "pageIds.has(id)" not in body


def test_admin_kols_add_keeps_filters_and_marks_row():
    """添加/导入不得改写筛选；新行在当前筛选里就标出，否则说明看不到。"""
    add = _fn_body("adminAddKol")
    batch = _fn_body("adminBatchAddKols")
    load = _fn_body("loadAdminKols")
    for body in (add, batch):
        assert "state.adminKolsPlatform" not in body
        assert "state.adminKolsCategory" not in body
        assert "goToLast" not in body
        assert "focusIds" in body
        assert "不在当前筛选" in body
    assert "focusIds" in load
    assert "ak-row-flash" in load


def test_admin_kols_mobile_table_uses_data_labels():
    """窄屏表用 data-label 卡片，桌面仍是表。"""
    body = _fn_body("loadAdminKols")
    assert "ak-table" in body
    assert 'data-label="昵称"' in body
    assert 'data-label="档位"' in body
    assert 'data-label="操作"' in body
    assert "ak-hide-mobile" in body
    css = STYLE_CSS.read_text()
    assert ".ak-table" in css
    assert "ak-hide-mobile" in css
    assert "ak-actions" in css


def test_admin_kols_edit_modal_is_dialog():
    """编辑弹层对齐用户管理：dialog + 焦点循环；白名单仅私有时出现。"""
    body = _fn_body("adminEditKol")
    assert 'role="dialog"' in body
    assert "aria-modal" in body
    assert "aria-labelledby" in body
    assert 'e.key === "Tab"' in body or 'e.key==="Tab"' in body
    assert "ek-users-wrap" in body
    assert "hidden" in body


def test_admin_kols_batch_normal_is_one_request():
    """设普通走一次 batch action=normal，不再连续打两次 flag。"""
    load = _fn_body("loadAdminKols")
    assert "adminKolBatch('normal')" in load
    src = APP_JS.read_text()
    assert "async function adminKolBatchTier" not in src


def test_admin_kols_platform_tab_reads_pending_search():
    """点平台 tab 时要把未提交的搜索框读进 state，避免筛丢。"""
    body = _fn_body("switchAdminKolsPlatform")
    assert "ak-q" in body


def test_admin_kols_filter_controls_match_input_height():
    """列表筛选与平台 tab 跟输入同高 42px，不得用 32px 药丸贴在 42px 框旁边。"""
    body = _fn_body("loadAdminKols")
    chunk = body.split('id="ak-q"')[1].split("admin-kols-tabs")[0]
    assert "btn-ghost" in chunk
    assert 'class="btn-sm"' not in chunk
    assert "ak-filters" in body
    assert "ak-platform-tabs" in body
    css = STYLE_CSS.read_text()
    assert re.search(r"\.toolbar \.btn-ghost[^{]*\{[^}]*--control-height-2xl", css)
    assert re.search(r"\.platform-tab\s*\{[^}]*44px", css, re.S)


def test_admin_kols_mobile_filters_and_actions_align():
    """窄屏：筛选两列网格；操作钮等宽，奇数个时最后一个铺满，避免删除孤一块。"""
    body = _fn_body("loadAdminKols")
    assert "ak-search-btn" in body
    assert "ak-clear-btn" in body
    css = STYLE_CSS.read_text()
    assert ".ak-filters #ak-q" in css
    assert "last-child:nth-child(odd)" in css
    assert ".ak-table td.ak-actions .btn-sm" in css
    assert "margin-right: 0" in css


def test_admin_kols_add_fields_have_accessible_names():
    """添加区控件要有可达名称，不能只靠 placeholder。"""
    body = _fn_body("loadAdminKols")
    assert 'aria-label="平台"' in body
    assert 'aria-label="昵称"' in body
    assert "aria-label=" in body and "外部ID" in body


def test_admin_kols_import_result_preserves_lines():
    """导入失败明细按行展示，不能塞进 inline span 把换行挤掉。"""
    body = _fn_body("loadAdminKols")
    assert '<span id="ad-batch-result"' not in body
    assert "ad-batch-result" in body
    assert "pre-line" in body or "<pre" in body


def test_type_emphasis_stays_on_ramp():
    """强调用字重/等宽，不上 1.1em 或 700。绑定码走 mono token。"""
    src = APP_JS.read_text()
    css = STYLE_CSS.read_text()
    assert "font-size:1.1em" not in src
    assert "class=\"bind-code\"" in _fn_body("fsPersonalStateHtml")
    assert 'resultEl.style.fontWeight = "600"' in _fn_body("adminBatchAddKols")
    paste = re.search(r"^\.cookie-paste\s*\{([^}]*)\}", css, re.M)
    bind = re.search(r"^\.bind-code\s*\{([^}]*)\}", css, re.M)
    assert paste and "var(--font-mono)" in paste.group(1) and "var(--text-sm)" in paste.group(1)
    assert bind and "var(--font-mono)" in bind.group(1) and "var(--text-body)" in bind.group(1)


def test_admin_kols_mutations_disable_while_in_flight():
    """添加/导入/保存/批量进行中要禁用，防连点。"""
    for name in ("adminAddKol", "adminBatchAddKols", "adminKolBatch", "saveKolEdit"):
        body = _fn_body(name)
        assert "disabled" in body, f"{name} 无进行中禁用"


def test_admin_kols_delete_and_private_name_consequences():
    """单删要说清级联；私有空名单要明示对所有人隐藏。"""
    delete = _fn_body("adminDeleteKol")
    assert "订阅" in delete
    assert "帖子" in delete
    save = _fn_body("saveKolEdit")
    assert "对所有人隐藏" in save


def test_admin_kols_edit_modal_dirty_check():
    """未保存修改时点遮罩/Esc 必须确认，不能直接丢掉白名单。"""
    body = _fn_body("adminEditKol")
    assert "dirty" in body.lower() or "未保存" in body


def test_admin_kols_batch_can_unset_tier():
    """批量栏能设普通档，不能只设优先/次要。"""
    body = _fn_body("loadAdminKols")
    assert "adminKolBatch('priority', false)" in body or "adminKolBatchTier(" in body or "设普通" in body


def test_admin_kols_tier_and_private_copy():
    """档位用普通/优先/次要；私有用警告色；原创只在微博显示。"""
    body = _fn_body("loadAdminKols")
    assert "普通" in body and "优先" in body and "次要" in body
    assert "status-warn" in body
    assert 'k.platform === "weibo"' in body or "k.platform == \"weibo\"" in body


def test_admin_kols_errors_use_flash_not_alert():
    """大V管理失败走 flash error，不弹 alert。"""
    for name in (
        "adminAddKol",
        "adminBatchAddKols",
        "adminKolBatch",
        "adminToggleKol",
        "adminTogglePriority",
        "adminToggleSecondary",
        "adminDeleteKol",
        "saveKolEdit",
    ):
        body = _fn_body(name)
        assert "alert(" not in body, f"{name} 仍使用 alert"
        assert 'flash(' in body and '"error"' in body, f"{name} 失败未走 flash error"


def test_admin_kols_empty_and_filter_controls():
    """空状态要算上平台筛选；搜索可点、可清除；全选支持 indeterminate。"""
    body = _fn_body("loadAdminKols")
    assert "adminKolsPlatform" in body
    assert "adminKolsClearFilter" in body or "清除" in body
    assert "adminKolsApplyFilter()" in body
    assert "indeterminate" in _fn_body("adminKolSyncCheckall")


def test_type_scale_uses_four_reading_roles():
    """产品字号只保留四档阅读角色：12 元信息 / 13 控件 / 15 正文 / 17 标题。"""
    tokens = (APP_JS.parent / "vendor" / "design-tokens.css").read_text()
    css = STYLE_CSS.read_text()
    assert re.search(r"--text-xs:\s*12px", tokens)
    assert re.search(r"--text-sm:\s*13px", tokens)
    assert re.search(r"--text-body:\s*15px", tokens)
    assert re.search(r"--text-title:\s*17px", tokens)
    assert re.search(r"--text-display:\s*30px", tokens)
    assert "--font-mono:" in tokens
    assert re.search(r"--font-weight-bold:\s*600", tokens)
    for retired in ("--text-md:", "--text-lg:", "--text-xl:", "--text-title-sm:"):
        assert retired not in tokens, f"token 仍保留已废弃的 {retired}"
        assert retired not in css, f"样式仍引用已废弃的 {retired}"

    body = re.search(r"^body\s*\{([^}]*)\}", css, re.M)
    assert body and "font-size: var(--text-body)" in body.group(1)
    assert "font-size: 14px" not in css

    content = re.search(r"\.post-item \.p-content\s*\{([^}]*)\}", css)
    assert content, "未找到 .post-item .p-content"
    block = content.group(1)
    assert "font-size: var(--text-body)" in block
    assert "word-break: break-all" not in block
    assert "overflow-wrap:" in block
    assert re.search(r"line-height:\s*1\.65", block)

    time = re.search(r"\.post-item \.p-time\s*\{([^}]*)\}", css)
    assert time and "tabular-nums" in time.group(1)

    for size in ("10px", "11px"):
        for match in re.finditer(rf"font-size:\s*{re.escape(size)}", css):
            window = css[max(0, match.start() - 80) : match.end()]
            assert "cube-nav" in window, f"{size} 只能用于图表刻度: {window!r}"


def test_success_token_is_muted_sage():
    """成功色用鼠尾草绿，不用高饱和交通灯绿。"""
    tokens = (APP_JS.parent / "vendor" / "design-tokens.css").read_text()
    assert "--color-success: #3a6e4b;" in tokens
    assert "#16a34a" not in tokens
    assert "rgba(52, 199, 123" not in tokens


def test_admin_chart_system_uses_tokens_and_external_rate_label():
    """管理端图表：净值面积走数据色、成功率数字在条外、趋势有名称、KPI 有 class。"""
    src = APP_JS.read_text()
    css = STYLE_CSS.read_text()
    assert "var(--color-data-positive-soft)" in src
    assert "var(--color-data-negative-soft)" in src
    assert "rgba(230,67,64" not in src
    rate = _fn_body("rateBar")
    assert "rate-row" in rate
    assert "rate-label" in rate
    assert "background:${color}" not in rate
    assert "aria-label" in _fn_body("loadAdminDashboard")
    assert 'class="dash-stat"' in _fn_body("statCard")
    assert ".dash-stats" in css
    assert ".dash-split" in css
    assert "grid-template-columns: minmax(0, 1fr) auto" in css
    assert "qr-frame" in src
    assert 'class="qr-card"' in _fn_body("startWeiboQr")
    assert "onclick=\"loadAdminDashboard()\"" in _fn_body("loadAdminDashboard")


def test_weibo_qr_poll_is_serial():
    """微博扫码轮询必须等上一轮结束再调度下一轮，避免成功后被并发 404 盖成过期。"""
    start = _fn_body("startWeiboQr")
    poll = _fn_body("pollWeiboQr")
    assert "setInterval" not in start
    assert "setInterval" not in poll
    assert "await pollWeiboQr(" in start
    assert "setTimeout" in start.split("await pollWeiboQr", 1)[1]
