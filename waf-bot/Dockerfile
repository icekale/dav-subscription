FROM python:3.12-slim

WORKDIR /app
# 国内网络可构建时传 --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=https://pypi.org/simple
# playwright CDN 镜像（国内加速）：构建时传 --build-arg PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/
ARG PLAYWRIGHT_DOWNLOAD_HOST=
ENV PLAYWRIGHT_DOWNLOAD_HOST=${PLAYWRIGHT_DOWNLOAD_HOST}
RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} --retries 5 --timeout 60 playwright && \
    playwright install --with-deps chromium

COPY watchdog.py /app/watchdog.py

ENV WAF_COOKIE_FILE=/data/waf_cookies.json
CMD ["python", "/app/watchdog.py"]
