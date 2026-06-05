# syntax=docker/dockerfile:1

FROM node:20-alpine AS frontend-build
WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -U pip && pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Built frontend is served by FastAPI from `frontend/dist`
COPY --from=frontend-build /frontend/dist ./frontend/dist

ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.api_server:app --host 0.0.0.0 --port ${PORT}"]

