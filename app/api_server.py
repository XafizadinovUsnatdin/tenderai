import json
import os
import re
from typing import Any
from datetime import datetime, timedelta
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.connectors.xarid_uzex_connector import XaridUzexConnector
from app.services.query_understanding_service import QueryUnderstandingService
from app.services.candidate_selector_service import CandidateSelectorService
from app.services.price_analysis_service import PriceAnalysisService
from app.services.llm_prompt_builder import LLMPromptBuilder
from app.services.generic_output_validator import GenericOutputValidator


load_dotenv()


app = FastAPI(
    title="TenderAI API",
    description="Xarid.uzex.uz asosida texnik topshiriq va narx tahlili generatsiya qilish API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    query: str = Field(..., min_length=2)
    period_months: int = Field(default=12, ge=1, le=60)


def extract_json(text: str) -> dict[str, Any]:
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

    async with httpx.AsyncClient(timeout=180) as client:
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
    return {
        "message": "TenderAI API ishlayapti",
        "docs": "/docs",
    }


@app.post("/api/generate")
async def generate_technical_task(request: GenerateRequest):
    try:
        query_service = QueryUnderstandingService()
        candidate_selector = CandidateSelectorService()
        connector = XaridUzexConnector()
        price_service = PriceAnalysisService()
        prompt_builder = LLMPromptBuilder()
        validator = GenericOutputValidator()

        search_plan = await query_service.build_search_plan(request.query)

        keywords = (
            search_plan.get("search_keywords_ru", [])
            + search_plan.get("search_keywords_uz", [])
        )
        keywords = list(dict.fromkeys([k for k in keywords if k]))

        if not keywords:
            raise HTTPException(
                status_code=404,
                detail="Qidiruv keywordlari topilmadi.",
            )

        candidates = await connector.find_product_candidates(
            keywords=keywords,
            max_candidates=15,
        )

        if not candidates:
            raise HTTPException(
                status_code=404,
                detail="Xarid katalogidan mos product candidate topilmadi.",
            )

        selected = await candidate_selector.select_best_candidate(
            user_query=request.query,
            search_plan=search_plan,
            candidates=candidates,
        )

        if selected is None:
            raise HTTPException(
                status_code=404,
                detail="Mos product_code tanlanmadi.",
            )

        
        now = datetime.now()
        cutoff = now - timedelta(days=request.period_months * 31)
        years_to_scan = list(range(now.year, cutoff.year - 1, -1))

        all_evidences = []

        for year in years_to_scan:
            year_evidences = await connector.collect_evidences_for_candidate(
                candidate=selected,
                year_id=year,
                page_size=20,
                max_pages=3,
            )
            all_evidences.extend(year_evidences)
        evidences = filter_by_period(
            evidences=all_evidences,
            period_months=request.period_months,
        )   
        if not evidences:
            raise HTTPException(
                status_code=404,
                detail=f"Oxirgi {request.period_months} oy bo‘yicha muvaffaqiyatli bitim topilmadi.",
        ) 
        

        price_analysis = price_service.analyze(evidences)

        source_data = {
            "user_query": request.query,
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

        prompt = prompt_builder.build(
            user_query=request.query,
            selected_product=selected,
            price_analysis=price_analysis,
            evidences=evidences,
        )

        raw_llm = await call_openrouter(prompt)
        llm_result = extract_json(raw_llm)

        validation_warnings = validator.validate(
            llm_result=llm_result,
            source_data=source_data,
        )

        return {
            "query": request.query,
            "source": "xarid.uzex.uz",
            "keywords": keywords,
            "search_plan": search_plan,
            "selected_product": source_data["selected_product"],
            "price_analysis": price_analysis,
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
