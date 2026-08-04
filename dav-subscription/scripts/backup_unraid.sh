#!/usr/bin/env bash
# Unraid 定时备份：把 dav-subscription 数据目录复制到备份目录并保留最近 N 份。
# 用法：在 Unraid User Scripts 里配为 daily，命令填：
#   bash /mnt/user/appdata/dav-subscription/scripts/backup_unraid.sh
set -euo pipefail

SOURCE="/mnt/user/appdata/dav-subscription/data"
BACKUP_ROOT="/mnt/user/backups/dav-subscription"
KEEP=${KEEP:-14}

mkdir -p "$BACKUP_ROOT"
STAMP="$(date +%Y%m%d_%H%M%S)"
cp -a "$SOURCE" "$BACKUP_ROOT/data_$STAMP"

# 删除旧备份，保留最近 KEEP 份
ls -1dt "$BACKUP_ROOT"/data_* 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -rf

echo "备份完成: $BACKUP_ROOT/data_$STAMP（保留最近 $KEEP 份）"
