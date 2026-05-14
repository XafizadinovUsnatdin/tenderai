import json
import os
import re
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv


load_dotenv()

INPUT_FILE = Path("printer_analysis_result.json")
OUTPUT_FILE = Path("printer_technical_task.json")


def load_analysis() -> dict[str, Any]:
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Fayl topilmadi: {INPUT_FILE}")

    return json.loads(INPUT_FILE.read_text(encoding="utf-8"))


def compact_analysis_for_llm(analysis: dict[str, Any]) -> dict[str, Any]:
    """
    LLMga hamma ma'lumotni emas, eng kerakli qismini beramiz.
    Aks holda token ko'p ketadi.
    """
    evidences = analysis.get("evidences", [])

    compact_evidences = []

    for ev in evidences[:20]:
        compact_evidences.append(
            {
                "lot_display_no": ev.get("lot_display_no"),
                "product_name": ev.get("product_name"),
                "condition": ev.get("condition"),
                "unit_price": ev.get("unit_price"),
                "currency": ev.get("currency"),
                "region": ev.get("customer_region_name"),
                "deal_date": ev.get("deal_date"),
                "deal_status_name": ev.get("deal_status_name"),
                "payment_status": ev.get("kazna_payment_status"),
            }
        )

    return {
        "source": analysis.get("source"),
        "product": analysis.get("product"),
        "raw_deals_count": analysis.get("raw_deals_count"),
        "successful_deals_count": analysis.get("successful_deals_count"),
        "price_analysis": analysis.get("price_analysis"),
        "region_analysis": analysis.get("region_analysis"),
        "common_terms": analysis.get("common_terms"),
        "evidences": compact_evidences,
    }


def build_prompt(analysis: dict[str, Any]) -> str:
    compact = compact_analysis_for_llm(analysis)

    return f"""
Sen bank xaridlari uchun texnik topshiriq tayyorlovchi AI yordamchisan.

Quyida xarid.uzex.uz portalidan olingan printer bo‘yicha muvaffaqiyatli yakunlangan xaridlar tahlili berilgan.

QOIDALAR:
1. Faqat berilgan ma’lumotlarga asoslan.
2. Yangi fakt o‘ylab topma.
3. Agar ma’lumot manbada bo‘lmasa, "manbalarda ko‘rsatilmagan" deb yoz.
4. Javobni o‘zbek tilida yoz.
5. Output faqat valid JSON bo‘lsin. Markdown ishlatma.
6. Narx hisob-kitobini qayta hisoblama, berilgan price_analysis natijasidan foydalan.
7. Aniq brend/modelni asosiy talab sifatida yozma.
8. Epson, Canon yoki boshqa brend/model nomlarini majburiy talab sifatida ishlatma.
9. Agar model nomini eslatish zarur bo‘lsa, faqat "masalan" yoki "yoki texnik jihatdan ekvivalent model" shaklida yoz.
10. Ekonom, Standart, Premium variantlarni model nomi bilan emas, texnik parametrlar darajasi bilan yoz.
11. Risk warning faqat berilgan ma’lumotdan kelib chiqsin.
12. Qatnashchilar soni, tender cheklanganligi, firibgarlik yoki raqobat kamaygani haqida dalil bo‘lmasa, bunday xulosa yozma.
13. Texnik topshiriq adolatli, aniq va raqobatni cheklamaydigan bo‘lsin.
14. Tavsiya etilgan texnik talablar oldingi xaridlarda ko‘p uchragan parametrlar asosida bo‘lsin.

VAZIFA:
Printer xaridi uchun quyidagilarni yarat:
- product_understanding
- previous_tender_insights
- recommended_specification
- econom_variant
- standard_variant
- premium_variant
- price_summary
- risk_warnings
- source_based_notes

recommended_specification ichida quyidagi bo‘limlar bo‘lsin:
- Xarid predmeti
- Umumiy talablar
- Texnik talablar
- Kafolat talabi
- Yetkazib berish va qabul qilish talabi
- Raqobatni cheklamaslik eslatmasi

Ekonom variant:
- minimal, arzon, oddiy ofis ishlari uchun mos parametrlar

Standart variant:
- bank/ofis uchun optimal parametrlar

Premium variant:
- yuqori yuklama, rangli/A3/A3+, tarmoq imkoniyatlari yoki kengaytirilgan funksiyalar

JSON FORMAT:
{{
  "title": "...",
  "product_understanding": "...",
  "previous_tender_insights": "...",
  "recommended_specification": "...",
  "econom_variant": "...",
  "standard_variant": "...",
  "premium_variant": "...",
  "price_summary": "...",
  "risk_warnings": ["...", "..."],
  "source_based_notes": ["...", "..."]
}}

MA’LUMOTLAR:
{json.dumps(compact, ensure_ascii=False, indent=2)}
""".strip()


def extract_json(text: str) -> dict[str, Any]:
    """
    Ba'zan LLM ```json ... ``` ichida qaytarishi mumkin.
    Shuni tozalab, JSON parse qilamiz.
    """
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```json", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"^```", "", text).strip()
        text = re.sub(r"```$", "", text).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise

        return json.loads(match.group(0))


async def call_openrouter(prompt: str) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    model = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY .env ichida yo‘q")

    url = f"{base_url}/chat/completions"

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a procurement technical specification assistant. "
                    "Write in Uzbek. Use only provided evidence. "
                    "Return valid JSON only."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": 0.2,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(url, headers=headers, json=payload)

    if response.status_code != 200:
        raise RuntimeError(
            f"OpenRouter error {response.status_code}: {response.text[:1000]}"
        )

    data = response.json()
    return data["choices"][0]["message"]["content"]


def call_gemini(prompt: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    if not api_key:
        raise RuntimeError("GEMINI_API_KEY .env ichida yo‘q")

    from google import genai

    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config={
            "temperature": 0.2,
            "response_mime_type": "application/json",
        },
    )

    return response.text


async def main():
    analysis = load_analysis()
    prompt = build_prompt(analysis)

    provider = os.getenv("LLM_PROVIDER", "openrouter").lower()

    print("LLM provider:", provider)

    if provider == "openrouter":
        raw_result = await call_openrouter(prompt)
    elif provider == "gemini":
        raw_result = call_gemini(prompt)
    else:
        raise RuntimeError("LLM_PROVIDER faqat openrouter yoki gemini bo‘lishi kerak")

    result_json = extract_json(raw_result)

    final_result = {
        "query": "Принтер",
        "source": analysis.get("source"),
        "price_analysis": analysis.get("price_analysis"),
        "technical_task": result_json,
    }

    OUTPUT_FILE.write_text(
        json.dumps(final_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n✅ Texnik topshiriq tayyorlandi")
    print("Saved to:", OUTPUT_FILE)
    print("\n--- TITLE ---")
    print(result_json.get("title"))
    print("\n--- PRICE SUMMARY ---")
    print(result_json.get("price_summary"))






if __name__ == "__main__":
    import asyncio

    asyncio.run(main())