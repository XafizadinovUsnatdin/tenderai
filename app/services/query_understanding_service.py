import json
import os
import re
from typing import Any

import httpx
from dotenv import load_dotenv

from app.services.env_config import (
    get_openrouter_api_key,
    get_openrouter_base_url,
    get_openrouter_max_tokens_small,
    get_openrouter_model,
)

load_dotenv()

_RU_LATIN_MULTI = [
    ("shch", "щ"),
    ("sch", "щ"),
    ("yo", "ё"),
    ("zh", "ж"),
    ("kh", "х"),
    ("ts", "ц"),
    ("ch", "ч"),
    ("sh", "ш"),
    ("yu", "ю"),
    ("ya", "я"),
    ("ye", "е"),
]

_RU_LATIN_SINGLE = {
    "a": "а",
    "b": "б",
    "v": "в",
    "g": "г",
    "d": "д",
    "e": "е",
    "z": "з",
    "i": "и",
    "j": "й",
    "k": "к",
    "l": "л",
    "m": "м",
    "n": "н",
    "o": "о",
    "p": "п",
    "r": "р",
    "s": "с",
    "t": "т",
    "u": "у",
    "f": "ф",
    "h": "х",
    "y": "ы",
    "q": "к",
    "w": "в",
}


class QueryUnderstandingService:
    """
    Har qanday mahsulot/xizmat nomini portal katalogida qidirishga mos keywordlarga aylantiradi.
    Dictionary ishlatmaydi.
    Asosiy ishni LLM qiladi.
    """

    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "openrouter").lower()

    async def build_search_plan(self, query: str) -> dict[str, Any]:
        if self.provider != "openrouter":
            return self._fallback_without_llm(query)

        prompt = self._build_prompt(query)
        raw = await self._call_openrouter(prompt=prompt, query=query)
        parsed = self._parse_json(raw)

        if parsed is None:
            retry_prompt = self._build_retry_prompt(query)
            retry_tokens = max(get_openrouter_max_tokens_small(), 2048)
            retry_raw = await self._call_openrouter(
                prompt=retry_prompt,
                query=query,
                max_tokens=retry_tokens,
            )
            parsed = self._parse_json(retry_raw)

        if parsed is None:
            return self._fallback_without_llm(query)

        return self._normalize_plan(parsed, query)

    def _build_prompt(self, query: str) -> str:
        translit_hint = self._build_translit_hint(query)
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
- Javob juda ixcham bo‘lsin: `notes` bitta qisqa gap, ro‘yxatlar 2-4 tadan oshmasin.
- JSON tashqarisida hech narsa yozma.
- Masalan: "TP-Link TL-SG108S" → "коммутатор", "сетевой коммутатор".
- Masalan: "HP LaserJet" → "принтер", "лазерный принтер".
- Masalan: "konditsioner 12 BTU" → "кондиционер".
- Masalan: "stul" → "стул".
- Masalan: "stol ofisniy" → "стол", "офисный стол".
- Masalan: "toner cartridge" → "картридж".
- Masalan: "шины для легковых автомобилей" → "шины", "автомобильные шины", "шина".
- Agar bu xizmat bo‘lsa, is_service=true qil.
{translit_hint}

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

    def _build_retry_prompt(self, query: str) -> str:
        translit_hint = self._build_translit_hint(query)
        return f"""
Return exactly one compact JSON object. No markdown. No code fences. No explanations.

Schema:
{{
  "original_query": "{query}",
  "detected_item_type": "...",
  "brand": null,
  "model": null,
  "is_service": false,
  "search_keywords_ru": ["..."],
  "search_keywords_uz": ["..."],
  "category_hints_ru": ["..."],
  "exclude_keywords_ru": ["..."],
  "notes": "..."
}}

Rules:
- detected_item_type: short generic product or service type.
- brand/model: fill only if clearly present, otherwise null.
- search_keywords_ru: 2-4 short Russian Cyrillic phrases.
- search_keywords_uz: 1-3 short Uzbek or Latin phrases.
- category_hints_ru: 0-2 short items.
- exclude_keywords_ru: 0-3 short items.
- notes: one short sentence only.
- Example: "stol ofisniy" -> detected_item_type "стол", search_keywords_ru ["стол", "офисный стол"].
{translit_hint}

Query: {query}
""".strip()

    def _build_translit_hint(self, query: str) -> str:
        translit = self._transliterate_ru_latin_to_cyrillic(query)
        if not translit or translit.strip().lower() == query.strip().lower():
            return ""
        return f'- Possible Cyrillic transliteration of the query: "{translit}". Use it only if semantically correct.'

    def _transliterate_ru_latin_to_cyrillic(self, text: str) -> str:
        if not text:
            return ""
        if re.search(r"[\u0400-\u04FF]", text):
            return ""
        if not re.search(r"[a-zA-Z]", text):
            return ""

        src = text.lower()
        out: list[str] = []
        index = 0

        while index < len(src):
            matched = False
            for latin, cyr in _RU_LATIN_MULTI:
                if src.startswith(latin, index):
                    out.append(cyr)
                    index += len(latin)
                    matched = True
                    break

            if matched:
                continue

            char = src[index]
            mapped = _RU_LATIN_SINGLE.get(char)
            out.append(mapped if mapped is not None else text[index])
            index += 1

        return "".join(out)

    async def _call_openrouter(self, prompt: str, query: str, *, max_tokens: int | None = None) -> str:
        api_key = get_openrouter_api_key()
        model = get_openrouter_model()
        base_url = get_openrouter_base_url()
        completion_tokens = max_tokens or get_openrouter_max_tokens_small()

        if not api_key:
            return ""

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "Return one compact valid JSON object only. No markdown. No code fences. No explanation."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0,
            "max_tokens": completion_tokens,
            "response_format": {"type": "json_object"},
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

            if response.status_code in {400, 422}:
                body_text = (response.text or "")[:1000].lower()
                if "response_format" in body_text or "json_object" in body_text:
                    payload_no_format = dict(payload)
                    payload_no_format.pop("response_format", None)
                    response = await client.post(
                        f"{base_url}/chat/completions",
                        headers=headers,
                        json=payload_no_format
                    )

        if response.status_code != 200:
            return ""

        data = response.json()
        choice0 = data["choices"][0] if isinstance(data.get("choices"), list) and data.get("choices") else {}
        message = choice0.get("message") if isinstance(choice0, dict) else {}
        content = message.get("content") if isinstance(message, dict) else None
        return content if isinstance(content, str) else ""

    def _parse_json(self, raw: str) -> dict[str, Any] | None:
        if not isinstance(raw, str) or not raw.strip():
            return None

        text = raw.strip()

        if text.startswith("```"):
            text = re.sub(r"^```json", "", text, flags=re.IGNORECASE).strip()
            text = re.sub(r"^```", "", text).strip()
            text = re.sub(r"```$", "", text).strip()

        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]

        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except Exception:
            return self._repair_truncated_json(text)

    def _repair_truncated_json(self, text: str) -> dict[str, Any] | None:
        if not text.startswith("{"):
            return None

        trimmed = text.rstrip(", \r\n\t")
        if trimmed != text:
            try:
                data = json.loads(f"{trimmed}}}")
                return data if isinstance(data, dict) else None
            except Exception:
                pass

        for comma_index in reversed(self._top_level_comma_positions(text)):
            candidate = f"{text[:comma_index].rstrip()}}}"
            try:
                data = json.loads(candidate)
                return data if isinstance(data, dict) else None
            except Exception:
                continue

        return None

    def _top_level_comma_positions(self, text: str) -> list[int]:
        positions: list[int] = []
        depth = 0
        in_string = False
        escape = False

        for index, char in enumerate(text):
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
                continue
            if char in "{[":
                depth += 1
                continue
            if char in "}]":
                depth = max(0, depth - 1)
                continue
            if char == "," and depth == 1:
                positions.append(index)

        return positions

    def _normalize_plan(self, data: dict[str, Any], query: str) -> dict[str, Any]:
        return {
            "original_query": self._clean_string(data.get("original_query")) or query,
            "detected_item_type": self._clean_string(data.get("detected_item_type")) or query,
            "brand": self._clean_string(data.get("brand")),
            "model": self._clean_string(data.get("model")),
            "is_service": self._coerce_bool(data.get("is_service")),
            "search_keywords_ru": self._clean_string_list(data.get("search_keywords_ru")) or [query],
            "search_keywords_uz": self._clean_string_list(data.get("search_keywords_uz")) or [query],
            "category_hints_ru": self._clean_string_list(data.get("category_hints_ru")),
            "exclude_keywords_ru": self._clean_string_list(data.get("exclude_keywords_ru")),
            "notes": self._clean_string(data.get("notes")) or "LLM asosida qidiruv rejasi tuzildi.",
        }

    def _clean_string(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _clean_string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []

        unique: list[str] = []
        for item in value:
            text = self._clean_string(item)
            if text and text not in unique:
                unique.append(text)
        return unique[:8]

    def _coerce_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes"}
        if isinstance(value, (int, float)):
            return bool(value)
        return False

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
