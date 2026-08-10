FROM node:22-bookworm-slim AS node

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts

FROM python:3.12-slim-bookworm

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /app/node_modules /app/node_modules

WORKDIR /app
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" curl_cffi==0.16.0

COPY solver.js watchdog.py ./

ENV WAF_COOKIE_FILE=/data/waf_cookies.json
CMD ["python", "/app/watchdog.py"]
