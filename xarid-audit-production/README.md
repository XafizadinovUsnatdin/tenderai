# TenderAI Production

Bu papka `xarid-audit` dan alohida, production uchun tayyorlangan izolyatsiyalangan nusxa.
Mavjud loyiha o‘zgartirilmaydi; deploy va Docker ishlari shu papka ichida yuradi.

## Tuzilma

- `app/` — FastAPI backend
- `frontend/` — Vite/React frontend source
- `Dockerfile` — single-container production image
- `compose.yaml` — Docker Compose orqali ishga tushirish
- `.env.example` — kerakli environment variables namunasi

## Ishga tushirish

1. `.env.example` dan `.env` yarating:

   - PowerShell: `Copy-Item .env.example .env`

2. `.env` ichiga kamida quyidagini to‘ldiring:

   - `OPENROUTER_API_KEY=...`

3. Docker bilan ishga tushiring:

   - `docker compose up --build -d`

4. Servis ochiladi:

   - App: `http://localhost:8000`
   - Health: `http://localhost:8000/api/health`

## Local tekshiruv

- Backend syntax: `python -m py_compile app/api_server.py`
- Frontend build:
  - `cd frontend`
  - `npm ci`
  - `npm run build`

## Muhim env sozlamalar

- `OPENROUTER_API_KEY` — majburiy
- `OPENROUTER_MODEL` — asosiy model
- `OPENROUTER_INTERNET_MODEL` — internet qidiruvi uchun model
- `APP_PORT` — Docker host porti
- `WEB_CONCURRENCY` — uvicorn worker soni
- `CORS_ORIGINS` — alohida frontend domen bo‘lsa kerak
- `XARID_CATEGORY_CACHE_TTL_SECONDS` — kategoriya cache TTL
- `XARID_PAGE_CONCURRENCY` — page parallelism
- `XARID_YEAR_CONCURRENCY` — year parallelism

## Eslatma

Bu production papka hozirgi `xarid-audit` dan mustaqil ishlashi uchun kerakli kodlarni ko‘chirib olingan.
Keyingi o‘zgarishlar avtomatik sinxron bo‘lmaydi; kerak bo‘lsa shu papkaga alohida ko‘chirish kerak bo‘ladi.
