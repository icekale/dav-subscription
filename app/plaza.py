"""动态广场数据源显隐：自动（启用大V 为 0 则藏）/ 显示 / 隐藏。"""
from __future__ import annotations

import json

from .db import DB

# 与前端 PLATFORM_TABS 对齐（不含 ima：广场没有 ima 角标）
PLAZA_PLATFORMS = ("xueqiu", "combination", "weibo", "twitter", "zsxq")
PLAZA_MODES = ("auto", "show", "hide")
PLAZA_VISIBILITY_KEY = "plaza_source_visibility"


def parse_plaza_visibility(raw: str | None) -> dict[str, str]:
    """读 settings JSON；坏数据或未知键一律忽略，缺省 auto。"""
    out = {platform: "auto" for platform in PLAZA_PLATFORMS}
    if not raw:
        return out
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return out
    if not isinstance(data, dict):
        return out
    for platform, mode in data.items():
        if platform in out and mode in PLAZA_MODES:
            out[platform] = mode
    return out


def plaza_source_rows(db: DB) -> list[dict]:
    counts = db.count_enabled_kols_by_platform()
    visibility = parse_plaza_visibility(db.get_setting(PLAZA_VISIBILITY_KEY))
    rows = []
    for platform in PLAZA_PLATFORMS:
        mode = visibility[platform]
        enabled = int(counts.get(platform, 0))
        visible = mode == "show" or (mode == "auto" and enabled > 0)
        rows.append(
            {
                "platform": platform,
                "mode": mode,
                "enabled_kols": enabled,
                "visible": visible,
            }
        )
    return rows


def plaza_visible_platforms(db: DB) -> list[str]:
    return [row["platform"] for row in plaza_source_rows(db) if row["visible"]]


def plaza_hidden_platforms(db: DB) -> list[str]:
    return [row["platform"] for row in plaza_source_rows(db) if not row["visible"]]


def is_plaza_hidden(db: DB, platform: str | None) -> bool:
    return bool(platform) and platform in set(plaza_hidden_platforms(db))


def filter_plaza_rows(db: DB, rows: list[dict], key: str = "platform") -> list[dict]:
    hidden = set(plaza_hidden_platforms(db))
    if not hidden:
        return list(rows)
    return [row for row in rows if row.get(key) not in hidden]


def set_plaza_visibility(db: DB, updates: dict[str, str]) -> list[dict]:
    """合并写入部分平台的 mode，返回最新 rows。非法平台/mode 抛 ValueError。"""
    visibility = parse_plaza_visibility(db.get_setting(PLAZA_VISIBILITY_KEY))
    for platform, mode in updates.items():
        if platform not in PLAZA_PLATFORMS:
            raise ValueError(f"不支持的平台: {platform}")
        if mode not in PLAZA_MODES:
            raise ValueError("显示方式须为自动、显示或隐藏")
        visibility[platform] = mode
    db.set_setting(PLAZA_VISIBILITY_KEY, json.dumps(visibility, ensure_ascii=False))
    return plaza_source_rows(db)
