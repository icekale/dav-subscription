# 默认方案：jsdom 求解器（无浏览器运行时，约 112MB）。
# 备用回退：若雪球升级挑战使 jsdom 失效，改用 Dockerfile.chromium
# （Playwright/Chromium，约数百 MB）——docker compose 中把 build 改为
#   build:
#     context: ./waf-bot
#     dockerfile: Dockerfile.chromium
# 观察 jsdom 方案稳定运行一段时间后再考虑移除回退文件。
FROM node:22-bookworm-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436 AS node

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts

FROM python:3.12-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /app/node_modules /app/node_modules

WORKDIR /app
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" curl_cffi==0.16.0

COPY --chown=99:100 solver.js watchdog.py ./

ENV WAF_COOKIE_FILE=/data/waf_cookies.json
USER 99:100
CMD ["python", "/app/watchdog.py"]
