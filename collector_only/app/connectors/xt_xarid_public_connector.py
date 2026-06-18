from __future__ import annotations

from typing import Any

import httpx

from app.connectors.common import (
    area_path_to_text,
    build_parameter_text,
    build_properties_text,
    build_raw_text,
    maybe_float,
    maybe_int,
    pick_text,
)
from app.schemas import Evidence


class XtXaridPublicConnector:
    RPC_URL = "https://api.xt-xarid.uz/rpc"
    SITE_URL = "https://xt-xarid.uz/"
    TENDER_URL = "https://xt-xarid.uz/procedure/tender"
    SELECTION_URL = "https://xt-xarid.uz/procedure/selection"
    REDUCTION_URL = "https://xt-xarid.uz/procedure/reduction"
    LOCAL_REDUCTION_URL = "https://xt-xarid.uz/procedure/local_reduction"
    AD_URL = "https://xt-xarid.uz/procedure/ad"
    NAD_URL = "https://xt-xarid.uz/procedure/nad"
    MASTER_AGREEMENT_URL = "https://xt-xarid.uz/procedure/master_agreement"
    REQUEST_PROPOSALS_URL = "https://xt-xarid.uz/procedure/request_proposals"
    HEADERS = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://xt-xarid.uz",
        "Referer": "https://xt-xarid.uz/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120 Safari/537.36"
        ),
    }

    DATASETS = [
        {
            "key": "tender",
            "source_name": "xt-xarid.uz/tender",
            "source_type": "xt_public_tender",
            "source_url": TENDER_URL,
            "method": "ref",
            "params": {
                "ref": "ref_tender_public",
                "op": "read",
                "filters": {},
                "fields": [
                    "green",
                    "id",
                    "publicated_at",
                    "status",
                    "name",
                    "good_count",
                    "close_at",
                    "totalcost",
                    "currency",
                    "lang",
                    "part_count",
                    "meta",
                    "remain_time",
                    "lot_count",
                    "docs_objections_remain_time",
                    "close_docs_objections_at",
                ],
            },
        },
        {
            "key": "selection",
            "source_name": "xt-xarid.uz/selection",
            "source_type": "xt_public_selection",
            "source_url": SELECTION_URL,
            "method": "ref",
            "params": {
                "ref": "ref_selection_public",
                "op": "read",
                "filters": {},
                "fields": [
                    "green",
                    "id",
                    "publicated_at",
                    "status",
                    "name",
                    "good_count",
                    "close_at",
                    "totalcost",
                    "currency",
                    "lang",
                    "part_count",
                    "meta",
                    "remain_time",
                    "lot_count",
                    "docs_objections_remain_time",
                    "close_docs_objections_at",
                ],
            },
        },
        {
            "key": "reduction",
            "source_name": "xt-xarid.uz/reduction",
            "source_type": "xt_public_reduction",
            "source_url": REDUCTION_URL,
            "method": "ref",
            "params": {
                "ref": "ref_reduction_object_public",
                "op": "read",
                "filters": {"local_reduction": False},
                "fields": [
                    "green",
                    "id",
                    "contract_pay_percent",
                    "publicated_at",
                    "status",
                    "name",
                    "good_count",
                    "close_at",
                    "totalcost",
                    "currency",
                    "lang",
                    "part_count",
                    "meta",
                    "start_price",
                    "last_price",
                    "remain_time",
                ],
            },
        },
        {
            "key": "local-reduction",
            "source_name": "xt-xarid.uz/local-reduction",
            "source_type": "xt_public_local_reduction",
            "source_url": LOCAL_REDUCTION_URL,
            "method": "ref",
            "params": {
                "ref": "ref_reduction_object_public",
                "op": "read",
                "filters": {"local_reduction": True},
                "fields": [
                    "green",
                    "id",
                    "contract_pay_percent",
                    "publicated_at",
                    "status",
                    "name",
                    "good_count",
                    "close_at",
                    "totalcost",
                    "currency",
                    "lang",
                    "part_count",
                    "meta",
                    "start_price",
                    "last_price",
                    "remain_time",
                ],
            },
        },
        {
            "key": "request-proposals",
            "source_name": "xt-xarid.uz/request-proposals",
            "source_type": "xt_public_request_proposals",
            "source_url": REQUEST_PROPOSALS_URL,
            "method": "ref",
            "params": {
                "ref": "ref_request_proposals_public",
                "op": "read",
                "filters": {},
            },
        },
        {
            "key": "ad",
            "source_name": "xt-xarid.uz/ad",
            "source_type": "xt_public_ad",
            "source_url": AD_URL,
            "method": "ref",
            "params": {
                "ref": "ref_online_shop_public",
                "op": "read",
                "filters": {"is_national": False, "is_gos_shop": True},
                "fields": [
                    "green",
                    "product",
                    "unit",
                    "debug_info",
                    "id",
                    "publicated_at",
                    "status",
                    "name",
                    "price",
                    "close_at",
                    "totalcost",
                    "currency",
                    "amount",
                    "min_amount",
                    "images",
                    "owner_legal_area_id",
                    "product_name",
                    "remain_time",
                    "is_self_ad",
                    "cart_proc_keys",
                ],
            },
        },
        {
            "key": "nad",
            "source_name": "xt-xarid.uz/nad",
            "source_type": "xt_public_nad",
            "source_url": NAD_URL,
            "method": "ref",
            "params": {
                "ref": "ref_online_shop_public",
                "op": "read",
                "filters": {"is_national": True, "is_gos_shop": True},
                "fields": [
                    "green",
                    "product",
                    "unit",
                    "debug_info",
                    "id",
                    "publicated_at",
                    "status",
                    "name",
                    "price",
                    "close_at",
                    "totalcost",
                    "currency",
                    "amount",
                    "min_amount",
                    "images",
                    "owner_legal_area_id",
                    "product_name",
                    "remain_time",
                    "is_self_ad",
                    "cart_proc_keys",
                ],
            },
        },
        {
            "key": "master-agreement",
            "source_name": "xt-xarid.uz/master-agreement",
            "source_type": "xt_public_master_agreement",
            "source_url": MASTER_AGREEMENT_URL,
            "method": "ref",
            "params": {
                "ref": "ref_master_agreement_public",
                "op": "read",
                "filters": {},
                "fields": ["green", "id", "publicated_at", "status", "name", "good_count", "close_at", "totalcost", "currency", "lang", "part_count", "meta"],
            },
        },
    ]

    async def _rpc(self, client: httpx.AsyncClient, method: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        response = await client.post(
            self.RPC_URL,
            json={"id": 1, "jsonrpc": "2.0", "method": method, "params": params},
            headers=self.HEADERS,
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        result = payload.get("result") if isinstance(payload, dict) else None
        return result if isinstance(result, list) else []

    @staticmethod
    def _category_title(category: Any) -> str:
        if isinstance(category, dict):
            return pick_text(category.get("title")) or pick_text(category)
        return pick_text(category)

    def _product_condition(self, product: dict[str, Any], row: dict[str, Any]) -> str | None:
        category = product.get("category") if isinstance(product.get("category"), dict) else {}
        properties = build_properties_text(product.get("product_properties"))
        parameters = build_parameter_text(
            [
                ("Mahsulot kodi", product.get("product_id")),
                ("Kategoriya kodi", category.get("code")),
                ("Kategoriya", category.get("title")),
                ("O'lchov", row.get("unit") or product.get("unit")),
                ("Miqdor", row.get("amount")),
                ("Minimal miqdor", row.get("min_amount")),
                ("Birlik narx", row.get("price")),
            ]
        )
        return properties or parameters or None

    def _good_condition(self, good: dict[str, Any] | None) -> str | None:
        if not isinstance(good, dict):
            return None

        category = good.get("category") if isinstance(good.get("category"), dict) else {}
        description = pick_text(good.get("desc"))
        parameters = build_parameter_text(
            [
                ("Mahsulot kodi", good.get("id")),
                ("Kategoriya kodi", category.get("code")),
                ("Kategoriya", category.get("title") if category else good.get("category")),
                ("O'lchov", good.get("unit")),
                ("Miqdor", good.get("amount")),
                ("Birlik narx", good.get("price")),
                ("Jami", good.get("totalcost_item")),
            ]
        )
        return description or parameters or None

    def _build_market_evidences(self, dataset: dict[str, Any], row: dict[str, Any]) -> list[Evidence]:
        if dataset["key"] in {"ad", "nad"}:
            product = row.get("product") if isinstance(row.get("product"), dict) else {}
            category = product.get("category") if isinstance(product.get("category"), dict) else {}
            condition = self._product_condition(product, row)
            raw_text = build_raw_text(
                [
                    ("Manba", dataset["source_name"]),
                    ("ID", row.get("id")),
                    ("Mahsulot", row.get("product_name")),
                    ("Kod", product.get("product_id")),
                    ("Kategoriya", category.get("title")),
                    ("Xususiyatlar", condition),
                    ("Narx", row.get("price")),
                    ("Miqdor", row.get("amount")),
                    ("Yopilish", row.get("close_at")),
                ]
            )
            return [
                Evidence(
                    source_name=dataset["source_name"],
                    source_type=dataset["source_type"],
                    source_url=dataset.get("source_url") or self.SITE_URL,
                    lot_id=str(row.get("id") or ""),
                    lot_display_no=pick_text(row.get("id")) or None,
                    product_name=pick_text(row.get("product_name")) or None,
                    category_name=pick_text(category.get("title")) or None,
                    condition=condition,
                    amount=maybe_float(row.get("amount")),
                    deal_cost=None,
                    unit_price=maybe_float(row.get("price")),
                    currency=pick_text(row.get("currency")) or "UZS",
                    region=None,
                    provider_name=None,
                    deal_date=pick_text(row.get("publicated_at")) or None,
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
                    contract_file_path=None,
                    additional_protocol_file_name=None,
                    additional_protocol_file_path=None,
                    procedure_type=dataset["key"],
                    contract_number=None,
                    begin_date=pick_text(row.get("publicated_at")) or None,
                    end_date=pick_text(row.get("close_at")) or None,
                    address=None,
                    district=None,
                    country=None,
                    measure=pick_text(row.get("unit")) or pick_text(product.get("unit")) or None,
                    manufacturer_country=None,
                    status_code=pick_text(row.get("status")) or None,
                    time_left_seconds=maybe_int(row.get("remain_time")),
                    product_code=pick_text(product.get("product_id")) or None,
                )
            ]

        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        good_maps = meta.get("good_maps") if isinstance(meta.get("good_maps"), list) else []
        region = area_path_to_text(meta.get("area_path")) or None
        company_name = pick_text(meta.get("company_name")) or pick_text(row.get("company_name"))
        company_inn = pick_text(meta.get("company_inn")) or None

        evidences: list[Evidence] = []
        for good in good_maps or [None]:
            category = good.get("category") if isinstance(good, dict) and isinstance(good.get("category"), dict) else {}
            condition = self._good_condition(good if isinstance(good, dict) else None)
            start_cost = maybe_float(row.get("start_price")) or maybe_float(row.get("totalcost"))
            deal_cost = (
                maybe_float(good.get("totalcost_item")) if isinstance(good, dict) else None
            ) or maybe_float(row.get("last_price")) or maybe_float(row.get("totalcost")) or start_cost
            raw_text = build_raw_text(
                [
                    ("Manba", dataset["source_name"]),
                    ("ID", row.get("id")),
                    ("Protsedura", row.get("name")),
                    ("Mahsulot", good.get("name") if isinstance(good, dict) else row.get("name")),
                    ("Kod", good.get("id") if isinstance(good, dict) else None),
                    ("Kategoriya", category.get("title") if category else good.get("category") if isinstance(good, dict) else None),
                    ("Xususiyatlar", condition),
                    ("Miqdor", good.get("amount") if isinstance(good, dict) else None),
                    ("Birlik narx", good.get("price") if isinstance(good, dict) else None),
                    ("Boshlang'ich narx", row.get("start_price")),
                    ("Oxirgi narx", row.get("last_price")),
                    ("Jami", good.get("totalcost_item") if isinstance(good, dict) else row.get("totalcost") or row.get("last_price")),
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
                    source_url=dataset.get("source_url") or self.SITE_URL,
                    lot_id=str(row.get("id") or ""),
                    lot_display_no=pick_text(row.get("id")) or None,
                    product_name=pick_text(good.get("name")) if isinstance(good, dict) else pick_text(row.get("name")),
                    category_name=self._category_title(category) if category else pick_text(good.get("category")) if isinstance(good, dict) else None,
                    condition=condition or pick_text(row.get("name")) or None,
                    amount=maybe_float(good.get("amount")) if isinstance(good, dict) else None,
                    deal_cost=deal_cost,
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
                    start_cost=start_cost,
                    contract_file_name=None,
                    contract_file_path=None,
                    additional_protocol_file_name=None,
                    additional_protocol_file_path=None,
                    procedure_type=dataset["key"],
                    contract_number=pick_text(row.get("contract_number")) or None,
                    begin_date=pick_text(row.get("publicated_at")) or None,
                    end_date=pick_text(row.get("close_at")) or None,
                    address=None,
                    district=None,
                    country=None,
                    measure=pick_text(good.get("unit")) if isinstance(good, dict) else pick_text(row.get("unit")) or None,
                    manufacturer_country=None,
                    status_code=pick_text(row.get("status")) or None,
                    time_left_seconds=maybe_int(row.get("remain_time")),
                    product_code=pick_text(good.get("id")) if isinstance(good, dict) else None,
                )
            )
        return evidences

    async def fetch_dataset_page(
        self,
        client: httpx.AsyncClient,
        dataset: dict[str, Any],
        *,
        page_index: int,
        page_size: int,
    ) -> tuple[list[Evidence], bool]:
        params = dict(dataset["params"])
        params["limit"] = page_size
        params["offset"] = page_index * page_size
        rows = await self._rpc(client, dataset["method"], params)
        evidences: list[Evidence] = []
        for row in rows:
            if isinstance(row, dict):
                evidences.extend(self._build_market_evidences(dataset, row))
        return evidences, len(rows) >= page_size
