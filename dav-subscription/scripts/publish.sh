#!/usr/bin/env bash
# 构建并推送多架构镜像到 Docker Hub。
# 用法：IMAGE=yourname/dav-subscription ./scripts/publish.sh
set -euo pipefail

IMAGE="${IMAGE:-dav-subscription}"
TAG="${TAG:-v1.0.0}"

docker login
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t "${IMAGE}:${TAG}" \
  -t "${IMAGE}:latest" \
  --push .
echo "已推送 ${IMAGE}:${TAG} 与 ${IMAGE}:latest"
