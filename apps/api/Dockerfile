FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=container \
    APP_NAME="AI Quant Platform API" \
    APP_PUBLIC_URL=http://127.0.0.1:8000 \
    API_PREFIX=/api/v1 \
    DATABASE_URL=sqlite+pysqlite:////app/data/quant_platform.db \
    MARKET_DATA_DATABASE_PATH=/app/data/market_data.db \
    JOB_EXECUTION_MODE=background \
    JOB_SIMULATION_LATENCY_MS=100

WORKDIR /app

COPY apps/api /app/apps/api

RUN python -m pip install --upgrade pip \
    && python -m pip install -e /app/apps/api \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "quant_platform_api.main:create_app", "--factory", "--app-dir", "/app/apps/api/src", "--host", "0.0.0.0", "--port", "8000"]
