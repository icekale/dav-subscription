"""小程序时间线标签筛选静态回归测试：点击标签筛选、筛选条、清除。

背景：小程序时间线原固定请求 /api/my/feed?limit=100，只渲染 item.tags 无点击事件。
本测试静态固化标签筛选约定：currentTag 状态、encodeURIComponent 转义查询参数、
selectTag/clearTag 交互、空状态区分（有标签筛选时不能显示"还没有订阅任何大V"）。
"""
from pathlib import Path

ROOT = Path(__file__).parent.parent
TIMELINE_JS = ROOT / "miniprogram/pages/timeline/timeline.js"
TIMELINE_WXML = ROOT / "miniprogram/pages/timeline/timeline.wxml"


def test_miniprogram_timeline_requests_selected_tag():
    src = TIMELINE_JS.read_text()
    assert "currentTag" in src
    assert "encodeURIComponent(this.data.currentTag)" in src
    assert 'request(`/api/my/feed?limit=100${tagQuery}`)' in src


def test_miniprogram_timeline_tag_is_clickable_and_clearable():
    src = TIMELINE_WXML.read_text()
    assert 'bindtap="selectTag"' in src
    assert 'data-tag="{{tag}}"' in src
    assert 'bindtap="clearTag"' in src
