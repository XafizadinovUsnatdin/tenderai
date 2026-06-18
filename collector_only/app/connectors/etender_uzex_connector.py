from __future__ import annotations

import asyncio
import ssl
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urljoin

import httpx

from app.connectors.common import clean_text, join_non_empty, pick_text
from app.schemas import Evidence
from app.services.env_config import env_int


class EtenderUzexConnector:
    source_name = "etender.uzex.uz"
    source_type = "government_etender_deals"

    API_BASE = "https://apietender.uzex.uz/api"
    FILE_BASE = "https://apietender.uzex.uz"
    SUCCESS_DEAL_STATUSES = {"Ғолиб томонидан қабул қилинган (Амалга ошган)", "Бажарилган"}
    SUCCESS_PAYMENT_STATUSES = {"Qabul qilingan", "Оплачен"}

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

    @staticmethod
    def _get_request_timeout_seconds() -> int:
        return env_int("ETENDER_REQUEST_TIMEOUT_SECONDS", 60)

    @staticmethod
    def _get_request_retries() -> int:
        return env_int("ETENDER_REQUEST_RETRIES", 3)

    @staticmethod
    def _get_retry_delay_seconds() -> int:
        return env_int("ETENDER_REQUEST_RETRY_DELAY_SECONDS", 2)

    @staticmethod
    def _get_criteria_concurrency() -> int:
        return env_int("ETENDER_CRITERIA_CONCURRENCY", 8)

    @classmethod
    def _absolute_file_url(cls, value: Any) -> str | None:
        text = clean_text(value)
        if not text:
            return None
        if text.lower().startswith(("http://", "https://")):
            return text
        return urljoin(cls.FILE_BASE, text)

    @staticmethod
    def _build_criteria_condition(criteria_files: list[dict[str, Any]] | None) -> str | None:
        names: list[str] = []
        seen: set[str] = set()
        for item in criteria_files or []:
            if not isinstance(item, dict):
                continue
            name = pick_text(item.get("name"))
            key = name.lower()
            if not name or key in seen:
                continue
            seen.add(key)
            names.append(name)
        condition = join_non_empty(names, sep="\n")
        return condition or None

    async def _get_criteria_files(
        self,
        client: httpx.AsyncClient,
        trade_id: Any,
    ) -> list[dict[str, Any]]:
        trade_id_text = clean_text(trade_id)
        if not trade_id_text:
            return []
        return await self._request_json_list(
            client,
            method="GET",
            url=f"{self.API_BASE}/Common/GetCriteriaFiles/{trade_id_text}",
            context=f"Etender GetCriteriaFiles {trade_id_text}",
            timeout_seconds=self._get_request_timeout_seconds(),
        )

    async def attach_criteria_files(
        self,
        client: httpx.AsyncClient,
        deals: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not deals:
            return deals

        semaphore = asyncio.Semaphore(max(1, self._get_criteria_concurrency()))

        async def attach(deal: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                criteria_files = await self._get_criteria_files(client, deal.get("trade_id"))
            enriched = dict(deal)
            enriched["_criteria_files"] = criteria_files
            return enriched

        return list(await asyncio.gather(*(attach(deal) for deal in deals)))

    async def _request_json_list(
        self,
        client: httpx.AsyncClient,
        *,
        method: str,
        url: str,
        context: str,
        json_payload: dict[str, Any] | None = None,
        timeout_seconds: int | None = None,
    ) -> list[dict[str, Any]]:
        retries = max(1, self._get_request_retries())
        timeout_value = timeout_seconds or self._get_request_timeout_seconds()
        retry_delay = max(0, self._get_retry_delay_seconds())
        retryable_status_codes = {429, 500, 502, 503, 504}

        for attempt in range(1, retries + 1):
            try:
                response = await client.request(
                    method,
                    url,
                    headers=self.HEADERS,
                    json=json_payload,
                    timeout=timeout_value,
                )
                if response.status_code != 200:
                    if response.status_code in retryable_status_codes and attempt < retries:
                        print(
                            f"{context} HTTP {response.status_code}, retry {attempt}/{retries}:",
                            response.text[:500],
                        )
                        await asyncio.sleep(retry_delay * attempt)
                        continue
                    print(f"{context} failed:", response.status_code, response.text[:500])
                    return []
                return self._safe_json_list(response, context=context)
            except (httpx.TimeoutException, httpx.RequestError, ssl.SSLError) as exc:
                if attempt >= retries:
                    print(f"{context} failed after {retries} attempts:", str(exc)[:300])
                    return []
                print(f"{context} timeout/network error, retry {attempt}/{retries}:", str(exc)[:300])
                await asyncio.sleep(retry_delay * attempt)

        return []

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

        return await self._request_json_list(
            client,
            method="POST",
            url=f"{self.API_BASE}/common/DealsList",
            context="Etender DealsList",
            json_payload=payload,
            timeout_seconds=self._get_request_timeout_seconds(),
        )

    async def get_deals_page(
        self,
        client: httpx.AsyncClient,
        keyword: str | None,
        from_row: int,
        to_row: int,
    ) -> list[dict[str, Any]]:
        return await self._get_deals_list(
            client=client,
            keyword=keyword,
            from_row=from_row,
            to_row=to_row,
        )

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
        criteria_condition = self._build_criteria_condition(deal.get("_criteria_files"))
        contract_file_path = self._absolute_file_url(deal.get("contract_file_path"))
        additional_protocol_file_path = self._absolute_file_url(deal.get("additional_protocol_file_path"))
        region = (
            pick_text(deal.get("region_name"))
            or pick_text(deal.get("customer_region_name"))
            or pick_text(deal.get("provider_region_name"))
            or None
        )

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
Qo‘shimcha bayonnoma fayl yo‘li: {additional_protocol_file_path}
Shartnoma fayli: {deal.get("contract_file_name")}
Shartnoma fayl yo‘li: {contract_file_path}
""".strip()

        return Evidence(
            source_name=self.source_name,
            source_type=self.source_type,
            source_url=self._build_source_url(deal),
            lot_id=deal.get("trade_id"),
            lot_display_no=deal.get("display_no"),
            product_name=deal.get("category_name") or deal.get("display_no"),
            category_name=deal.get("category_name"),
            condition=criteria_condition,
            amount=None,
            deal_cost=deal_cost,
            unit_price=unit_price,
            currency=deal.get("currency_name") or "UZS",
            region=region,
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
            contract_file_path=contract_file_path,
            additional_protocol_file_name=deal.get("additional_protocol_file_name"),
            additional_protocol_file_path=additional_protocol_file_path,
            procedure_type=deal.get("procedure_type") or deal.get("trade_type_name") or "etender",
            district=pick_text(deal.get("district_name")) or None,
        )

    def build_evidence(self, deal: dict[str, Any]) -> Evidence:
        return self._build_evidence(deal)

    def _is_successful_deal(self, deal: dict[str, Any]) -> bool:
        return (
            deal.get("deal_status_name") in self.SUCCESS_DEAL_STATUSES
            or deal.get("deal_contract_kazna_status_name") in self.SUCCESS_PAYMENT_STATUSES
        )

    def is_successful_deal(self, deal: dict[str, Any]) -> bool:
        return self._is_successful_deal(deal)

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
