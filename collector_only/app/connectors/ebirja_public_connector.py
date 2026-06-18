from __future__ import annotations

from typing import Any

import httpx

from app.connectors.common import (
    area_path_to_text,
    build_parameter_text,
    build_properties_text,
    build_raw_text,
    find_property_value,
    maybe_float,
    maybe_int,
    pick_region_name,
    pick_text,
)
from app.schemas import Evidence


class EbirjaPublicConnector:
    API_BASE = "https://xarid-api.ebirja.uz"
    SITE_URL = "https://xarid.ebirja.uz/uz"

    DATASETS = [
        {
            "key": "shop-e-shop",
            "source_name": "xarid.ebirja.uz/e-shop",
            "source_type": "ebirja_shop_listing",
            "kind": "shop",
            "platform_display": "e-shop",
        },
        {
            "key": "shop-national-shop",
            "source_name": "xarid.ebirja.uz/national-shop",
            "source_type": "ebirja_shop_listing",
            "kind": "shop",
            "platform_display": "national-shop",
        },
        {
            "key": "auction-1",
            "source_name": "xarid.ebirja.uz/auction",
            "source_type": "ebirja_active_auction",
            "kind": "auction",
            "auction_type": 1,
        },
        {
            "key": "auction-2",
            "source_name": "xarid.ebirja.uz/local-auction",
            "source_type": "ebirja_active_auction",
            "kind": "auction",
            "auction_type": 2,
        },
        {
            "key": "tender-1",
            "source_name": "xarid.ebirja.uz/tender",
            "source_type": "ebirja_active_tender",
            "kind": "tender",
            "type": 1,
            "states": [45, 50],
        },
        {
            "key": "tender-2",
            "source_name": "xarid.ebirja.uz/selection",
            "source_type": "ebirja_active_tender",
            "kind": "tender",
            "type": 2,
            "states": [45, 50],
        },
        {
            "key": "offer-request",
            "source_name": "xarid.ebirja.uz/offer-request",
            "source_type": "ebirja_offer_request",
            "kind": "offer-request",
        },
        {
            "key": "contract-shop-e",
            "source_name": "xarid.ebirja.uz/contracts/e-shop",
            "source_type": "ebirja_contract_shop",
            "kind": "contract-shop",
            "contract_type": "e-shop",
        },
        {
            "key": "contract-shop-national",
            "source_name": "xarid.ebirja.uz/contracts/national-shop",
            "source_type": "ebirja_contract_shop",
            "kind": "contract-shop",
            "contract_type": "national-shop",
        },
        {
            "key": "contract-auction-1",
            "source_name": "xarid.ebirja.uz/contracts/auction",
            "source_type": "ebirja_contract_auction",
            "kind": "contract-auction",
            "auction_type": 1,
        },
        {
            "key": "contract-auction-2",
            "source_name": "xarid.ebirja.uz/contracts/local-auction",
            "source_type": "ebirja_contract_auction",
            "kind": "contract-auction",
            "auction_type": 2,
        },
        {
            "key": "contract-tender-1",
            "source_name": "xarid.ebirja.uz/contracts/tender",
            "source_type": "ebirja_contract_tender",
            "kind": "contract-tender",
            "type": 1,
        },
        {
            "key": "contract-tender-2",
            "source_name": "xarid.ebirja.uz/contracts/selection",
            "source_type": "ebirja_contract_tender",
            "kind": "contract-tender",
            "type": 2,
        },
        {
            "key": "contract-offer-request",
            "source_name": "xarid.ebirja.uz/contracts/offer-request",
            "source_type": "ebirja_contract_offer_request",
            "kind": "contract-offer-request",
        },
    ]

    HEADERS = {
        "Accept": "application/json",
        "Origin": "https://xarid.ebirja.uz",
        "Referer": "https://xarid.ebirja.uz/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120 Safari/537.36"
        ),
    }

    async def _get(self, client: httpx.AsyncClient, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        response = await client.get(
            f"{self.API_BASE}/{path}",
            params=params,
            headers=self.HEADERS,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}

    async def _get_contract_tender_view(self, client: httpx.AsyncClient, row_id: int) -> dict[str, Any]:
        return await self._get(client, "common/contract/external-tender-view", params={"id": row_id})

    async def _get_contract_auction_view(self, client: httpx.AsyncClient, row_id: int) -> dict[str, Any]:
        return await self._get(client, "common/contract/external-auction-view", params={"id": row_id})

    @classmethod
    def _dataset_source_url(cls, dataset: dict[str, Any]) -> str:
        source_name = pick_text(dataset.get("source_name"))
        mapped_paths = {
            "xarid.ebirja.uz/contracts/e-shop": "/contracts/shop",
            "xarid.ebirja.uz/contracts/national-shop": "/contracts/national-shop",
            "xarid.ebirja.uz/contracts/auction": "/contracts/auction",
            "xarid.ebirja.uz/contracts/local-auction": "/contracts/local-auction",
            "xarid.ebirja.uz/contracts/tender": "/contracts/tender",
            "xarid.ebirja.uz/contracts/selection": "/contracts/selection",
            "xarid.ebirja.uz/contracts/offer-request": "/contracts/offer-requests",
            "xarid.ebirja.uz/auction": "/contracts/auction",
            "xarid.ebirja.uz/local-auction": "/contracts/local-auction",
            "xarid.ebirja.uz/tender": "/contracts/tender",
            "xarid.ebirja.uz/selection": "/contracts/selection",
            "xarid.ebirja.uz/offer-request": "/contracts/offer-requests",
        }
        path = mapped_paths.get(source_name)
        if path:
            return f"{cls.SITE_URL}{path}"
        return cls.SITE_URL

    @staticmethod
    def _classifier_code(classifier: dict[str, Any]) -> str | None:
        return pick_text(classifier.get("code")) or None

    @staticmethod
    def _classifier_category_id(classifier: dict[str, Any]) -> int | None:
        category_id = classifier.get("classifier_category_id")
        if category_id is None and isinstance(classifier.get("classifier_category"), dict):
            category_id = classifier["classifier_category"].get("id")
        return maybe_int(category_id)

    def _build_shop_evidence(self, dataset: dict[str, Any], row: dict[str, Any]) -> Evidence:
        classifier = row.get("classifier") if isinstance(row.get("classifier"), dict) else {}
        category = classifier.get("classifier_category") if isinstance(classifier.get("classifier_category"), dict) else {}
        quantity = maybe_float(row.get("quantity"))
        unit_price = maybe_float(row.get("unit_price"))
        condition = build_parameter_text(
            [
                ("Mahsulot kodi", classifier.get("code")),
                ("Kategoriya kodi", category.get("code")),
                ("Kategoriya", category),
                ("Ishlab chiqaruvchi mamlakat", row.get("made_in")),
                ("Miqdor", quantity),
                ("Minimal buyurtma", row.get("min_order")),
                ("Maksimal buyurtma", row.get("max_order")),
                ("Yetkazib berish muddati", row.get("delivery_period")),
            ]
        )
        raw_text = build_raw_text(
            [
                ("Manba", dataset["source_name"]),
                ("ID", row.get("id")),
                ("Sarlavha", row.get("title")),
                ("Mahsulot", classifier.get("title_uz") or classifier.get("title_ru")),
                ("Kod", classifier.get("code")),
                ("Xususiyatlar", condition),
                ("Miqdor", quantity),
                ("Birlik narx", unit_price),
                ("Mamlakat", row.get("made_in")),
                ("Faolsiz sana", row.get("inactive_date")),
            ]
        )
        return Evidence(
            source_name=dataset["source_name"],
            source_type=dataset["source_type"],
            source_url=self._dataset_source_url(dataset),
            lot_id=str(row.get("id") or ""),
            lot_display_no=pick_text(row.get("title")) or None,
            product_name=pick_text(row.get("title")) or pick_text(classifier),
            category_name=pick_text(category) or pick_text(classifier),
            condition=condition or None,
            amount=quantity,
            deal_cost=None,
            unit_price=unit_price,
            currency="UZS",
            region=None,
            provider_name=None,
            deal_date=pick_text(row.get("inactive_date")) or None,
            deal_status_name=None,
            payment_status=None,
            raw_payload=row,
            raw_text=raw_text,
            participants_count=None,
            customer_name=None,
            customer_inn=None,
            provider_inn=None,
            start_cost=None,
            contract_file_name=None,
            contract_file_path=None,
            additional_protocol_file_name=None,
            additional_protocol_file_path=None,
            procedure_type=pick_text(row.get("platform_display")) or dataset["key"],
            contract_number=None,
            begin_date=None,
            end_date=pick_text(row.get("inactive_date")) or None,
            address=None,
            district=None,
            country=pick_text(row.get("made_in")) or None,
            measure=None,
            manufacturer_country=pick_text(row.get("made_in")) or None,
            status_code=None,
            time_left_second=None,
            product_code=self._classifier_code(classifier),
            category_id=self._classifier_category_id(classifier),
        )

    def _build_auction_evidence(self, dataset: dict[str, Any], row: dict[str, Any]) -> Evidence:
        company = row.get("company") if isinstance(row.get("company"), dict) else {}
        condition = build_parameter_text(
            [
                ("Pozitsiyalar soni", row.get("position_count")),
                ("Boshlang'ich summa", row.get("total_sum")),
                ("Joriy narx", row.get("current_price")),
                ("Keyingi narx", row.get("next_price")),
                ("Takliflar soni", row.get("offer_count")),
            ]
        )
        raw_text = build_raw_text(
            [
                ("Manba", dataset["source_name"]),
                ("Lot", row.get("lot")),
                ("Sarlavha", row.get("title")),
                ("Buyurtmachi", company.get("title")),
                ("Buyurtmachi STIR", company.get("tin")),
                ("Hudud", row.get("region")),
                ("Tuman", row.get("district")),
                ("Manzil", row.get("address")),
                ("Xususiyatlar", condition),
                ("Boshlanish", row.get("begin_date")),
                ("Tugash", row.get("auction_end")),
                ("Joriy narx", row.get("current_price")),
                ("Boshlang'ich summa", row.get("total_sum")),
                ("Takliflar", row.get("offer_count")),
            ]
        )
        return Evidence(
            source_name=dataset["source_name"],
            source_type=dataset["source_type"],
            source_url=self._dataset_source_url(dataset),
            lot_id=str(row.get("id") or row.get("lot") or ""),
            lot_display_no=pick_text(row.get("lot")) or None,
            product_name=pick_text(row.get("title")) or None,
            category_name=None,
            condition=condition or None,
            amount=maybe_float(row.get("position_count")),
            deal_cost=maybe_float(row.get("current_price")),
            unit_price=None,
            currency="UZS",
            region=pick_region_name(row.get("region")),
            provider_name=None,
            deal_date=pick_text(row.get("begin_date")) or None,
            deal_status_name=None,
            payment_status=None,
            raw_payload=row,
            raw_text=raw_text,
            participants_count=maybe_int(row.get("offer_count")),
            customer_name=pick_text(company.get("title")) or None,
            customer_inn=pick_text(company.get("tin")) or None,
            provider_inn=None,
            start_cost=maybe_float(row.get("total_sum")),
            contract_file_name=None,
            contract_file_path=None,
            additional_protocol_file_name=None,
            additional_protocol_file_path=None,
            procedure_type="auction",
            contract_number=None,
            begin_date=pick_text(row.get("begin_date")) or None,
            end_date=pick_text(row.get("auction_end")) or None,
            address=pick_text(row.get("address")) or None,
            district=pick_region_name(row.get("district")),
            country=None,
            measure=None,
            manufacturer_country=None,
            status_code=pick_text(row.get("type")) or None,
            time_left_second=None,
        )

    def _build_tender_evidences(self, dataset: dict[str, Any], row: dict[str, Any]) -> list[Evidence]:
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        good_maps = meta.get("good_maps") if isinstance(meta.get("good_maps"), list) else []
        company = row.get("company") if isinstance(row.get("company"), dict) else {}
        company_name = pick_text(meta.get("company_name")) or pick_text(row.get("company_name")) or pick_text(company.get("title"))
        company_inn = pick_text(meta.get("company_inn")) or pick_text(company.get("tin")) or None
        region = area_path_to_text(meta.get("area_path")) or pick_region_name(row.get("region")) or pick_region_name(company.get("region"))
        district = pick_region_name(row.get("district")) or pick_region_name(company.get("district"))
        address = pick_text(row.get("address")) or pick_text(company.get("address")) or None

        if not good_maps:
            condition = build_parameter_text(
                [
                    ("Pozitsiyalar soni", row.get("position_count")),
                    ("Boshlang'ich summa", row.get("total_price")),
                    ("Valyuta", row.get("purchase_currency")),
                    ("Moliyalashtirish manbasi", row.get("funding_source")),
                    ("Joylashtirish muddati", row.get("placement_period")),
                ]
            )
            raw_text = build_raw_text(
                [
                    ("Manba", dataset["source_name"]),
                    ("Lot", row.get("lot")),
                    ("Sarlavha", row.get("title")),
                    ("Buyurtmachi", company_name),
                    ("Buyurtmachi STIR", company_inn),
                    ("Hudud", region),
                    ("Tuman", district),
                    ("Manzil", address),
                    ("Xususiyatlar", condition),
                    ("Boshlanish", row.get("begin_date") or row.get("public_discussion_begin_date")),
                    ("Tugash", row.get("end_date") or row.get("public_discussion_end_date")),
                ]
            )
            return [
                Evidence(
                    source_name=dataset["source_name"],
                    source_type=dataset["source_type"],
                    source_url=self._dataset_source_url(dataset),
                    lot_id=str(row.get("id") or row.get("lot") or ""),
                    lot_display_no=pick_text(row.get("lot")) or None,
                    product_name=pick_text(row.get("title")) or None,
                    category_name=None,
                    condition=condition or None,
                    amount=maybe_float(row.get("position_count")),
                    deal_cost=maybe_float(row.get("total_price")),
                    unit_price=None,
                    currency=pick_text(row.get("currency")) or "UZS",
                    region=region,
                    provider_name=None,
                    deal_date=pick_text(row.get("begin_date") or row.get("public_discussion_begin_date")) or None,
                    deal_status_name=pick_text(row.get("status")) or pick_text(row.get("state")) or None,
                    payment_status=None,
                    raw_payload=row,
                    raw_text=raw_text,
                    participants_count=maybe_int(row.get("participant_count")),
                    customer_name=company_name or None,
                    customer_inn=company_inn,
                    provider_inn=None,
                    start_cost=maybe_float(row.get("total_price")),
                    contract_file_name=None,
                    contract_file_path=None,
                    additional_protocol_file_name=None,
                    additional_protocol_file_path=None,
                    procedure_type=dataset["source_name"].split("/")[-1],
                    contract_number=None,
                    begin_date=pick_text(row.get("begin_date") or row.get("public_discussion_begin_date")) or None,
                    end_date=pick_text(row.get("end_date") or row.get("public_discussion_end_date")) or None,
                    address=address,
                    district=district,
                    country=None,
                    measure=None,
                    manufacturer_country=None,
                    status_code=pick_text(row.get("state")) or None,
                    time_left_second=None,
                )
            ]

        evidences: list[Evidence] = []
        for good in good_maps or [None]:
            amount = maybe_float(good.get("amount")) if isinstance(good, dict) else None
            category = good.get("category") if isinstance(good, dict) and isinstance(good.get("category"), dict) else {}
            condition = build_parameter_text(
                [
                    ("Mahsulot kodi", good.get("id") if isinstance(good, dict) else None),
                    ("Kategoriya kodi", category.get("code")),
                    ("Kategoriya", category.get("title") if category else good.get("category") if isinstance(good, dict) else None),
                    ("O'lchov", good.get("unit") if isinstance(good, dict) else None),
                    ("Miqdor", amount),
                    ("Birlik narx", good.get("price") if isinstance(good, dict) else None),
                    ("Jami", good.get("totalcost_item") if isinstance(good, dict) else row.get("totalcost")),
                ]
            )
            raw_text = build_raw_text(
                [
                    ("Manba", dataset["source_name"]),
                    ("ID", row.get("id")),
                    ("Protsedura", row.get("name")),
                    ("Mahsulot", good.get("name") if isinstance(good, dict) else row.get("name")),
                    ("Kod", good.get("id") if isinstance(good, dict) else None),
                    ("Xususiyatlar", condition),
                    ("Miqdor", amount),
                    ("Narx", good.get("price") if isinstance(good, dict) else None),
                    ("Jami", good.get("totalcost_item") if isinstance(good, dict) else row.get("totalcost")),
                    ("Buyurtmachi", company_name),
                    ("Buyurtmachi STIR", company_inn),
                    ("Hudud", region),
                    ("E'lon qilingan", row.get("publicated_at")),
                    ("Yopilish", row.get("close_at")),
                ]
            )
            evidences.append(
                Evidence(
                    source_name=dataset["source_name"],
                    source_type=dataset["source_type"],
                    source_url=self._dataset_source_url(dataset),
                    lot_id=str(row.get("id") or ""),
                    lot_display_no=pick_text(row.get("id")) or None,
                    product_name=pick_text(good.get("name")) if isinstance(good, dict) else pick_text(row.get("name")),
                    category_name=pick_text(category.get("title")) if category else pick_text(good.get("category")) if isinstance(good, dict) else None,
                    condition=condition or pick_text(row.get("name")) or None,
                    amount=amount,
                    deal_cost=maybe_float(good.get("totalcost_item")) if isinstance(good, dict) else maybe_float(row.get("totalcost")),
                    unit_price=maybe_float(good.get("price")) if isinstance(good, dict) else None,
                    currency=pick_text(row.get("currency")) or "UZS",
                    region=region,
                    provider_name=None,
                    deal_date=pick_text(row.get("publicated_at")) or None,
                    deal_status_name=pick_text(row.get("status")) or None,
                    payment_status=None,
                    raw_payload=row,
                    raw_text=raw_text,
                    participants_count=maybe_int(row.get("part_count")),
                    customer_name=company_name or None,
                    customer_inn=company_inn,
                    provider_inn=None,
                    start_cost=maybe_float(row.get("totalcost")),
                    contract_file_name=None,
                    contract_file_path=None,
                    additional_protocol_file_name=None,
                    additional_protocol_file_path=None,
                    procedure_type=dataset["source_name"].split("/")[-1],
                    contract_number=pick_text(row.get("contract_number")) or None,
                    begin_date=pick_text(row.get("publicated_at")) or None,
                    end_date=pick_text(row.get("close_at")) or None,
                    address=address,
                    district=district,
                    country=None,
                    measure=pick_text(good.get("unit")) if isinstance(good, dict) else None,
                    manufacturer_country=None,
                    status_code=pick_text(row.get("status")) or None,
                    time_left_second=maybe_int(row.get("remain_time")),
                    product_code=pick_text(good.get("id")) if isinstance(good, dict) else None,
                )
            )
        return evidences

    def _build_offer_request_evidence(self, dataset: dict[str, Any], row: dict[str, Any]) -> Evidence:
        company = row.get("company") if isinstance(row.get("company"), dict) else {}
        condition = build_parameter_text(
            [
                ("Pozitsiyalar soni", row.get("position_count")),
                ("Jami narx", row.get("total_price")),
                ("Takliflar soni", row.get("bids_count")),
                ("Moliyalashtirish manbasi", row.get("financial_source")),
            ]
        )
        raw_text = build_raw_text(
            [
                ("Manba", dataset["source_name"]),
                ("Lot", row.get("lot")),
                ("Sarlavha", row.get("title")),
                ("Buyurtmachi", company.get("title")),
                ("Buyurtmachi STIR", company.get("tin")),
                ("Hudud", row.get("region")),
                ("Tuman", row.get("district")),
                ("Manzil", row.get("address")),
                ("Xususiyatlar", condition),
                ("Boshlanish", row.get("begin_date")),
                ("Tugash", row.get("end_date")),
                ("Jami narx", row.get("total_price")),
            ]
        )
        return Evidence(
            source_name=dataset["source_name"],
            source_type=dataset["source_type"],
            source_url=self._dataset_source_url(dataset),
            lot_id=str(row.get("id") or ""),
            lot_display_no=pick_text(row.get("lot")) or None,
            product_name=pick_text(row.get("title")) or None,
            category_name=None,
            condition=condition or None,
            amount=maybe_float(row.get("position_count")),
            deal_cost=maybe_float(row.get("total_price")),
            unit_price=None,
            currency="UZS",
            region=pick_region_name(row.get("region")),
            provider_name=None,
            deal_date=pick_text(row.get("begin_date")) or None,
            deal_status_name=None,
            payment_status=None,
            raw_payload=row,
            raw_text=raw_text,
            participants_count=maybe_int(row.get("bids_count")),
            customer_name=pick_text(company.get("title")) or None,
            customer_inn=pick_text(company.get("tin")) or None,
            provider_inn=None,
            start_cost=maybe_float(row.get("total_price")),
            contract_file_name=None,
            contract_file_path=None,
            additional_protocol_file_name=None,
            additional_protocol_file_path=None,
            procedure_type="offer-request",
            contract_number=None,
            begin_date=pick_text(row.get("begin_date")) or None,
            end_date=pick_text(row.get("end_date")) or None,
            address=pick_text(row.get("address")) or None,
            district=pick_region_name(row.get("district")),
            country=None,
            measure=None,
            manufacturer_country=None,
            status_code=None,
            time_left_second=None,
        )

    def _build_contract_evidence(self, dataset: dict[str, Any], row: dict[str, Any]) -> Evidence:
        order = row.get("order") if isinstance(row.get("order"), dict) else {}
        offer_request = row.get("offer_request") if isinstance(row.get("offer_request"), dict) else {}
        customer = row.get("customer") if isinstance(row.get("customer"), dict) else {}
        producer = row.get("producer") if isinstance(row.get("producer"), dict) else {}
        product_name = (
            pick_text(order.get("title"))
            or pick_text(offer_request.get("title"))
            or pick_text(order.get("lot_number"))
            or pick_text(row.get("number"))
        )
        condition = build_parameter_text(
            [
                ("Lot", order.get("lot_number") or offer_request.get("lot")),
                ("Pozitsiyalar soni", row.get("position_count")),
                ("Shartnoma summasi", row.get("price")),
                ("Holat", row.get("status")),
            ]
        )
        raw_text = build_raw_text(
            [
                ("Manba", dataset["source_name"]),
                ("Shartnoma", row.get("number")),
                ("Lot", row.get("order")),
                ("Xususiyatlar", condition),
                ("Buyurtmachi", row.get("customer")),
                ("Yetkazib beruvchi", row.get("producer")),
                ("Narx", row.get("price")),
                ("Sana", row.get("created_at")),
                ("Holat", row.get("status")),
            ]
        )
        return Evidence(
            source_name=dataset["source_name"],
            source_type=dataset["source_type"],
            source_url=self._dataset_source_url(dataset),
            lot_id=str(row.get("id") or row.get("number") or ""),
            lot_display_no=pick_text(order.get("lot_number")) or pick_text(row.get("number")) or None,
            product_name=product_name or None,
            category_name=None,
            condition=condition or None,
            amount=maybe_float(row.get("position_count")),
            deal_cost=maybe_float(row.get("price")),
            unit_price=None,
            currency=pick_text(row.get("currency")) or "UZS",
            region=None,
            provider_name=pick_text(producer.get("title")) or None,
            deal_date=pick_text(row.get("created_at")) or None,
            deal_status_name=pick_text(row.get("status")) or None,
            payment_status=None,
            raw_payload=row,
            raw_text=raw_text,
            participants_count=None,
            customer_name=pick_text(customer.get("title")) or None,
            customer_inn=None,
            provider_inn=None,
            start_cost=None,
            contract_file_name=None,
            contract_file_path=None,
            additional_protocol_file_name=None,
            additional_protocol_file_path=None,
            procedure_type=dataset["source_name"].split("/")[-1],
            contract_number=pick_text(row.get("number")) or None,
            begin_date=None,
            end_date=None,
            address=None,
            district=None,
            country=None,
            measure=None,
            manufacturer_country=None,
            status_code=pick_text(row.get("status")) or None,
            time_left_second=None,
        )

    def _build_contract_tender_evidences(
        self,
        dataset: dict[str, Any],
        row: dict[str, Any],
        detail: dict[str, Any],
    ) -> list[Evidence]:
        result = detail.get("result") if isinstance(detail.get("result"), dict) else {}
        tender = result.get("tender") if isinstance(result.get("tender"), dict) else {}
        classifiers = tender.get("tender_classifiers") if isinstance(tender.get("tender_classifiers"), list) else []
        if not classifiers:
            return [self._build_contract_evidence(dataset, row)]

        customer = row.get("customer") if isinstance(row.get("customer"), dict) else {}
        producer = row.get("producer") if isinstance(row.get("producer"), dict) else {}
        evidences: list[Evidence] = []
        for item in classifiers:
            if not isinstance(item, dict):
                continue
            classifier = item.get("classifier") if isinstance(item.get("classifier"), dict) else {}
            properties = item.get("classifier_properties")
            properties_text = build_properties_text(properties)
            measure = find_property_value(properties, ["o'lchov", "unit", "единиц"])
            manufacturer_country = pick_text(item.get("country_of_origin")) or None
            condition = build_parameter_text(
                [
                    ("Tavsif", item.get("description")),
                    ("Xususiyatlar", properties_text),
                    ("Mahsulot kodi", classifier.get("code")),
                    ("O'lchov", measure),
                    ("Miqdor", item.get("number_purchased")),
                    ("Birlik narx", item.get("unit_price")),
                    ("Taklif narxi", item.get("offer_price")),
                    ("Jami", item.get("total_offer_price") or item.get("total_price")),
                    ("Ishlab chiqaruvchi mamlakat", manufacturer_country),
                ]
            )
            raw_text = build_raw_text(
                [
                    ("Manba", dataset["source_name"]),
                    ("Shartnoma", row.get("number")),
                    ("Lot", row.get("lot")),
                    ("Mahsulot", classifier),
                    ("Kod", classifier.get("code")),
                    ("Xususiyatlar", condition),
                    ("Buyurtmachi", customer.get("title")),
                    ("Yetkazib beruvchi", producer.get("title")),
                    ("Sana", row.get("created_at")),
                    ("Holat", row.get("status")),
                ]
            )
            evidences.append(
                Evidence(
                    source_name=dataset["source_name"],
                    source_type=dataset["source_type"],
                    source_url=self._dataset_source_url(dataset),
                    lot_id=str(row.get("id") or row.get("number") or ""),
                    lot_display_no=pick_text(row.get("lot")) or pick_text(row.get("number")) or None,
                    product_name=pick_text(classifier) or pick_text(row.get("number")) or None,
                    category_name=None,
                    condition=condition or None,
                    amount=maybe_float(item.get("number_purchased")),
                    deal_cost=maybe_float(item.get("total_offer_price")) or maybe_float(item.get("total_price")) or maybe_float(row.get("price")),
                    unit_price=maybe_float(item.get("offer_price")) or maybe_float(item.get("unit_price")),
                    currency=pick_text(row.get("currency")) or "UZS",
                    region=None,
                    provider_name=pick_text(producer.get("title")) or None,
                    deal_date=pick_text(row.get("created_at")) or None,
                    deal_status_name=pick_text(row.get("status")) or None,
                    payment_status=None,
                    raw_payload={"row": row, "detail": item},
                    raw_text=raw_text,
                    participants_count=None,
                    customer_name=pick_text(customer.get("title")) or None,
                    customer_inn=None,
                    provider_inn=None,
                    start_cost=maybe_float(item.get("total_price")),
                    contract_file_name=None,
                    contract_file_path=None,
                    additional_protocol_file_name=None,
                    additional_protocol_file_path=None,
                    procedure_type=dataset["source_name"].split("/")[-1],
                    contract_number=pick_text(row.get("number")) or None,
                    begin_date=None,
                    end_date=None,
                    address=None,
                    district=None,
                    country=None,
                    measure=measure or None,
                    manufacturer_country=manufacturer_country,
                    status_code=pick_text(row.get("status")) or None,
                    time_left_second=None,
                    product_code=self._classifier_code(classifier),
                    category_id=self._classifier_category_id(classifier),
                )
            )
        return evidences or [self._build_contract_evidence(dataset, row)]

    async def fetch_dataset_page(
        self,
        client: httpx.AsyncClient,
        dataset: dict[str, Any],
        *,
        page_index: int,
        page_size: int,
    ) -> tuple[list[Evidence], bool]:
        kind = dataset["kind"]
        if kind == "shop":
            payload = await self._get(
                client,
                "shop/product/announce-list",
                params={"currentPage": page_index, "perPage": page_size, "platform_display": dataset["platform_display"]},
            )
            rows = (((payload.get("result") or {}).get("data")) if isinstance(payload.get("result"), dict) else []) or []
            meta = ((payload.get("result") or {}).get("meta")) if isinstance(payload.get("result"), dict) else {}
            evidences = [self._build_shop_evidence(dataset, row) for row in rows if isinstance(row, dict)]
            page_count = maybe_int(meta.get("pageCount")) if isinstance(meta, dict) else None
            has_more = page_count is not None and page_index + 1 < page_count or len(rows) >= page_size
            return evidences, bool(has_more)

        if kind == "auction":
            payload = await self._get(
                client,
                "auction/auction/active",
                params={"currentPage": page_index, "perPage": page_size, "auction_type": dataset["auction_type"]},
            )
            rows = (((payload.get("result") or {}).get("data")) if isinstance(payload.get("result"), dict) else []) or []
            meta = ((payload.get("result") or {}).get("meta")) if isinstance(payload.get("result"), dict) else {}
            evidences = [self._build_auction_evidence(dataset, row) for row in rows if isinstance(row, dict)]
            page_count = maybe_int(meta.get("pageCount")) if isinstance(meta, dict) else None
            has_more = page_count is not None and page_index + 1 < page_count or len(rows) >= page_size
            return evidences, bool(has_more)

        if kind == "tender":
            all_rows: list[dict[str, Any]] = []
            has_more = False
            for state in dataset["states"]:
                payload = await self._get(
                    client,
                    "tender-v2/producer/active-lots",
                    params={"currentPage": page_index, "perPage": page_size, "type": dataset["type"], "state": state},
                )
                rows = (((payload.get("result") or {}).get("data")) if isinstance(payload.get("result"), dict) else []) or []
                meta = ((payload.get("result") or {}).get("meta")) if isinstance(payload.get("result"), dict) else {}
                all_rows.extend(row for row in rows if isinstance(row, dict))
                page_count = maybe_int(meta.get("pageCount")) if isinstance(meta, dict) else None
                has_more = has_more or bool(page_count is not None and page_index + 1 < page_count or len(rows) >= page_size)
            evidences: list[Evidence] = []
            for row in all_rows:
                evidences.extend(self._build_tender_evidences(dataset, row))
            return evidences, has_more

        if kind == "offer-request":
            payload = await self._get(
                client,
                "offer-request/offer-request/announce-list",
                params={"currentPage": page_index, "perPage": page_size},
            )
            rows = (((payload.get("result") or {}).get("data")) if isinstance(payload.get("result"), dict) else []) or []
            meta = ((payload.get("result") or {}).get("meta")) if isinstance(payload.get("result"), dict) else {}
            evidences = [self._build_offer_request_evidence(dataset, row) for row in rows if isinstance(row, dict)]
            page_count = maybe_int(meta.get("pageCount")) if isinstance(meta, dict) else None
            has_more = page_count is not None and page_index + 1 < page_count or len(rows) >= page_size
            return evidences, bool(has_more)

        if kind == "contract-shop":
            payload = await self._get(
                client,
                "common/contract/external-shop",
                params={"type": dataset["contract_type"], "currentPage": page_index, "perPage": page_size},
            )
        elif kind == "contract-auction":
            payload = await self._get(
                client,
                "common/contract/external-auction",
                params={"auction_type": dataset["auction_type"], "currentPage": page_index, "perPage": page_size, "expand": "classifiers,moderating,history"},
            )
        elif kind == "contract-tender":
            payload = await self._get(
                client,
                "common/contract/external-tender",
                params={"type": dataset["type"], "currentPage": page_index, "perPage": page_size},
            )
        else:
            payload = await self._get(
                client,
                "common/contract/external-offer-request",
                params={"currentPage": page_index, "perPage": page_size, "expand": "classifiers,moderating,history"},
            )

        rows = (((payload.get("result") or {}).get("data")) if isinstance(payload.get("result"), dict) else []) or []
        meta = ((payload.get("result") or {}).get("meta")) if isinstance(payload.get("result"), dict) else {}
        evidences: list[Evidence] = []
        if kind == "contract-tender":
            for row in rows:
                if not isinstance(row, dict):
                    continue
                row_id = maybe_int(row.get("id"))
                if row_id is None:
                    evidences.append(self._build_contract_evidence(dataset, row))
                    continue
                detail = await self._get_contract_tender_view(client, row_id)
                evidences.extend(self._build_contract_tender_evidences(dataset, row, detail))
        else:
            evidences = [self._build_contract_evidence(dataset, row) for row in rows if isinstance(row, dict)]
        page_count = maybe_int(meta.get("pageCount")) if isinstance(meta, dict) else None
        has_more = page_count is not None and page_index + 1 < page_count or len(rows) >= page_size
        return evidences, bool(has_more)
