import asyncio
import json
from typing import Any

import httpx

from app.schemas import ProductCandidate, Evidence


class XaridUzexConnector:
    source_name = "xarid.uzex.uz"
    source_type = "government_completed_deals_shop"

    VIEW_SHOP = "shop"
    VIEW_NATIONAL = "national"
    VIEW_AUCTION = "auction"

    TRADE_API = "https://xarid-api-trade.uzex.uz"
    SHOP_API = "https://xarid-api-shop.uzex.uz"
    AUCTION_API = "https://xarid-api-auction.uzex.uz"

    HEADERS = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://xarid.uzex.uz",
        "Referer": "https://xarid.uzex.uz/completed-deals/shop/shop",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120 Safari/537.36"
        ),
    }

    SUCCESS_DEAL_STATUSES = {"Оплачена", "Поставлена"}
    SUCCESS_PAYMENT_STATUSES = {"Оплачен"}

    def __init__(self, view: str = VIEW_SHOP):
        if view not in {self.VIEW_SHOP, self.VIEW_NATIONAL, self.VIEW_AUCTION}:
            raise ValueError(f"Unsupported view: {view}")

        self.view = view

        if view == self.VIEW_SHOP:
            self.source_name = "xarid.uzex.uz"
            self.source_type = "government_completed_deals_shop"
            self._display_on_shop = 1
            self._display_on_national = 0
            self._referer_path = "/completed-deals/shop/shop"
            self._deals_api_base = self.SHOP_API
        elif view == self.VIEW_NATIONAL:
            self.source_name = "xarid.uzex.uz/national"
            self.source_type = "government_completed_deals_national"
            self._display_on_shop = 0
            self._display_on_national = 1
            self._referer_path = "/completed-deals/shop/national"
            self._deals_api_base = self.SHOP_API
        else:
            self.source_name = "xarid.uzex.uz/auction"
            self.source_type = "government_completed_deals_auction"
            self._display_on_shop = 0
            self._display_on_national = 0
            self._referer_path = "/completed-deals/auction"
            self._deals_api_base = self.AUCTION_API

        self.headers = dict(self.HEADERS)
        self.headers["Referer"] = f"https://xarid.uzex.uz{self._referer_path}"

    def _safe_json_list(self, response: httpx.Response, *, context: str) -> list[dict[str, Any]]:
        try:
            data = response.json()
        except Exception:
            print(f"{context} invalid JSON:", response.status_code, response.text[:300])
            return []

        return data if isinstance(data, list) else []

    async def get_categories(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        response = await client.get(
            f"{self.TRADE_API}/Lib/GetCategories",
            headers=self.headers,
            timeout=30,
        )
        response.raise_for_status()
        return self._safe_json_list(response, context="GetCategories")

    async def get_products(
        self,
        client: httpx.AsyncClient,
        category_id: int,
        keyword: str,
    ) -> list[dict[str, Any]]:
        url = f"{self.TRADE_API}/Lib/GetProducts/{category_id}"

        response = await client.get(
            url,
            headers=self.headers,
            params={"keyword": keyword},
            timeout=30,
        )

        if response.status_code != 200:
            return []

        return self._safe_json_list(response, context="GetProducts")

    async def find_product_candidates(
        self,
        keywords: list[str],
        max_candidates: int = 10,
    ) -> list[ProductCandidate]:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            categories = await self.get_categories(client)

            candidates: list[ProductCandidate] = []

            for keyword in keywords:
                for category in categories:
                    products = await self.get_products(
                        client=client,
                        category_id=category["id"],
                        keyword=keyword,
                    )

                    for product in products:
                        candidate = ProductCandidate(
                            id=product["id"],
                            product_code=product["product_code"],
                            name=product["name"],
                            category_id=product["category_id"],
                            category_name=product["category_name"],
                            score=self._score_product_candidate(
                                keyword=keyword,
                                product=product,
                            ),
                        )
                        candidates.append(candidate)

                    await asyncio.sleep(0.05)

            # duplicate product_code larni olib tashlaymiz
            unique: dict[str, ProductCandidate] = {}

            for candidate in candidates:
                if candidate.product_code not in unique:
                    unique[candidate.product_code] = candidate
                else:
                    if candidate.score > unique[candidate.product_code].score:
                        unique[candidate.product_code] = candidate

            sorted_candidates = sorted(
                unique.values(),
                key=lambda x: x.score,
                reverse=True,
            )

            return sorted_candidates[:max_candidates]

    def _score_product_candidate(
        self,
        keyword: str,
        product: dict[str, Any],
    ) -> float:
        """
        Universal candidate scoring.
        Product nomi keywordga qanchalik yaqinligini baholaydi.
        """
        keyword_lower = keyword.lower()
        name = (product.get("name") or "").lower()
        category_name = (product.get("category_name") or "").lower()

        score = 0.0

        if keyword_lower == name:
            score += 1.0

        if keyword_lower in name:
            score += 0.7

        if name in keyword_lower:
            score += 0.5

        if keyword_lower in category_name:
            score += 0.2

        # Noto‘g‘ri avtomobil "komмутатор зажигания" kabi narsalarni kamaytirish
        bad_words = ["автомоб", "зажигания", "прицеп"]
        if any(word in name or word in category_name for word in bad_words):
            score -= 0.5

        return round(max(score, 0.0), 2)

    async def get_completed_deals(
        self,
        client: httpx.AsyncClient,
        candidate: ProductCandidate,
        year_id: int,
        from_row: int,
        to_row: int,
    ) -> list[dict[str, Any]]:
        payload = {
            "region_ids": [],
            "year_id": year_id,
            "from": from_row,
            "to": to_row,
            "category_id": candidate.category_id,
            "product_code": candidate.product_code,
        }

        if self.view != self.VIEW_AUCTION:
            payload["display_on_shop"] = self._display_on_shop
            payload["display_on_national"] = self._display_on_national

        response = await client.post(
            f"{self._deals_api_base}/Common/GetCompletedDeals",
            headers=self.headers,
            json=payload,
            timeout=60,
        )

        if response.status_code != 200:
            print("GetCompletedDeals failed:", response.status_code, response.text[:300])
            return []

        return self._safe_json_list(response, context="GetCompletedDeals")

    async def collect_evidences_for_candidate(
        self,
        candidate: ProductCandidate,
        year_id: int = 2026,
        page_size: int = 20,
        max_pages: int = 3,
    ) -> list[Evidence]:
        all_deals: list[dict[str, Any]] = []

        async with httpx.AsyncClient(follow_redirects=True) as client:
            for page in range(max_pages):
                from_row = page * page_size + 1
                to_row = (page + 1) * page_size

                deals = await self.get_completed_deals(
                    client=client,
                    candidate=candidate,
                    year_id=year_id,
                    from_row=from_row,
                    to_row=to_row,
                )

                if not deals:
                    break

                all_deals.extend(deals)
                await asyncio.sleep(0.2)

        successful_deals = [
            deal for deal in all_deals
            if self._is_successful_deal(deal)
        ]

        evidences = [
            self._build_evidence(deal)
            for deal in successful_deals
        ]

        return evidences

    def _is_successful_deal(self, deal: dict[str, Any]) -> bool:
        return (
            deal.get("deal_status_name") in self.SUCCESS_DEAL_STATUSES
            or deal.get("kazna_payment_status") in self.SUCCESS_PAYMENT_STATUSES
        )

    def _get_unit_price(self, deal: dict[str, Any]) -> float | None:
        deal_cost = deal.get("deal_cost")
        amount = deal.get("amount")

        if not isinstance(deal_cost, (int, float)):
            return None

        if not isinstance(amount, (int, float)) or amount <= 0:
            return None

        return float(deal_cost) / float(amount)

    def _build_source_url(self, deal: dict[str, Any]) -> str:
        lot_id = deal.get("lot_id")
        if self.view == self.VIEW_NATIONAL:
            base_url = "https://xarid.uzex.uz/completed-deals/shop/national"
        elif self.view == self.VIEW_AUCTION:
            base_url = "https://xarid.uzex.uz/completed-deals/auction"
        else:
            base_url = "https://xarid.uzex.uz/completed-deals/shop/shop"

        if lot_id:
            return f"{base_url}?lot_id={lot_id}"

        return base_url

    def _build_evidence(self, deal: dict[str, Any]) -> Evidence:
        unit_price = self._get_unit_price(deal)

        region = deal.get("customer_region_name") or deal.get("customer_region")

        pcp_count = deal.get("pcp_count")
        participants_count = int(pcp_count) if isinstance(pcp_count, (int, float)) else None

        product_name = deal.get("product_name") or deal.get("category_name")

        raw_text = f"""
Manba: {self.source_name}
Lot raqami: {deal.get("lot_display_no")}
Mahsulot: {product_name}
Kategoriya: {deal.get("category_name")}
Texnik tavsif:
{deal.get("condition")}

Miqdor: {deal.get("amount")}
Boshlang‘ich narx: {deal.get("start_cost")}
Umumiy bitim summasi: {deal.get("deal_cost")}
Bitta dona narxi: {unit_price}
Ishtirokchilar soni: {participants_count}
Hudud: {region}
Yetkazib beruvchi: {deal.get("provider_name")}
Bitim sanasi: {deal.get("deal_date")}
Bitim holati: {deal.get("deal_status_name")}
To‘lov holati: {deal.get("kazna_payment_status")}
""".strip()

        return Evidence(
            source_name=self.source_name,
            source_type=self.source_type,
            source_url=self._build_source_url(deal),
            lot_id=deal.get("lot_id"),
            lot_display_no=deal.get("lot_display_no"),
            product_name=product_name,
            category_name=deal.get("category_name"),
            condition=deal.get("condition"),
            amount=deal.get("amount"),
            deal_cost=deal.get("deal_cost"),
            unit_price=unit_price,
            currency="UZS",
            region=region,
            provider_name=deal.get("provider_name"),
            deal_date=deal.get("deal_date"),
            deal_status_name=deal.get("deal_status_name"),
            payment_status=deal.get("kazna_payment_status"),
            raw_payload=deal,
            raw_text=raw_text,
            customer_name=deal.get("customer_name"),
            customer_inn=deal.get("customer_inn"),
            provider_inn=deal.get("provider_inn"),
            participants_count=participants_count,
            start_cost=deal.get("start_cost"),
        )
