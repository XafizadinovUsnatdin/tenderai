# TenderAI Frontend (React + Vite)

TenderAI backend (`FastAPI`) dan natijalarni olib, **multi-source evidence**, **narx tahlili** va **texnik topshiriq**ni dashboard ko‘rinishida ko‘rsatadi.

## Ishga tushirish

```powershell
cd d:\BRB\9\tenderai\xarid-audit\frontend
npm install
npm run dev
```

Brauzer: `http://127.0.0.1:5173`

## Backend URL

Frontend backendga quyidagi URL orqali murojaat qiladi:

- `http://127.0.0.1:8000/api/generate`

Agar backend host/port o‘zgarsa, `src/App.jsx` ichidagi `API_URL` ni moslab qo‘ying.

## UI imkoniyatlari

- Qidiruv: mahsulot/xizmat nomi + davr (`period_months`)
- Manbalarni tanlash:
  - `xarid.uzex.uz` (shop)
  - `xarid.uzex.uz/national` (national)
  - `xarid.uzex.uz/auction` (auction)
  - `etender.uzex.uz` (deals list)
- Manba holati kartalari (`source_status`)
- Tanlangan mahsulot va “Nega shu tanlandi?” (`candidate_selection_reason`)
- Narx tahlili:
  - Global (faqat `unit_price` bor evidence’lar)
  - By-source
- Evidence tab’lari (All + source bo‘yicha), filterlar, CSV export
- Narx trend grafigi (unit_price bo‘lsa)
- Hudud / provider kesimida narx tahlili
- Texnik parametrlar summary (chip’lar)
