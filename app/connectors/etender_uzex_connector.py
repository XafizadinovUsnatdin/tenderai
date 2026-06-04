from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.schemas import Evidence


class EtenderUzexConnector:
    source_name = "etender.uzex.uz"
    source_type = "government_etender_deals"

    API_BASE = "https://apietender.uzex.uz/api"

    HEADERS = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://etender.uzex.uz",
        "Referer": "https://etender.uzex.uz/deals-list",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120 Safari/537.36"
        ),
    }

    def _safe_json_list(self, response: httpx.Response, *, context: str) -> list[dict[str, Any]]:
        try:
            data = response.json()
        except Exception:
            print(f"{context} invalid JSON:", response.status_code, response.text[:300])
            return []

        return data if isinstance(data, list) else []

    async def search(
        self,
        query: str,
        period_months: int = 12,
        page_size: int = 20,
        max_pages: int = 3,
    ) -> list[Evidence]:
        all_deals: list[dict[str, Any]] = []

        async with httpx.AsyncClient(follow_redirects=True) as client:
            for page in range(max_pages):
                from_row = page * page_size + 1
                to_row = (page + 1) * page_size

                deals = await self._get_deals_list(
                    client=client,
                    keyword=query,
                    from_row=from_row,
                    to_row=to_row,
                )

                if not deals:
                    break

                all_deals.extend(deals)
                await asyncio.sleep(0.2)

        evidences = [
            self._build_evidence(deal)
            for deal in all_deals
        ]

        evidences = self._filter_by_period(
            evidences=evidences,
            period_months=period_months,
        )

        return evidences

    async def _get_deals_list(
        self,
        client: httpx.AsyncClient,
        keyword: str | None,
        from_row: int,
        to_row: int,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "From": from_row,
            "To": to_row,
            "currencyId": None,
            "System_Id": 0,
        }

        if keyword:
            payload["Keyword"] = keyword

        response = await client.post(
            f"{self.API_BASE}/common/DealsList",
            headers=self.HEADERS,
            json=payload,
            timeout=60,
        )

        if response.status_code != 200:
            print(
                "Etender DealsList failed:",
                response.status_code,
                response.text[:500],
            )
            return []

        return self._safe_json_list(response, context="Etender DealsList")

    def _build_source_url(self, deal: dict[str, Any]) -> str:
        """
        Hozircha deals-list sahifasiga display_no bilan link beramiz.
        Agar aniq detail route topilsa, shu joyni keyin almashtiramiz.
        """
        display_no = deal.get("display_no")
        trade_id = deal.get("trade_id")

        base_url = "https://etender.uzex.uz/deals-list"

        if trade_id:
            return f"{base_url}?trade_id={trade_id}"

        if display_no:
            return f"{base_url}?display_no={display_no}"

        return base_url

    def _build_evidence(self, deal: dict[str, Any]) -> Evidence:
        deal_cost = deal.get("deal_cost")

        # Etender DealsList ichida amount / quantity yo‘q.
        # Shuning uchun unit_price hisoblamaymiz.
        # deal_cost umumiy tender/bitim summasi sifatida qoladi.
        unit_price = None

        raw_text = f"""
Manba: etender.uzex.uz
Bitim raqami: {deal.get("display_no")}
Trade ID: {deal.get("trade_id")}
Deal ID: {deal.get("deal_id")}
Kategoriya: {deal.get("category_name")}
Boshlang‘ich narx: {deal.get("start_cost")}
Bitim narxi: {deal.get("deal_cost")}
Valyuta: {deal.get("currency_name")}
Ishtirokchilar soni: {deal.get("participants_count")}
Buyurtmachi: {deal.get("customer_name")}
Buyurtmachi INN: {deal.get("customer_inn")}
Yetkazib beruvchi: {deal.get("provider_name")}
Yetkazib beruvchi INN: {deal.get("provider_inn")}
Bitim sanasi: {deal.get("deal_date")}
Bitim holati: {deal.get("deal_status_name")}
Taklif/protokol holati: {deal.get("proposal_status_name")}
Shartnoma holati: {deal.get("deal_contract_status_name")}
Kazna holati: {deal.get("deal_contract_kazna_status_name")}
Qo‘shimcha bayonnoma fayli: {deal.get("additional_protocol_file_name")}
Qo‘shimcha bayonnoma fayl yo‘li: {deal.get("additional_protocol_file_path")}
Shartnoma fayli: {deal.get("contract_file_name")}
Shartnoma fayl yo‘li: {deal.get("contract_file_path")}
""".strip()

        return Evidence(
            source_name=self.source_name,
            source_type=self.source_type,
            source_url=self._build_source_url(deal),
            lot_id=deal.get("trade_id"),
            lot_display_no=deal.get("display_no"),
            product_name=deal.get("category_name") or deal.get("display_no"),
            category_name=deal.get("category_name"),
            condition=raw_text,
            amount=None,
            deal_cost=deal_cost,
            unit_price=unit_price,
            currency=deal.get("currency_name") or "UZS",
            region=None,
            provider_name=deal.get("provider_name"),
            deal_date=deal.get("deal_date"),
            deal_status_name=deal.get("deal_status_name"),
            payment_status=deal.get("deal_contract_kazna_status_name"),
            raw_payload=deal,
            raw_text=raw_text,
            participants_count=deal.get("participants_count"),
            customer_name=deal.get("customer_name"),
            customer_inn=deal.get("customer_inn"),
            provider_inn=deal.get("provider_inn"),
            start_cost=deal.get("start_cost"),
            contract_file_name=deal.get("contract_file_name"),
            contract_file_path=deal.get("contract_file_path"),
            additional_protocol_file_name=deal.get("additional_protocol_file_name"),
            additional_protocol_file_path=deal.get("additional_protocol_file_path"),
        )

    def _filter_by_period(
        self,
        evidences: list[Evidence],
        period_months: int,
    ) -> list[Evidence]:
        cutoff = datetime.now() - timedelta(days=period_months * 31)

        filtered = []

        for ev in evidences:
            deal_date = self._parse_date(ev.deal_date)

            if deal_date is None:
                continue

            if deal_date >= cutoff:
                filtered.append(ev)

        return filtered

    def _parse_date(self, value: str | None):
        if not value:
            return None

        try:
            return datetime.fromisoformat(value.replace("Z", ""))
        except Exception:
            return None
