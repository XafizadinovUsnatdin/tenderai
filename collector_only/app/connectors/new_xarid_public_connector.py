from __future__ import annotations

from typing import Any

import httpx

from app.connectors.common import build_parameter_text, build_raw_text, maybe_float, maybe_int, pick_text
from app.schemas import Evidence


class NewXaridPublicConnector:
    API_BASE = "https://xarid-api-auction.uzex.uz"
    SOURCE_NAME = "new-xarid.uzex.uz/completed-deals"
    SOURCE_TYPE = "new_xarid_completed_deals"
    SOURCE_URL = "https://new-xarid.uzex.uz/"
    HEADERS = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://new-xarid.uzex.uz",
        "Referer": "https://new-xarid.uzex.uz/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120 Safari/537.36"
        ),
    }

    async def fetch_page(
        self,
        client: httpx.AsyncClient,
        *,
        page_index: int,
        page_size: int,
    ) -> tuple[list[Evidence], bool]:
        from_row = page_index * page_size + 1
        to_row = (page_index + 1) * page_size
        response = await client.post(
            f"{self.API_BASE}/Common/GetCompletedDeals",
            json={"from": from_row, "to": to_row},
            headers=self.HEADERS,
            timeout=60,
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            rows = []

        evidences = [self.build_evidence(row) for row in rows if isinstance(row, dict)]
        return evidences, len(rows) >= page_size

    def build_evidence(self, row: dict[str, Any]) -> Evidence:
        condition = pick_text(row.get("condition")) or build_parameter_text(
            [
                ("Turi", row.get("type_name")),
                ("Kategoriya", row.get("category_name")),
                ("Boshlang'ich narx", row.get("start_cost")),
                ("Bitim narxi", row.get("deal_cost")),
            ]
        )
        raw_text = build_raw_text(
            [
                ("Manba", self.SOURCE_NAME),
                ("Lot", row.get("lot_display_no")),
                ("Kategoriya", row.get("category_name")),
                ("Xususiyatlar", condition),
                ("Boshlang'ich narx", row.get("start_cost")),
                ("Bitim narxi", row.get("deal_cost")),
                ("Buyurtmachi", row.get("customer_name")),
                ("Buyurtmachi STIR", row.get("customer_inn")),
                ("Yetkazib beruvchi", row.get("provider_name")),
                ("Yetkazib beruvchi STIR", row.get("provider_inn")),
                ("Boshlanish", row.get("lot_start_date")),
                ("Tugash", row.get("lot_end_date")),
                ("Bitim sanasi", row.get("deal_date")),
                ("Kazna holati", row.get("kazna_status")),
                ("To'lov holati", row.get("kazna_payment_status")),
            ]
        )
        return Evidence(
            source_name=self.SOURCE_NAME,
            source_type=self.SOURCE_TYPE,
            source_url=self.SOURCE_URL,
            lot_id=str(row.get("lot_id") or row.get("deal_id") or row.get("lot_display_no") or ""),
            lot_display_no=pick_text(row.get("lot_display_no")) or None,
            product_name=pick_text(row.get("category_name")) or pick_text(row.get("lot_display_no")) or None,
            category_name=pick_text(row.get("category_name")) or None,
            condition=condition or None,
            amount=None,
            deal_cost=maybe_float(row.get("deal_cost")),
            unit_price=None,
            currency=pick_text(row.get("currency_name")) or "UZS",
            region=pick_text(row.get("customer_region")) or None,
            provider_name=pick_text(row.get("provider_name")) or None,
            deal_date=pick_text(row.get("deal_date")) or None,
            deal_status_name=pick_text(row.get("kazna_status")) or None,
            payment_status=pick_text(row.get("kazna_payment_status")) or None,
            raw_payload=row,
            raw_text=raw_text,
            participants_count=maybe_int(row.get("pcp_count")),
            customer_name=pick_text(row.get("customer_name")) or None,
            customer_inn=pick_text(row.get("customer_inn")) or None,
            provider_inn=pick_text(row.get("provider_inn")) or None,
            start_cost=maybe_float(row.get("start_cost")),
            contract_file_name=None,
            contract_file_path=None,
            additional_protocol_file_name=None,
            additional_protocol_file_path=None,
            procedure_type="completed-deals",
            contract_number=None,
            begin_date=pick_text(row.get("lot_start_date")) or None,
            end_date=pick_text(row.get("lot_end_date")) or None,
            address=None,
            district=None,
            country=None,
            measure=None,
            manufacturer_country=None,
            status_code=pick_text(row.get("kazna_status_id")) or None,
            time_left_seconds=None,
            product_code=pick_text(row.get("product_code")) or None,
            category_id=maybe_int(row.get("category_id")),
        )
