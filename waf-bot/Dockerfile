FROM node:22-bookworm-slim AS node

FROM python:3.12-slim-bookworm

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

WORKDIR /app
ARG PIP_INDEX_URL=https://pypi.org/simple

COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts && \
    pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" curl_cffi==0.16.0

COPY solver.js watchdog.py ./

ENV WAF_COOKIE_FILE=/data/waf_cookies.json
CMD ["python", "/app/watchdog.py"]
