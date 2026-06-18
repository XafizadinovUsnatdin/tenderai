# TenderAI Collector Only

Bu papka faqat tender ma'lumotlarini yig'ish uchun. API, frontend va LLM qismlari yo'q.

To'liq foydalanish guide: [GUIDE.md](GUIDE.md)

Collector PostgreSQL bazasini hozirgi production schema bilan yaratadi va to'ldiradi:

- `tender_evidences`
- `tender_products`
- `tender_categories`
- `tender_sync_state`
- `tender_statuses` view - statuslar bo'yicha breakdown
- audit capture jadvallari ham schema mosligi uchun yaratiladi

Collector statusidan qat'i nazar barcha public rowlarni yig'adi. Ya'ni `Поставлена`, `Оплачена`, `Расторжена`, `Новая`, `Не оплачен` va boshqa holatlar ham `tender_evidences` ichiga yoziladi.

## Manbalar

Collector quyidagi public/API manbalardan ma'lumot yig'adi:

- `xarid.uzex.uz`
- `xarid.uzex.uz/national`
- `xarid.uzex.uz/auction`
- `etender.uzex.uz`
- `stat-new.cooperation.uz`
- `new.cooperation.uz`
- `new-xarid.uzex.uz`
- `xarid.ebirja.uz`
- `xt-xarid.uz`

## 1. Docker bilan ishga tushirish

Yangi kompyuterda Docker Desktop o'rnatilgan bo'lishi kerak.

```powershell
cd C:\path\to\tenderai_collector
Copy-Item .env.example .env
docker compose up -d postgres
docker compose build collector
```

Birinchi marta bazani noldan yig'ish:

```powershell
docker compose run --rm collector python -m app.collector --reset-archive --full-backfill --years-back 5
```

`--reset-archive` bazani tozalaydi. Uni faqat birinchi yig'ishda yoki ataylab qayta boshlamoqchi bo'lsangiz ishlating.
Jarayon uzilib qolsa, davom ettirish uchun `--reset-archive`siz qayta ishga tushiring:

```powershell
docker compose run --rm collector python -m app.collector --full-backfill --years-back 5
```

## Reset yoki davom ettirish

Bazani o'chirib, hammasini noldan qayta yig'ish:

```powershell
docker compose run --rm collector python -m app.collector --reset-archive --full-backfill --years-back 5
```

Mavjud bazaga davomidan yig'ish:

```powershell
docker compose run --rm collector python -m app.collector --full-backfill --years-back 5
```

Faqat fon collectorini davom ettirish:

```powershell
docker compose up -d collector
```

Qoidasi oddiy: `--reset-archive` bo'lsa baza tozalanadi, bo'lmasa collector `tender_sync_state`dagi progressdan davom etadi.

Keyin collector doimiy ishlashi uchun:

```powershell
docker compose up -d collector
docker compose logs -f collector
```

PostgreSQL ulanishi:

```text
Host: 127.0.0.1
Port: 55432
Database: tenderai
User: tenderai
Password: tenderai
URL: postgresql://tenderai:tenderai@127.0.0.1:55432/tenderai
```

Bazada nechta yozuv yig'ilganini tekshirish:

```powershell
docker exec -it tenderai-collector-postgres psql -U tenderai -d tenderai -c "select source_name, count(*) from tender_evidences group by source_name order by count(*) desc;"
docker exec -it tenderai-collector-postgres psql -U tenderai -d tenderai -c "select count(*) as evidences from tender_evidences;"
docker exec -it tenderai-collector-postgres psql -U tenderai -d tenderai -c "select count(*) as products from tender_products;"
docker exec -it tenderai-collector-postgres psql -U tenderai -d tenderai -c "select status_name, sum(evidence_count) as count from tender_statuses group by status_name order by count desc;"
```

Keyingi safar kompyuter yoqilganda davom ettirish:

```powershell
cd C:\path\to\tenderai_collector
docker compose up -d
docker compose logs -f collector
```

## 2. Python bilan ishga tushirish

Bu usulda PostgreSQL Docker orqali ishlaydi, collector esa host Python ichida yuradi.

```powershell
cd C:\path\to\tenderai_collector
Copy-Item .env.example .env
docker compose up -d postgres

py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Birinchi to'liq yig'ish:

```powershell
python -m app.collector --reset-archive --full-backfill --years-back 5
```

Doimiy collector:

```powershell
python -m app.collector
```

## Foydali komandalar

Collector statusini ko'rish:

```powershell
docker exec -it tenderai-collector-postgres psql -U tenderai -d tenderai -c "select state_key, updated_at, state_json from tender_sync_state order by updated_at desc limit 20;"
```

Loglarni ko'rish:

```powershell
docker compose logs -f collector
```

Collectorni to'xtatish:

```powershell
docker compose stop collector
```

Hamma servislarni to'xtatish:

```powershell
docker compose down
```

Bazani ham butunlay o'chirish:

```powershell
docker compose down -v
```

## Eslatma

`--full-backfill` yakunlanguncha vaqt oladi. Collector progressni `tender_sync_state` jadvalida saqlaydi, shuning uchun jarayon uzilib qolsa, keyingi ishga tushirishda davom ettiradi.
