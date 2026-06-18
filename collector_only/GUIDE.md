# TenderAI Collector Guide

Bu guide yangi kompyuterda bazani ko'chirmasdan, scraping orqali ma'lumotni qayta yig'ish uchun.

## Talablar

- Docker Desktop
- Git
- Internet access
- Kamida 5-10 GB bo'sh disk joy

Python bilan ishlatmoqchi bo'lsangiz:

- Python 3.12

## 1. Repositoryni olish

```powershell
git clone https://github.com/XafizadinovUsnatdin/tenderai_collector.git
cd tenderai_collector
```

## 2. Environment yaratish

```powershell
Copy-Item .env.example .env
```

Default `.env` qiymatlari:

```text
POSTGRES_DB=tenderai
POSTGRES_USER=tenderai
POSTGRES_PASSWORD=tenderai
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=55432
TENDER_ARCHIVE_DATABASE_URL=postgresql://tenderai:tenderai@127.0.0.1:55432/tenderai
```

Port `55432` band bo'lsa, `.env` ichidagi `POSTGRES_PORT`ni boshqa portga almashtiring.

## 3. PostgreSQLni ishga tushirish

```powershell
docker compose up -d postgres
```

Postgres tayyorligini tekshirish:

```powershell
docker compose ps
```

## 4. Collector image build qilish

```powershell
docker compose build collector
```

## 5. Birinchi to'liq yig'ish

Bu komanda bazani tozalaydi, schema yaratadi va oxirgi 5 yil uchun ma'lumotlarni yig'adi:

```powershell
docker compose run --rm collector python -m app.collector --reset-archive --full-backfill --years-back 5
```

Collector statusidan qat'i nazar barcha public rowlarni yig'adi. Ya'ni faqat `Поставлена` yoki `Оплачена` emas, `Расторжена`, `Новая`, `Не оплачен` va boshqa holatlar ham bazaga yoziladi.

Muhim: `--reset-archive` bazani tozalaydi. Jarayon uzilib qolsa, davom ettirishda `--reset-archive` ishlatmang:

```powershell
docker compose run --rm collector python -m app.collector --full-backfill --years-back 5
```

## 5.1. Reset yoki davom ettirish

Quyidagi komanda mavjud bazani o'chirib, hammasini noldan qayta yig'adi:

```powershell
docker compose run --rm collector python -m app.collector --reset-archive --full-backfill --years-back 5
```

Quyidagi komanda mavjud bazani o'chirmaydi. Collector `tender_sync_state` jadvalidagi progressdan davom etadi:

```powershell
docker compose run --rm collector python -m app.collector --full-backfill --years-back 5
```

Quyidagi komanda collectorni fonda ishga tushirib, keyingi cycle'lardan davom ettiradi:

```powershell
docker compose up -d collector
```

Qisqa qoida: `--reset-archive` ishlatilsa baza tozalanadi; ishlatilmasa mavjud baza saqlanadi.

## 6. Doimiy collector

Backfill tugagandan keyin collectorni fonda doimiy ishlating:

```powershell
docker compose up -d collector
docker compose logs -f collector
```

Collector har `TENDER_ARCHIVE_SYNC_INTERVAL_SECONDS` sekundda yangi cycle ishlaydi. Default: 300 sekund.

## 7. Bazani tekshirish

Umumiy evidence soni:

```powershell
docker exec -it tenderai-collector-postgres psql -U tenderai -d tenderai -c "select count(*) as evidences from tender_evidences;"
```

Source bo'yicha breakdown:

```powershell
docker exec -it tenderai-collector-postgres psql -U tenderai -d tenderai -c "select source_name, count(*) from tender_evidences group by source_name order by count(*) desc;"
```

Product catalog soni:

```powershell
docker exec -it tenderai-collector-postgres psql -U tenderai -d tenderai -c "select count(*) as products from tender_products;"
```

Statuslar:

```powershell
docker exec -it tenderai-collector-postgres psql -U tenderai -d tenderai -c "select status_name, sum(evidence_count) as count from tender_statuses group by status_name order by count desc;"
```

Collector progress state:

```powershell
docker exec -it tenderai-collector-postgres psql -U tenderai -d tenderai -c "select state_key, updated_at, state_json from tender_sync_state order by updated_at desc limit 20;"
```

## 8. Python orqali ishlatish

Docker faqat PostgreSQL uchun, collector esa lokal Python ichida ishlaydi:

```powershell
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

Doimiy ishlatish:

```powershell
python -m app.collector
```

## 9. To'xtatish va tozalash

Collectorni to'xtatish:

```powershell
docker compose stop collector
```

Hamma servislarni to'xtatish:

```powershell
docker compose down
```

Bazani ham o'chirish:

```powershell
docker compose down -v
```

## 10. Ulanish ma'lumotlari

Host kompyuterdan ulanish:

```text
Host: 127.0.0.1
Port: 55432
Database: tenderai
User: tenderai
Password: tenderai
URL: postgresql://tenderai:tenderai@127.0.0.1:55432/tenderai
```

Docker network ichidan ulanish:

```text
Host: postgres
Port: 5432
Database: tenderai
User: tenderai
Password: tenderai
URL: postgresql://tenderai:tenderai@postgres:5432/tenderai
```
