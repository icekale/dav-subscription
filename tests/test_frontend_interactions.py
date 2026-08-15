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
