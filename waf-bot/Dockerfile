FROM python:3.12-slim

WORKDIR /app
# 国内网络加速（构建时可用 --build-arg 覆盖）：
#   PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
#   PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/
# chromium 本体走 playwright CDN 下载；--with-deps 的系统依赖走 apt，Debian 官方源
# 在 CN 网络极慢（实测 apt-get 卡 36 分钟），直接把 debian.sources 换成清华镜像。
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PLAYWRIGHT_DOWNLOAD_HOST=
ENV PLAYWRIGHT_DOWNLOAD_HOST=${PLAYWRIGHT_DOWNLOAD_HOST}

# 覆盖 debian.sources 为清华镜像（python:3.12-slim 为 trixie；security 独立路径）
RUN cat > /etc/apt/sources.list.d/debian.sources <<'EOF'
Types: deb
URIs: https://mirrors.tuna.tsinghua.edu.cn/debian
Suites: trixie trixie-updates
Components: main
Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp

Types: deb
URIs: https://mirrors.tuna.tsinghua.edu.cn/debian-security
Suites: trixie-security
Components: main
Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp
EOF
RUN apt-get update && apt-get install -y --no-install-recommends \
    libasound2t64 libatk-bridge2.0-0t64 libatk1.0-0t64 libatspi2.0-0t64 \
    libcairo2 libcups2t64 libdbus-1-3 libdrm2 libgbm1 libglib2.0-0t64 \
    libnspr4 libnss3 libpango-1.0-0 libx11-6 libxcb1 libxcomposite1 \
    libxdamage1 libxext6 libxfixes3 libxkbcommon0 libxrandr2 xvfb \
    fonts-noto-color-emoji fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# chromium 下载独立一层：镜像重建时 pip/apt 层命中缓存不重跑
RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} --retries 5 --timeout 60 playwright && \
    playwright install chromium

COPY watchdog.py /app/watchdog.py

ENV WAF_COOKIE_FILE=/data/waf_cookies.json
CMD ["python", "/app/watchdog.py"]
