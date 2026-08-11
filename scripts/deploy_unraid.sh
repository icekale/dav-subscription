#!/usr/bin/env bash
# 部署到 Unraid：完整运行文件同步 → 在线备份 → 重建 → 健康检查。
set -euo pipefail

HOST="root@192.168.5.28"
REMOTE_DIR="/mnt/user/appdata/dav-subscription"
COMPOSE_FILE="docker-compose.unraid.yml"
PORT="18084"

cd "$(git rev-parse --show-toplevel)"

runtime_files() {
  git ls-files | awk '
    /^app\// || /^waf-bot\// || /^deploy\// || /^scripts\/backup/ ||
    $0 == "Dockerfile" || $0 == "requirements.txt" || $0 == ".dockerignore" ||
    $0 == "docker-compose.unraid.yml" || $0 == "README.md" { print }
  '
}

FILES=()
while IFS= read -r file; do
  FILES+=("$file")
done < <(runtime_files)
[ "${#FILES[@]}" -gt 0 ] || { echo "没有运行文件可同步"; exit 1; }

printf '%s\n' "${FILES[@]}" > /tmp/vpush-runtime-files.txt

# 只同步明确的 Git 运行文件，不触碰 .env/data；已删除文件由下方 manifest 对比清理。
# 不用 --delete-missing-args：macOS 自带 openrsync 不支持该选项。
echo "== 同步完整运行文件 =="
rsync -azR --files-from=/tmp/vpush-runtime-files.txt ./ "$HOST:$REMOTE_DIR/"

# 删除上一版 manifest 中已不再跟踪的运行文件。
scp /tmp/vpush-runtime-files.txt "$HOST:$REMOTE_DIR/.deploy-manifest.new" >/dev/null
ssh "$HOST" "cd '$REMOTE_DIR' && if [ -f .deploy-manifest ]; then while IFS= read -r f; do grep -Fxq \"\$f\" .deploy-manifest.new || rm -f -- \"\$f\"; done < .deploy-manifest; fi; mv .deploy-manifest.new .deploy-manifest"

# 先生成经过 SQLite quick_check 的线上备份，再把数据目录交给非 root 容器用户。
echo "== 上线前备份 =="
ssh "$HOST" "cd '$REMOTE_DIR' && KEEP=14 bash scripts/backup_unraid.sh" | tail -1
echo "== 数据目录权限 =="
ssh "$HOST" "chown -R 99:100 '$REMOTE_DIR/data' && find '$REMOTE_DIR/data' -type d -exec chmod 770 {} + && find '$REMOTE_DIR/data' -type f -exec chmod 660 {} + && chmod 600 '$REMOTE_DIR/data/dav.db'"

echo "== 重建与重启 =="
ssh "$HOST" "cd '$REMOTE_DIR' && docker compose -f '$COMPOSE_FILE' build vpush waf-bot"
ssh "$HOST" "cd '$REMOTE_DIR' && docker compose -f '$COMPOSE_FILE' up -d --remove-orphans"

echo "== 健康检查 =="
for _ in $(seq 1 24); do
  if curl -fsS -m 5 "http://192.168.5.28:$PORT/healthz" >/dev/null; then break; fi
  sleep 2
done
curl -fsS -m 8 "http://192.168.5.28:$PORT/api/version"
echo
ssh "$HOST" "docker ps --format '{{.Names}} {{.Status}}' | grep -E 'vpush|rsshub'; docker logs --tail=80 vpush 2>&1 | tail -80"
echo "部署完成"
