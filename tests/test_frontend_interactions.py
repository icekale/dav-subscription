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


def test_mobile_mysubs_filter_renders_icon_badges_keeps_desktop_toolbar():
    """订阅页移动端：平台+特别关注全部变为一行角标；桌面保留文字胶囊+按钮。"""
    render = _fn_body("renderMySubs")
    tabs = _fn_body("renderMySubsTabs")
    mobile_html = _fn_body("mysubsMobileFiltersHtml")

    assert "isMobileTimelineFilter()" in render
    assert '"tl-mobile-platforms cols-6"' in render
    assert 'id="mysubs-tabs"' in render
    # 桌面分支必须保留完整工具栏
    assert 'id="mysubs-fav-toggle"' in render
    assert '"platform-tabs"' in render
    # 移动角标：无文字标签，平台+星标都走角标
    assert "PLATFORM_ICONS[p]" in mobile_html
    assert "switchMySubsPlatform('${p}')" in mobile_html
    assert "toggleMySubsFav()" in mobile_html
    assert "STAR_SVG" in mobile_html
    assert "<span>${label}</span>" not in mobile_html
    # 星标点击后需重绘角标选中态
    assert "renderMySubsTabs()" in _fn_body("toggleMySubsFav")
    # 双分支渲染：移动角标 / 桌面文字胶囊
    assert "mysubsMobileFiltersHtml()" in tabs
    assert 'platformTabHTML(p, state.mysubsPlatform' in tabs


def test_mobile_mysubs_filter_is_six_equal_44px_targets():
    """订阅页一行六角标（全部+4平台+特别关注），等宽且至少 44px。"""
    css = STYLE_CSS.read_text()
    cols6 = re.search(r"\.tl-mobile-platforms\.cols-6\s*\{([^}]*)\}", css)
    assert cols6 and "repeat(6, minmax(0, 1fr))" in cols6.group(1)
    assert ".tl-mobile-platform .star-icon" in css


# ---- 订阅广场移动端头部密度 ----

def test_mobile_home_filter_reuses_native_and_shared_controls():
    """移动端用原生折叠和共享角标；桌面筛选保持完整。"""
    render = _fn_body("renderHome")
    mobile_platforms = _fn_body("homeMobilePlatformsHtml")
    pick = _fn_body("homePickMobilePlatform")

    for marker in ('<details class="home-filter"', '<summary id="home-filter-toggle"',
                   'id="home-search"', 'id="platform-tabs"', 'id="home-cats"'):
        assert marker in render
    assert 'class="tl-mobile-platform ' in mobile_platforms
    assert "PLATFORM_ICONS[p]" in mobile_platforms
    assert "homePickMobilePlatform('${p}')" in mobile_platforms
    assert "state.platform = platform" in pick
    assert "panel.open = false" in pick
    assert "loadHomeKols(routeRenderSeq)" in pick


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
    assert re.search(r"\.ak-platform-tabs \.platform-tab[^{]*\{[^}]*--control-height-2xl", css)


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
