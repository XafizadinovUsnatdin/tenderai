# TenderAI (Xarid Audit) — Multi-source procurement analysis

Ushbu loyiha O‘zbekiston tender/xarid portallaridan dalillarni (evidence) yig‘ib, **narx tahlili** va **texnik topshiriq (TT) drafti** generatsiya qiladi.

## Manbalar (sources)

- `xarid.uzex.uz` (completed deals, **shop**) — odatda `amount` bor, `unit_price = deal_cost / amount` hisoblanadi.
- `xarid.uzex.uz/national` (completed deals, **national**) — ko‘p holatda `amount` bor, `unit_price` hisoblanadi.
- `xarid.uzex.uz/auction` (completed deals, **auction**) — ko‘pincha `amount` yo‘q, shuning uchun `unit_price = null` (narx tahliliga kiritilmaydi), lekin audit/evidence uchun foydali.
- `etender.uzex.uz` (deals list) — `amount/quantity` yo‘q bo‘lishi mumkin, shuning uchun `unit_price = null`, lekin tender konteksti, statuslar, ishtirokchilar soni va fayl yo‘llari (shartnoma/protokol) uchun foydali.

## Muhim biznes qoidalar

1. `unit_price` bo‘lmagan evidence **per-unit narx tahliliga kiritilmaydi**.
2. `etender.uzex.uz` dagi `deal_cost` ko‘pincha **butun tender/bitim paket summasi** — uni bitta dona narxi deb talqin qilmang.
3. `xarid.uzex.uz/auction` natijalarida `amount` bo‘lmasa, `unit_price` hisoblanmaydi.
4. Frontend har bir natijaning `source_name` va `source_url` (lotga link)ini aniq ko‘rsatadi.

## Tez start (Windows / PowerShell)

### 1) Backend (FastAPI)

```powershell
cd d:\BRB\9\tenderai\xarid-audit

# .env tayyorlang (API key shart)
Copy-Item .env.example .env
notepad .env

# venv (agar yo‘q bo‘lsa)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -U pip
pip install fastapi "uvicorn[standard]" httpx python-dotenv pydantic

uvicorn app.api_server:app --reload --host 127.0.0.1 --port 8000
```

Backend:
- API: `http://127.0.0.1:8000/api/generate`
- Swagger: `http://127.0.0.1:8000/docs`

### 2) Frontend (React + Vite)

```powershell
cd d:\BRB\9\tenderai\xarid-audit\frontend
npm install
npm run dev
```

Frontend: `http://127.0.0.1:5173`

## Deploy (Render — bitta servisda backend + frontend)

Loyiha Docker orqali bitta web servis sifatida deploy qilinadi:
- Frontend build: `frontend/` (Vite)
- Backend: `app/api_server.py` (FastAPI)
- Production’da frontend `frontend/dist` dan serve qilinadi, API esa `/api/generate`.

### 1) Render’ga ulash

1. Render Dashboard → **New** → **Blueprint**
2. GitHub repo: `XafizadinovUsnatdin/tenderai`
3. Blueprint file: repo root’dagi `render.yaml`
4. Environment variables:
   - `OPENROUTER_API_KEY` (majburiy)
   - `OPENROUTER_MODEL` (ixtiyoriy, default `openai/gpt-4o-mini`)
   - `OPENROUTER_BASE_URL` (ixtiyoriy)

### 2) Deploydan keyin

- Sayt: `https://<render-app>.onrender.com/`
- API: `https://<render-app>.onrender.com/api/generate`
- Swagger: `https://<render-app>.onrender.com/docs`

Eslatma:
- Frontend production’da `VITE_API_URL` talab qilmaydi (default `/api/generate`).
- Agar frontend’ni alohida domen’da deploy qilsangiz, backend’da `CORS_ORIGINS` ni shunga sozlang (vergul bilan bir nechta domain bo‘lishi mumkin).

## Deploy (Railway — Dockerfile)

Railway `Dockerfile` orqali deploy qiladi (`railway.json`).
Production’da `.env` fayl odatda konteyner ichiga nusxalanmaydi, shuning uchun secret’larni Railway **Variables** orqali bering:

- `OPENROUTER_API_KEY` (majburiy)
- `OPENROUTER_MODEL` (ixtiyoriy)
- `OPENROUTER_BASE_URL` (ixtiyoriy)

## Sozlamalar (.env)

`.env.example` dan `.env` ga nusxa oling va quyidagini to‘ldiring:

- `OPENROUTER_API_KEY` — majburiy
- `OPENROUTER_MODEL` — default: `openai/gpt-4o-mini`
- `OPENROUTER_BASE_URL` — default: `https://openrouter.ai/api/v1`

Eslatma: `.env` ni gitga commit qilmang.

## API ishlatilishi

### Request

`POST /api/generate`

```json
{
  "query": "TP-Link TL-SG108S",
  "period_months": 12,
  "enabled_sources": ["xarid.uzex.uz", "xarid.uzex.uz/national", "xarid.uzex.uz/auction", "etender.uzex.uz"]
}
```

### Response (qisqacha)

- `selected_product` — xarid katalogidan tanlangan product_code
- `candidate_selection_reason` — nega shu candidate tanlangani
- `source_status` — har bir manba holati (`success/failed/skipped`) va count
- `evidences` / `evidences_by_source` — lotlar jadvali uchun
- `price_analysis.global` — faqat `unit_price` bor evidencelar bo‘yicha
- `price_analysis.by_source` — manbalar kesimida
- `technical_task` — LLM generatsiya qilgan TT (JSON)
- `validation_warnings` — guardrail ogohlantirishlar

## Tizim qanday ishlaydi (qisqacha)

1. `QueryUnderstandingService` so‘rovdan `search_plan` va keywordlarni chiqaradi.
2. `XaridUzexConnector` katalogdan product candidate’lar topadi.
3. `CandidateSelectorService` (LLM) eng mos `product_code` ni tanlaydi va `selection_reason` qaytaradi.
4. `SearchOrchestrator` tanlangan manbalardan evidence’larni yig‘adi (xarid shop/national/auction + etender).
5. `PriceAnalysisService` faqat `unit_price` bor evidence’lar bilan narx tahlili qiladi.
6. `LLMPromptBuilder` multi-source prompt tuzadi, LLM TT JSON qaytaradi.
7. `GenericOutputValidator` natijani tekshiradi (narx mosligi, brand/model lock, dalilsiz risk claim).

Diagram/flowchart: `docs/product_search_flow.md`

## Frontend nimalarni ko‘rsatadi

- Manbalarni tanlash: `xarid` / `national` / `auction` / `etender`
- Source status kartalar (success/failed/skipped)
- Candidate tanlash sababi (reason)
- Global va by-source narx tahlili
- Evidence tab’lari + filterlar + CSV export
- Narx trend grafigi (unit_price bo‘lsa)
- Hudud / provider kesimida narx tahlili
- Texnik parametrlar summary chip’lari
