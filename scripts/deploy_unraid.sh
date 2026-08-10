#!/usr/bin/env bash
# 部署到 Unraid：基线校验 → rsync 同步 → md5 校验 → 重建镜像 → 重启容器 → 健康检查。
# 用法：
#   ./scripts/deploy_unraid.sh               # 同步最近一次提交改动的文件
#   ./scripts/deploy_unraid.sh app/api.py    # 同步指定文件（可多个）
# 防误覆盖：每个待同步文件会先比对 Unraid 与本地 HEAD~1 的 md5，
# 不一致（Unraid 上有本地基线之外的改动）时中止，避免覆盖 Unraid 独有修改。
set -euo pipefail

HOST="root@192.168.5.28"
REMOTE_DIR="/mnt/user/appdata/dav-subscription"
COMPOSE_FILE="docker-compose.unraid.yml"
PORT="18084"

# 默认同步最近一次提交改动的文件；可传文件列表覆盖
if [ "$#" -gt 0 ]; then
  FILES=("$@")
else
  FILES=()
  while IFS= read -r line; do
    FILES+=("$line")
  done < <(git diff --name-only HEAD~1)
fi

echo "== 筛选生产运行文件 =="
RUNNING_FILES=()
for f in "${FILES[@]}"; do
  case "$f" in
    app/*|README.md)
      RUNNING_FILES+=("$f") ;;
    *)
      echo "  跳过（非生产运行文件）：$f" ;;
  esac
done
FILES=("${RUNNING_FILES[@]}")
if [ "${#FILES[@]}" -eq 0 ]; then
  echo "没有需要同步的生产运行文件"; exit 0
fi

echo "== 基线校验（防覆盖 Unraid 独有改动）=="
for f in "${FILES[@]}"; do
  [ -f "$f" ] || { echo "跳过（本地不存在）：$f"; continue; }
  remote=$(ssh "$HOST" "md5sum '$REMOTE_DIR/$f'" 2>/dev/null | awk '{print $1}' || true)
  if [ -z "$remote" ]; then
    echo "  新增文件（Unraid 无此文件）：$f"
    continue
  fi
  # Unraid 版本允许为「本地 HEAD」或「本地 HEAD~1」两种状态：
  #   HEAD   = 已是最新，重复部署（重跑幂等）
  #   HEAD~1 = 落后一个提交，正常同步目标
  # 两者都不是才判定为 Unraid 上的第三方/并发改动，中止保护
  head_md5=$(git show HEAD:"$f" | md5 -q)
  prev_md5=$(git show HEAD~1:"$f" 2>/dev/null | md5 -q || true)
  if [ "$remote" != "$head_md5" ] && [ "$remote" != "$prev_md5" ]; then
    echo "✋ 中止：$f 在 Unraid 上有本地 HEAD/HEAD~1 之外的改动（可能被并发修改）"
    echo "  Unraid: $remote"
    echo "  HEAD:   $head_md5"
    echo "  HEAD~1: $prev_md5"
    echo "  请先人工确认 Unraid 上的改动是否需要保留，再重试"
    exit 1
  fi
done

echo "== rsync 同步 =="
for f in "${FILES[@]}"; do
  [ -f "$f" ] || continue
  rsync -az "$f" "$HOST:$REMOTE_DIR/$f"
done

echo "== md5 校验 =="
for f in "${FILES[@]}"; do
  [ -f "$f" ] || continue
  local_md5=$(md5 -q "$f")
  remote_md5=$(ssh "$HOST" "md5sum '$REMOTE_DIR/$f'" | awk '{print $1}')
  if [ "$local_md5" != "$remote_md5" ]; then
    echo "✗ 校验失败：$f"; exit 1
  fi
  echo "  ✓ $f"
done

echo "== 重建镜像 =="
ssh "$HOST" "cd '$REMOTE_DIR' && docker compose -f $COMPOSE_FILE build dav-subscription" | tail -2

echo "== 重启容器 =="
ssh "$HOST" "cd '$REMOTE_DIR' && docker compose -f $COMPOSE_FILE up -d --no-deps dav-subscription" | tail -1

echo "== 健康检查 =="
sleep 8
ssh "$HOST" "docker ps --format '{{.Names}} {{.Status}}' | grep dav-subscription"
curl -s -m 8 "http://192.168.5.28:$PORT/api/version"
echo
echo "✅ 部署完成"
