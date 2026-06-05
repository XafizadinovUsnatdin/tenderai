from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import re

from app.connectors.etender_uzex_connector import EtenderUzexConnector
from app.connectors.xarid_uzex_connector import XaridUzexConnector
from app.schemas import Evidence, ProductCandidate
from app.services.env_config import env_int


def _is_number(value) -> bool:
    return isinstance(value, (int, float))


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", ""))
    except Exception:
        return None


def _filter_by_period(evidences: list[Evidence], period_months: int) -> list[Evidence]:
    cutoff = datetime.now() - timedelta(days=period_months * 31)
    filtered: list[Evidence] = []

    for ev in evidences:
        deal_date = _parse_date(ev.deal_date)
        if deal_date is None:
            continue
        if deal_date >= cutoff:
            filtered.append(ev)

    return filtered


def _dedupe_evidences(evidences: list[Evidence]) -> list[Evidence]:
    unique: dict[tuple, Evidence] = {}

    for ev in evidences:
        key = (
            ev.source_name,
            ev.lot_id if ev.lot_id is not None else ev.lot_display_no,
            ev.product_name or ev.category_name,
            ev.provider_name,
            ev.deal_date,
        )
        if key not in unique:
            unique[key] = ev

    return list(unique.values())


def _pick_keyword_for_etender(keywords: list[str], user_query: str) -> str:
    """
    Etender portalida ko‘pincha kirillcha keyword aniqroq ishlaydi.
    Shuning uchun keywordlar orasida kirillcha bo‘lsa, o‘shani prioritet qilamiz.
    """
    for k in keywords or []:
        if k and re.search(r"[\u0400-\u04FF]", k):
            return k

    return next((k for k in keywords or [] if k), None) or user_query


class SearchOrchestrator:
    def __init__(self):
        self.xarid_shop = XaridUzexConnector(view=XaridUzexConnector.VIEW_SHOP)
        self.xarid_national = XaridUzexConnector(view=XaridUzexConnector.VIEW_NATIONAL)
        self.xarid_auction = XaridUzexConnector(view=XaridUzexConnector.VIEW_AUCTION)
        self.etender = EtenderUzexConnector()

    async def collect_all_sources(
        self,
        user_query: str,
        keywords: list[str],
        selected_products: list[ProductCandidate] | None,
        period_months: int,
        page_size: int = 20,
        max_pages: int = 3,
        enabled_sources: list[str] | None = None,
    ) -> dict:
        enabled = set(
            enabled_sources
            or [
                self.xarid_shop.source_name,
                self.xarid_national.source_name,
                self.xarid_auction.source_name,
                self.etender.source_name,
            ]
        )

        evidences_by_source: dict[str, list[Evidence]] = {}
        source_status: dict[str, dict] = {}

        async def handle_xarid(conn: XaridUzexConnector):
            name = conn.source_name
            if name not in enabled:
                source_status[name] = {
                    "status": "skipped",
                    "count": 0,
                    "price_eligible_count": 0,
                    "message": "Manba o‘chirib qo‘yilgan (enabled_sources).",
                }
                evidences_by_source[name] = []
                return

            selected_products_list = [item for item in (selected_products or []) if item is not None]
            if not selected_products_list:
                source_status[name] = {
                    "status": "skipped",
                    "count": 0,
                    "price_eligible_count": 0,
                    "message": "selected_products yo‘q, xarid.uzex qidiruvi o‘tkazib yuborildi.",
                }
                evidences_by_source[name] = []
                return

            try:
                now = datetime.now()
                cutoff = now - timedelta(days=period_months * 31)
                years_to_scan = list(range(now.year, cutoff.year - 1, -1))
                year_concurrency = env_int("XARID_YEAR_CONCURRENCY", 3)
                semaphore = asyncio.Semaphore(max(1, year_concurrency))

                all_evidences: list[Evidence] = []

                async def fetch_candidate_year(
                    candidate: ProductCandidate,
                    year: int,
                ) -> list[Evidence]:
                    async with semaphore:
                        return await conn.collect_evidences_for_candidate(
                            candidate=candidate,
                            year_id=year,
                            page_size=page_size,
                            max_pages=max_pages,
                        )

                tasks = [
                    fetch_candidate_year(candidate, year)
                    for candidate in selected_products_list
                    for year in years_to_scan
                ]
                if tasks:
                    for evidences_chunk in await asyncio.gather(*tasks):
                        all_evidences.extend(evidences_chunk)

                evidences = _filter_by_period(
                    _dedupe_evidences(all_evidences),
                    period_months=period_months,
                )

                evidences_by_source[name] = evidences
                source_status[name] = {
                    "status": "success",
                    "count": len(evidences),
                    "price_eligible_count": sum(1 for ev in evidences if _is_number(ev.unit_price)),
                    "message": None,
                }
            except Exception as exc:
                evidences_by_source[name] = []
                source_status[name] = {
                    "status": "failed",
                    "count": 0,
                    "price_eligible_count": 0,
                    "message": str(exc),
                }

        async def handle_etender():
            name = self.etender.source_name
            if name not in enabled:
                source_status[name] = {
                    "status": "skipped",
                    "count": 0,
                    "price_eligible_count": 0,
                    "message": "Manba o‘chirib qo‘yilgan (enabled_sources).",
                }
                evidences_by_source[name] = []
                return

            try:
                keyword = _pick_keyword_for_etender(keywords=keywords, user_query=user_query)

                evidences = await self.etender.search(
                    query=keyword,
                    period_months=period_months,
                    page_size=page_size,
                    max_pages=max_pages,
                )

                evidences_by_source[name] = evidences
                source_status[name] = {
                    "status": "success",
                    "count": len(evidences),
                    "price_eligible_count": sum(1 for ev in evidences if _is_number(ev.unit_price)),
                    "message": None,
                }
            except Exception as exc:
                evidences_by_source[name] = []
                source_status[name] = {
                    "status": "failed",
                    "count": 0,
                    "price_eligible_count": 0,
                    "message": str(exc),
                }

        # Run sequentially to keep portal load low and avoid being blocked.
        await handle_xarid(self.xarid_shop)
        await handle_xarid(self.xarid_national)
        await handle_xarid(self.xarid_auction)
        await handle_etender()

        all_evidences: list[Evidence] = []
        for items in evidences_by_source.values():
            all_evidences.extend(items)

        return {
            "all_evidences": all_evidences,
            "evidences_by_source": evidences_by_source,
            "source_status": source_status,
        }
