import json
import os
import re
from typing import Any

import httpx
from dotenv import load_dotenv


load_dotenv()


class QueryUnderstandingService:
    """
    Har qanday mahsulot/xizmat nomini portal katalogida qidirishga mos keywordlarga aylantiradi.
    Dictionary ishlatmaydi.
    Asosiy ishni LLM qiladi.
    """

    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "openrouter").lower()

    async def build_search_plan(self, query: str) -> dict[str, Any]:
        prompt = self._build_prompt(query)

        if self.provider == "openrouter":
            raw = await self._call_openrouter(prompt=prompt, query=query)
        else:
            raw = self._fallback_without_llm(query)

        return self._safe_parse_json(raw, query)

    def _build_prompt(self, query: str) -> str:
        return f"""
Sen xarid katalogi uchun qidiruv so‘zlarini tayyorlovchi AI yordamchisan.

Foydalanuvchi mahsulot yoki xizmat nomini yozadi.
Sening vazifang:
1. Bu nima mahsulot/xizmat ekanini tushunish.
2. Xarid.uzex katalogida qidirish uchun ruscha keywordlar berish.
3. Agar brand/model yozilgan bo‘lsa, umumiy mahsulot turini aniqlash.
4. Noto‘g‘ri candidate'larni chiqarib tashlash uchun exclude keywordlar berish.
5. Javobni faqat JSON formatda qaytarish.

Muhim:
- Foydalanuvchi so‘rovi lotincha ham, kirillcha (ruscha yoki o‘zbekcha) ham bo‘lishi mumkin.
- Foydalanuvchi ruscha so‘zlarni lotin harflarida translit qilib yozishi ham mumkin (masalan: "bumaga A4 list").
  Bunday holatda `search_keywords_ru` ichida ruscha kirillcha keywordlarni ber (masalan: ["бумага", "лист", "бумага a4"]).
- Foydalanuvchi so‘rovda imlo xatolari (typo) qilishi mumkin. Shuni to‘g‘rilab tushun va qidiruv keywordlarini xatosiz qaytar.
  Masalan: "konditsioenr" → ["кондиционер", "сплит-система"], "prinetr" → ["принтер"] va h.k.
- Agar so‘rov allaqachon kirill/ruscha bo‘lsa, ma’noni buzmasdan, asosiy mahsulot nomini o‘zgartirmasdan ishlat.
- O‘xshash so‘zlarni adashtirma: masalan "шины" (tyres) so‘zini "машины" (machines/cars) ga almashtirma.
- `search_keywords_ru` ichida kamida bitta keyword foydalanuvchi so‘rovdagi asosiy kirill so‘z(lar)dan aynan o‘z holicha bo‘lsin (agar so‘rovda kirill bo‘lsa).
- Aniq brand/modelni emas, umumiy mahsulot turini top.
- Masalan: "TP-Link TL-SG108S" → "коммутатор", "сетевой коммутатор".
- Masalan: "HP LaserJet" → "принтер", "лазерный принтер".
- Masalan: "konditsioner 12 BTU" → "кондиционер".
- Masalan: "stul" → "стул".
- Masalan: "toner cartridge" → "картридж".
- Masalan: "шины для легковых автомобилей" → "шины", "автомобильные шины", "шина".
- Agar bu xizmat bo‘lsa, is_service=true qil.

JSON format:
{{
  "original_query": "...",
  "detected_item_type": "...",
  "brand": null,
  "model": null,
  "is_service": false,
  "search_keywords_ru": ["...", "..."],
  "search_keywords_uz": ["...", "..."],
  "category_hints_ru": ["...", "..."],
  "exclude_keywords_ru": ["...", "..."],
  "notes": "..."
}}

Foydalanuvchi so‘rovi:
{query}
""".strip()

    async def _call_openrouter(self, prompt: str, query: str) -> str:
        api_key = os.getenv("OPENROUTER_API_KEY")
        model = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
        base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        max_tokens_raw = (os.getenv("OPENROUTER_MAX_TOKENS_SMALL") or "").strip()
        try:
            max_tokens = int(max_tokens_raw) if max_tokens_raw else 1024
            if max_tokens <= 0:
                max_tokens = 1024
        except Exception:
            max_tokens = 1024

        if not api_key:
            return json.dumps(self._fallback_without_llm(query), ensure_ascii=False)

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
            "temperature": 0.1,
            "max_tokens": max_tokens,
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
            return json.dumps(self._fallback_without_llm(query), ensure_ascii=False)

        data = response.json()
        return data["choices"][0]["message"]["content"]

    def _safe_parse_json(self, raw: str, query: str) -> dict[str, Any]:
        try:
            text = raw.strip()

            if text.startswith("```"):
                text = re.sub(r"^```json", "", text, flags=re.IGNORECASE).strip()
                text = re.sub(r"^```", "", text).strip()
                text = re.sub(r"```$", "", text).strip()

            return json.loads(text)

        except Exception:
            return self._fallback_without_llm(query)

    def _fallback_without_llm(self, query: str) -> dict[str, Any]:
        """
        LLM ishlamasa, hech bo‘lmasa original query bilan qidiramiz.
        """
        return {
            "original_query": query,
            "detected_item_type": query,
            "brand": None,
            "model": None,
            "is_service": False,
            "search_keywords_ru": [query],
            "search_keywords_uz": [query],
            "category_hints_ru": [],
            "exclude_keywords_ru": [],
            "notes": "LLM ishlamagani sababli original query ishlatildi."
        }
