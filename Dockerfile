FROM python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36

WORKDIR /app
COPY requirements.txt .
# 国内网络可构建时传 --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} --retries 5 --timeout 60 -r requirements.txt
COPY --chown=99:100 app ./app

ENV CONFIG_PATH=/app/config.yaml
ENV DB_PATH=/data/dav.db
ENV PYTHONDONTWRITEBYTECODE=1

USER 99:100

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
