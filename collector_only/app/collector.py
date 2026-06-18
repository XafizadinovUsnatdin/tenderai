from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import string
from collections import deque
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from dotenv import load_dotenv

from app.connectors.ebirja_public_connector import EbirjaPublicConnector
from app.connectors.etender_uzex_connector import EtenderUzexConnector
from app.connectors.new_cooperation_connector import NewCooperationConnector
from app.connectors.new_xarid_public_connector import NewXaridPublicConnector
from app.connectors.stat_new_cooperation_connector import StatNewCooperationConnector
from app.connectors.xt_xarid_public_connector import XtXaridPublicConnector
from app.connectors.xarid_uzex_connector import XaridUzexConnector
from app.schemas import Evidence, ProductCandidate
from app.services.env_config import (
    get_tender_archive_database_url,
    get_tender_archive_db_path,
    get_tender_archive_sync_interval_seconds,
)
from app.services.tender_archive_repository_factory import create_tender_archive_repository


load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("tenderai.full_collector")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", ""))
    except Exception:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\x00", "").replace("\u00a0", " ").strip()
    return " ".join(text.split())


def _tokenize(value: str | None) -> list[str]:
    if not value:
        return []

    parts = re.split(r"[^0-9A-Za-zА-Яа-яЁё]+", value)
    return [part.strip() for part in parts if len(part.strip()) >= 2]


def _keyword_variants(value: str | None) -> list[str]:
    text = _clean_text(value)
    if not text:
        return []

    variants: list[str] = []
    seen: set[str] = set()

    def add(candidate: str | None) -> None:
        cleaned = _clean_text(candidate)
        key = cleaned.lower()
        if not cleaned or key in seen:
            return
        seen.add(key)
        variants.append(cleaned)

    add(text)

    tokens = _tokenize(text)
    for token in tokens:
        add(token)
        if len(token) >= 3:
            upper_bound = min(len(token), 8)
            for length in range(3, upper_bound + 1):
                add(token[:length])

    if len(tokens) >= 2:
        add(" ".join(tokens[:2]))
    if len(tokens) >= 3:
        add(" ".join(tokens[:3]))

    return variants


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        cleaned = _clean_text(value)
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def _evidence_to_record(
    evidence: Evidence,
    *,
    category_id: int | None = None,
    product_code: str | None = None,
) -> dict[str, Any]:
    payload = asdict(evidence)
    payload.pop("raw_payload", None)
    payload.pop("raw_text", None)
    payload.pop("contract_file_name", None)
    payload.pop("additional_protocol_file_name", None)

    payload["category_id"] = category_id if category_id is not None else payload.get("category_id")
    payload["product_code"] = product_code if product_code is not None else payload.get("product_code")

    return payload


def _category_record(source_name: str, category: dict[str, Any]) -> dict[str, Any] | None:
    category_id = category.get("id")
    if not isinstance(category_id, int):
        try:
            category_id = int(category_id)
        except Exception:
            return None

    return {
        "source_name": source_name,
        "category_id": category_id,
        "category_name": _clean_text(category.get("name") or category.get("category_name") or ""),
        "raw_json": json.dumps(category, ensure_ascii=False, separators=(",", ":")),
    }


def _product_record(
    source_name: str,
    category_id: int,
    keyword: str,
    product: dict[str, Any],
) -> dict[str, Any] | None:
    product_code = _clean_text(product.get("product_code"))
    if not product_code:
        return None

    return {
        "source_name": source_name,
        "category_id": category_id,
        "product_code": product_code,
        "product_name": _clean_text(product.get("name")),
        "category_name": _clean_text(product.get("category_name")),
        "type_id": product.get("type_id"),
        "total_count": product.get("total_count"),
        "rn": product.get("rn"),
        "query_keyword": _clean_text(keyword),
        "raw_json": json.dumps(product, ensure_ascii=False, separators=(",", ":")),
    }


class TenderArchiveCollector:
    def __init__(
        self,
        *,
        repository: Any | None = None,
        years_back: int = 5,
        xarid_pages_per_cycle: int = 3,
        product_queries_per_cycle: int = 10,
        etender_pages_per_cycle: int = 3,
        xarid_page_size: int = 200,
        etender_page_size: int = 500,
        public_pages_per_cycle: int = 1,
        public_page_size: int = 20,
        xt_page_size: int = 5,
        public_dataset_concurrency: int = 4,
        sleep_seconds: int = 300,
    ):
        self.repository = repository or create_tender_archive_repository()
        self.years_back = max(1, int(years_back))
        self.xarid_pages_per_cycle = max(1, int(xarid_pages_per_cycle))
        self.product_queries_per_cycle = max(1, int(product_queries_per_cycle))
        self.etender_pages_per_cycle = max(1, int(etender_pages_per_cycle))
        self.xarid_page_size = max(20, int(xarid_page_size))
        self.etender_page_size = max(20, int(etender_page_size))
        self.public_pages_per_cycle = max(1, int(public_pages_per_cycle))
        self.public_page_size = max(5, int(public_page_size))
        self.xt_page_size = max(2, int(xt_page_size))
        self.public_dataset_concurrency = max(1, int(public_dataset_concurrency))
        self.sleep_seconds = max(30, int(sleep_seconds))
        self._repository_write_lock = asyncio.Lock()

        self.catalog_source_name = "xarid.uzex.uz"
        self.xarid_shop = XaridUzexConnector(view=XaridUzexConnector.VIEW_SHOP)
        self.xarid_national = XaridUzexConnector(view=XaridUzexConnector.VIEW_NATIONAL)
        self.xarid_auction = XaridUzexConnector(view=XaridUzexConnector.VIEW_AUCTION)
        self.etender = EtenderUzexConnector()
        self.stat_cooperation = StatNewCooperationConnector()
        self.new_cooperation = NewCooperationConnector()
        self.new_xarid = NewXaridPublicConnector()
        self.ebirja = EbirjaPublicConnector()
        self.xt_xarid = XtXaridPublicConnector()

    async def _run_repository_write(self, func, *args, **kwargs):
        async with self._repository_write_lock:
            return await asyncio.to_thread(func, *args, **kwargs)

    def _cutoff(self) -> datetime:
        return datetime.now(timezone.utc) - timedelta(days=365 * self.years_back)

    def _years_to_scan(self) -> list[int]:
        cutoff = self._cutoff()
        now = datetime.now(timezone.utc)
        return list(range(now.year, cutoff.year - 1, -1))

    @staticmethod
    def _evidence_date(evidence: Evidence) -> datetime | None:
        for value in (evidence.deal_date, evidence.begin_date, evidence.end_date):
            parsed = _parse_iso_datetime(value)
            if parsed is not None:
                return parsed
        return None

    def _is_evidence_in_year_scope(self, evidence: Evidence) -> bool:
        parsed = self._evidence_date(evidence)
        return parsed is None or parsed >= self._cutoff()

    def _build_product_seeds(self, category_name: str, recent_product_names: list[str]) -> list[str]:
        seeds: list[str] = [""]

        def add(value: str | None) -> None:
            cleaned = _clean_text(value)
            if cleaned and cleaned.lower() not in seen:
                seen.add(cleaned.lower())
                seeds.append(cleaned)

        seen: set[str] = {""}
        add(category_name)

        for token in _tokenize(category_name):
            add(token)

        for name in recent_product_names[:20]:
            add(name)
            for token in _tokenize(name):
                add(token)

        for char in string.ascii_lowercase:
            add(char)
        for char in "абвгдежзийклмнопрстуфхцчшщъыьэюя":
            add(char)
        for char in string.digits:
            add(char)

        return seeds

    async def _store_categories(self, categories: list[dict[str, Any]]) -> int:
        records = []
        for category in categories:
            record = _category_record(self.catalog_source_name, category)
            if record is not None:
                records.append(record)
        return await self._run_repository_write(self.repository.upsert_categories, records)

    async def _store_products(self, records: list[dict[str, Any]]) -> int:
        if not records:
            return 0
        return await self._run_repository_write(self.repository.upsert_products, records)

    async def _store_evidences(self, records: list[dict[str, Any]]) -> int:
        if not records:
            return 0
        return await self._run_repository_write(self.repository.upsert_evidences, records)

    async def _set_state(self, state_key: str, state: dict[str, Any]) -> None:
        await self._run_repository_write(self.repository.set_state, state_key, state)

    async def _set_cycle_status(self, state: dict[str, Any]) -> None:
        payload = dict(state)
        payload["updated_at"] = _now_iso()
        await self._set_state("collector:cycle:last_status", payload)

    @staticmethod
    def _find_category_index(categories: list[dict[str, Any]], category_id: int) -> int | None:
        for index, category in enumerate(categories):
            try:
                current_id = int(category.get("id"))
            except Exception:
                continue
            if current_id == category_id:
                return index
        return None

    @staticmethod
    def _serialize_text_list(values: list[str]) -> list[str]:
        return _dedupe_preserve_order([_clean_text(value) for value in values])

    def _build_full_product_seeds(
        self,
        category_name: str,
        product_names: list[str],
        product_codes: list[str],
    ) -> list[str]:
        seeds: list[str] = []
        seen: set[str] = set()

        def add(value: str | None) -> None:
            cleaned = _clean_text(value)
            key = cleaned.lower()
            if cleaned and key not in seen:
                seen.add(key)
                seeds.append(cleaned)

        add(category_name)
        for token in _tokenize(category_name):
            add(token)

        for name in product_names:
            for variant in _keyword_variants(name):
                add(variant)

        for product_code in product_codes:
            add(product_code)

        for char in string.ascii_lowercase:
            add(char)
        for char in "Р°Р±РІРіРґРµР¶Р·РёР№РєР»РјРЅРѕРїСЂСЃС‚СѓС„С…С†С‡С€С‰СЉС‹СЊСЌСЋСЏ":
            add(char)
        for char in string.digits:
            add(char)

        return seeds

    async def collect_xarid_deals_full(
        self,
        client: httpx.AsyncClient,
        connector: XaridUzexConnector,
        categories: list[dict[str, Any]],
    ) -> dict[str, Any]:
        state_key = f"collector:full:xarid:{connector.view}"
        state = await asyncio.to_thread(self.repository.get_state, state_key) or {}

        cutoff = self._cutoff()
        cutoff_year = cutoff.year
        years = self._years_to_scan()
        ordered_categories = sorted(
            categories,
            key=lambda category: int(category.get("id") or 0) if str(category.get("id") or "").strip() else 0,
        )

        if state.get("completed"):
            return {
                "state_key": state_key,
                "status": "done",
                "records_written": 0,
                "completed": True,
            }

        if not years or not ordered_categories:
            return {
                "state_key": state_key,
                "status": "empty",
                "records_written": 0,
                "completed": False,
            }

        def _resolve_year_index() -> int:
            raw_year = state.get("year")
            if raw_year is not None:
                try:
                    year_value = int(raw_year)
                    if year_value in years:
                        return years.index(year_value)
                except Exception:
                    pass

            raw_year_index = state.get("year_index")
            if raw_year_index is not None:
                try:
                    year_index = int(raw_year_index)
                    if 0 <= year_index < len(years):
                        return year_index
                except Exception:
                    pass

            return 0

        def _resolve_category_index() -> int:
            raw_category_id = state.get("category_id")
            if raw_category_id is not None:
                try:
                    category_id = int(raw_category_id)
                except Exception:
                    category_id = None
                if category_id is not None:
                    found = self._find_category_index(ordered_categories, category_id)
                    if found is not None:
                        return found

            raw_category_index = state.get("category_index")
            if raw_category_index is not None:
                try:
                    category_index = int(raw_category_index)
                    if 0 <= category_index < len(ordered_categories):
                        return category_index
                except Exception:
                    pass

            return 0

        start_year_index = _resolve_year_index()
        start_category_index = _resolve_category_index()
        start_page_index = max(int(state.get("page_index", 0) or 0), 0)

        if start_year_index >= len(years):
            start_year_index = len(years) - 1
            start_category_index = len(ordered_categories) - 1
            start_page_index = 0

        start_year = years[start_year_index]
        start_category = ordered_categories[start_category_index]
        start_category_id = start_category.get("id")
        try:
            start_category_id = int(start_category_id)
        except Exception:
            start_category_id = None

        logger.info(
            "Full deal crawl %s: year=%s category_id=%s page=%s resumed=%s",
            connector.view,
            start_year,
            start_category_id,
            start_page_index,
            bool(state),
        )

        async def save_progress(
            *,
            year_index: int,
            category_index: int,
            category_id: int | None,
            page_index: int,
            completed: bool = False,
        ) -> None:
            await self._set_state(
                state_key,
                {
                    "year": years[year_index] if 0 <= year_index < len(years) else None,
                    "year_index": year_index,
                    "category_index": category_index,
                    "category_id": category_id,
                    "page_index": page_index,
                    "completed": completed,
                    "updated_at": _now_iso(),
                },
            )

        def next_position(year_index: int, category_index: int) -> tuple[int, int, int | None, bool]:
            next_category_index = category_index + 1
            next_year_index = year_index
            next_category_id: int | None = None

            if next_category_index >= len(ordered_categories):
                next_year_index = year_index + 1
                next_category_index = 0
                if next_year_index < len(years):
                    try:
                        next_category_id = int(ordered_categories[0].get("id"))
                    except Exception:
                        next_category_id = None
            else:
                try:
                    next_category_id = int(ordered_categories[next_category_index].get("id"))
                except Exception:
                    next_category_id = None

            completed = next_year_index >= len(years)
            return next_year_index, next_category_index, next_category_id, completed

        records_written = 0
        view_results: list[dict[str, Any]] = []

        for year_index in range(start_year_index, len(years)):
            year = years[year_index]
            year_written = 0
            year_result: dict[str, Any] = {"year": year, "categories": []}
            category_start_index = start_category_index if year_index == start_year_index else 0

            for category_index in range(category_start_index, len(ordered_categories)):
                category = ordered_categories[category_index]
                category_id_raw = category.get("id")
                try:
                    category_id = int(category_id_raw)
                except Exception:
                    continue

                category_name = _clean_text(category.get("name") or category.get("category_name") or str(category_id))
                candidate = ProductCandidate(
                    id=category_id,
                    product_code="",
                    name=category_name,
                    category_id=category_id,
                    category_name=category_name,
                )

                page_index = start_page_index if (year_index == start_year_index and category_index == category_start_index) else 0
                category_written = 0
                max_pages_per_category_year = 5000

                logger.info(
                    "Full deal crawl: view=%s year=%s category=%s(%s) page=%s",
                    connector.view,
                    year,
                    category_name,
                    category_id,
                    page_index,
                )

                while True:
                    if page_index >= max_pages_per_category_year:
                        logger.warning(
                            "Full deal crawl page cap reached: view=%s year=%s category=%s(%s) cap=%s",
                            connector.view,
                            year,
                            category_name,
                            category_id,
                            max_pages_per_category_year,
                        )
                        next_year_index, next_category_index, next_category_id, completed = next_position(year_index, category_index)
                        await save_progress(
                            year_index=next_year_index,
                            category_index=next_category_index,
                            category_id=next_category_id,
                            page_index=0,
                            completed=False,
                        )
                        return {
                            "state_key": state_key,
                            "status": "page_cap",
                            "records_written": records_written,
                            "completed": False,
                            "years": view_results,
                        }

                    from_row = page_index * self.xarid_page_size + 1
                    to_row = (page_index + 1) * self.xarid_page_size
                    raw_deals = await connector.get_completed_deals(
                        client=client,
                        candidate=candidate,
                        year_id=year,
                        from_row=from_row,
                        to_row=to_row,
                    )

                    if not raw_deals:
                        next_year_index, next_category_index, next_category_id, completed = next_position(year_index, category_index)
                        if completed:
                            await save_progress(
                                year_index=len(years) - 1,
                                category_index=len(ordered_categories) - 1,
                                category_id=None,
                                page_index=0,
                                completed=True,
                            )
                            break
                        await save_progress(
                            year_index=next_year_index,
                            category_index=next_category_index,
                            category_id=next_category_id,
                            page_index=0,
                        )
                        break

                    records: list[dict[str, Any]] = []
                    for deal in raw_deals:
                        evidence = connector.build_evidence(deal)
                        deal_date = _parse_iso_datetime(evidence.deal_date)
                        if year == cutoff_year and deal_date is not None and deal_date < cutoff:
                            continue

                        product_code = None
                        if evidence.product_name:
                            product_code = await asyncio.to_thread(
                                self.repository.get_product_code_for_name,
                                category_id=category_id,
                                product_name=evidence.product_name,
                            )

                        records.append(
                            _evidence_to_record(
                                evidence,
                                category_id=category_id,
                                product_code=product_code,
                            )
                        )

                    written = await self._store_evidences(records)
                    records_written += written
                    category_written += written
                    year_written += written

                    page_index += 1
                    await save_progress(
                        year_index=year_index,
                        category_index=category_index,
                        category_id=category_id,
                        page_index=page_index,
                    )

                    oldest_raw_date = _parse_iso_datetime(raw_deals[-1].get("deal_date"))
                    if oldest_raw_date is not None and oldest_raw_date < cutoff:
                        next_year_index, next_category_index, next_category_id, completed = next_position(year_index, category_index)
                        if completed:
                            await save_progress(
                                year_index=len(years) - 1,
                                category_index=len(ordered_categories) - 1,
                                category_id=None,
                                page_index=0,
                                completed=True,
                            )
                        else:
                            await save_progress(
                                year_index=next_year_index,
                                category_index=next_category_index,
                                category_id=next_category_id,
                                page_index=0,
                            )
                        break

                year_result["categories"].append(
                    {
                        "category_id": category_id,
                        "category_name": category_name,
                        "records_written": category_written,
                    }
                )

            year_result["records_written"] = year_written
            view_results.append(year_result)
            start_category_index = 0
            start_page_index = 0

        await save_progress(
            year_index=len(years) - 1,
            category_index=len(ordered_categories) - 1,
            category_id=None,
            page_index=0,
            completed=True,
        )

        return {
            "state_key": state_key,
            "status": "ok",
            "records_written": records_written,
            "completed": True,
            "years": view_results,
        }

    async def collect_xarid_products_full(
        self,
        client: httpx.AsyncClient,
        categories: list[dict[str, Any]],
    ) -> dict[str, Any]:
        state_key = "collector:full:xarid:products"
        state = await asyncio.to_thread(self.repository.get_state, state_key) or {}

        if state.get("completed"):
            return {
                "state_key": state_key,
                "status": "done",
                "records_written": 0,
                "completed": True,
            }

        ordered_categories = sorted(
            categories,
            key=lambda category: int(category.get("id") or 0) if str(category.get("id") or "").strip() else 0,
        )
        if not ordered_categories:
            return {
                "state_key": state_key,
                "status": "empty",
                "records_written": 0,
                "completed": False,
            }

        def _resolve_start_category_index() -> int:
            raw_category_id = state.get("category_id")
            if raw_category_id is not None:
                try:
                    category_id = int(raw_category_id)
                except Exception:
                    category_id = None
                if category_id is not None:
                    found = self._find_category_index(ordered_categories, category_id)
                    if found is not None:
                        return found

            raw_category_index = state.get("category_index")
            if raw_category_index is not None:
                try:
                    category_index = int(raw_category_index)
                    if 0 <= category_index < len(ordered_categories):
                        return category_index
                except Exception:
                    pass

            return 0

        start_category_index = _resolve_start_category_index()
        resumed_category_id = state.get("category_id")
        try:
            resumed_category_id = int(resumed_category_id) if resumed_category_id is not None else None
        except Exception:
            resumed_category_id = None

        logger.info(
            "Full product crawl resumed=%s start_category_index=%s start_category_id=%s",
            bool(state),
            start_category_index,
            resumed_category_id,
        )

        async def save_progress(
            *,
            category_index: int,
            category_id: int | None,
            queue: deque[str],
            seen_keywords: set[str],
            known_codes: set[str],
            category_written: int,
            category_queries: int,
            completed: bool = False,
        ) -> None:
            await self._set_state(
                state_key,
                {
                    "category_index": category_index,
                    "category_id": category_id,
                    "queue": list(queue),
                    "seen_keywords": self._serialize_text_list(list(seen_keywords)),
                    "known_codes": self._serialize_text_list(list(known_codes)),
                    "category_written": category_written,
                    "category_queries": category_queries,
                    "completed": completed,
                    "updated_at": _now_iso(),
                },
            )

        async def load_category_state(
            *,
            category_index: int,
            category_id: int,
            category_name: str,
        ) -> tuple[deque[str], set[str], set[str], int, int]:
            if category_index == start_category_index and resumed_category_id == category_id and state.get("queue") is not None:
                queue_values = state.get("queue") or []
                seen_values = state.get("seen_keywords") or []
                known_values = state.get("known_codes") or []
                queue = deque(_clean_text(value) for value in queue_values if _clean_text(value))
                seen_keywords = { _clean_text(value).lower() for value in seen_values if _clean_text(value) }
                known_codes = { _clean_text(value).lower() for value in known_values if _clean_text(value) }
                category_written = int(state.get("category_written", 0) or 0)
                category_queries = int(state.get("category_queries", 0) or 0)
                return queue, seen_keywords, known_codes, category_written, category_queries

            product_names = await asyncio.to_thread(
                self.repository.get_recent_product_names,
                category_id=category_id,
                limit=5000,
            )
            product_codes = await asyncio.to_thread(
                self.repository.get_product_codes,
                category_id=category_id,
                limit=5000,
            )
            seeds = self._build_full_product_seeds(
                category_name=category_name,
                product_names=product_names,
                product_codes=product_codes,
            )

            logger.info(
                "Full product crawl: category=%s(%s) seeds=%s known_codes=%s",
                category_name,
                category_id,
                len(seeds),
                len(product_codes),
            )

            queue = deque(seeds)
            seen_keywords: set[str] = set()
            known_codes = {code.lower() for code in product_codes if code}
            return queue, seen_keywords, known_codes, 0, 0

        records_written = 0
        category_results: list[dict[str, Any]] = []

        for category_index in range(start_category_index, len(ordered_categories)):
            category = ordered_categories[category_index]
            category_id_raw = category.get("id")
            try:
                category_id = int(category_id_raw)
            except Exception:
                continue

            category_name = _clean_text(category.get("name") or category.get("category_name") or str(category_id))
            queue, seen_keywords, known_codes, category_written, category_queries = await load_category_state(
                category_index=category_index,
                category_id=category_id,
                category_name=category_name,
            )

            logger.info(
                "Full product crawl: category=%s(%s) queue=%s known_codes=%s resumed=%s",
                category_name,
                category_id,
                len(queue),
                len(known_codes),
                bool(state) and category_index == start_category_index and resumed_category_id == category_id,
            )

            while queue:
                keyword = _clean_text(queue.popleft())
                keyword_key = keyword.lower()
                if not keyword or keyword_key in seen_keywords:
                    continue
                seen_keywords.add(keyword_key)

                products = await self.xarid_shop.get_products(
                    client=client,
                    category_id=category_id,
                    keyword=keyword,
                )
                category_queries += 1

                records: list[dict[str, Any]] = []
                newly_discovered_terms: list[str] = []

                for product in products:
                    record = _product_record(self.catalog_source_name, category_id, keyword, product)
                    if record is not None:
                        records.append(record)

                    product_code = _clean_text(product.get("product_code"))
                    product_name = _clean_text(product.get("name"))
                    if product_code and product_code.lower() not in known_codes:
                        known_codes.add(product_code.lower())
                        newly_discovered_terms.append(product_name or product_code)
                    elif product_name:
                        newly_discovered_terms.append(product_name)

                written = await self._store_products(records)
                records_written += written
                category_written += written

                for term in newly_discovered_terms:
                    for variant in _keyword_variants(term):
                        variant_key = variant.lower()
                        if variant_key not in seen_keywords:
                            queue.append(variant)

                await save_progress(
                    category_index=category_index,
                    category_id=category_id,
                    queue=queue,
                    seen_keywords=seen_keywords,
                    known_codes=known_codes,
                    category_written=category_written,
                    category_queries=category_queries,
                )

                await asyncio.sleep(0.05)

            category_results.append(
                {
                    "category_id": category_id,
                    "category_name": category_name,
                    "records_written": category_written,
                    "queries": category_queries,
                    "known_codes": len(known_codes),
                }
            )

            next_category_index = category_index + 1
            next_category_id = None
            if next_category_index < len(ordered_categories):
                try:
                    next_category_id = int(ordered_categories[next_category_index].get("id"))
                except Exception:
                    next_category_id = None

            await save_progress(
                category_index=next_category_index,
                category_id=next_category_id,
                queue=deque(),
                seen_keywords=set(),
                known_codes=set(),
                category_written=0,
                category_queries=0,
                completed=next_category_index >= len(ordered_categories),
            )

        await save_progress(
            category_index=len(ordered_categories),
            category_id=None,
            queue=deque(),
            seen_keywords=set(),
            known_codes=set(),
            category_written=0,
            category_queries=0,
            completed=True,
        )

        return {
            "state_key": state_key,
            "status": "ok",
            "records_written": records_written,
            "completed": True,
            "categories": category_results,
        }

    async def collect_etender_deals_full(self, client: httpx.AsyncClient) -> dict[str, Any]:
        state_key = "collector:full:etender"
        state = await asyncio.to_thread(self.repository.get_state, state_key) or {}

        if state.get("completed"):
            return {
                "state_key": state_key,
                "status": "done",
                "records_written": 0,
                "completed": True,
            }

        cutoff = self._cutoff()
        page_index = max(int(state.get("page_index", 0) or 0), 0)
        max_pages = 5000
        records_written = 0

        logger.info("Full Etender crawl resumed=%s page_index=%s", bool(state), page_index)

        async def save_progress(*, page_index_value: int, completed: bool = False) -> None:
            await self._set_state(
                state_key,
                {
                    "page_index": page_index_value,
                    "completed": completed,
                    "updated_at": _now_iso(),
                },
            )

        while True:
            if page_index >= max_pages:
                logger.warning("Full Etender crawl page cap reached: cap=%s", max_pages)
                await save_progress(page_index_value=page_index, completed=False)
                return {
                    "state_key": state_key,
                    "status": "page_cap",
                    "records_written": records_written,
                    "completed": False,
                    "page_index": page_index,
                }

            from_row = page_index * self.etender_page_size + 1
            to_row = (page_index + 1) * self.etender_page_size
            raw_deals = await self.etender.get_deals_page(
                client=client,
                keyword=None,
                from_row=from_row,
                to_row=to_row,
            )

            if not raw_deals:
                await save_progress(page_index_value=page_index, completed=True)
                break

            raw_deals = await self.etender.attach_criteria_files(client, raw_deals)

            records: list[dict[str, Any]] = []
            for deal in raw_deals:
                evidence = self.etender.build_evidence(deal)
                deal_date = _parse_iso_datetime(evidence.deal_date)
                if deal_date is not None and deal_date < cutoff:
                    continue
                records.append(_evidence_to_record(evidence))

            written = await self._store_evidences(records)
            records_written += written

            oldest_date = _parse_iso_datetime(raw_deals[-1].get("deal_date"))
            page_index += 1
            if oldest_date is not None and oldest_date < cutoff:
                await save_progress(page_index_value=page_index, completed=True)
                break

            await save_progress(page_index_value=page_index, completed=False)

        return {
            "state_key": state_key,
            "status": "ok",
            "records_written": records_written,
            "completed": True,
            "page_index": page_index,
        }

    async def _collect_public_pages(
        self,
        *,
        connector_label: str,
        datasets: list[dict[str, Any]],
        page_size: int,
        fetch_page,
        full_backfill: bool,
    ) -> dict[str, Any]:
        cutoff = self._cutoff()

        async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
            semaphore = asyncio.Semaphore(self.public_dataset_concurrency)

            async def process_dataset(index: int, dataset: dict[str, Any]) -> tuple[int, dict[str, Any]]:
                async with semaphore:
                    page_index = 0
                    dataset_written = 0
                    pages_processed = 0
                    has_more = False

                    while True:
                        evidences, has_more = await fetch_page(client, dataset, page_index, page_size)
                        scoped_evidences = [ev for ev in evidences if self._is_evidence_in_year_scope(ev)]
                        written = await self._store_evidences([_evidence_to_record(ev) for ev in scoped_evidences])
                        dataset_written += written
                        pages_processed += 1

                        parsed_dates = [
                            parsed
                            for parsed in (self._evidence_date(ev) for ev in evidences)
                            if parsed is not None
                        ]
                        page_is_before_cutoff = bool(parsed_dates) and max(parsed_dates) < cutoff

                        if not full_backfill and pages_processed >= self.public_pages_per_cycle:
                            break
                        if not has_more:
                            break
                        if full_backfill and page_is_before_cutoff:
                            break

                        page_index += 1
                        await asyncio.sleep(0.05)

                    await self._set_state(
                        f"collector:public:{dataset['source_name']}",
                        {
                            "source_name": dataset["source_name"],
                            "page_index": page_index,
                            "page_size": page_size,
                            "pages_processed": pages_processed,
                            "records_written": dataset_written,
                            "has_more": bool(has_more),
                            "full_backfill": bool(full_backfill),
                            "updated_at": _now_iso(),
                        },
                    )
                    logger.info(
                        "%s synced: dataset=%s records=%s pages=%s full=%s",
                        connector_label,
                        dataset["source_name"],
                        dataset_written,
                        pages_processed,
                        full_backfill,
                    )
                    return index, {
                        "dataset": dataset["source_name"],
                        "records_written": dataset_written,
                        "pages_processed": pages_processed,
                    }

            results = await asyncio.gather(
                *(process_dataset(index, dataset) for index, dataset in enumerate(datasets))
            )

        ordered_dataset_results = [
            result
            for _, result in sorted(results, key=lambda item: item[0])
        ]
        records_written = sum(int(result["records_written"]) for result in ordered_dataset_results)

        return {
            "connector": connector_label,
            "records_written": records_written,
            "datasets": ordered_dataset_results,
            "full_backfill": full_backfill,
        }

    async def _collect_public_connectors(self, *, full_backfill: bool) -> dict[str, dict[str, Any]]:
        tasks = {
            "stat_cooperation_result": asyncio.create_task(self.collect_stat_cooperation(full_backfill=full_backfill)),
            "new_cooperation_result": asyncio.create_task(self.collect_new_cooperation(full_backfill=full_backfill)),
            "new_xarid_result": asyncio.create_task(self.collect_new_xarid_public(full_backfill=full_backfill)),
            "ebirja_result": asyncio.create_task(self.collect_ebirja_public(full_backfill=full_backfill)),
            "xt_xarid_result": asyncio.create_task(self.collect_xt_xarid_public(full_backfill=full_backfill)),
        }
        task_names = list(tasks.keys())
        task_results = await asyncio.gather(*(tasks[name] for name in task_names))
        return {
            name: result
            for name, result in zip(task_names, task_results)
        }

    async def collect_stat_cooperation(self, *, full_backfill: bool = False) -> dict[str, Any]:
        return await self._collect_public_pages(
            connector_label="stat-new.cooperation",
            datasets=list(self.stat_cooperation.DATASETS),
            page_size=self.public_page_size,
            fetch_page=lambda client, dataset, page_index, page_size: self.stat_cooperation.fetch_dataset_page(
                client,
                dataset,
                page_index=page_index,
                page_size=page_size,
            ),
            full_backfill=full_backfill,
        )

    async def collect_new_cooperation(self, *, full_backfill: bool = False) -> dict[str, Any]:
        return await self._collect_public_pages(
            connector_label="new.cooperation",
            datasets=list(self.new_cooperation.DATASETS),
            page_size=self.public_page_size,
            fetch_page=lambda client, dataset, page_index, page_size: self.new_cooperation.fetch_dataset_page(
                client,
                dataset,
                page_index=page_index,
                page_size=page_size,
            ),
            full_backfill=full_backfill,
        )

    async def collect_new_xarid_public(self, *, full_backfill: bool = False) -> dict[str, Any]:
        datasets = [
            {
                "source_name": self.new_xarid.SOURCE_NAME,
                "source_type": self.new_xarid.SOURCE_TYPE,
            }
        ]
        return await self._collect_public_pages(
            connector_label="new-xarid",
            datasets=datasets,
            page_size=self.public_page_size,
            fetch_page=lambda client, dataset, page_index, page_size: self.new_xarid.fetch_page(
                client,
                page_index=page_index,
                page_size=page_size,
            ),
            full_backfill=full_backfill,
        )

    async def collect_ebirja_public(self, *, full_backfill: bool = False) -> dict[str, Any]:
        return await self._collect_public_pages(
            connector_label="ebirja-public",
            datasets=list(self.ebirja.DATASETS),
            page_size=self.public_page_size,
            fetch_page=lambda client, dataset, page_index, page_size: self.ebirja.fetch_dataset_page(
                client,
                dataset,
                page_index=page_index,
                page_size=page_size,
            ),
            full_backfill=full_backfill,
        )

    async def collect_xt_xarid_public(self, *, full_backfill: bool = False) -> dict[str, Any]:
        return await self._collect_public_pages(
            connector_label="xt-xarid",
            datasets=list(self.xt_xarid.DATASETS),
            page_size=self.xt_page_size,
            fetch_page=lambda client, dataset, page_index, page_size: self.xt_xarid.fetch_dataset_page(
                client,
                dataset,
                page_index=page_index,
                page_size=page_size,
            ),
            full_backfill=full_backfill,
        )

    async def run_full_backfill(self) -> dict[str, Any]:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60) as xarid_client, httpx.AsyncClient(
            follow_redirects=True,
            timeout=60,
        ) as etender_client:
            categories = await self.collect_categories(xarid_client)
            public_task = asyncio.create_task(self._collect_public_connectors(full_backfill=True))
            etender_task = asyncio.create_task(self.collect_etender_deals_full(etender_client))

            xarid_results = list(
                await asyncio.gather(
                    self.collect_xarid_deals_full(xarid_client, self.xarid_shop, categories),
                    self.collect_xarid_deals_full(xarid_client, self.xarid_national, categories),
                    self.collect_xarid_deals_full(xarid_client, self.xarid_auction, categories),
                )
            )

            product_result = await self.collect_xarid_products_full(xarid_client, categories)
            product_code_backfill = await self._run_repository_write(self.repository.backfill_evidence_product_codes)
            etender_result = await etender_task
            public_results = await public_task

        stats = await asyncio.to_thread(self.repository.get_stats)
        return {
            "categories_count": len(categories),
            "xarid_results": xarid_results,
            "product_result": product_result,
            "product_code_backfill": product_code_backfill,
            "etender_result": etender_result,
            **public_results,
            "stats": stats,
        }

    async def collect_categories(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        categories = await self.xarid_shop.get_categories(client)
        written = await self._store_categories(categories)
        logger.info("Categories synced: fetched=%s stored=%s", len(categories), written)
        await self._set_state(
            "collector:xarid:categories",
            {
                "fetched": len(categories),
                "stored": written,
                "updated_at": _now_iso(),
            },
        )
        return categories

    async def collect_xarid_deals(
        self,
        client: httpx.AsyncClient,
        connector: XaridUzexConnector,
        categories: list[dict[str, Any]],
    ) -> dict[str, Any]:
        state_key = f"collector:xarid:deals:{connector.view}"
        state = await asyncio.to_thread(self.repository.get_state, state_key) or {}

        work_index = int(state.get("work_index", 0))
        page_index = int(state.get("page_index", 0))
        years = self._years_to_scan()
        work_items = [(category, year) for year in years for category in categories]
        cutoff = self._cutoff()
        cutoff_year = cutoff.year

        if not work_items:
            return {
                "state_key": state_key,
                "status": "empty",
                "records_written": 0,
                "work_index": 0,
                "page_index": 0,
            }

        records_written = 0
        product_code_cache: dict[tuple[int, str], str | None] = {}

        for _ in range(self.xarid_pages_per_cycle):
            if work_index >= len(work_items):
                work_index = 0

            category, year = work_items[work_index]
            category_id = category.get("id")
            try:
                category_id = int(category_id)
            except Exception:
                work_index = (work_index + 1) % len(work_items)
                page_index = 0
                continue

            category_name = _clean_text(category.get("name") or category.get("category_name") or str(category_id))
            candidate = ProductCandidate(
                id=category_id,
                product_code="",
                name=category_name,
                category_id=category_id,
                category_name=category_name,
            )

            from_row = page_index * self.xarid_page_size + 1
            to_row = (page_index + 1) * self.xarid_page_size
            raw_deals = await connector.get_completed_deals(
                client=client,
                candidate=candidate,
                year_id=year,
                from_row=from_row,
                to_row=to_row,
            )

            if not raw_deals:
                work_index = (work_index + 1) % len(work_items)
                page_index = 0
                continue

            records: list[dict[str, Any]] = []
            for deal in raw_deals:
                evidence = connector.build_evidence(deal)
                deal_date = _parse_iso_datetime(evidence.deal_date)
                if year == cutoff_year and deal_date is not None and deal_date < cutoff:
                    continue

                product_code = None
                if evidence.product_name:
                    cache_key = (category_id, evidence.product_name.lower())
                    if cache_key in product_code_cache:
                        product_code = product_code_cache[cache_key]
                    else:
                        product_code = await asyncio.to_thread(
                            self.repository.get_product_code_for_name,
                            category_id=category_id,
                            product_name=evidence.product_name,
                        )
                        product_code_cache[cache_key] = product_code

                records.append(
                    _evidence_to_record(
                        evidence,
                        category_id=category_id,
                        product_code=product_code,
                    )
                )

            written = await self._store_evidences(records)
            records_written += written

            oldest_raw_date = _parse_iso_datetime(raw_deals[-1].get("deal_date"))
            if year == cutoff_year and oldest_raw_date is not None and oldest_raw_date < cutoff:
                work_index = (work_index + 1) % len(work_items)
                page_index = 0
            else:
                page_index += 1

        await self._set_state(
            state_key,
            {
                "work_index": work_index,
                "page_index": page_index,
                "updated_at": _now_iso(),
            },
        )

        return {
            "state_key": state_key,
            "status": "ok",
            "records_written": records_written,
            "work_index": work_index,
            "page_index": page_index,
        }

    async def collect_xarid_products(
        self,
        client: httpx.AsyncClient,
        categories: list[dict[str, Any]],
    ) -> dict[str, Any]:
        state_key = "collector:xarid:products"
        state = await asyncio.to_thread(self.repository.get_state, state_key) or {}

        work_index = int(state.get("work_index", 0))
        seed_index = int(state.get("seed_index", 0))

        if not categories:
            return {
                "state_key": state_key,
                "status": "empty",
                "records_written": 0,
                "work_index": 0,
                "seed_index": 0,
            }

        records_written = 0
        queries_done = 0

        while queries_done < self.product_queries_per_cycle:
            if work_index >= len(categories):
                work_index = 0

            category = categories[work_index]
            category_id = category.get("id")
            try:
                category_id = int(category_id)
            except Exception:
                work_index = (work_index + 1) % len(categories)
                seed_index = 0
                continue

            category_name = _clean_text(category.get("name") or category.get("category_name") or str(category_id))
            recent_product_names = await asyncio.to_thread(
                self.repository.get_recent_product_names,
                category_id=category_id,
                limit=20,
            )
            seeds = self._build_product_seeds(category_name, recent_product_names)

            if seed_index >= len(seeds):
                work_index = (work_index + 1) % len(categories)
                seed_index = 0
                continue

            keyword = seeds[seed_index]
            products = await self.xarid_shop.get_products(
                client=client,
                category_id=category_id,
                keyword=keyword,
            )

            records: list[dict[str, Any]] = []
            for product in products:
                record = _product_record(self.catalog_source_name, category_id, keyword, product)
                if record is not None:
                    records.append(record)

            written = await self._store_products(records)
            records_written += written

            seed_index += 1
            queries_done += 1

        await self._set_state(
            state_key,
            {
                "work_index": work_index,
                "seed_index": seed_index,
                "updated_at": _now_iso(),
            },
        )

        return {
            "state_key": state_key,
            "status": "ok",
            "records_written": records_written,
            "work_index": work_index,
            "seed_index": seed_index,
        }

    async def collect_etender_deals(self, client: httpx.AsyncClient) -> dict[str, Any]:
        state_key = "collector:etender:deals"
        state = await asyncio.to_thread(self.repository.get_state, state_key) or {}
        page_index = int(state.get("page_index", 0))
        cutoff = self._cutoff()
        records_written = 0

        for _ in range(self.etender_pages_per_cycle):
            from_row = page_index * self.etender_page_size + 1
            to_row = (page_index + 1) * self.etender_page_size
            raw_deals = await self.etender.get_deals_page(
                client=client,
                keyword=None,
                from_row=from_row,
                to_row=to_row,
            )

            if not raw_deals:
                page_index = 0
                break

            raw_deals = await self.etender.attach_criteria_files(client, raw_deals)

            records: list[dict[str, Any]] = []
            for deal in raw_deals:
                evidence = self.etender.build_evidence(deal)
                deal_date = _parse_iso_datetime(evidence.deal_date)
                if deal_date is not None and deal_date < cutoff:
                    continue
                records.append(_evidence_to_record(evidence))

            written = await self._store_evidences(records)
            records_written += written

            oldest_date = _parse_iso_datetime(raw_deals[-1].get("deal_date"))
            page_index += 1
            if oldest_date is not None and oldest_date < cutoff:
                break

        await self._set_state(
            state_key,
            {
                "page_index": page_index,
                "updated_at": _now_iso(),
            },
        )

        return {
            "state_key": state_key,
            "status": "ok",
            "records_written": records_written,
            "page_index": page_index,
        }

    async def run_cycle(self) -> dict[str, Any]:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60) as xarid_client, httpx.AsyncClient(
            follow_redirects=True,
            timeout=60,
        ) as etender_client:
            categories = await self.collect_categories(xarid_client)
            public_task = asyncio.create_task(self._collect_public_connectors(full_backfill=False))
            etender_task = asyncio.create_task(self.collect_etender_deals(etender_client))

            xarid_results = list(
                await asyncio.gather(
                    self.collect_xarid_deals(xarid_client, self.xarid_shop, categories),
                    self.collect_xarid_deals(xarid_client, self.xarid_national, categories),
                    self.collect_xarid_deals(xarid_client, self.xarid_auction, categories),
                )
            )

            product_result = await self.collect_xarid_products(xarid_client, categories)
            product_code_backfill = await self._run_repository_write(self.repository.backfill_evidence_product_codes)
            etender_result = await etender_task
            public_results = await public_task

        stats = await asyncio.to_thread(self.repository.get_stats)
        return {
            "categories_count": len(categories),
            "xarid_results": xarid_results,
            "product_result": product_result,
            "product_code_backfill": product_code_backfill,
            "etender_result": etender_result,
            **public_results,
            "stats": stats,
        }

    async def run_forever(self) -> None:
        while True:
            try:
                cycle = await self.run_cycle()
                xarid_written = sum(int(item.get("records_written", 0)) for item in cycle["xarid_results"])
                public_written = sum(
                    int(cycle[key].get("records_written", 0))
                    for key in [
                        "stat_cooperation_result",
                        "new_cooperation_result",
                        "new_xarid_result",
                        "ebirja_result",
                        "xt_xarid_result",
                    ]
                )
                logger.info(
                    "Collector cycle finished: categories=%s xarid=%s products=%s product_code_backfill=%s etender=%s public=%s total=%s",
                    cycle["categories_count"],
                    xarid_written,
                    int(cycle["product_result"].get("records_written", 0)),
                    int(cycle["product_code_backfill"]),
                    int(cycle["etender_result"].get("records_written", 0)),
                    public_written,
                    cycle["stats"].get("total_records"),
                )
                await self._set_cycle_status(
                    {
                        "status": "ok",
                        "completed": True,
                        "categories_count": int(cycle["categories_count"]),
                        "xarid_written": int(xarid_written),
                        "products_written": int(cycle["product_result"].get("records_written", 0)),
                        "etender_written": int(cycle["etender_result"].get("records_written", 0)),
                        "public_written": int(public_written),
                        "total_records": int(cycle["stats"].get("total_records", 0) or 0),
                        "message": "",
                    }
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Collector cycle failed: %s", exc)
                try:
                    await self._set_cycle_status(
                        {
                            "status": "error",
                            "completed": False,
                            "message": str(exc),
                        }
                    )
                except Exception:
                    logger.exception("Collector cycle error state save failed")

            await asyncio.sleep(self.sleep_seconds)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect tender API data into the archive database.")
    parser.add_argument(
        "--db-path",
        default=get_tender_archive_db_path(),
        help="SQLite archive path fallback. Ignored when PostgreSQL database URL is provided.",
    )
    parser.add_argument(
        "--database-url",
        default=get_tender_archive_database_url(),
        help="Optional PostgreSQL archive database URL.",
    )
    parser.add_argument("--years-back", type=int, default=5, help="How many years back to collect.")
    parser.add_argument(
        "--xarid-pages-per-cycle",
        type=int,
        default=3,
        help="How many Xarid deal pages to process per cycle for each view.",
    )
    parser.add_argument(
        "--product-queries-per-cycle",
        type=int,
        default=10,
        help="How many product search queries to run per cycle.",
    )
    parser.add_argument(
        "--etender-pages-per-cycle",
        type=int,
        default=3,
        help="How many Etender pages to process per cycle.",
    )
    parser.add_argument(
        "--public-pages-per-cycle",
        type=int,
        default=1,
        help="How many first pages to refresh per cycle for new public sources.",
    )
    parser.add_argument("--xarid-page-size", type=int, default=200, help="Batch size for Xarid deal queries.")
    parser.add_argument("--etender-page-size", type=int, default=500, help="Batch size for Etender deal queries.")
    parser.add_argument("--public-page-size", type=int, default=20, help="Batch size for paginated public-source queries.")
    parser.add_argument("--xt-page-size", type=int, default=5, help="Batch size for xt-xarid public RPC queries.")
    parser.add_argument(
        "--public-dataset-concurrency",
        type=int,
        default=4,
        help="How many public datasets to refresh in parallel inside each connector.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=int,
        default=get_tender_archive_sync_interval_seconds(),
        help="Sleep between collector cycles.",
    )
    parser.add_argument("--reset-archive", action="store_true", help="Delete all cached archive data before running.")
    parser.add_argument("--full-backfill", action="store_true", help="Run an exhaustive 5-year backfill and exit.")
    parser.add_argument("--once", action="store_true", help="Run one collection cycle and exit.")
    return parser


async def main(argv: list[str] | None = None) -> None:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    repository = create_tender_archive_repository(args.db_path, database_url=args.database_url)
    collector = TenderArchiveCollector(
        repository=repository,
        years_back=args.years_back,
        xarid_pages_per_cycle=args.xarid_pages_per_cycle,
        product_queries_per_cycle=args.product_queries_per_cycle,
        etender_pages_per_cycle=args.etender_pages_per_cycle,
        xarid_page_size=args.xarid_page_size,
        etender_page_size=args.etender_page_size,
        public_pages_per_cycle=args.public_pages_per_cycle,
        public_page_size=args.public_page_size,
        xt_page_size=args.xt_page_size,
        public_dataset_concurrency=args.public_dataset_concurrency,
        sleep_seconds=args.sleep_seconds,
    )

    if args.reset_archive:
        await asyncio.to_thread(repository.reset_archive)
        logger.info("Archive reset finished.")
        if not args.full_backfill and not args.once:
            return

    if args.full_backfill:
        result = await collector.run_full_backfill()
        xarid_written = sum(int(item.get("records_written", 0)) for item in result["xarid_results"])
        public_written = sum(
            int(result[key].get("records_written", 0))
            for key in [
                "stat_cooperation_result",
                "new_cooperation_result",
                "new_xarid_result",
                "ebirja_result",
                "xt_xarid_result",
            ]
        )
        logger.info(
            "Full backfill finished: categories=%s xarid=%s products=%s product_code_backfill=%s etender=%s public=%s total=%s",
            result["categories_count"],
            xarid_written,
            int(result["product_result"].get("records_written", 0)),
            int(result["product_code_backfill"]),
            int(result["etender_result"].get("records_written", 0)),
            public_written,
            result["stats"].get("total_records"),
        )
        return

    if args.once:
        cycle = await collector.run_cycle()
        xarid_written = sum(int(item.get("records_written", 0)) for item in cycle["xarid_results"])
        public_written = sum(
            int(cycle[key].get("records_written", 0))
            for key in [
                "stat_cooperation_result",
                "new_cooperation_result",
                "new_xarid_result",
                "ebirja_result",
                "xt_xarid_result",
            ]
        )
        logger.info(
            "One cycle finished: categories=%s xarid=%s products=%s product_code_backfill=%s etender=%s public=%s total=%s",
            cycle["categories_count"],
            xarid_written,
            int(cycle["product_result"].get("records_written", 0)),
            int(cycle["product_code_backfill"]),
            int(cycle["etender_result"].get("records_written", 0)),
            public_written,
            cycle["stats"].get("total_records"),
        )
        return

    await collector.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
