import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from app.connectors.xarid_uzex_connector import XaridUzexConnector
from app.services.query_understanding_service import QueryUnderstandingService
from app.services.candidate_selector_service import CandidateSelectorService
from app.services.price_analysis_service import PriceAnalysisService
from app.services.llm_prompt_builder import LLMPromptBuilder
from app.services.generic_output_validator import GenericOutputValidator


load_dotenv()


def extract_json(text: str) -> dict[str, Any]:
    """
    LLM ba'zan ```json ... ``` ichida qaytarishi mumkin.
    Shuni tozalab JSON parse qilamiz.
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

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a procurement technical specification assistant. "
                    "Write in Uzbek. Use only provided evidence. "
                    "Return valid JSON only. No markdown."
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
        response = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
        )

    if response.status_code != 200:
        raise RuntimeError(
            f"OpenRouter error {response.status_code}: {response.text[:1000]}"
        )

    data = response.json()
    return data["choices"][0]["message"]["content"]


async def main():
    user_query = input("Mahsulot nomini kiriting: ").strip()

    if not user_query:
        print("Mahsulot nomi bo‘sh bo‘lishi mumkin emas.")
        return

    query_service = QueryUnderstandingService()
    candidate_selector = CandidateSelectorService()
    connector = XaridUzexConnector()
    price_service = PriceAnalysisService()
    prompt_builder = LLMPromptBuilder()
    validator = GenericOutputValidator()

    print("\n1) Query understanding qilinyapti...")

    search_plan = await query_service.build_search_plan(user_query)

    print("\n--- SEARCH PLAN ---")
    print(json.dumps(search_plan, ensure_ascii=False, indent=2))

    keywords = (
        search_plan.get("search_keywords_ru", [])
        + search_plan.get("search_keywords_uz", [])
    )

    keywords = list(dict.fromkeys([k for k in keywords if k]))

    if not keywords:
        print("Qidiruv keywordlari topilmadi.")
        return

    print("\nGenerated keywords:", keywords)

    print("\n2) Xarid.uzex katalogidan product candidate qidirilyapti...")

    candidates = await connector.find_product_candidates(
        keywords=keywords,
        max_candidates=15,
    )

    if not candidates:
        print("Product candidate topilmadi.")
        return

    print("\n--- PRODUCT CANDIDATES ---")
    for idx, candidate in enumerate(candidates, start=1):
        print(
            idx,
            candidate.name,
            "| code:",
            candidate.product_code,
            "| category:",
            candidate.category_name,
            "| score:",
            candidate.score,
        )

    print("\n3) Eng mos product_code LLM orqali tanlanyapti...")

    selected = await candidate_selector.select_best_candidate(
        user_query=user_query,
        search_plan=search_plan,
        candidates=candidates,
    )

    if selected is None:
        print("Mos product candidate tanlanmadi.")
        return

    print("\n--- SELECTED PRODUCT ---")
    print("Name:", selected.name)
    print("Code:", selected.product_code)
    print("Category:", selected.category_name)
    print("Score:", selected.score)

    print("\n4) Completed deals olinmoqda...")

    evidences = await connector.collect_evidences_for_candidate(
        candidate=selected,
        year_id=2026,
        page_size=20,
        max_pages=3,
    )

    print("Evidence count:", len(evidences))

    if not evidences:
        print("Bu product_code bo‘yicha muvaffaqiyatli bitim topilmadi.")
        return

    print("\n5) Narx tahlili qilinyapti...")

    price_analysis = price_service.analyze(evidences)

    print("\n--- PRICE ANALYSIS ---")
    print(json.dumps(price_analysis, ensure_ascii=False, indent=2))

    source_data = {
        "user_query": user_query,
        "keywords": keywords,
        "search_plan": search_plan,
        "selected_product": {
            "name": selected.name,
            "product_code": selected.product_code,
            "category_id": selected.category_id,
            "category_name": selected.category_name,
        },
        "price_analysis": price_analysis,
        "evidences": [
            {
                "lot_display_no": ev.lot_display_no,
                "product_name": ev.product_name,
                "category_name": ev.category_name,
                "condition": ev.condition,
                "unit_price": ev.unit_price,
                "region": ev.region,
                "deal_date": ev.deal_date,
                "deal_status_name": ev.deal_status_name,
                "payment_status": ev.payment_status,
            }
            for ev in evidences[:30]
        ],
    }

    print("\n6) Texnik topshiriq prompt tayyorlanyapti...")

    prompt = prompt_builder.build(
        user_query=user_query,
        selected_product=selected,
        price_analysis=price_analysis,
        evidences=evidences,
    )

    print("\n7) LLM texnik topshiriq generatsiya qilyapti...")

    raw_llm = await call_openrouter(prompt)
    llm_result = extract_json(raw_llm)

    print("\n8) LLM javobi validator orqali tekshirilyapti...")

    validation_warnings = validator.validate(
        llm_result=llm_result,
        source_data=source_data,
    )

    final_result = {
        "query": user_query,
        "source": "xarid.uzex.uz",
        "keywords": keywords,
        "search_plan": search_plan,
        "selected_product": source_data["selected_product"],
        "price_analysis": price_analysis,
        "technical_task": llm_result,
        "validation_warnings": validation_warnings,
    }

    safe_name = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ_-]+", "_", user_query).strip("_")
    output_path = Path(f"{safe_name}_result.json")

    output_path.write_text(
        json.dumps(final_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n✅ Tayyor")
    print("Saved to:", output_path)

    print("\n--- TITLE ---")
    print(llm_result.get("title"))

    print("\n--- SELECTED PRODUCT ---")
    print(source_data["selected_product"])

    print("\n--- PRICE SUMMARY ---")
    print(json.dumps(price_analysis, ensure_ascii=False, indent=2))

    if validation_warnings:
        print("\n⚠️ VALIDATION WARNINGS:")
        for warning in validation_warnings:
            print("-", warning)


if __name__ == "__main__":
    asyncio.run(main())