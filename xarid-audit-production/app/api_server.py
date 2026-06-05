import json
import os
import re
import asyncio
import html
from typing import Any
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
import httpx
import logging
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.connectors.xarid_uzex_connector import XaridUzexConnector
from app.schemas import ProductCandidate
from app.services.query_understanding_service import QueryUnderstandingService
from app.services.price_analysis_service import PriceAnalysisService
from app.services.llm_prompt_builder import LLMPromptBuilder
from app.services.generic_output_validator import GenericOutputValidator
from app.services.search_orchestrator import SearchOrchestrator
from app.services.env_config import (
    env_str,
    get_gemini_api_key,
    get_gemini_api_version,
    get_gemini_base_url,
    get_gemini_max_output_tokens,
    get_gemini_model,
    get_openrouter_api_key,
    get_openrouter_base_url,
    get_openrouter_max_tokens,
    get_openrouter_max_tokens_small,
    get_openrouter_model,
)


load_dotenv()

logger = logging.getLogger("tenderai.api")

app = FastAPI(
    title="TenderAI API",
    description="Xarid.uzex.uz asosida texnik topshiriq va narx tahlili generatsiya qilish API",
    version="1.0.0",
)

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIST_DIR = ROOT_DIR / "frontend" / "dist"
FRONTEND_INDEX_FILE = FRONTEND_DIST_DIR / "index.html"


@app.on_event("startup")
async def _log_runtime_config():
    api_key_present = bool(get_openrouter_api_key())
    api_key_len = len(get_openrouter_api_key() or "")
    model = get_openrouter_model()
    base_url = get_openrouter_base_url()
    railway_env = env_str("RAILWAY_ENVIRONMENT_NAME") or env_str("RAILWAY_ENVIRONMENT") or None
    service_name = env_str("RAILWAY_SERVICE_NAME")

    logger.info(
        "Runtime config: openrouter_key_present=%s openrouter_key_len=%s model=%s base_url=%s railway_env=%s railway_service=%s",
        api_key_present,
        api_key_len,
        model,
        base_url,
        railway_env,
        service_name,
    )


def _parse_cors_origins() -> tuple[list[str], bool]:
    raw = (os.getenv("CORS_ORIGINS") or "").strip()
    if raw:
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        if origins == ["*"]:
            return origins, False
        return origins, True

    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ], True


cors_origins, cors_allow_credentials = _parse_cors_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    query: str = Field(..., min_length=2)
    period_months: int = Field(default=12, ge=1, le=60)
    enabled_sources: list[str] | None = None
    # Optional: manual candidate selection from UI
    selected_candidate: dict[str, Any] | None = None
    selected_candidates: list[dict[str, Any]] | None = None
    # Optional: pass candidates/keywords/search_plan from `/api/candidates` to avoid recomputing.
    candidates: list[dict[str, Any]] | None = None
    keywords: list[str] | None = None
    search_plan: dict[str, Any] | None = None


class CandidatesRequest(BaseModel):
    query: str = Field(..., min_length=2)
    enabled_sources: list[str] | None = None
    max_candidates: int = Field(default=15, ge=1, le=50)


class InternetRequest(BaseModel):
    query: str = Field(..., min_length=2)


def extract_json(text: str) -> dict[str, Any]:
    def _strip_code_fences(value: str) -> str:
        value = value.strip()
        if value.startswith("```"):
            value = re.sub(r"^```json", "", value, flags=re.IGNORECASE).strip()
            value = re.sub(r"^```", "", value).strip()
            value = re.sub(r"```$", "", value).strip()
        return value

    def _normalize_quotes(value: str) -> str:
        return (
            value.replace("\ufeff", "")
            .replace("“", '"')
            .replace("”", '"')
            .replace("„", '"')
            .replace("’", "'")
            .replace("‘", "'")
        )

    def _extract_balanced_object(value: str) -> str | None:
        start = value.find("{")
        if start == -1:
            return None

        depth = 0
        in_string = False
        escaped = False

        for index in range(start, len(value)):
            char = value[index]

            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return value[start:index + 1]

        return None

    def _quote_unquoted_keys(value: str) -> str:
        pattern = re.compile(r'([{\s,]\s*)([A-Za-z_\u0400-\u04FF][^:{}\[\],"\n\r]*?)(\s*:)')
        repaired = value
        for _ in range(3):
            updated = pattern.sub(
                lambda match: f'{match.group(1)}"{match.group(2).strip()}"{match.group(3)}',
                repaired,
            )
            if updated == repaired:
                break
            repaired = updated
        return repaired

    def _repair_common_json_issues(value: str) -> str:
        repaired = _normalize_quotes(value)
        key_starts = r'(?:"[^"]+"|[A-Za-z_\u0400-\u04FF][^:{}\[\],"\n\r]*?)\s*:'
        next_item_starts = rf'(?:{key_starts}|"(?!\s*:)|[{{\[]|-?[0-9]|true\b|false\b|null\b)'
        repaired = re.sub(r"(?m)^\s*//.*$", "", repaired)
        repaired = re.sub(r"/\*.*?\*/", "", repaired, flags=re.DOTALL)
        repaired = re.sub(r"([{,]\s*)'([^'\n\r]+?)'(\s*:)", r'\1"\2"\3', repaired)
        repaired = _quote_unquoted_keys(repaired)
        repaired = re.sub(
            rf'(:\s*)\'([^\'\\]*(?:\\.[^\'\\]*)*)\'(?=\s*(?:[,}}\]]|{next_item_starts}))',
            lambda match: f'{match.group(1)}"{match.group(2).replace(chr(34), r"\"")}"',
            repaired,
        )
        repaired = re.sub(r"\bNone\b", "null", repaired)
        repaired = re.sub(r"\bTrue\b", "true", repaired)
        repaired = re.sub(r"\bFalse\b", "false", repaired)
        repaired = re.sub(r",(\s*[}\]])", r"\1", repaired)
        repaired = re.sub(rf'(["}}\]])(\s*)(?={next_item_starts})', r"\1,\2", repaired)
        repaired = re.sub(rf'([0-9])(\s*)(?={next_item_starts})', r"\1,\2", repaired)
        repaired = re.sub(rf'\b(true|false|null)(\s*)(?={next_item_starts})', r"\1,\2", repaired)
        return repaired

    raw_text = _normalize_quotes(_strip_code_fences(text))
    candidates = [raw_text]

    balanced = _extract_balanced_object(raw_text)
    if balanced and balanced not in candidates:
        candidates.append(balanced)

    if balanced:
        repaired = _repair_common_json_issues(balanced)
        if repaired not in candidates:
            candidates.append(repaired)

    repaired_raw = _repair_common_json_issues(raw_text)
    if repaired_raw not in candidates:
        candidates.append(repaired_raw)

    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    raise json.JSONDecodeError("No JSON object found", raw_text, 0)


_RU_STOPWORDS = {
    "и",
    "в",
    "во",
    "на",
    "по",
    "с",
    "со",
    "к",
    "ко",
    "от",
    "из",
    "у",
    "для",
    "или",
    "без",
    "при",
    "над",
    "под",
    "про",
    "об",
    "о",
    "до",
    "за",
}


def extract_query_cyrillic_keywords(query: str, max_items: int = 2) -> list[str]:
    """
    Query kirillcha bo‘lsa, LLM xato tushunib yubormasligi uchun original so‘rovdan ham 1-2 ta seed keyword ajratamiz.
    Masalan: "шины для легковых автомобилей" -> ["шины", "автомобилей"] (stopwordlar tashlanadi).
    """
    if not query:
        return []

    tokens = re.findall("[\u0400-\u04FF]{3,}", query.lower())
    tokens = [t for t in tokens if t not in _RU_STOPWORDS]

    unique: list[str] = []
    for t in tokens:
        if t not in unique:
            unique.append(t)

    if not unique:
        return []

    first = unique[0]
    longest = max(unique, key=len)
    out = [first]
    if longest != first:
        out.append(longest)
    return out[:max_items]


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


def transliterate_ru_latin_to_cyrillic(text: str) -> str:
    """
    Ruscha so‘zlar lotin harflarida translit qilib yozilgan bo‘lsa (masalan: "bumaga A4 list"),
    portal qidiruvi uchun kirillcha variantini taxminan tiklaymiz: "бумага A4 лист".

    Bu 100% mukammal transliteratsiya emas, lekin tender keyword qidiruv uchun yetarli seed beradi.
    """
    if not text:
        return ""

    src = text.lower()
    out: list[str] = []
    i = 0

    while i < len(src):
        matched = False

        for latin, cyr in _RU_LATIN_MULTI:
            if src.startswith(latin, i):
                out.append(cyr)
                i += len(latin)
                matched = True
                break

        if matched:
            continue

        ch = src[i]
        mapped = _RU_LATIN_SINGLE.get(ch)
        if mapped is not None:
            out.append(mapped)
        else:
            out.append(text[i])

        i += 1

    return "".join(out)


def extract_query_translit_ru_keywords(query: str, max_items: int = 2) -> list[str]:
    """
    Query lotincha bo‘lsa ham, ruscha translit bo‘lishi mumkin.
    Shuning uchun kirillcha seed keywordlarni ajratib, qidiruvga qo‘shamiz.
    """
    if not query:
        return []

    # Agar allaqachon kirill bo‘lsa, bu funksiya kerak emas.
    if re.search("[\u0400-\u04FF]", query):
        return []

    # Hech bo‘lmasa lotin harflari bo‘lsin.
    if not re.search(r"[a-zA-Z]", query):
        return []

    translit = transliterate_ru_latin_to_cyrillic(query)
    tokens = re.findall("[\u0400-\u04FF]{3,}", translit.lower())
    tokens = [t for t in tokens if t not in _RU_STOPWORDS]

    unique: list[str] = []
    for t in tokens:
        if t not in unique:
            unique.append(t)

    if not unique:
        return []

    return unique[:max_items]


async def call_openrouter(prompt: str) -> str:
    api_key = get_openrouter_api_key()
    model = get_openrouter_model()
    base_url = get_openrouter_base_url()
    max_tokens = get_openrouter_max_tokens()

    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY topilmadi (env var bo‘lishi kerak). "
            "Local’da `.env` ga yozing, Railway/production’da esa Service Variables’da "
            "`OPENROUTER_API_KEY` ni set qiling (o‘sha environment uchun) va staged changes bo‘lsa Deploy qiling. "
            "Agar Shared Variables ishlatsangiz, service’ga variable reference sifatida qo‘shilganini tekshiring."
        )

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
        # OpenRouter: limit completion tokens to avoid 402 on low credits.
        "max_tokens": max_tokens,
        # Ask OpenRouter for JSON mode when supported (helps avoid JSONDecodeError).
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
        )

        # Some providers/models may not support `response_format`. Retry without it.
        if response.status_code in {400, 422}:
            body_text = (response.text or "")[:1000].lower()
            if "response_format" in body_text or "json_object" in body_text:
                payload_no_format = dict(payload)
                payload_no_format.pop("response_format", None)
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=payload_no_format,
                )

    if response.status_code != 200:
        raise RuntimeError(
            f"OpenRouter error {response.status_code}: {response.text[:1000]}"
        )

    data = _safe_json(response)
    if not data:
        raise RuntimeError("OpenRouter bo‘sh yoki noto‘g‘ri JSON qaytardi.")
    choice0 = data["choices"][0] if isinstance(data.get("choices"), list) and data.get("choices") else {}
    finish_reason = choice0.get("finish_reason") if isinstance(choice0, dict) else None
    content = (choice0.get("message") or {}).get("content") if isinstance(choice0, dict) else None
    content = content if isinstance(content, str) else ""
    content = content.strip()

    # If the model was cut off, JSON parsing will often fail with "Unterminated string...".
    if finish_reason == "length":
        raise RuntimeError(
            "OpenRouter javobi kesilib qoldi (finish_reason=length). "
            "`.env` dagi `OPENROUTER_MAX_TOKENS` ni oshiring yoki boshqa model tanlang."
        )

    return content


async def repair_json_with_openrouter(malformed_json: str) -> dict[str, Any] | None:
    api_key = get_openrouter_api_key()
    model = get_openrouter_model()
    base_url = get_openrouter_base_url()
    max_tokens = get_openrouter_max_tokens()

    if not api_key or not malformed_json.strip():
        return None

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You repair malformed JSON. "
                    "Return one valid JSON object only. "
                    "Preserve existing keys and values as much as possible. "
                    "Do not add markdown or explanations."
                ),
            },
            {
                "role": "user",
                "content": malformed_json,
            },
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
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

        if response.status_code in {400, 422}:
            body_text = (response.text or "")[:1000].lower()
            if "response_format" in body_text or "json_object" in body_text:
                payload_no_format = dict(payload)
                payload_no_format.pop("response_format", None)
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=payload_no_format,
                )

    if response.status_code != 200:
        return None

    data = _safe_json(response)
    if not data:
        return None

    choice0 = data["choices"][0] if isinstance(data.get("choices"), list) and data.get("choices") else {}
    content = (choice0.get("message") or {}).get("content") if isinstance(choice0, dict) else None
    if not isinstance(content, str) or not content.strip():
        return None

    try:
        parsed = extract_json(content)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


async def call_gemini_json(prompt: str, *, max_output_tokens: int | None = None) -> dict[str, Any]:
    """
    Uses Gemini to generate a JSON-only response for long structured outputs (e.g., `/api/generate`).
    """
    api_key = get_gemini_api_key()
    model = get_gemini_model()
    base_url = get_gemini_base_url()
    api_version = get_gemini_api_version()
    initial_max_tokens = max_output_tokens or get_gemini_max_output_tokens()

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY topilmadi (env var bo?lishi kerak). "
            "Local?da `.env` ga yozing, Railway/production?da esa Service Variables?da "
            "`GEMINI_API_KEY` ni set qiling."
        )

    url = f"{base_url}/{api_version}/models/{model}:generateContent"
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }

    retryable_statuses = {429, 500, 502, 503, 504}
    max_attempts = 3
    last_error: GeminiAPIError | None = None

    token_budgets: list[int] = []
    for budget in [initial_max_tokens, max(initial_max_tokens * 2, 8192)]:
        if budget not in token_budgets:
            token_budgets.append(budget)

    async with httpx.AsyncClient(timeout=180) as client:
        for token_budget in token_budgets:
            data: dict[str, Any] | None = None
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": token_budget,
                    "responseMimeType": "application/json",
                },
            }

            for attempt in range(1, max_attempts + 1):
                response = await client.post(url, headers=headers, json=payload)
                if response.status_code == 200:
                    data = _safe_json(response)
                    if data is not None:
                        break
                    last_error = GeminiAPIError(502, "Gemini bo‘sh yoki noto‘g‘ri JSON qaytardi.")
                    continue

                raw = _safe_json(response)
                error_obj = raw.get("error") if raw else None
                error_obj = error_obj if isinstance(error_obj, dict) else None
                error_message = (
                    error_obj.get("message")
                    if (error_obj and isinstance(error_obj.get("message"), str))
                    else None
                )
                retry_after_seconds = _extract_retry_after_seconds(response, error_obj)
                message = _build_gemini_error_message(
                    status_code=response.status_code,
                    model=model,
                    error_message=error_message,
                    retry_after_seconds=retry_after_seconds,
                )

                last_error = GeminiAPIError(
                    response.status_code,
                    message,
                    retry_after_seconds=retry_after_seconds,
                )

                logger.warning(
                    "Gemini JSON request failed (attempt %s/%s) status=%s model=%s max_tokens=%s retry_after=%s body=%s",
                    attempt,
                    max_attempts,
                    response.status_code,
                    model,
                    token_budget,
                    retry_after_seconds,
                    (response.text or "")[:800],
                )

                if response.status_code not in retryable_statuses:
                    break

                if response.status_code == 429 and _should_fast_fail_gemini_429(error_message):
                    break

                if attempt < max_attempts:
                    delay = retry_after_seconds or min(2**attempt, 10)
                    await asyncio.sleep(delay)

            if data is None:
                continue

            text = _extract_gemini_text(data)
            if not text:
                last_error = GeminiAPIError(500, "Gemini JSON: bo?sh javob qaytdi.")
                continue

            try:
                parsed = extract_json(text)
            except Exception as exc:
                finish_reason = _extract_gemini_finish_reason(data)
                parse_message = str(exc)[:200]
                logger.warning(
                    "Gemini JSON parse failed model=%s max_tokens=%s finish_reason=%s error=%s",
                    model,
                    token_budget,
                    finish_reason,
                    parse_message,
                )
                last_error = GeminiAPIError(
                    500,
                    f"Gemini JSON parse xatolik: {parse_message}",
                )
                is_truncated = (
                    finish_reason in {"MAX_TOKENS", "LENGTH"}
                    or "Unterminated string" in parse_message
                )
                if is_truncated and token_budget != token_budgets[-1]:
                    continue
                raise last_error from exc

            if not isinstance(parsed, dict):
                last_error = GeminiAPIError(500, "Gemini JSON: object (dict) bo?lishi kerak.")
                continue

            return parsed

    raise last_error or GeminiAPIError(500, "Gemini API: noma?lum xatolik.")


def _extract_gemini_text(response_json: dict[str, Any]) -> str:
    candidates = response_json.get("candidates") or []
    if not candidates:
        return ""

    candidate = candidates[0] if isinstance(candidates[0], dict) else {}
    content = candidate.get("content") or {}
    parts = content.get("parts") or []
    texts: list[str] = []
    for part in parts:
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            texts.append(part["text"])
    return "".join(texts).strip()


def _extract_gemini_finish_reason(response_json: dict[str, Any]) -> str | None:
    candidates = response_json.get("candidates") or []
    if not candidates:
        return None

    candidate = candidates[0] if isinstance(candidates[0], dict) else {}
    finish_reason = candidate.get("finishReason")
    return finish_reason if isinstance(finish_reason, str) else None


class GeminiAPIError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.retry_after_seconds = retry_after_seconds


class OpenRouterAPIError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


_GEMINI_DURATION_RE = re.compile(r"^(?P<seconds>\d+(?:\.\d+)?)s$")
_OPENROUTER_CAN_ONLY_AFFORD_RE = re.compile(r"can only afford\s+(?P<n>\d+)", re.IGNORECASE)


def _parse_duration_seconds(value: str | None) -> float | None:
    if not value or not isinstance(value, str):
        return None
    match = _GEMINI_DURATION_RE.match(value.strip())
    if not match:
        return None
    try:
        seconds = float(match.group("seconds"))
    except Exception:
        return None
    return seconds if seconds > 0 else None


def _extract_retry_after_seconds(
    response: httpx.Response, error_obj: dict[str, Any] | None
) -> float | None:
    header = response.headers.get("retry-after")
    if header:
        try:
            seconds = float(str(header).strip())
            return seconds if seconds > 0 else None
        except Exception:
            pass

    if error_obj:
        details = error_obj.get("details")
        if isinstance(details, list):
            for item in details:
                if not isinstance(item, dict):
                    continue
                if item.get("@type") != "type.googleapis.com/google.rpc.RetryInfo":
                    continue
                retry_delay = item.get("retryDelay")
                seconds = _parse_duration_seconds(retry_delay)
                if seconds:
                    return seconds

    return None


def _safe_json(response: httpx.Response) -> dict[str, Any] | None:
    try:
        data = response.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _build_gemini_error_message(
    *,
    status_code: int,
    model: str,
    error_message: str | None,
    retry_after_seconds: float | None,
) -> str:
    retry_hint = ""
    if retry_after_seconds:
        retry_hint = (
            f" Taxminan {int(retry_after_seconds + 0.999)} soniyadan keyin qayta urinib ko‘ring."
        )

    # Special case: many accounts get 429 with "limit: 0" (no quota provisioned / not eligible).
    if status_code == 429 and error_message and "limit: 0" in error_message:
        return (
            "Gemini API kvotasi mavjud emas (limit: 0). "
            f"`{model}` modelida so‘rovlar ruxsat etilmagan. "
            "Google AI Studio/GCP’da billing va quota (rate limits) ni tekshiring "
            "yoki `.env` dagi `GEMINI_MODEL` ni o‘zgartiring."
        )

    if status_code == 429:
        return "Gemini API limit/quota (429). Keyinroq qayta urinib ko‘ring." + retry_hint

    short = (error_message or "").strip()
    if short:
        short = short.replace("\n", " ").strip()
        if len(short) > 300:
            short = short[:300].rstrip() + "…"
        return f"Gemini API xatolik ({status_code}). {short}{retry_hint}"

    return f"Gemini API xatolik ({status_code}).{retry_hint}"


def _should_fast_fail_gemini_429(error_message: str | None) -> bool:
    text = (error_message or "").lower()
    if not text:
        return True

    markers = [
        "limit: 0",
        "quota",
        "billing",
        "resource_exhausted",
        "exceeded your current quota",
        "quota exceeded",
        "rate-limit",
        "rate limit",
        "please retry in",
    ]
    return any(marker in text for marker in markers)


def _has_meaningful_internet_result(result: dict[str, Any] | None) -> bool:
    if not isinstance(result, dict):
        return False
    answer_text = result.get("answer_text")
    if isinstance(answer_text, str) and answer_text.strip():
        return True
    sources = result.get("sources")
    return isinstance(sources, list) and len(sources) > 0


def _extract_gemini_sources(response_json: dict[str, Any]) -> list[dict[str, str]]:
    candidates = response_json.get("candidates") or []
    if not candidates:
        return []

    candidate = candidates[0] if isinstance(candidates[0], dict) else {}
    grounding = candidate.get("groundingMetadata") or candidate.get("grounding_metadata") or {}

    chunks = grounding.get("groundingChunks") or grounding.get("grounding_chunks") or []
    sources: list[dict[str, str]] = []
    seen: set[str] = set()

    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        web = chunk.get("web") or chunk.get("web") or {}
        if not isinstance(web, dict):
            continue
        uri = web.get("uri")
        if not uri or not isinstance(uri, str):
            continue
        if uri in seen:
            continue
        seen.add(uri)
        title = web.get("title")
        if not isinstance(title, str) or not title.strip():
            title = uri
        sources.append({"title": title.strip(), "uri": uri.strip()})

    return sources[:12]


async def call_gemini_grounded_answer(user_query: str) -> dict[str, Any]:
    """
    Uses Gemini API with Google Search grounding to generate a short product/service overview.
    """
    api_key = get_gemini_api_key()
    model = get_gemini_model()
    base_url = get_gemini_base_url()
    api_version = get_gemini_api_version()
    max_output_tokens = get_gemini_max_output_tokens()
    lang = _choose_answer_language(user_query)

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY topilmadi (env var bo‘lishi kerak). "
            "Local’da `.env` ga yozing, Railway/production’da esa Service Variables’da "
            "`GEMINI_API_KEY` ni set qiling."
        )

    language_rule = "rus tilida" if lang == "ru" else "o‘zbek tilida"
    heading = "Основные характеристики" if lang == "ru" else "Asosiy xarakteristikalar"

    prompt = f"""
    Siz internetdan foydalangan holda mahsulot yoki xizmat haqida qisqa ma’lumot beruvchi AI yordamchisiz.

    Foydalanuvchi so‘rovi: {user_query}

    Talablar:
    1) Javob faqat {language_rule} bo‘lsin.
    2) 1–3 gapdan iborat qisqa tavsif yozing.
    3) Keyin "{heading}" bo‘limida 6–10 ta band yozing.
    4) Juda aniq brend/modelni majburiy talab sifatida yozmang; umumiy mahsulot turiga mos tavsif bering.
    5) Juda uzun yozmang.
    """.strip()

    url = f"{base_url}/{api_version}/models/{model}:generateContent"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": max_output_tokens,
        },
    }

    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }

    # Retry a little for transient 429/5xx. NOTE: "limit: 0" is not transient (no quota).
    retryable_statuses = {429, 500, 502, 503, 504}
    max_attempts = 3

    last_error: GeminiAPIError | None = None
    data: dict[str, Any] | None = None

    async with httpx.AsyncClient(timeout=90) as client:
        for attempt in range(1, max_attempts + 1):
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code == 200:
                data = _safe_json(response)
                if data is not None:
                    break
                last_error = GeminiAPIError(502, "Gemini bo‘sh yoki noto‘g‘ri JSON qaytardi.")
                continue

            raw = _safe_json(response)
            error_obj = raw.get("error") if raw else None
            error_obj = error_obj if isinstance(error_obj, dict) else None
            error_message = (
                error_obj.get("message")
                if (error_obj and isinstance(error_obj.get("message"), str))
                else None
            )
            retry_after_seconds = _extract_retry_after_seconds(response, error_obj)
            message = _build_gemini_error_message(
                status_code=response.status_code,
                model=model,
                error_message=error_message,
                retry_after_seconds=retry_after_seconds,
            )

            last_error = GeminiAPIError(
                response.status_code,
                message,
                retry_after_seconds=retry_after_seconds,
            )

            logger.warning(
                "Gemini request failed (attempt %s/%s) status=%s model=%s retry_after=%s body=%s",
                attempt,
                max_attempts,
                response.status_code,
                model,
                retry_after_seconds,
                (response.text or "")[:800],
            )

            if response.status_code not in retryable_statuses:
                break

            # Not retrying on "limit: 0" because it's almost always a quota/config issue.
            if response.status_code == 429 and _should_fast_fail_gemini_429(error_message):
                break

            if attempt < max_attempts:
                delay = retry_after_seconds or min(2**attempt, 10)
                await asyncio.sleep(delay)

    if data is None:
        raise last_error or GeminiAPIError(500, "Gemini API: noma’lum xatolik.")

    return {
        "query": user_query,
        "answer_text": _extract_gemini_text(data),
        "sources": _extract_gemini_sources(data),
        "model": model,
        "provider": "gemini",
    }


async def call_gemini_from_internet_context(
    user_query: str,
    *,
    internet_context: str,
    sources: list[dict[str, str]] | None,
) -> dict[str, Any]:
    """
    Uses Gemini to rewrite an already fetched internet context (no Google Search grounding).

    Intended flow: internet search/extraction -> Gemini (polish/structure).
    """
    api_key = get_gemini_api_key()
    model = get_gemini_model()
    base_url = get_gemini_base_url()
    api_version = get_gemini_api_version()
    max_output_tokens = get_gemini_max_output_tokens()
    lang = _choose_answer_language(user_query)

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY topilmadi (env var bo‘lishi kerak). "
            "Local’da `.env` ga yozing, Railway/production’da esa Service Variables’da "
            "`GEMINI_API_KEY` ni set qiling."
        )

    language_rule = "rus tilida" if lang == "ru" else "o'zbek tilida"
    heading = "Основные характеристики" if lang == "ru" else "Asosiy xarakteristikalar"

    safe_context = (internet_context or "").strip()
    if len(safe_context) > 6000:
        safe_context = safe_context[:6000].rstrip() + "…"

    src_lines: list[str] = []
    for s in sources or []:
        if not isinstance(s, dict):
            continue
        uri = s.get("uri")
        if not isinstance(uri, str) or not uri.strip():
            continue
        title = s.get("title")
        title = title.strip() if isinstance(title, str) else ""
        label = title or uri.strip()
        src_lines.append(f"- {label}: {uri.strip()}")
        if len(src_lines) >= 12:
            break

    sources_text = "\n".join(src_lines).strip() or "- (manba yo‘q)"

    prompt = f"""
Siz internetdan topilgan ma'lumotlarni qayta ishlab, qisqa va aniq javob yozuvchi AI yordamchisiz.

Foydalanuvchi so'rovi: {user_query}

Qoidalar:
1) Javob faqat {language_rule} bo'lsin.
2) Faqat `INTERNET_CONTEXT` ichidagi ma'lumotlarga tayangan holda yozing (taxmin qilmang).
3) 1–3 gapdan iborat qisqa tavsif yozing.
4) Keyin "{heading}" bo'limida 6–10 ta band yozing (bandlar `-` bilan boshlansin).
5) Agar aniq ma'lumot yetarli bo'lmasa: "Bu ma'lumot topilmadi" deb yozing.

INTERNET_CONTEXT:
{safe_context}

SOURCES:
{sources_text}
""".strip()

    url = f"{base_url}/{api_version}/models/{model}:generateContent"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": max_output_tokens,
        },
    }

    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }

    retryable_statuses = {429, 500, 502, 503, 504}
    max_attempts = 3

    last_error: GeminiAPIError | None = None
    data: dict[str, Any] | None = None

    async with httpx.AsyncClient(timeout=90) as client:
        for attempt in range(1, max_attempts + 1):
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code == 200:
                data = _safe_json(response)
                if data is not None:
                    break
                last_error = GeminiAPIError(502, "Gemini bo‘sh yoki noto‘g‘ri JSON qaytardi.")
                continue

            raw = _safe_json(response)
            error_obj = raw.get("error") if raw else None
            error_obj = error_obj if isinstance(error_obj, dict) else None
            error_message = (
                error_obj.get("message")
                if (error_obj and isinstance(error_obj.get("message"), str))
                else None
            )
            retry_after_seconds = _extract_retry_after_seconds(response, error_obj)
            message = _build_gemini_error_message(
                status_code=response.status_code,
                model=model,
                error_message=error_message,
                retry_after_seconds=retry_after_seconds,
            )

            last_error = GeminiAPIError(
                response.status_code,
                message,
                retry_after_seconds=retry_after_seconds,
            )

            logger.warning(
                "Gemini (rewrite) request failed (attempt %s/%s) status=%s model=%s retry_after=%s body=%s",
                attempt,
                max_attempts,
                response.status_code,
                model,
                retry_after_seconds,
                (response.text or "")[:800],
            )

            if response.status_code not in retryable_statuses:
                break

            if response.status_code == 429 and _should_fast_fail_gemini_429(error_message):
                break

            if attempt < max_attempts:
                delay = retry_after_seconds or min(2**attempt, 10)
                await asyncio.sleep(delay)

    if data is None:
        raise last_error or GeminiAPIError(500, "Gemini API: noma’lum xatolik.")

    return {
        "query": user_query,
        "answer_text": _extract_gemini_text(data),
        "sources": (sources or [])[:12],
        "model": model,
        "provider": "internet_then_gemini",
    }


def _extract_openrouter_message(data: dict[str, Any]) -> dict[str, Any] | None:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    choice0 = choices[0] if isinstance(choices[0], dict) else None
    if not choice0:
        return None
    message = choice0.get("message")
    return message if isinstance(message, dict) else None


def _extract_openrouter_text(data: dict[str, Any]) -> str:
    message = _extract_openrouter_message(data) or {}
    content = message.get("content")
    return content.strip() if isinstance(content, str) else ""


def _extract_openrouter_sources(data: dict[str, Any]) -> list[dict[str, str]]:
    message = _extract_openrouter_message(data) or {}
    annotations = message.get("annotations")
    if not isinstance(annotations, list):
        return []

    sources: list[dict[str, str]] = []
    seen: set[str] = set()

    for ann in annotations:
        if not isinstance(ann, dict):
            continue
        if ann.get("type") != "url_citation":
            continue
        payload = ann.get("url_citation")
        if not isinstance(payload, dict):
            continue
        url = payload.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        url = url.strip()
        if url in seen:
            continue
        seen.add(url)

        title = payload.get("title")
        if not isinstance(title, str) or not title.strip():
            title = url
        sources.append({"title": title.strip(), "uri": url})

    return sources[:12]


async def call_openrouter_grounded_answer(user_query: str) -> dict[str, Any]:
    """
    Uses OpenRouter + web search grounding to generate a short product/service overview.
    """
    api_key = get_openrouter_api_key()
    base_url = get_openrouter_base_url()
    model = env_str("OPENROUTER_INTERNET_MODEL") or get_openrouter_model()
    max_tokens = min(get_openrouter_max_tokens_small(), 512)
    lang = _choose_answer_language(user_query)

    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY topilmadi (env var bo'lishi kerak). "
            "Local'da `.env` ga yozing, production'da esa environment variables'ga qo'shing."
        )

    language_rule = "rus tilida" if lang == "ru" else "o'zbek tilida"
    heading = "Основные характеристики" if lang == "ru" else "Asosiy xarakteristikalar"

    prompt = f"""
Siz internetdan foydalanib mahsulot yoki xizmat haqida qisqa ma'lumot beruvchi AI yordamchisiz.

Foydalanuvchi so'rovi: {user_query}

Talablar:
1) Javob faqat {language_rule} bo'lsin.
2) 1–3 gapdan iborat qisqa tavsif yozing.
3) Keyin \"{heading}\" bo'limida 6–10 ta band yozing.
4) Javobni internet manbalari bilan asoslang va markdown linklar ko'rinishida kamida 3 ta manbani keltiring.
5) Juda uzun yozmang.
""".strip()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    url = f"{base_url}/chat/completions"

    # Prefer server tools when the model supports tool calling.
    tool_payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    f"You are a helpful assistant. Write in {'Russian' if lang == 'ru' else 'Uzbek'}. "
                    "Use web search results and always cite sources as markdown links."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "tools": [
            {
                "type": "openrouter:web_search",
                "parameters": {
                    "engine": "exa",
                    "max_results": 3,
                    "max_total_results": 3,
                    "search_context_size": "low",
                    "user_location": {
                        "type": "approximate",
                        "country": "UZ",
                        "timezone": "Asia/Tashkent",
                    },
                },
            }
        ],
        "tool_choice": "required",
    }

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(url, headers=headers, json=tool_payload)

    if response.status_code == 402:
        raw = _safe_json(response)
        error_obj = raw.get("error") if raw else None
        error_obj = error_obj if isinstance(error_obj, dict) else None
        error_message = (
            error_obj.get("message")
            if (error_obj and isinstance(error_obj.get("message"), str))
            else (response.text or "")
        )
        match = _OPENROUTER_CAN_ONLY_AFFORD_RE.search(error_message or "")
        if match:
            try:
                affordable = int(match.group("n"))
            except Exception:
                affordable = 0
            if affordable > 1:
                max_tokens = max(1, min(max_tokens, affordable - 32))
                tool_payload["max_tokens"] = max_tokens
                async with httpx.AsyncClient(timeout=120) as client:
                    response = await client.post(url, headers=headers, json=tool_payload)

    # Fallback: deprecated web plugin path (works even if model/tool calling is unsupported).
    if response.status_code != 200:
        plugin_payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"You are a helpful assistant. Write in {'Russian' if lang == 'ru' else 'Uzbek'}. "
                        "Use web search results and cite sources as markdown links."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "plugins": [{"id": "web", "engine": "exa", "max_results": 3}],
            "temperature": 0.2,
            "max_tokens": max_tokens,
        }

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(url, headers=headers, json=plugin_payload)
        if response.status_code == 402:
            raw = _safe_json(response)
            error_obj = raw.get("error") if raw else None
            error_obj = error_obj if isinstance(error_obj, dict) else None
            error_message = (
                error_obj.get("message")
                if (error_obj and isinstance(error_obj.get("message"), str))
                else (response.text or "")
            )
            match = _OPENROUTER_CAN_ONLY_AFFORD_RE.search(error_message or "")
            if match:
                try:
                    affordable = int(match.group("n"))
                except Exception:
                    affordable = 0
                if affordable > 1:
                    max_tokens = max(1, min(max_tokens, affordable - 32))
                    plugin_payload["max_tokens"] = max_tokens
                    async with httpx.AsyncClient(timeout=120) as client:
                        response = await client.post(url, headers=headers, json=plugin_payload)

    if response.status_code != 200:
        raise OpenRouterAPIError(
            response.status_code,
            f"OpenRouter xatolik ({response.status_code}). {response.text[:800]}",
        )

    data = _safe_json(response)
    if not data:
        raise OpenRouterAPIError(502, "OpenRouter bo‘sh yoki noto‘g‘ri JSON qaytardi.")
    return {
        "query": user_query,
        "answer_text": _extract_openrouter_text(data),
        "sources": _extract_openrouter_sources(data),
        "model": data.get("model") if isinstance(data.get("model"), str) else model,
        "provider": "openrouter",
    }








_DDG_LINK_RE = re.compile(
    r"<a(?=[^>]*\bclass=['\"]result-link['\"])(?=[^>]*\bhref=['\"]([^'\"]+)['\"])[^>]*>(.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
_DDG_SNIPPET_RE = re.compile(
    r"<td[^>]*class=['\"]result-snippet['\"][^>]*>(.*?)</td>",
    re.IGNORECASE | re.DOTALL,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_CYRILLIC_CHAR_RE = re.compile("[\u0400-\u04FF]")


def _choose_answer_language(text: str) -> str:
    """
    Returns "ru" for Cyrillic queries, otherwise "uz".
    """
    return "ru" if _CYRILLIC_CHAR_RE.search(text or "") else "uz"


def _strip_html(value: str) -> str:
    if not value:
        return ""
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = _HTML_TAG_RE.sub(" ", value)
    value = html.unescape(value)
    value = _WS_RE.sub(" ", value)
    return value.strip()


def _decode_duckduckgo_redirect(href: str) -> str:
    href = html.unescape((href or "").strip())
    if not href:
        return ""

    if href.startswith("//"):
        href = "https:" + href

    try:
        parsed = urlparse(href)
        qs = parse_qs(parsed.query)
        uddg = qs.get("uddg", [None])[0]
        if isinstance(uddg, str) and uddg.strip():
            return unquote(uddg.strip())
    except Exception:
        pass

    return href


async def duckduckgo_lite_search(query: str, max_results: int = 5) -> list[dict[str, str]]:
    if not query.strip():
        return []

    url = "https://lite.duckduckgo.com/lite/"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; TenderAI/1.0)"}

    timeout = httpx.Timeout(45.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response: httpx.Response | None = None
        for attempt in range(2):
            try:
                response = await client.get(url, params={"q": query}, headers=headers)
                break
            except httpx.TimeoutException as exc:
                if attempt == 0:
                    await asyncio.sleep(0.4)
                    continue
                raise RuntimeError("DuckDuckGo search timeout.") from exc

    if not response:
        raise RuntimeError("DuckDuckGo search xatolik.")

    if response.status_code != 200:
        raise RuntimeError(f"DuckDuckGo search xatolik ({response.status_code}).")

    html_text = response.text or ""
    results: list[dict[str, str]] = []
    seen: set[str] = set()

    for match in _DDG_LINK_RE.finditer(html_text):
        href = match.group(1) or ""
        title = _strip_html(match.group(2) or "")

        target_url = _decode_duckduckgo_redirect(href)
        if not target_url or target_url in seen:
            continue
        seen.add(target_url)

        tail = html_text[match.end() : match.end() + 2500]
        snippet = ""
        snip_match = _DDG_SNIPPET_RE.search(tail)
        if snip_match:
            snippet = _strip_html(snip_match.group(1) or "")

        results.append({"title": title or target_url, "uri": target_url, "snippet": snippet})
        if len(results) >= max(1, min(max_results, 10)):
            break

    return results


def _extract_meta_description(html_text: str) -> str:
    if not html_text:
        return ""
    match = re.search(
        r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"']([^\"']+)[\"']",
        html_text,
        flags=re.IGNORECASE,
    )
    return _strip_html(match.group(1)) if match else ""


def _extract_spec_pairs_from_html(html_text: str, max_pairs: int = 10) -> list[tuple[str, str]]:
    if not html_text:
        return []

    pairs: list[tuple[str, str]] = []

    for row in re.findall(r"<tr[^>]*>.*?</tr>", html_text, flags=re.IGNORECASE | re.DOTALL):
        th_match = re.search(r"<th[^>]*>(.*?)</th>", row, flags=re.IGNORECASE | re.DOTALL)
        td_match = re.search(r"<td[^>]*>(.*?)</td>", row, flags=re.IGNORECASE | re.DOTALL)
        if not th_match or not td_match:
            continue
        key = _strip_html(th_match.group(1))
        value = _strip_html(td_match.group(1))
        if not key or not value:
            continue
        pairs.append((key, value))
        if len(pairs) >= max(1, min(max_pairs, 20)):
            break
    return pairs


async def call_free_search_grounded_answer(user_query: str) -> dict[str, Any]:
    """
    No-API-key fallback for `/api/internet`.

    Uses DuckDuckGo Lite search + simple extraction (meta description + spec table pairs) to build
    a short Uzbek/Russian overview with sources.
    """
    lang = _choose_answer_language(user_query)
    results = await duckduckgo_lite_search(user_query, max_results=5)
    sources = [{"title": r["title"], "uri": r["uri"]} for r in results if r.get("uri")]

    description = ""
    bullets: list[str] = []

    if results:
        first_url = results[0].get("uri") or ""
        if first_url:
            try:
                timeout = httpx.Timeout(35.0, connect=15.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    page = await client.get(
                        first_url,
                        headers={"User-Agent": "Mozilla/5.0 (compatible; TenderAI/1.0)"},
                        follow_redirects=True,
                    )
                if page.status_code == 200:
                    description = _extract_meta_description(page.text or "")
                    pairs = _extract_spec_pairs_from_html(page.text or "", max_pairs=10)
                    bullets = [f"{k}: {v}" for k, v in pairs]
            except httpx.TimeoutException:
                pass
            except Exception:
                pass

    if not description:
        for r in results:
            snippet = (r.get("snippet") or "").strip()
            if snippet:
                description = snippet
                break

    if not bullets:
        for r in results:
            snippet = (r.get("snippet") or "").strip()
            if not snippet:
                continue
            bullets.append(snippet)
            if len(bullets) >= 8:
                break

    description = (description or "").strip()
    if not description:
        description = (
            "Internetdan mos manbalar topilmadi yoki bloklandi."
            if lang == "uz"
            else "Не удалось найти подходящие источники в интернете или доступ ограничен."
        )

    # Lightweight translation for the free fallback (no LLM).
    if lang == "uz":
        desc_repl = [
            ("Desktop Switch", "stol usti kommutator (switch)"),
            ("Desktop Network Switch", "stol usti tarmoq kommutatori (switch)"),
            ("Unmanaged", "boshqarilmaydigan"),
            ("Switch", "kommutator (switch)"),
            ("Gigabit", "Gigabit"),
            ("10/100/1000Mbps", "10/100/1000 Mbit/s"),
        ]
        key_map = {
            "Standards and Protocols": "Standartlar va protokollar",
            "Interface": "Interfeys",
            "Fan Quantity": "Ventilyatorlar soni",
            "Max. Power Consumption": "Maksimal quvvat sarfi",
            "External Power Supply": "Tashqi quvvat manbai",
            "LED": "LED indikatorlar",
            "Buffer Size": "Bufer xotira",
            "Dimensions ( W x D x H )": "O'lchamlari (W×D×H)",
            "MAC Address Table": "MAC manzillar jadvali",
            "Packet Forwarding Rate": "Paket uzatish tezligi",
            "Jumbo Frame": "Jumbo freym",
            "Transmission Method": "Uzatish usuli",
        }
        value_map = {
            "Fanless": "Ventilyatorsiz",
            "Store and Forward": "Store-and-forward",
        }
    else:
        desc_repl = [
            ("Desktop Switch", "настольный коммутатор"),
            ("Desktop Network Switch", "настольный сетевой коммутатор"),
            ("Unmanaged", "неуправляемый"),
            ("Switch", "коммутатор"),
            ("Gigabit", "Gigabit"),
            ("10/100/1000Mbps", "10/100/1000 Мбит/с"),
        ]
        key_map = {
            "Standards and Protocols": "Стандарты и протоколы",
            "Interface": "Интерфейсы",
            "Fan Quantity": "Вентиляторы",
            "Max. Power Consumption": "Макс. потребление",
            "External Power Supply": "Внешнее питание",
            "LED": "Индикаторы LED",
            "Buffer Size": "Буфер",
            "Dimensions ( W x D x H )": "Габариты (Ш×Г×В)",
            "MAC Address Table": "Таблица MAC-адресов",
            "Packet Forwarding Rate": "Скорость пересылки пакетов",
            "Jumbo Frame": "Jumbo frame",
            "Transmission Method": "Метод передачи",
        }
        value_map = {
            "Fanless": "Без вентилятора",
            "Store and Forward": "Store-and-forward",
        }

    for src, dst in desc_repl:
        if description:
            description = re.sub(re.escape(src), dst, description, flags=re.IGNORECASE)

    translated_bullets: list[str] = []
    for b in bullets:
        if ":" in b:
            k, v = b.split(":", 1)
            k = key_map.get(k.strip(), k.strip())
            v = v.strip()
            v = value_map.get(v, v)
            if lang == "uz":
                v = (
                    v.replace("Mbps", "Mbit/s")
                    .replace("Ports", "port")
                    .replace("Port", "port")
                    .replace("Auto-Negotiation", "avto-negotiation")
                )
            else:
                v = (
                    v.replace("Mbps", "Мбит/с")
                    .replace("Ports", "портов")
                    .replace("Port", "порт")
                    .replace("Auto-Negotiation", "авто‑согласование")
                )
            translated_bullets.append(f"{k}: {v}")
        else:
            translated_bullets.append(b)
    bullets = translated_bullets

    bullets = [b.strip() for b in bullets if b and b.strip()]
    bullets = bullets[:12]

    heading = "Asosiy xarakteristikalar:" if lang == "uz" else "Основные характеристики:"
    answer_lines = [description, "", heading]
    if bullets:
        answer_lines.extend([f"- {b}" for b in bullets])
    else:
        answer_lines.append("- Ma'lumot topilmadi." if lang == "uz" else "- Данные не найдены.")

    return {
        "query": user_query,
        "answer_text": "\n".join(answer_lines).strip(),
        "sources": sources[:12],
        "model": None,
        "provider": "free_search",
    }


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", ""))
    except Exception:
        return None


def filter_by_period(evidences, period_months: int):
    cutoff = datetime.now() - timedelta(days=period_months * 31)

    filtered = []

    for ev in evidences:
        deal_date = parse_date(ev.deal_date)

        if deal_date is None:
            continue

        if deal_date >= cutoff:
            filtered.append(ev)

    return filtered






@app.get("/")
async def root():
    if FRONTEND_INDEX_FILE.exists():
        return FileResponse(FRONTEND_INDEX_FILE)

    return {"message": "TenderAI API ishlayapti", "docs": "/docs"}


@app.get("/api/health")
async def health():
    """
    Lightweight diagnostics endpoint (does NOT reveal secrets).
    Useful in production to confirm env vars are visible.
    """
    api_key = get_openrouter_api_key()
    gemini_key = get_gemini_api_key()
    return {
        "status": "ok",
        "runtime_provider": "openrouter_only",
        "openrouter": {
            "api_key_present": bool(api_key),
            "api_key_length": len(api_key or ""),
            "model": get_openrouter_model(),
            "base_url": get_openrouter_base_url(),
            "max_tokens": get_openrouter_max_tokens(),
        },
        "gemini": {
            "api_key_present": bool(gemini_key),
            "api_key_length": len(gemini_key or ""),
            "model": get_gemini_model(),
            "base_url": get_gemini_base_url(),
            "api_version": get_gemini_api_version(),
            "max_output_tokens": get_gemini_max_output_tokens(),
        },
        "railway": {
            "environment_name": env_str("RAILWAY_ENVIRONMENT_NAME") or env_str("RAILWAY_ENVIRONMENT"),
            "service_name": env_str("RAILWAY_SERVICE_NAME"),
            "project_id": env_str("RAILWAY_PROJECT_ID"),
            "service_id": env_str("RAILWAY_SERVICE_ID"),
        },
    }


def _default_enabled_sources() -> list[str]:
    return [
        "xarid.uzex.uz",
        "xarid.uzex.uz/national",
        "xarid.uzex.uz/auction",
        "etender.uzex.uz",
    ]


def _build_keywords_for_query(user_query: str, search_plan: dict[str, Any]) -> list[str]:
    keywords = (
        (search_plan.get("search_keywords_ru") or [])
        + (search_plan.get("search_keywords_uz") or [])
    )
    keywords = [k for k in keywords if isinstance(k, str) and k.strip()]
    keywords = list(dict.fromkeys(keywords))

    if not keywords:
        keywords = [user_query]
    else:
        seed = extract_query_cyrillic_keywords(user_query, max_items=2)
        if seed:
            keywords = list(dict.fromkeys([*keywords, *seed]))

        translit_seed = extract_query_translit_ru_keywords(user_query, max_items=2)
        if translit_seed:
            keywords = list(dict.fromkeys([*keywords, *translit_seed]))

        keywords = keywords[:8]

    return keywords


def _candidate_to_json(c: ProductCandidate) -> dict[str, Any]:
    return {
        "product_code": c.product_code,
        "name": c.name,
        "category_id": c.category_id,
        "category_name": c.category_name,
        "score": c.score,
    }


def _candidate_from_json(value: dict[str, Any], *, selection_reason: str | None = None) -> ProductCandidate | None:
    if not isinstance(value, dict):
        return None

    product_code = value.get("product_code")
    if not isinstance(product_code, str) or not product_code.strip():
        return None
    product_code = product_code.strip()

    category_id_raw = value.get("category_id")
    try:
        category_id = int(category_id_raw)
    except Exception:
        return None

    name = value.get("name")
    name = name.strip() if isinstance(name, str) and name.strip() else product_code

    category_name = value.get("category_name")
    category_name = category_name.strip() if isinstance(category_name, str) else ""

    score_raw = value.get("score")
    score = 0.0
    if isinstance(score_raw, (int, float)):
        score = float(score_raw)

    return ProductCandidate(
        id=0,
        product_code=product_code,
        name=name,
        category_id=category_id,
        category_name=category_name,
        score=score,
        selection_reason=selection_reason,
    )


@app.post("/api/candidates")
async def candidates(request: CandidatesRequest):
    """
    Step-1 endpoint for manual candidate selection in UI.

    Returns product candidates from Xarid katalog (when Xarid sources enabled),
    plus `keywords`/`search_plan` so frontend can pass them back to `/api/generate`
    without recomputing.
    """
    query_service = QueryUnderstandingService()
    connector = XaridUzexConnector()

    enabled_sources = request.enabled_sources or _default_enabled_sources()
    xarid_sources = {"xarid.uzex.uz", "xarid.uzex.uz/national", "xarid.uzex.uz/auction"}

    search_plan = await query_service.build_search_plan(request.query)
    keywords = _build_keywords_for_query(request.query, search_plan)

    candidates_list: list[ProductCandidate] = []
    if any(source in enabled_sources for source in xarid_sources):
        candidates_list = await connector.find_product_candidates(
            keywords=keywords,
            max_candidates=request.max_candidates,
        )

    candidates_json = [_candidate_to_json(c) for c in (candidates_list or [])]

    return {
        "query": request.query,
        "enabled_sources": enabled_sources,
        "keywords": keywords,
        "search_plan": search_plan,
        "candidates": candidates_json,
    }


@app.post("/api/internet")
async def internet_answer(request: InternetRequest):
    query = request.query

    free_result: dict[str, Any] | None = None
    try:
        openrouter_result = await call_openrouter_grounded_answer(query)
        if _has_meaningful_internet_result(openrouter_result):
            return openrouter_result
    except OpenRouterAPIError as exc:
        logger.info("OpenRouter failed for /api/internet, trying free search fallback: %s", exc.message)
        openrouter_error: Exception | None = exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.info("OpenRouter not available for /api/internet, trying free search fallback: %s", str(exc)[:300])
        openrouter_error = exc
    else:
        openrouter_error = None

    try:
        free_result = await call_free_search_grounded_answer(query)
        if _has_meaningful_internet_result(free_result):
            return free_result
    except Exception as free_exc:
        logger.info("Free search failed for /api/internet: %s", str(free_exc)[:300])
        if isinstance(openrouter_error, OpenRouterAPIError):
            raise HTTPException(
                status_code=openrouter_error.status_code,
                detail={"message": openrouter_error.message, "provider": "openrouter"},
            )
        if openrouter_error is not None:
            raise HTTPException(status_code=500, detail=str(openrouter_error))
        raise HTTPException(status_code=500, detail=str(free_exc))

    if free_result is not None:
        return free_result

    if isinstance(openrouter_error, OpenRouterAPIError):
        raise HTTPException(
            status_code=openrouter_error.status_code,
            detail={"message": openrouter_error.message, "provider": "openrouter"},
        )
    if openrouter_error is not None:
        raise HTTPException(status_code=500, detail=str(openrouter_error))

    raise HTTPException(status_code=500, detail="Internet qidiruvi natija qaytarmadi.")


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    """
    Production deploy uchun: `frontend/dist` mavjud bo‘lsa, SPA frontendni bitta servisdan serve qiladi.
    """
    if not FRONTEND_INDEX_FILE.exists():
        raise HTTPException(status_code=404, detail="Not found")

    # API va docs routelarini tegmasdan qoldiramiz (ular yuqorida aniq route sifatida bor).
    if full_path.startswith(("api/", "docs", "openapi.json", "redoc")):
        raise HTTPException(status_code=404, detail="Not found")

    requested = (FRONTEND_DIST_DIR / full_path).resolve()
    try:
        requested.relative_to(FRONTEND_DIST_DIR.resolve())
    except Exception:
        return FileResponse(FRONTEND_INDEX_FILE)

    if requested.is_file():
        return FileResponse(requested)

    return FileResponse(FRONTEND_INDEX_FILE)


@app.post("/api/generate")
async def generate_technical_task(request: GenerateRequest):
    try:
        query_service = QueryUnderstandingService()
        connector = XaridUzexConnector()
        price_service = PriceAnalysisService()
        prompt_builder = LLMPromptBuilder()
        validator = GenericOutputValidator()

        search_plan = request.search_plan or None
        if not isinstance(search_plan, dict):
            search_plan = await query_service.build_search_plan(request.query)

        keywords = request.keywords or None
        if not isinstance(keywords, list) or not keywords:
            keywords = _build_keywords_for_query(request.query, search_plan)
        else:
            keywords = [k for k in keywords if isinstance(k, str) and k.strip()]
            keywords = list(dict.fromkeys(keywords))[:8] or [request.query]

        enabled_sources = request.enabled_sources or _default_enabled_sources()

        selected = None
        selected_products: list[ProductCandidate] = []
        candidates = []

        xarid_sources = {"xarid.uzex.uz", "xarid.uzex.uz/national", "xarid.uzex.uz/auction"}

        candidates_from_request = request.candidates or None
        if isinstance(candidates_from_request, list) and candidates_from_request:
            parsed: list[ProductCandidate] = []
            for item in candidates_from_request[:50]:
                if not isinstance(item, dict):
                    continue
                cand = _candidate_from_json(item)
                if cand:
                    parsed.append(cand)
            candidates = parsed[:20]
        elif any(source in enabled_sources for source in xarid_sources):
            candidates = await connector.find_product_candidates(
                keywords=keywords,
                max_candidates=15,
            )

        picked_by_code = {c.product_code: c for c in (candidates or [])}

        selected_list_from_request = request.selected_candidates or None
        if isinstance(selected_list_from_request, list) and selected_list_from_request:
            seen_codes: set[str] = set()
            for item in selected_list_from_request[:20]:
                if not isinstance(item, dict):
                    continue
                picked = _candidate_from_json(item, selection_reason="user_selected")
                if not picked or picked.product_code in seen_codes:
                    continue
                resolved = picked_by_code.get(picked.product_code) or picked
                resolved.selection_reason = "user_selected"
                selected_products.append(resolved)
                seen_codes.add(resolved.product_code)

        if not selected_products:
            selected_from_request = request.selected_candidate or None
            if isinstance(selected_from_request, dict) and selected_from_request:
                picked = _candidate_from_json(selected_from_request, selection_reason="user_selected")
                if picked:
                    resolved = picked_by_code.get(picked.product_code) or picked
                    resolved.selection_reason = "user_selected"
                    selected_products = [resolved]

        if not selected_products and candidates:
            for candidate in candidates[:20]:
                candidate.selection_reason = "auto_selected_all"
            selected_products = list(candidates[:20])

        if selected_products:
            selected = selected_products[0]

         
        orchestrator = SearchOrchestrator()

        orchestration = await orchestrator.collect_all_sources(
            user_query=request.query,
            keywords=keywords,
            selected_products=selected_products,
            period_months=request.period_months,
            page_size=20,
            max_pages=3,
            enabled_sources=enabled_sources,
        )

        evidences_by_source = orchestration["evidences_by_source"]
        evidences = orchestration["all_evidences"]
        source_status = orchestration["source_status"]

        price_analysis = price_service.analyze_by_source(evidences_by_source)

        if (price_analysis.get("global") or {}).get("count", 0) == 0 and not evidences:
            raise HTTPException(
                status_code=404,
                detail=f"Oxirgi {request.period_months} oy bo‘yicha evidence topilmadi.",
            )

        selected_product_dict = (
            {
                "name": selected.name,
                "product_code": selected.product_code,
                "category_id": selected.category_id,
                "category_name": selected.category_name,
                "selection_reason": getattr(selected, "selection_reason", None),
            }
            if selected is not None
            else None
        )

        selected_products_json = [
            {
                "name": item.name,
                "product_code": item.product_code,
                "category_id": item.category_id,
                "category_name": item.category_name,
                "selection_reason": getattr(item, "selection_reason", None),
            }
            for item in selected_products
        ]

        candidates_json = [
            {
                "product_code": c.product_code,
                "name": c.name,
                "category_id": c.category_id,
                "category_name": c.category_name,
                "score": c.score,
            }
            for c in (candidates or [])[:20]
        ]

        candidate_confidence = None
        if candidates_json:
            selected_code = selected_product_dict.get("product_code") if selected_product_dict else None
            selected_code_set = {item.get("product_code") for item in selected_products_json if item.get("product_code")}
            selected_rank = None
            selected_ranks: list[int] = []
            selected_score = None
            for idx, c in enumerate(candidates_json, start=1):
                if selected_code and c.get("product_code") == selected_code:
                    selected_rank = idx
                    selected_score = c.get("score")
                if c.get("product_code") in selected_code_set:
                    selected_ranks.append(idx)

            top_score = candidates_json[0].get("score")
            second_score = candidates_json[1].get("score") if len(candidates_json) > 1 else None
            gap = (
                float(top_score) - float(second_score)
                if isinstance(top_score, (int, float)) and isinstance(second_score, (int, float))
                else None
            )

            candidate_confidence = {
                "candidate_count": len(candidates_json),
                "selected_count": len(selected_products_json),
                "selected_rank": selected_rank,
                "selected_ranks": selected_ranks,
                "selected_score": selected_score,
                "top_score": top_score,
                "second_score": second_score,
                "score_gap_top_vs_second": gap,
            }

        def evidence_to_dict(ev):
            return {
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
            }

        evidences_json = [evidence_to_dict(ev) for ev in evidences[:200]]
        evidences_by_source_json = {
            source: [evidence_to_dict(ev) for ev in items[:200]]
            for source, items in evidences_by_source.items()
        }

        source_summaries = {}
        for source, items in evidences_by_source.items():
            eligible_count = sum(1 for ev in items if isinstance(ev.unit_price, (int, float)))
            by_source_item = (price_analysis.get("by_source") or {}).get(source) or {}
            note = by_source_item.get("note") if isinstance(by_source_item, dict) else None
            source_summaries[source] = {
                "total_evidences": len(items),
                "price_eligible_count": eligible_count,
                "note": note,
            }

        aggregated_characteristics = "\n\n--- KEYINGI LOT ---\n\n".join(
            [ev.condition for ev in evidences if ev.condition and str(ev.condition).strip()]
        )

        source_data = {
            "user_query": request.query,
            "keywords": keywords,
            "search_plan": search_plan,
            "selected_product": selected_product_dict,
            "selected_products": selected_products_json,
            "source_status": source_status,
            "price_analysis": price_analysis,
            "evidences_by_source": {
                source: [evidence_to_dict(ev) for ev in items[:20]]
                for source, items in evidences_by_source.items()
            },
        }

        prompt = prompt_builder.build(
            user_query=request.query,
            selected_product=selected,
            selected_products=selected_products,
            source_status=source_status,
            price_analysis=price_analysis,
            evidences_by_source=evidences_by_source,
        )

        llm_result: dict[str, Any] | None = None
        raw_llm = ""
        try:
            raw_llm = await call_openrouter(prompt)
            llm_result = extract_json(raw_llm)
        except Exception as exc:
            recovered = await repair_json_with_openrouter(raw_llm)
            if recovered is not None:
                llm_result = recovered
            else:
                raise HTTPException(
                    status_code=502,
                    detail={
                        "message": str(exc)[:500] or "OpenRouter xatoligi",
                        "provider": "openrouter",
                    },
                )

        if not isinstance(llm_result, dict):
            raise HTTPException(status_code=500, detail="LLM natijasi JSON object bo‘lishi kerak.")

        validation_warnings = validator.validate(
            llm_result=llm_result,
            source_data=source_data,
        )

        return {
            "query": request.query,
            "source": "multi-source",
            "enabled_sources": enabled_sources,
            "keywords": keywords,
            "search_plan": search_plan,
            "candidate_selection_reason": getattr(selected, "selection_reason", None) if selected else None,
            "selected_product": selected_product_dict,
            "selected_products": selected_products_json,
            "candidates": candidates_json,
            "candidate_confidence": candidate_confidence,
            "source_status": source_status,
            "price_analysis": price_analysis,
            "evidences": evidences_json,
            "evidences_by_source": evidences_by_source_json,
            "source_summaries": source_summaries,
            "aggregated_characteristics": aggregated_characteristics,
            "technical_task": llm_result,
            "validation_warnings": validation_warnings,
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )
