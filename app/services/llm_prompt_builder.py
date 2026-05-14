import json
from typing import Any

from app.schemas import Evidence, ProductCandidate


class LLMPromptBuilder:
    def build(
        self,
        user_query: str,
        selected_product: ProductCandidate,
        price_analysis: dict[str, Any],
        evidences: list[Evidence],
    ) -> str:
        compact_evidences = []

        for ev in evidences[:25]:
            compact_evidences.append(
                {
                    "lot_display_no": ev.lot_display_no,
                    "product_name": ev.product_name,
                    "category_name": ev.category_name,
                    "condition": ev.condition,
                    "unit_price": ev.unit_price,
                    "currency": ev.currency,
                    "region": ev.region,
                    "deal_date": ev.deal_date,
                    "deal_status_name": ev.deal_status_name,
                    "payment_status": ev.payment_status,
                }
            )

        data = {
            "user_query": user_query,
            "selected_product": {
                "name": selected_product.name,
                "product_code": selected_product.product_code,
                "category_id": selected_product.category_id,
                "category_name": selected_product.category_name,
            },
            "price_analysis": price_analysis,
            "evidences": compact_evidences,
        }

        return f"""
Sen bank xaridlari uchun texnik topshiriq tayyorlovchi AI yordamchisan.

QOIDALAR:
1. Faqat berilgan ma’lumotlarga asoslan.
2. Yangi fakt o‘ylab topma.
3. Agar ma’lumot manbada bo‘lmasa, "manbalarda ko‘rsatilmagan" deb yoz.
4. Javobni o‘zbek tilida yoz.
5. Output faqat valid JSON bo‘lsin. Markdown ishlatma.
6. Narx hisob-kitobini qayta hisoblama, berilgan price_analysis natijasidan foydalan.
7. Aniq brend/modelni asosiy majburiy talab sifatida yozma.
8. Model nomlari uchrasa, ularni faqat "masalan" yoki "yoki texnik jihatdan ekvivalent model" shaklida yoz.
9. Ekonom, Standart, Premium variantlarni model nomi bilan emas, texnik parametrlar darajasi bilan yoz.
10. Risk warning faqat berilgan evidence asosida bo‘lsin.
11. Qatnashchilar soni, tender cheklanganligi, firibgarlik yoki raqobat kamaygani haqida dalil bo‘lmasa, bunday xulosa yozma.
12. Yetkazib berish muddati evidence ichida bo‘lmasa, aniq kun soni yozma.
13. Kafolat evidence ichida uchrasa, uni umumlashtir; bo‘lmasa "manbalarda kafolat muddati aniq ko‘rsatilmagan" deb yoz.
14. Texnik topshiriq adolatli, aniq va raqobatni cheklamaydigan bo‘lsin.

VAZIFA:
Foydalanuvchi so‘rovi bo‘yicha texnik topshiriq loyihasini yarat:
- product_understanding
- previous_tender_insights
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

JSON FORMAT:
{{
  "title": "...",
  "product_understanding": "...",
  "previous_tender_insights": "...",
  "recommended_specification": {{
    "Xarid predmeti": "...",
    "Umumiy talablar": "...",
    "Texnik talablar": ["...", "..."],
    "Kafolat talabi": "...",
    "Yetkazib berish va qabul qilish talabi": "...",
    "Raqobatni cheklamaslik eslatmasi": "..."
  }},
  "econom_variant": {{
    "description": "...",
    "technical_parameters": ["...", "..."]
  }},
  "standard_variant": {{
    "description": "...",
    "technical_parameters": ["...", "..."]
  }},
  "premium_variant": {{
    "description": "...",
    "technical_parameters": ["...", "..."]
  }},
  "price_summary": {{
    "text": "...",
    "min_price": null,
    "max_price": null,
    "avg_price": null,
    "median_price": null,
    "recommended_min_price": null,
    "recommended_max_price": null
  }},
  "risk_warnings": ["...", "..."],
  "source_based_notes": ["...", "..."]
}}

MA’LUMOTLAR:
{json.dumps(data, ensure_ascii=False, indent=2)}
""".strip()