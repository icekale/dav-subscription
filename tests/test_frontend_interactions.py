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
    """routeStillActive 必须与全局 routeRenderSeq 比较，未传 token 的局部刷新保持活跃。"""
    src = APP_JS.read_text()
    m = re.search(r"function routeStillActive\(seq\)\s*\{[^}]*\}", src)
    assert m, "未找到 routeStillActive"
    assert "routeRenderSeq" in m.group(0)
    assert "undefined" in m.group(0)
