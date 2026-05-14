import json
import os
import re
from typing import Any

import httpx
from dotenv import load_dotenv

from app.schemas import ProductCandidate


load_dotenv()


class CandidateSelectorService:
    """
    GetProducts’dan chiqqan candidate'lar orasidan user query uchun eng mos product_code ni tanlaydi.
    """

    async def select_best_candidate(
        self,
        user_query: str,
        search_plan: dict[str, Any],
        candidates: list[ProductCandidate],
    ) -> ProductCandidate | None:
        if not candidates:
            return None

        if len(candidates) == 1:
            candidates[0].selection_reason = "Faqat bitta candidate topildi, shuning uchun shu tanlandi."
            return candidates[0]

        prompt = self._build_prompt(user_query, search_plan, candidates)

        raw = await self._call_openrouter(prompt)

        selected_code, reason = self._extract_selection(raw)

        if not selected_code:
            candidates[0].selection_reason = (
                reason
                or "LLM aniq product_code qaytarmadi; ro‘yxatdagi eng yuqori score candidate tanlandi."
            )
            return candidates[0]

        for candidate in candidates:
            if candidate.product_code == selected_code:
                candidate.selection_reason = reason or "LLM tanlovi asosida tanlandi."
                return candidate

        candidates[0].selection_reason = (
            reason
            or "LLM product_code qaytardi, lekin u candidate ro‘yxatida topilmadi; eng yuqori score candidate tanlandi."
        )
        return candidates[0]

    def _build_prompt(
        self,
        user_query: str,
        search_plan: dict[str, Any],
        candidates: list[ProductCandidate],
    ) -> str:
        candidates_json = [
            {
                "product_code": c.product_code,
                "name": c.name,
                "category_id": c.category_id,
                "category_name": c.category_name,
                "score": c.score,
            }
            for c in candidates[:20]
        ]

        return f"""
Sen xarid katalogidan eng mos mahsulotni tanlovchi AI yordamchisan.

Foydalanuvchi so‘rovi:
{user_query}

Query understanding:
{json.dumps(search_plan, ensure_ascii=False, indent=2)}

Candidate ro‘yxati:
{json.dumps(candidates_json, ensure_ascii=False, indent=2)}

Vazifa:
Eng mos product_code ni tanla.

Qoidalar:
1. Brand/modelga qarab umumiy mahsulot turini tanla.
2. Noto‘g‘ri soha candidate'larini chiqarib tashla.
3. Masalan TP-Link switch bo‘lsa "Коммутатор" tanlanadi, "Коммутатор зажигания автомобиля" emas.
4. Printer bo‘lsa "Принтер" tanlanadi, "Картридж", "Лента", "Подставка" emas.
5. Javob faqat JSON bo‘lsin.

JSON format:
{{
  "selected_product_code": "...",
  "reason": "..."
}}
""".strip()

    async def _call_openrouter(self, prompt: str) -> str:
        api_key = os.getenv("OPENROUTER_API_KEY")
        model = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
        base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

        if not api_key:
            return "{}"

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "Return valid JSON only. No markdown."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.1
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload
            )

        if response.status_code != 200:
            return "{}"

        data = response.json()
        return data["choices"][0]["message"]["content"]

    def _extract_selection(self, raw: str) -> tuple[str | None, str | None]:
        try:
            text = raw.strip()

            if text.startswith("```"):
                text = re.sub(r"^```json", "", text, flags=re.IGNORECASE).strip()
                text = re.sub(r"^```", "", text).strip()
                text = re.sub(r"```$", "", text).strip()

            data = json.loads(text)
            return data.get("selected_product_code"), data.get("reason")

        except Exception:
            return None, None
