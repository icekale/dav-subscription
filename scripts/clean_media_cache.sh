#!/bin/bash
# 清理知识星球/各平台媒体缓存（安全版）。
# 规则：只清可重新下载的媒体缓存目录；**【保留】 avatars/（DB 存本地路径，清了头像全 404）、
#        dav.db 主库、backups/、logs/、probes/、*_cookie/waf_cookies 等状态文件。
# 用法：DATA_DIR=${DATA_DIR:-/opt/vpush/data} scripts/clean_media_cache.sh
set -e
DATA="${DATA_DIR:-/opt/vpush/data}"
[ -d "$DATA" ] || { echo "数据目录不存在: $DATA"; exit 2; }
CLEAR=(zsxq_files zsxq_images xq_images)
echo "将清空（可自动重下）：${CLEAR[*]}"
for d in "${CLEAR[@]}"; do
  [ -d "$DATA/$d" ] && { rm -rf "$DATA/$d"/* 2>/dev/null && echo "清空 $d"; }
done
echo "保留：avatars/ dav.db backups/ logs/ probes/ 状态文件"
