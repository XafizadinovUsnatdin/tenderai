# syntax=docker/dockerfile:1.7

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN adduser --system --uid 10001 appuser \
    && chown -R appuser:root /app

USER appuser

CMD ["python", "-m", "app.collector"]
