#!/usr/bin/env python3
"""SQLite 在线备份（WAL 安全）：python scripts/backup.py [db] [backup_dir] [keep]"""
from __future__ import annotations

import pathlib
import sqlite3
import sys
import time


def main() -> int:
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/dav.db"
    backup_dir = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "backups")
    keep = int(sys.argv[3]) if len(sys.argv) > 3 else 14

    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup_dir.chmod(0o700)
    target = backup_dir / f"dav-{time.strftime('%Y%m%d-%H%M%S')}.db"

    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(target)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()

    check = sqlite3.connect(target)
    try:
        result = check.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        check.close()
    if result != "ok":
        target.unlink(missing_ok=True)
        raise RuntimeError(f"备份校验失败: {result}")
    target.chmod(0o600)

    backups = sorted(backup_dir.glob("dav-*.db"))
    for old in backups[:-keep]:
        old.unlink()
    print(f"备份完成: {target}（保留最近 {keep} 份）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
