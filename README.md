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
- `OPENROUTER_MAX_TOKENS` (ixtiyoriy, default 4096; kredit kam bo‘lsa kamaytiring)
- `OPENROUTER_MAX_TOKENS_SMALL` (ixtiyoriy, default 1024)

Eslatma: Railway’da Variables o‘zgartirilsa “staged changes” bo‘lishi mumkin — ular ishlashi uchun Deploy qilish kerak.
Diagnostika uchun `GET /api/health` endpointida `api_key_present` true/false ko‘rinadi (secret chiqmaydi).

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

### Internet (Qidiruv → Gemini)

Frontend’dagi **Internet** tugmasi `POST /api/internet` endpointiga murojaat qiladi. Endpoint odatda:
- DuckDuckGo Lite qidiruvi + oddiy extraction orqali manbalar (URL) va kontekstni oladi (**bepul**, API key kerak emas).
- Agar Gemini sozlangan bo‘lsa, shu kontekstni Gemini qayta yozadi/strukturaydi (`provider: internet_then_gemini`).

Agar bepul qidiruvdan manbalar chiqmasa, endpoint Gemini’ning Google Search grounding rejimiga (keyin OpenRouter, keyin free) fallback qiladi.

Kerakli env (Gemini bosqichi uchun):
- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `GEMINI_MAX_OUTPUT_TOKENS`

Fallback:
- Gemini ishlamasa (quota/429 va h.k.), endpoint OpenRouter web search grounding’ga o‘tadi. Kerakli env: `OPENROUTER_API_KEY` (ixtiyoriy: `OPENROUTER_INTERNET_MODEL`). Eslatma: OpenRouter’da web search odatda kredit sarflaydi.
- OpenRouter ham ishlamasa (kalit yo‘q yoki limit), endpoint faqat DuckDuckGo Lite + extraction natijasini qaytaradi (sifat LLM’dan pastroq).

Troubleshooting:
- `429 RESOURCE_EXHAUSTED` va xabarda `limit: 0` bo‘lsa — bu odatda quota/billing tomonda (kalit/proyekt/model tier) muammo. Quota/billing’ni tekshiring yoki `GEMINI_MODEL` ni almashtiring.
- Eslatma: Free tier’da `google_search` grounding hamma modelda ham yoqilmagan bo‘lishi mumkin (masalan, `gemini-3.1-flash-lite` uchun “Not available”). Bunday holatda `gemini-2.5-flash` yoki `gemini-2.5-flash-lite` ni sinab ko‘ring.

## Tizim qanday ishlaydi (qisqacha)

1. `QueryUnderstandingService` so‘rovdan `search_plan` va keywordlarni chiqaradi.
2. `XaridUzexConnector` katalogdan product candidate’lar topadi.
3. `CandidateSelectorService` (LLM) eng mos `product_code` ni tanlaydi va `selection_reason` qaytaradi.
4. `SearchOrchestrator` tanlangan manbalardan evidence’larni yig‘adi (xarid shop/national/auction + etender).
5. `PriceAnalysisService` faqat `unit_price` bor evidence’lar bilan narx tahlili qiladi.
6. `LLMPromptBuilder` multi-source prompt tuzadi, LLM TT JSON qaytaradi.
7. `GenericOutputValidator` natijani tekshiradi (narx mosligi, brand/model lock, dalilsiz risk claim).

Diagram/flowchart: `docs/product_search_flow.md`

## Loyiha tuzilmasi (asosiy fayllar va vazifasi)

### Backend (FastAPI)

- `app/api_server.py` — FastAPI serveri, `/api/generate` endpointi, keyword→candidate→evidence→LLM→validation pipeline’ini birlashtiradi.
- `app/schemas.py` — asosiy dataclass’lar: `ProductCandidate`, `Evidence`.
- `app/connectors/xarid_uzex_connector.py` — `xarid.uzex.uz` completed-deals va katalog API’lari bilan ishlaydi:
  - `Lib/GetCategories` → kategoriyalar
  - `Lib/GetProducts/{category_id}?keyword=...` → product candidate’lar
  - `Common/GetCompletedDeals` → tanlangan `product_code` bo‘yicha lotlar
- `app/connectors/etender_uzex_connector.py` — `etender.uzex.uz` DealsList bo‘yicha qidiradi (`product_code` yo‘q, keyword bilan ishlaydi).
- `app/services/search_orchestrator.py` — barcha manbalar bo‘yicha evidence yig‘ishni boshqaradi (qaysi source yoqilgan/skip/failed, period filter).
- `app/services/query_understanding_service.py` — user query’dan RU/UZ keywordlar va `search_plan` chiqaradi (LLM; fallback ham bor).
- `app/services/candidate_selector_service.py` — katalogdan chiqqan candidate’lardan eng mos `product_code` ni tanlaydi (LLM; fallback: top score).
- `app/services/price_analysis_service.py` — `unit_price` bor evidence’lar bo‘yicha narx tahlili (global va source kesimida).
- `app/services/llm_prompt_builder.py` — evidence + tahlil + statuslardan LLM prompt tuzadi (prompt hajmini env bilan boshqaradi).
- `app/services/generic_output_validator.py` — LLM qaytargan TT JSON’ni guardrail qoidalar bilan tekshiradi, ogohlantirishlar beradi.
- `app/services/env_config.py` — env/config o‘qish helper’lari (`OPENROUTER_API_KEY` va h.k.), `/api/health` diagnostika ma’lumotlari shu asosida.

### Frontend (React + Vite)

- `frontend/` — UI: query kiritish, manbalarni yoqib-o‘chirish, evidence jadvali, narx tahlili va TT natijalarini ko‘rsatish.

### Hujjatlar va testlar

- `docs/product_search_flow.md` — mahsulot katalogidan topish oqimi (flowchart).
- `test_etender_connector.py`, `xarid_*_test.py`, `etender_*_test.py` — connector va qidiruvni qo‘lda test qilish skriptlari (debug uchun).

## Frontend nimalarni ko‘rsatadi

- Manbalarni tanlash: `xarid` / `national` / `auction` / `etender`
- Source status kartalar (success/failed/skipped)
- Candidate tanlash sababi (reason)
- Global va by-source narx tahlili
- Evidence tab’lari + filterlar + CSV export
- Narx trend grafigi (unit_price bo‘lsa)
- Hudud / provider kesimida narx tahlili
- Texnik parametrlar summary chip’lari

## Sozlamalar (env) — amaliy eslatmalar

- `.env` faqat lokal uchun; production’da (Render/Railway) secret’lar service **Variables** orqali beriladi.
- OpenRouter:
  - `OPENROUTER_API_KEY` — majburiy (yoki `OPENROUTER_API_KEY_FILE`)
  - `OPENROUTER_MAX_TOKENS` — LLM javob uzunligi (kredit kam bo‘lsa kamaytiring)
  - `OPENROUTER_MAX_TOKENS_SMALL` — keyword/candidate tanlash uchun kichik limit
- Prompt hajmini kamaytirish (prompt token limit xatolariga qarshi):
  - `PROMPT_EVIDENCES_PER_SOURCE` — har bir source’dan promptga nechta evidence kiritish
  - `PROMPT_MAX_TEXT_CHARS` — evidence matnini (condition) nechta belgigacha qisqartirish
