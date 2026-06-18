from __future__ import annotations

from typing import Any

import httpx

from app.connectors.common import build_parameter_text, build_raw_text, maybe_float, maybe_int, pick_region_name, pick_text
from app.schemas import Evidence


class StatNewCooperationConnector:
    BASE_URL = "https://stat-new.cooperation.uz/gateway/api-stat"
    SITE_URL = "https://stat-new.cooperation.uz/all-deals"
    HEADERS = {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://stat-new.cooperation.uz",
        "Referer": "https://stat-new.cooperation.uz/all-deals",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120 Safari/537.36"
        ),
    }

    DATASETS = [
        {
            "key": "auction-contracts",
            "source_name": "stat-new.cooperation.uz/auction-contracts",
            "source_type": "cooperation_stat_auction_contract",
        },
        {
            "key": "eshop-contracts",
            "source_name": "stat-new.cooperation.uz/eshop-contracts",
            "source_type": "cooperation_stat_eshop_contract",
        },
        {
            "key": "contracts/getAll",
            "source_name": "stat-new.cooperation.uz/all-contracts",
            "source_type": "cooperation_stat_contract_registry",
        },
    ]

    async def _get_json(self, client: httpx.AsyncClient, path: str, *, skip: int, take: int) -> dict[str, Any]:
        response = await client.get(
            f"{self.BASE_URL}/{path}",
            params={"skip": skip, "take": take},
            headers=self.HEADERS,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}

    def _build_evidence(
        self,
        dataset: dict[str, str],
        row: dict[str, Any],
        *,
        product_name: str | None,
        product_code: str | None,
        amount: float | None,
        measure: str | None,
        manufacturer_country: str | None,
        condition: str | None,
    ) -> Evidence:
        customer_region = row.get("customerRegion")
        customer_district = row.get("customerDistrict")
        country = None
        if isinstance(customer_region, dict):
            country = pick_text(customer_region.get("countryModel")) or None
        status_name = pick_text(row.get("statusName")) or pick_text(row.get("terminationReason")) or str(row.get("statusId") or "")
        unit_price = maybe_float(row.get("price")) or maybe_float(row.get("unitPrice"))
        raw_text = build_raw_text(
            [
                ("Manba", dataset["source_name"]),
                ("Shartnoma", row.get("contractNumber")),
                ("Lot", row.get("lotNumber")),
                ("Mahsulot", product_name),
                ("Kod", product_code),
                ("O'lchov", measure),
                ("Miqdor", amount),
                ("Boshlang'ich narx", row.get("startPrice")),
                ("Narx", row.get("price")),
                ("Shartnoma summasi", row.get("contractAmount")),
                ("Buyurtmachi", row.get("customerName")),
                ("Buyurtmachi STIR", row.get("customerTin")),
                ("Yetkazib beruvchi", row.get("producerName")),
                ("Yetkazib beruvchi STIR", row.get("producerTin")),
                ("Hudud", pick_region_name(customer_region)),
                ("Tuman", pick_region_name(customer_district)),
                ("Holat", status_name),
                ("Boshlanish", row.get("beginDate")),
                ("Tugash", row.get("endDate")),
                ("Bitim vaqti", row.get("dealTime")),
                ("Tavsif", condition),
            ]
        )

        return Evidence(
            source_name=dataset["source_name"],
            source_type=dataset["source_type"],
            source_url=self.SITE_URL,
            lot_id=str(row.get("id") or row.get("docId") or row.get("contractNumber") or ""),
            lot_display_no=pick_text(row.get("lotNumber")) or pick_text(row.get("contractNumber")),
            product_name=product_name,
            category_name=None,
            condition=condition,
            amount=amount,
            deal_cost=maybe_float(row.get("contractAmount")),
            unit_price=unit_price,
            currency="UZS",
            region=pick_region_name(customer_region),
            provider_name=pick_text(row.get("producerName")),
            deal_date=pick_text(row.get("dealTime")) or pick_text(row.get("endDate")) or pick_text(row.get("beginDate")),
            deal_status_name=status_name or None,
            payment_status=None,
            raw_payload=row,
            raw_text=raw_text,
            participants_count=maybe_int(row.get("participantCount")) or maybe_int(row.get("offerCount")),
            customer_name=pick_text(row.get("customerName")),
            customer_inn=pick_text(row.get("customerTin")) or None,
            provider_inn=pick_text(row.get("producerTin")) or None,
            start_cost=maybe_float(row.get("startPrice")),
            contract_file_name=None,
            contract_file_path=None,
            additional_protocol_file_name=None,
            additional_protocol_file_path=None,
            procedure_type=dataset["key"],
            contract_number=pick_text(row.get("contractNumber")) or None,
            begin_date=pick_text(row.get("beginDate")) or None,
            end_date=pick_text(row.get("endDate")) or None,
            address=None,
            district=pick_region_name(customer_district),
            country=country,
            measure=measure,
            manufacturer_country=manufacturer_country,
            status_code=pick_text(row.get("statusId")) or None,
            time_left_seconds=None,
            product_code=product_code,
        )

    def build_evidences_for_row(self, dataset: dict[str, str], row: dict[str, Any]) -> list[Evidence]:
        if dataset["key"] == "auction-contracts":
            products = row.get("products") if isinstance(row.get("products"), list) else []
            evidences: list[Evidence] = []
            for product in products or [None]:
                product_name = pick_text(product.get("name")) if isinstance(product, dict) else None
                product_code = pick_text(product.get("enktCode")) if isinstance(product, dict) else None
                amount = maybe_float(product.get("quantity")) if isinstance(product, dict) else maybe_float(row.get("amount"))
                measure = pick_text(product.get("measure")) if isinstance(product, dict) else None
                description = pick_text(product.get("description")) if isinstance(product, dict) else None
                condition = description or build_parameter_text(
                    [
                        ("Mahsulot kodi", product_code or pick_text(row.get("enktCode")) or pick_text(row.get("hsCode"))),
                        ("O'lchov", measure or pick_text(row.get("measure"))),
                        ("Miqdor", amount),
                        ("Boshlang'ich narx", product.get("startPrice") if isinstance(product, dict) else row.get("startPrice")),
                        ("Birlik narx", row.get("price") or row.get("unitPrice")),
                        ("Ishlab chiqaruvchi mamlakat", row.get("manufacturerCountry")),
                    ]
                )
                evidences.append(
                    self._build_evidence(
                        dataset,
                        row,
                        product_name=product_name or pick_text(row.get("productName")) or pick_text(row.get("lotNumber")),
                        product_code=product_code or pick_text(row.get("enktCode")) or pick_text(row.get("hsCode")),
                        amount=amount,
                        measure=measure or pick_text(row.get("measure")),
                        manufacturer_country=pick_text(row.get("manufacturerCountry")) or None,
                        condition=condition or None,
                    )
                )
            return evidences

        condition = build_parameter_text(
            [
                ("Mahsulot kodi", pick_text(row.get("enktCode")) or pick_text(row.get("hsCode"))),
                ("O'lchov", row.get("measure")),
                ("Miqdor", row.get("amount")),
                ("Boshlang'ich narx", row.get("startPrice")),
                ("Birlik narx", row.get("price") or row.get("unitPrice")),
                ("Ishlab chiqaruvchi mamlakat", row.get("manufacturerCountry")),
                ("Bekor qilish sababi", row.get("terminationReason") or row.get("reasonCancel")),
            ]
        )
        return [
            self._build_evidence(
                dataset,
                row,
                product_name=pick_text(row.get("productName")) or pick_text(row.get("lotNumber")) or pick_text(row.get("contractNumber")),
                product_code=pick_text(row.get("enktCode")) or pick_text(row.get("hsCode")),
                amount=maybe_float(row.get("amount")),
                measure=pick_text(row.get("measure")) or None,
                manufacturer_country=pick_text(row.get("manufacturerCountry")) or None,
                condition=condition or None,
            )
        ]

    async def fetch_dataset_page(
        self,
        client: httpx.AsyncClient,
        dataset: dict[str, str],
        *,
        page_index: int,
        page_size: int,
    ) -> tuple[list[Evidence], bool]:
        payload = await self._get_json(
            client,
            dataset["key"],
            skip=page_index * page_size,
            take=page_size,
        )
        rows = payload.get("content")
        if not isinstance(rows, list):
            rows = []

        evidences: list[Evidence] = []
        for row in rows:
            if isinstance(row, dict):
                evidences.extend(self.build_evidences_for_row(dataset, row))

        return evidences, len(rows) >= page_size
