# syntax=docker/dockerfile:1.7

FROM node:20-alpine AS frontend-build
WORKDIR /build/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    WEB_CONCURRENCY=2

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY --from=frontend-build /build/frontend/dist ./frontend/dist

RUN adduser --system --uid 10001 appuser \
    && chown -R appuser:root /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).read()"

CMD ["sh", "-c", "uvicorn app.api_server:app --host ${HOST} --port ${PORT} --workers ${WEB_CONCURRENCY}"]
