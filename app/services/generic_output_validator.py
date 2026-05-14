import json
import re
from typing import Any


class GenericOutputValidator:
    """
    Har qanday mahsulot uchun universal LLM guardrail.
    """

    UNSUPPORTED_RISK_PHRASES = [
        "qatnashchilar soni",
        "qatnashuvchilar soni",
        "tenderda qatnashgan",
        "raqobat kamaygan",
        "raqobatni kamaytirishi mumkin",
        "firibgarlik",
        "kelishilgan",
    ]

    DELIVERY_PATTERNS = [
        r"\b\d+\s*kun\b",
        r"\b\d+\s*дн",
        r"\b\d+\s*days\b",
    ]

    def validate(
        self,
        llm_result: dict[str, Any],
        source_data: dict[str, Any],
    ) -> list[str]:
        warnings: list[str] = []

        result_text = json.dumps(llm_result, ensure_ascii=False).lower()
        source_text = json.dumps(source_data, ensure_ascii=False).lower()

        warnings.extend(
            self._check_unsupported_claims(result_text=result_text)
        )

        warnings.extend(
            self._check_delivery_claims(
                result_text=result_text,
                source_text=source_text,
            )
        )

        warnings.extend(
            self._check_price_summary(
                llm_result=llm_result,
                source_data=source_data,
            )
        )

        warnings.extend(
            self._check_brand_model_lock(
                result_text=result_text,
                source_data=source_data,
            )
        )

        return warnings

    def _check_unsupported_claims(self, result_text: str) -> list[str]:
        warnings = []

        for phrase in self.UNSUPPORTED_RISK_PHRASES:
            if phrase in result_text:
                warnings.append(
                    f"Dalilsiz yoki ehtiyotkorlik talab qiladigan xulosa topildi: '{phrase}'. "
                    "Agar evidence ichida bunday ma’lumot bo‘lmasa, bu gapni olib tashlash kerak."
                )

        return warnings

    def _check_delivery_claims(
        self,
        result_text: str,
        source_text: str,
    ) -> list[str]:
        warnings = []

        has_delivery_in_source = any(
            word in source_text
            for word in [
                "yetkazib berish",
                "доставка",
                "поставка",
                "срок поставки",
                "delivery",
            ]
        )

        if has_delivery_in_source:
            return warnings

        for pattern in self.DELIVERY_PATTERNS:
            if re.search(pattern, result_text):
                warnings.append(
                    "LLM yetkazib berish muddatini aniq raqam bilan yozgan, "
                    "lekin source evidence ichida yetkazib berish muddati topilmadi."
                )
                break

        return warnings

    def _check_price_summary(
        self,
        llm_result: dict[str, Any],
        source_data: dict[str, Any],
    ) -> list[str]:
        warnings = []

        expected_wrapper = source_data.get("price_analysis") or {}
        expected = (
            expected_wrapper.get("global")
            if isinstance(expected_wrapper, dict)
            else None
        )
        if not isinstance(expected, dict):
            expected = expected_wrapper if isinstance(expected_wrapper, dict) else {}
        actual = llm_result.get("price_summary") or {}

        if not isinstance(actual, dict):
            warnings.append("price_summary object bo‘lishi kerak.")
            return warnings

        for key in [
            "min_price",
            "max_price",
            "avg_price",
            "median_price",
            "recommended_min_price",
            "recommended_max_price",
        ]:
            if key in actual and actual[key] is not None:
                if key in expected and expected[key] is not None:
                    if float(actual[key]) != float(expected[key]):
                        warnings.append(
                            f"LLM price_summary.{key} qiymatini o‘zgartirgan. "
                            f"Expected={expected[key]}, actual={actual[key]}"
                        )

        return warnings

    def _check_brand_model_lock(
        self,
        result_text: str,
        source_data: dict[str, Any],
    ) -> list[str]:
        """
        Universal brand/model lock detection:
        Source evidence ichidagi modelga o‘xshash tokenlarni topadi.
        Agar LLM ularni ko‘p ishlatib, 'ekvivalent' demagan bo‘lsa warning beradi.
        """
        warnings = []

        source_text = json.dumps(source_data, ensure_ascii=False)

        model_tokens = self._extract_model_like_tokens(source_text)

        if not model_tokens:
            return warnings

        for token in model_tokens[:30]:
            token_lower = token.lower()

            if token_lower not in result_text:
                continue

            # Agar ekvivalent bor bo‘lsa, qisman xavf kamayadi
            nearby_equivalent = (
                "ekvivalent" in result_text
                or "эквивалент" in result_text
                or "equivalent" in result_text
            )

            if not nearby_equivalent:
                warnings.append(
                    f"LLM aniq modelga bog‘lab qo‘ygan bo‘lishi mumkin: {token}. "
                    "Texnik topshiriq modelga emas, parametrga asoslanishi kerak."
                )

        return warnings

    def _extract_model_like_tokens(self, text: str) -> list[str]:
        """
        Har qanday mahsulot uchun modelga o‘xshash tokenlarni topish.
        Masalan:
        L3250, L3260, TL-SG108S, MF3010, MF754Cdw, i-SENSYS.
        """
        patterns = [
            r"\b[A-Z]{1,5}[-]?[A-Z0-9]{2,12}\b",
            r"\b[A-Za-z]+[-]?[A-Za-z]*\d{2,8}[A-Za-z]*\b",
            r"\b\d{2,4}[A-Za-z]{1,5}\b",
        ]

        found = []

        for pattern in patterns:
            found.extend(re.findall(pattern, text))

        blacklist = {
            "RJ45",
            "USB",
            "WI-FI",
            "WIFI",
            "ETHERNET",
            "POE",
            "SFP",
            "LAN",
            "WAN",
            "DPI",
            "GB",
            "TB",
            "SSD",
            "HDD",
            "RAM",
            "CPU",
            "HDMI",
            "VGA",
            "A4",
            "A3",
            "OS",
            "PDF",
            "UZS",
        }

        clean = []

        for token in found:
            token = token.strip()

            if token.upper() in blacklist:
                continue

            if len(token) < 3:
                continue

            clean.append(token)

        return list(dict.fromkeys(clean))
