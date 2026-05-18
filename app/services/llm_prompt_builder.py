import json
from typing import Any

from app.schemas import Evidence, ProductCandidate


class LLMPromptBuilder:
    def build(
        self,
        user_query: str,
        selected_product: ProductCandidate | None,
        source_status: dict[str, Any],
        price_analysis: dict[str, Any],
        evidences_by_source: dict[str, list[Evidence]],
    ) -> str:
        evidence_summaries: dict[str, Any] = {}
        compact_by_source: dict[str, list[dict[str, Any]]] = {}

        for source, evidences in evidences_by_source.items():
            price_eligible_count = sum(
                1 for ev in evidences if isinstance(ev.unit_price, (int, float))
            )
            evidence_summaries[source] = {
                "total_evidences": len(evidences),
                "price_eligible_count": price_eligible_count,
            }

            compact: list[dict[str, Any]] = []

            for ev in evidences[:20]:
                compact.append(
                    {
                        "source_name": ev.source_name,
                        "source_type": ev.source_type,
                        "source_url": ev.source_url,
                        "lot_id": ev.lot_id,
                        "lot_display_no": ev.lot_display_no,
                        "product_name": ev.product_name,
                        "category_name": ev.category_name,
                        "condition": ev.condition,
                        "amount": ev.amount,
                        "deal_cost": ev.deal_cost,
                        "unit_price": ev.unit_price,
                        "currency": ev.currency,
                        "region": ev.region,
                        "customer_name": ev.customer_name,
                        "customer_inn": ev.customer_inn,
                        "provider_name": ev.provider_name,
                        "provider_inn": ev.provider_inn,
                        "participants_count": ev.participants_count,
                        "start_cost": ev.start_cost,
                        "deal_date": ev.deal_date,
                        "deal_status_name": ev.deal_status_name,
                        "payment_status": ev.payment_status,
                        "contract_file_name": ev.contract_file_name,
                        "contract_file_path": ev.contract_file_path,
                        "additional_protocol_file_name": ev.additional_protocol_file_name,
                        "additional_protocol_file_path": ev.additional_protocol_file_path,
                        "raw_text": ev.raw_text,
                    }
                )

            compact_by_source[source] = compact

        selected_product_block = (
            {
                "name": selected_product.name,
                "product_code": selected_product.product_code,
                "category_id": selected_product.category_id,
                "category_name": selected_product.category_name,
                "selection_reason": getattr(selected_product, "selection_reason", None),
            }
            if selected_product is not None
            else None
        )

        data = {
            "user_query": user_query,
            "selected_product": selected_product_block,
            "source_status": source_status,
            "price_analysis": price_analysis,
            "evidence_summaries": evidence_summaries,
            "evidences_by_source": compact_by_source,
        }

        return f"""
Sen bank xaridlari uchun texnik topshiriq tayyorlovchi AI yordamchisan.

QOIDALAR:
1. Faqat berilgan ma’lumotlarga asoslan.
2. Yangi fakt o‘ylab topma.
3. Agar ma’lumot manbada bo‘lmasa, \"manbalarda ko‘rsatilmagan\" deb yoz.
4. Javobni o‘zbek tilida yoz.
5. Output faqat valid JSON bo‘lsin. Markdown ishlatma.
6. Narx hisob-kitobini qayta hisoblama, faqat `price_analysis.global` natijasidan foydalan.
7. Xarid.uzex.uz completed deals ichida unit_price bor (deal_cost/amount) — per-unit narx tahlili shundan olinadi.
8. Etender.uzex.uz DealsList ichida amount/quantity bo‘lmasligi mumkin — etender `deal_cost` ni unit_price sifatida talqin qilma.
9. Aniq brend/modelni asosiy majburiy talab sifatida yozma.
10. Model nomlari uchrasa, ularni faqat \"masalan\" yoki \"yoki texnik jihatdan ekvivalent model\" shaklida yoz.
11. Ekonom/Standart/Premium variantlarni model nomi bilan emas, texnik parametrlar darajasi bilan yoz.
12. Risk warning faqat berilgan evidence asosida bo‘lsin.
13. Qatnashchilar soni, tender cheklanganligi, firibgarlik yoki raqobat kamaygani haqida dalil bo‘lmasa, bunday xulosa yozma.
14. Yetkazib berish muddati evidence ichida bo‘lmasa, aniq kun soni yozma.
15. Texnik topshiriq adolatli, aniq va raqobatni cheklamaydigan bo‘lsin.
16. Ekonom/Standart/Premium variantlarida `technical_parameters` ro‘yxatini imkon qadar batafsil yoz:
    - kamida 10 ta band berishga harakat qil
    - har bir band "Parametr: qiymat" ko‘rinishida bo‘lsin (masalan: "Portlar soni: 8 ta")
    - faqat evidence ichida uchragan yoki aniq xulosa qilinadigan (model/brandga bog‘lamaydigan) parametrlarni yoz
    - agar parametr manbalarda yo‘q bo‘lsa, "manbalarda ko‘rsatilmagan" deb yoz (taxmin qilma)

VAZIFA:
Foydalanuvchi so‘rovi bo‘yicha texnik topshiriq loyihasini yarat:
- product_understanding
- previous_tender_insights
- source_comparison
- recommended_specification
- econom_variant
- standard_variant
- premium_variant
- price_summary
- risk_warnings
- source_based_notes

recommended_specification ichida:
- Xarid predmeti
- Umumiy talablar
- Texnik talablar
- Kafolat talabi
- Yetkazib berish va qabul qilish talabi
- Raqobatni cheklamaslik eslatmasi

`recommended_specification["Texnik talablar"]` bo‘yicha:
- imkon qadar 12–20 ta band yoz
- bandlar evidence matnidan (condition/raw_text) ajratilgan bo‘lsin
- aniq bo‘lmagan joylarda "manbalarda ko‘rsatilmagan" deb yoz

JSON FORMAT:
{{
  \"title\": \"...\",
  \"product_understanding\": \"...\",
  \"previous_tender_insights\": \"...\",
  \"source_comparison\": {{
    \"xarid_uzex\": \"...\",
    \"etender_uzex\": \"...\"
  }},
  \"recommended_specification\": {{
    \"Xarid predmeti\": \"...\",
    \"Umumiy talablar\": \"...\",
    \"Texnik talablar\": [\"...\", \"...\"],
    \"Kafolat talabi\": \"...\",
    \"Yetkazib berish va qabul qilish talabi\": \"...\",
    \"Raqobatni cheklamaslik eslatmasi\": \"...\"
  }},
  \"econom_variant\": {{
    \"description\": \"...\",
    \"technical_parameters\": [\"...\", \"...\"]
  }},
  \"standard_variant\": {{
    \"description\": \"...\",
    \"technical_parameters\": [\"...\", \"...\"]
  }},
  \"premium_variant\": {{
    \"description\": \"...\",
    \"technical_parameters\": [\"...\", \"...\"]
  }},
  \"price_summary\": {{
    \"text\": \"...\",
    \"min_price\": null,
    \"max_price\": null,
    \"avg_price\": null,
    \"median_price\": null,
    \"recommended_min_price\": null,
    \"recommended_max_price\": null
  }},
  \"risk_warnings\": [\"...\"],
  \"source_based_notes\": {{
    \"xarid.uzex.uz\": [\"...\"],
    \"etender.uzex.uz\": [\"...\"]
  }}
}}

MA’LUMOTLAR:
{json.dumps(data, ensure_ascii=False, indent=2)}
""".strip()
