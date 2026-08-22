"""小程序订阅广场角标跟 /api/me.plaza_platforms，不写死全平台。"""
from pathlib import Path

ROOT = Path(__file__).parent.parent
INDEX_JS = ROOT / "miniprogram/pages/index/index.js"


def test_miniprogram_home_tabs_follow_plaza_platforms():
    src = INDEX_JS.read_text()
    assert "/api/me" in src
    assert "plaza_platforms" in src
    assert "zsxq" in src
