FROM python:3.11-slim

WORKDIR /app

COPY apps/api /app/apps/api

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -e /app/apps/api

EXPOSE 8000

CMD ["uvicorn", "quant_platform_api.main:create_app", "--factory", "--app-dir", "/app/apps/api/src", "--host", "0.0.0.0", "--port", "8000"]
