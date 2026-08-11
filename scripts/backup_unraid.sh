#!/usr/bin/env bash
# Unraid 定时备份：SQLite 在线快照 + 非数据库资源归档。
set -euo pipefail
umask 077

APP_DIR="/mnt/user/appdata/dav-subscription"
SOURCE="$APP_DIR/data"
BACKUP_ROOT="/mnt/user/backups/dav-subscription"
CONTAINER=${VPUSH_CONTAINER:-vpush}
KEEP=${KEEP:-14}
STAMP="$(date +%Y%m%d_%H%M%S)"
STAGING="$SOURCE/.backup_$STAMP"
TARGET="$BACKUP_ROOT/data_$STAMP"

mkdir -p "$BACKUP_ROOT"
trap 'rm -rf "$STAGING"' EXIT
docker exec -i "$CONTAINER" python - /data/dav.db "/data/.backup_$STAMP" 1 \
  < "$APP_DIR/scripts/backup.py"
mv "$STAGING" "$TARGET"
for path in avatars xq_images logs waf_cookies.json xueqiu_seed_cookie.txt; do
  [ -e "$SOURCE/$path" ] && cp -a "$SOURCE/$path" "$TARGET/"
done
find "$TARGET" -type d -exec chmod 700 {} +
find "$TARGET" -type f -exec chmod 600 {} +

ls -1dt "$BACKUP_ROOT"/data_* 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -rf

echo "备份完成: $TARGET（SQLite quick_check=ok，保留最近 $KEEP 份）"
