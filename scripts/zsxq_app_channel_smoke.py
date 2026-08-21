#!/usr/bin/env python3
"""知识星球 App 通道真实抓取冒烟（操作者执行并留档）。

用法（在服务器或本机、具备 ZSXQ_COOKIE 的环境）：
    ZSXQ_COOKIE=zsxq_access_token=... GROUP_ID=28888112822211 \
    ZSXQ_FETCH_DELAY_SECONDS=1.0 ZSXQ_MAX_PAGES=2 \
    .venv/bin/python scripts/zsxq_app_channel_smoke.py

默认强制 App 通道（App 头 + X-Request-Id/X-Version），单星球、低页数、不抓评论、
不下载附件，只验证「模拟安卓客户端」能抓回贴文。结果写入 work/zsxq_app_smoke-*.json
留档。退出码：0=成功抓到或明确无新帖；2=凭证/网络/额度类错误（13607 等）。

仅本人账号、已授权星球；沿用 fetcher 自带 1059 重试与延时，不做高频。
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ZSXQ_APP_CHANNEL", "1")  # 冒烟强制 App 通道
os.environ.setdefault("ZSXQ_FETCH_COMMENTS", "0")  # 冒烟不抓评论
os.environ.setdefault("ZSXQ_MAX_PAGES", "1")  # 冒烟低页数
os.environ.setdefault("ZSXQ_FETCH_DELAY_SECONDS", "1.0")

from app.fetchers.zsxq import ZsxqError, ZsxqFetcher, configured_token  # noqa: E402


class _EnvDb:
    """最小 db 门面：把设置读成环境变量，让 fetcher 的配置路径生效。"""

    def get_setting(self, key: str) -> str:
        return os.environ.get(key.upper(), "")


def main() -> int:
    group_id = (os.environ.get("GROUP_ID") or "").strip()
    token = configured_token(_EnvDb())
    if not group_id or not token:
        print("缺少 GROUP_ID 或 ZSXQ_COOKIE")
        return 2
    start = time.time()
    fetcher = ZsxqFetcher(db=_EnvDb())
    try:
        posts = fetcher.fetch({"external_id": group_id, "name": group_id, "id": None})
    except ZsxqError as exc:
        print(f"[FAIL] code={exc.code} {exc}")
        _write(group_id, {"ok": False, "error": str(exc), "code": exc.code})
        return 2
    except Exception as exc:  # noqa: BLE001 - 冒烟脚本汇总所有失败
        print(f"[FAIL] {exc}")
        _write(group_id, {"ok": False, "error": str(exc)})
        return 2
    summary = {
        "ok": True,
        "group_id": group_id,
        "app_channel": True,
        "posts": len(posts),
        "seconds": round(time.time() - start, 1),
        "first_titles": [p.title for p in posts[:5]],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    _write(group_id, summary)
    return 0


def _write(group_id: str, data: dict) -> str:
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "work")
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(out_dir, f"zsxq_app_smoke-{ts}-{group_id}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"ts": ts, "group_id": group_id, **data}, fh, ensure_ascii=False, indent=2)
    print(f"留档: {path}")
    return path


if __name__ == "__main__":
    sys.exit(main())