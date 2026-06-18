from __future__ import annotations

import asyncio
from urllib.parse import urljoin
from typing import Any

import httpx

from app.connectors.common import build_parameter_text, build_raw_text, maybe_float, maybe_int, pick_region_name, pick_text
from app.schemas import Evidence


class NewCooperationConnector:
    SITE_URL = "https://new.cooperation.uz"
    CABINET_API_URL = "https://cabinet.cooperation.uz/api"
    CLIENT_API_URL = "https://new.cooperation.uz/ocelot/api-client"
    AUCTION_URL = "https://new.cooperation.uz/auction"
    E_CATALOG_URL = "https://new.cooperation.uz/e-catalog?type=product"
    E_SHOP_URL = "https://new.cooperation.uz/e-shop"
    LOCAL_SHOP_URL = "https://new.cooperation.uz/local-shop"
    HEADERS = {
        "Accept": "application/json, text/plain, */*",
        "Origin": SITE_URL,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120 Safari/537.36"
        ),
    }

    AUCTION_DATASET = {
        "key": "auction",
        "source_name": "new.cooperation.uz/auction",
        "source_type": "cooperation_public_auction",
        "source_url": AUCTION_URL,
    }
    E_CATALOG_DATASET = {
        "key": "e-catalog",
        "source_name": "new.cooperation.uz/e-catalog",
        "source_type": "cooperation_public_ecatalog",
        "source_url": E_CATALOG_URL,
    }
    E_SHOP_DATASET = {
        "key": "e-shop",
        "source_name": "new.cooperation.uz/e-shop",
        "source_type": "cooperation_public_eshop",
        "source_url": E_SHOP_URL,
        "api_path": "offer/public/offers",
        "api_params": {"OfferType": 2},
    }
    LOCAL_SHOP_DATASET = {
        "key": "local-shop",
        "source_name": "new.cooperation.uz/local-shop",
        "source_type": "cooperation_public_local_shop",
        "source_url": LOCAL_SHOP_URL,
        "api_path": "local-offer/public/offers",
        "api_params": {},
    }
    OFFER_DATASET = E_SHOP_DATASET
    DATASETS = [
        AUCTION_DATASET,
        E_CATALOG_DATASET,
        E_SHOP_DATASET,
        LOCAL_SHOP_DATASET,
    ]

    def _headers(self, referer: str) -> dict[str, str]:
        headers = dict(self.HEADERS)
        headers["Referer"] = referer
        return headers

    def _absolute_url(self, value: Any) -> str | None:
        text = pick_text(value)
        if not text:
            return None
        if text.startswith(("http://", "https://")):
            return text
        return urljoin(f"{self.SITE_URL}/", text.lstrip("/"))

    def _first_file_url(self, value: Any) -> str | None:
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    candidate = self._absolute_url(item.get("path") or item.get("url") or item.get("id"))
                else:
                    candidate = self._absolute_url(item)
                if candidate:
                    return candidate
            return None
        return self._absolute_url(value)

    async def _get_json(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str,
        path: str,
        referer: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = await client.get(
            f"{base_url}/{path}",
            params=params,
            headers=self._headers(referer),
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}

    async def _get_auction_detail(self, client: httpx.AsyncClient, lot_id: int, *, referer: str) -> dict[str, Any]:
        payload = await self._get_json(
            client,
            base_url=self.CABINET_API_URL,
            path=f"auction/public/lots/{lot_id}",
            referer=referer,
        )
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    def _build_auction_evidences(self, dataset: dict[str, Any], detail: dict[str, Any]) -> list[Evidence]:
        delivery = detail.get("deliveryInformation") if isinstance(detail.get("deliveryInformation"), dict) else {}
        general = detail.get("generalInformation") if isinstance(detail.get("generalInformation"), dict) else {}
        lot_products = detail.get("lotProducts") if isinstance(detail.get("lotProducts"), list) else []

        evidences: list[Evidence] = []
        for product in lot_products or [None]:
            quantity = maybe_float(product.get("quantity")) if isinstance(product, dict) else None
            current_price = maybe_float(product.get("currentPrice")) if isinstance(product, dict) else maybe_float(general.get("currentPrice"))
            unit_price = (current_price / quantity) if current_price is not None and quantity not in {None, 0} else None
            product_code = pick_text(product.get("code")) if isinstance(product, dict) else None
            condition = (
                pick_text(product.get("description"))
                if isinstance(product, dict)
                else None
            ) or build_parameter_text(
                [
                    ("Mahsulot kodi", product_code),
                    ("O'lchov", product.get("measure") if isinstance(product, dict) else None),
                    ("Miqdor", quantity),
                    ("Boshlang'ich narx", product.get("startPrice") if isinstance(product, dict) else general.get("startingPrice")),
                    ("Joriy narx", current_price),
                ]
            )
            raw_text = build_raw_text(
                [
                    ("Manba", dataset["source_name"]),
                    ("Lot", detail.get("lotNumber")),
                    ("Mahsulot", pick_text(product.get("name")) if isinstance(product, dict) else detail.get("name")),
                    ("Kod", pick_text(product.get("code")) if isinstance(product, dict) else None),
                    ("Miqdor", quantity),
                    ("Boshlang'ich narx", product.get("startPrice") if isinstance(product, dict) else general.get("startingPrice")),
                    ("Joriy narx", current_price),
                    ("Keyingi narx", product.get("nextPrice") if isinstance(product, dict) else general.get("price")),
                    ("Buyurtmachi", detail.get("companyName")),
                    ("Hudud", detail.get("region")),
                    ("Tuman", delivery.get("district")),
                    ("Manzil", delivery.get("address")),
                    ("Boshlanish", detail.get("beginDate")),
                    ("Tugash", detail.get("endDate")),
                    ("Tavsif", condition),
                ]
            )
            evidences.append(
                Evidence(
                    source_name=dataset["source_name"],
                    source_type=dataset["source_type"],
                    source_url=dataset["source_url"],
                    lot_id=str(detail.get("id") or detail.get("lotNumber") or ""),
                    lot_display_no=pick_text(detail.get("lotNumber")) or None,
                    product_name=pick_text(product.get("name")) if isinstance(product, dict) else pick_text(detail.get("name")),
                    category_name=None,
                    condition=condition or None,
                    amount=quantity,
                    deal_cost=current_price,
                    unit_price=unit_price,
                    currency="UZS",
                    region=pick_region_name(detail.get("region")),
                    provider_name=None,
                    deal_date=pick_text(detail.get("beginDate")) or None,
                    deal_status_name=pick_text(detail.get("lotStatus")) or None,
                    payment_status=None,
                    raw_payload=detail,
                    raw_text=raw_text,
                    participants_count=maybe_int(detail.get("providerCount")),
                    customer_name=pick_text(detail.get("companyName")) or None,
                    customer_inn=None,
                    provider_inn=None,
                    start_cost=maybe_float(product.get("startPrice")) if isinstance(product, dict) else maybe_float(general.get("startingPrice")),
                    contract_file_name=None,
                    contract_file_path=None,
                    additional_protocol_file_name=None,
                    additional_protocol_file_path=None,
                    procedure_type="auction",
                    contract_number=None,
                    begin_date=pick_text(detail.get("beginDate")) or None,
                    end_date=pick_text(detail.get("endDate")) or None,
                    address=pick_text(delivery.get("address")) or None,
                    district=pick_region_name(delivery.get("district")),
                    country=None,
                    measure=pick_text(product.get("measure")) if isinstance(product, dict) else None,
                    manufacturer_country=None,
                    status_code=pick_text(detail.get("lotStatus")) or None,
                    time_left_seconds=maybe_int(detail.get("timeLeft")),
                    product_code=product_code,
                )
            )
        return evidences

    def _build_market_evidence(self, dataset: dict[str, Any], row: dict[str, Any]) -> Evidence:
        condition = build_parameter_text(
            [
                ("Mahsulot kodi", row.get("enktCode")),
                ("O'lchov", row.get("measure")),
                ("Minimal miqdor", row.get("minQuantity")),
                ("Maksimal miqdor", row.get("maxQuantity")),
                ("Birlik narx", row.get("price")),
            ]
        )
        raw_text = build_raw_text(
            [
                ("Manba", dataset["source_name"]),
                ("Taklif", row.get("offerNumber")),
                ("Mahsulot", row.get("name")),
                ("Kod", row.get("enktCode")),
                ("Xususiyatlar", condition),
                ("Narx", row.get("price")),
                ("Min miqdor", row.get("minQuantity")),
                ("Max miqdor", row.get("maxQuantity")),
                ("Boshlanish", row.get("startDate")),
                ("Tugash", row.get("endDate")),
            ]
        )
        amount = maybe_float(row.get("maxQuantity")) or maybe_float(row.get("minQuantity"))
        return Evidence(
            source_name=dataset["source_name"],
            source_type=dataset["source_type"],
            source_url=dataset["source_url"],
            lot_id=str(row.get("id") or row.get("offerNumber") or ""),
            lot_display_no=pick_text(row.get("offerNumber")) or None,
            product_name=pick_text(row.get("name")) or None,
            category_name=None,
            condition=condition or None,
            amount=amount,
            deal_cost=None,
            unit_price=maybe_float(row.get("price")),
            currency="UZS",
            region=None,
            provider_name=None,
            deal_date=pick_text(row.get("startDate")) or None,
            deal_status_name=pick_text(row.get("status")) or None,
            payment_status=None,
            raw_payload=row,
            raw_text=raw_text,
            participants_count=None,
            customer_name=None,
            customer_inn=None,
            provider_inn=None,
            start_cost=None,
            contract_file_name=None,
            contract_file_path=self._first_file_url(row.get("photos")),
            additional_protocol_file_name=None,
            additional_protocol_file_path=None,
            procedure_type=dataset["key"],
            contract_number=None,
            begin_date=pick_text(row.get("startDate")) or None,
            end_date=pick_text(row.get("endDate")) or None,
            address=None,
            district=None,
            country=None,
            measure=pick_text(row.get("measure")) or None,
            manufacturer_country=None,
            status_code=pick_text(row.get("status")) or None,
            time_left_seconds=maybe_int(row.get("timeLeft")),
            product_code=pick_text(row.get("enktCode")) or None,
        )

    def _build_catalog_evidence(self, row: dict[str, Any]) -> Evidence:
        category = row.get("category") if isinstance(row.get("category"), dict) else {}
        company = row.get("company") if isinstance(row.get("company"), dict) else {}
        condition = build_parameter_text(
            [
                ("Mahsulot kodi", row.get("code")),
                ("TN VED", row.get("companyTnvedName")),
                ("O'lchov", row.get("measureName")),
                ("Miqdor", row.get("productQuantity")),
                ("Min partiya", row.get("minPart")),
                ("Max partiya", row.get("maxPart")),
                ("Birlik narx", row.get("unitPrice")),
                ("Sertifikat", row.get("isCertificate")),
            ]
        )
        raw_text = build_raw_text(
            [
                ("Manba", self.E_CATALOG_DATASET["source_name"]),
                ("Taklif", row.get("offerNumber")),
                ("Mahsulot", row.get("productName")),
                ("Kod", row.get("code")),
                ("Kategoriya", category.get("name")),
                ("Xususiyatlar", condition),
                ("Birlik", row.get("measureName")),
                ("Birlik narx", row.get("unitPrice")),
                ("Miqdor", row.get("productQuantity")),
                ("Min partiya", row.get("minPart")),
                ("Max partiya", row.get("maxPart")),
                ("Tugash", row.get("publicEndDate")),
                ("Ta'minotchi", company.get("name")),
                ("Ta'minotchi STIR", company.get("tin")),
                ("Hudud", company.get("companyRegion")),
            ]
        )
        return Evidence(
            source_name=self.E_CATALOG_DATASET["source_name"],
            source_type=self.E_CATALOG_DATASET["source_type"],
            source_url=self.E_CATALOG_DATASET["source_url"],
            lot_id=str(row.get("id") or row.get("offerNumber") or ""),
            lot_display_no=pick_text(row.get("offerNumber")) or None,
            product_name=pick_text(row.get("productName")) or None,
            category_name=pick_text(category.get("name")) or None,
            condition=condition or None,
            amount=maybe_float(row.get("productQuantity")) or maybe_float(row.get("maxPart")) or maybe_float(row.get("minPart")),
            deal_cost=None,
            unit_price=maybe_float(row.get("unitPrice")),
            currency="UZS",
            region=pick_region_name(company.get("companyRegion")),
            provider_name=pick_text(company.get("name")) or None,
            deal_date=pick_text(row.get("statusDate")) or None,
            deal_status_name=None,
            payment_status=None,
            raw_payload=row,
            raw_text=raw_text,
            participants_count=None,
            customer_name=None,
            customer_inn=None,
            provider_inn=pick_text(company.get("tin")) or None,
            start_cost=None,
            contract_file_name=None,
            contract_file_path=self._first_file_url(row.get("photos")),
            additional_protocol_file_name=None,
            additional_protocol_file_path=None,
            procedure_type=self.E_CATALOG_DATASET["key"],
            contract_number=None,
            begin_date=pick_text(row.get("statusDate")) or None,
            end_date=pick_text(row.get("publicEndDate")) or None,
            address=None,
            district=None,
            country=None,
            measure=pick_text(row.get("measureName")) or None,
            manufacturer_country=None,
            status_code=None,
            time_left_seconds=None,
            product_code=pick_text(row.get("code")) or None,
            category_id=maybe_int(category.get("id")),
        )

    async def fetch_auction_page(
        self,
        client: httpx.AsyncClient,
        *,
        page_index: int,
        page_size: int,
    ) -> tuple[list[Evidence], bool]:
        payload = await self._get_json(
            client,
            base_url=self.CABINET_API_URL,
            path="auction/public/lots",
            referer=self.AUCTION_DATASET["source_url"],
            params={"pageSize": page_size, "pageIndex": page_index + 1},
        )
        rows = payload.get("data")
        if not isinstance(rows, list):
            rows = []

        detail_tasks = [
            self._get_auction_detail(client, maybe_int(row.get("id")) or 0, referer=self.AUCTION_DATASET["source_url"])
            for row in rows
            if isinstance(row, dict) and maybe_int(row.get("id"))
        ]
        details = await asyncio.gather(*detail_tasks) if detail_tasks else []

        evidences: list[Evidence] = []
        for detail in details:
            if detail:
                evidences.extend(self._build_auction_evidences(self.AUCTION_DATASET, detail))

        return evidences, len(rows) >= page_size

    async def fetch_catalog_page(
        self,
        client: httpx.AsyncClient,
        *,
        page_index: int,
        page_size: int,
    ) -> tuple[list[Evidence], bool]:
        payload = await self._get_json(
            client,
            base_url=self.CLIENT_API_URL,
            path="Client/GetAllOffer",
            referer=self.E_CATALOG_DATASET["source_url"],
            params={
                "OfferType": 1,
                "skip": page_index * page_size,
                "take": page_size,
                "productName": "",
            },
        )
        result = payload.get("result")
        rows = result.get("data") if isinstance(result, dict) else None
        if not isinstance(rows, list):
            rows = []
        evidences = [self._build_catalog_evidence(row) for row in rows if isinstance(row, dict)]
        return evidences, len(rows) >= page_size

    async def fetch_market_page(
        self,
        client: httpx.AsyncClient,
        dataset: dict[str, Any],
        *,
        page_index: int,
        page_size: int,
    ) -> tuple[list[Evidence], bool]:
        params = dict(dataset.get("api_params") or {})
        params["pageSize"] = page_size
        params["pageIndex"] = page_index + 1

        payload = await self._get_json(
            client,
            base_url=self.CABINET_API_URL,
            path=dataset["api_path"],
            referer=dataset["source_url"],
            params=params,
        )
        rows = payload.get("data")
        if not isinstance(rows, list):
            rows = []
        evidences = [self._build_market_evidence(dataset, row) for row in rows if isinstance(row, dict)]
        return evidences, len(rows) >= page_size

    async def fetch_offer_page(
        self,
        client: httpx.AsyncClient,
        *,
        page_index: int,
        page_size: int,
    ) -> tuple[list[Evidence], bool]:
        return await self.fetch_market_page(
            client,
            self.E_SHOP_DATASET,
            page_index=page_index,
            page_size=page_size,
        )

    async def fetch_dataset_page(
        self,
        client: httpx.AsyncClient,
        dataset: dict[str, Any],
        *,
        page_index: int,
        page_size: int,
    ) -> tuple[list[Evidence], bool]:
        key = dataset["key"]
        if key == "auction":
            return await self.fetch_auction_page(client, page_index=page_index, page_size=page_size)
        if key == "e-catalog":
            return await self.fetch_catalog_page(client, page_index=page_index, page_size=page_size)
        if key in {"e-shop", "local-shop"}:
            return await self.fetch_market_page(client, dataset, page_index=page_index, page_size=page_size)
        raise ValueError(f"Unsupported new.cooperation dataset: {key}")
