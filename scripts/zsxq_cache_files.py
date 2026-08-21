"""知识星球附件本地缓存脚本。

把帖子 detail.files 里的附件下载到 data/zsxq_files/ 并回写本地 URL。
- 优先用库里未过期的签名 URL（不烧 download_url 配额）
- 缺失/过期签名 URL 时才调 download_url（受 13607 每日配额），慢速退避
- 已落盘的文件跳过，保证可重复跑/断点续传

用法:
    ./.venv/bin/python scripts/zsxq_cache_files.py [--limit N] [--delay SEC]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import DB  # noqa: E402
from app.fetchers.zsxq import (  # noqa: E402
    ZsxqError,
    cache_zsxq_file,
    resolve_zsxq_file_url,
)


def _valid(url: str, now: int) -> bool:
    m = re.search(r"[?&]e=(\d+)", url or "")
    return bool(url) and (not m or int(m.group(1)) > now)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个未缓存文件（0=全部）")
    ap.add_argument("--delay", type=float, default=2.0, help="缺失 URL 时的请求间隔秒数")
    args = ap.parse_args()

    db = DB("data/dav.db")
    now = int(time.time())
    files_dir = Path("data/zsxq_files")
    files_dir.mkdir(parents=True, exist_ok=True)

    # 收集全部唯一 file_id -> (name, url)
    seen: dict[str, tuple[str, str]] = {}
    for row in db._conn.execute(
        "SELECT detail FROM posts WHERE platform='zsxq' AND detail LIKE '%files%'"
    ):
        d = json.loads(row[0] or "{}")
        for f in d.get("files") or []:
            fid = str(f.get("file_id") or "")
            if fid and fid not in seen:
                seen[fid] = (str(f.get("name") or ""), str(f.get("url") or ""))

    # 已落盘
    have = {p.stem for p in files_dir.glob("*")}
    todo = [fid for fid in seen if fid not in have]
    if args.limit:
        todo = todo[: args.limit]
    done = 0
    quota_hit = 0
    for i, fid in enumerate(todo, 1):
        name, url = seen[fid]
        # 只有签名 URL 缺失/过期才调 download_url（受配额）；否则直接用签名 URL
        if not _valid(url, now):
            for attempt in range(6):
                try:
                    url = resolve_zsxq_file_url(fid, db=db)
                    break
                except ZsxqError as exc:
                    if exc.code in (13607, 20601):
                        print(f"[quota {exc.code}] {name[:40]} 额度受限，跳过；{exc.info if hasattr(exc,'info') else ''}")
                        quota_hit += 1
                        url = ""
                        break
                    time.sleep(args.delay * (attempt + 1))
            else:
                url = ""
            time.sleep(args.delay)
        local = cache_zsxq_file(db, fid, name, url) if url else ""
        if local:
            done += 1
            # 回写库
            for row in db._conn.execute(
                "SELECT id, detail FROM posts WHERE platform='zsxq' AND detail LIKE ?", (f"%{fid}%",)
            ):
                d = json.loads(row[1] or "{}")
                changed = False
                for f in d.get("files") or []:
                    if str(f.get("file_id")) == fid:
                        f["url"] = local
                        changed = True
                if changed:
                    db._conn.execute(
                        "UPDATE posts SET detail=? WHERE id=?",
                        (json.dumps(d, ensure_ascii=False), row[0]),
                    )
            db._conn.commit()
        if (i % 20 == 0) or local:
            print(f"[{i}/{len(todo)}] {name[:40]} -> {local or 'SKIP'} ({done} cached, {quota_hit} quota)")
    print(f"done: cached {done}, quota_hit {quota_hit}, remaining {len(todo) - done}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
