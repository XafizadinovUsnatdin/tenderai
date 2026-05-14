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
from app.services.search_orchestrator import SearchOrchestrator


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
    enabled_sources: list[str] | None = None


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
            keywords = [request.query]

        enabled_sources = request.enabled_sources or [
            "xarid.uzex.uz",
            "xarid.uzex.uz/national",
            "xarid.uzex.uz/auction",
            "etender.uzex.uz",
        ]

        selected = None
        candidates = []

        xarid_sources = {"xarid.uzex.uz", "xarid.uzex.uz/national", "xarid.uzex.uz/auction"}

        if any(source in enabled_sources for source in xarid_sources):
            candidates = await connector.find_product_candidates(
                keywords=keywords,
                max_candidates=15,
            )

            if candidates:
                selected = await candidate_selector.select_best_candidate(
                    user_query=request.query,
                    search_plan=search_plan,
                    candidates=candidates,
                )

        
        orchestrator = SearchOrchestrator()

        orchestration = await orchestrator.collect_all_sources(
            user_query=request.query,
            keywords=keywords,
            selected_product=selected,
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

        source_data = {
            "user_query": request.query,
            "keywords": keywords,
            "search_plan": search_plan,
            "selected_product": selected_product_dict,
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
            source_status=source_status,
            price_analysis=price_analysis,
            evidences_by_source=evidences_by_source,
        )

        raw_llm = await call_openrouter(prompt)
        llm_result = extract_json(raw_llm)

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
            "source_status": source_status,
            "price_analysis": price_analysis,
            "evidences": evidences_json,
            "evidences_by_source": evidences_by_source_json,
            "source_summaries": source_summaries,
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
