import asyncio
import json
import time
from typing import Any

import httpx

from app.connectors.common import build_parameter_text, maybe_int, pick_text
from app.schemas import ProductCandidate, Evidence
from app.services.env_config import env_int


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

    SUCCESS_DEAL_STATUSES = {"Оплачена", "Поставлена", "Поставлена (Восстановлена)"}
    SUCCESS_PAYMENT_STATUSES = {"Оплачен"}

    _categories_cache: list[dict[str, Any]] | None = None
    _categories_cache_expires_at: float = 0.0
    _categories_cache_lock: asyncio.Lock | None = None

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

    @classmethod
    def _get_categories_cache_lock(cls) -> asyncio.Lock:
        if cls._categories_cache_lock is None:
            cls._categories_cache_lock = asyncio.Lock()
        return cls._categories_cache_lock

    @staticmethod
    def _get_categories_cache_ttl_seconds() -> int:
        return env_int("XARID_CATEGORY_CACHE_TTL_SECONDS", 1800)

    @staticmethod
    def _get_page_concurrency() -> int:
        return env_int("XARID_PAGE_CONCURRENCY", 2)

    @staticmethod
    def _get_request_timeout_seconds() -> int:
        return env_int("XARID_REQUEST_TIMEOUT_SECONDS", 60)

    @staticmethod
    def _get_request_retries() -> int:
        return env_int("XARID_REQUEST_RETRIES", 3)

    @staticmethod
    def _get_retry_delay_seconds() -> int:
        return env_int("XARID_REQUEST_RETRY_DELAY_SECONDS", 2)

    async def _request_json_list(
        self,
        client: httpx.AsyncClient,
        *,
        method: str,
        url: str,
        context: str,
        params: dict[str, Any] | None = None,
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
                    headers=self.headers,
                    params=params,
                    json=json_payload,
                    timeout=timeout_value,
                )
                if response.status_code != 200:
                    response_text = response.text[:300]
                    if response.status_code == 500 and self._is_upstream_no_data_response(response_text):
                        print(f"{context} upstream returned no data; treating as empty result.")
                        return []
                    if response.status_code in retryable_status_codes and attempt < retries:
                        print(
                            f"{context} HTTP {response.status_code}, retry {attempt}/{retries}:",
                            response_text,
                        )
                        await asyncio.sleep(retry_delay * attempt)
                        continue
                    print(f"{context} failed:", response.status_code, response_text)
                    return []
                return self._safe_json_list(response, context=context)
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                if attempt >= retries:
                    print(f"{context} failed after {retries} attempts:", str(exc)[:300])
                    return []
                print(f"{context} timeout/network error, retry {attempt}/{retries}:", str(exc)[:300])
                await asyncio.sleep(retry_delay * attempt)

        return []

    @staticmethod
    def _is_upstream_no_data_response(response_text: str | None) -> bool:
        text = (response_text or "").lower()
        return "ora-01403" in text or "no_data_found" in text or "no data found" in text

    async def get_categories(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        now = time.monotonic()
        cached = self.__class__._categories_cache
        if cached and self.__class__._categories_cache_expires_at > now:
            return list(cached)

        lock = self.__class__._get_categories_cache_lock()
        async with lock:
            now = time.monotonic()
            cached = self.__class__._categories_cache
            if cached and self.__class__._categories_cache_expires_at > now:
                return list(cached)

            categories = await self._request_json_list(
                client,
                method="GET",
                url=f"{self.TRADE_API}/Lib/GetCategories",
                context="GetCategories",
                timeout_seconds=30,
            )

            if categories:
                self.__class__._categories_cache = categories
                self.__class__._categories_cache_expires_at = (
                    time.monotonic() + self._get_categories_cache_ttl_seconds()
                )
                return list(categories)

            return list(cached or [])

    async def get_products(
        self,
        client: httpx.AsyncClient,
        category_id: int,
        keyword: str,
    ) -> list[dict[str, Any]]:
        return await self._request_json_list(
            client,
            method="GET",
            url=f"{self.TRADE_API}/Lib/GetProducts/{category_id}",
            context="GetProducts",
            params={"keyword": keyword},
            timeout_seconds=self._get_request_timeout_seconds(),
        )

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

        return await self._request_json_list(
            client,
            method="POST",
            url=f"{self._deals_api_base}/Common/GetCompletedDeals",
            context="GetCompletedDeals",
            json_payload=payload,
            timeout_seconds=60,
        )

    async def collect_evidences_for_candidate(
        self,
        candidate: ProductCandidate,
        year_id: int = 2026,
        page_size: int = 20,
        max_pages: int = 3,
    ) -> list[Evidence]:
        all_deals: list[dict[str, Any]] = []
        page_concurrency = max(1, min(max_pages, self._get_page_concurrency()))
        semaphore = asyncio.Semaphore(page_concurrency)

        async def fetch_page(page: int, client: httpx.AsyncClient) -> tuple[int, list[dict[str, Any]]]:
            from_row = page * page_size + 1
            to_row = (page + 1) * page_size

            async with semaphore:
                deals = await self.get_completed_deals(
                    client=client,
                    candidate=candidate,
                    year_id=year_id,
                    from_row=from_row,
                    to_row=to_row,
                )
                if deals:
                    await asyncio.sleep(0.05)
                return page, deals

        async with httpx.AsyncClient(follow_redirects=True) as client:
            page_results = await asyncio.gather(
                *(fetch_page(page, client) for page in range(max_pages))
            )

        for _, deals in sorted(page_results, key=lambda item: item[0]):
            if not deals:
                break
            all_deals.extend(deals)

        evidences = [
            self._build_evidence(deal)
            for deal in all_deals
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
        condition = pick_text(deal.get("condition")) or build_parameter_text(
            [
                ("Mahsulot kodi", deal.get("product_code")),
                ("Kategoriya", deal.get("category_name")),
                ("O'lchov", deal.get("measure") or deal.get("measure_name")),
                ("Miqdor", deal.get("amount")),
                ("Boshlang'ich narx", deal.get("start_cost")),
                ("Bitim narxi", deal.get("deal_cost")),
            ]
        )

        raw_text = f"""
Manba: {self.source_name}
Lot raqami: {deal.get("lot_display_no")}
Mahsulot: {product_name}
Kategoriya: {deal.get("category_name")}
Texnik tavsif:
{condition}

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
            condition=condition or None,
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
            procedure_type=self.view,
            contract_number=pick_text(deal.get("contract_number")) or None,
            begin_date=pick_text(deal.get("lot_start_date") or deal.get("begin_date")) or None,
            end_date=pick_text(deal.get("lot_end_date") or deal.get("end_date")) or None,
            address=pick_text(deal.get("address")) or None,
            district=pick_text(deal.get("customer_district_name") or deal.get("district_name")) or None,
            country=pick_text(deal.get("country")) or None,
            measure=pick_text(deal.get("measure") or deal.get("measure_name")) or None,
            manufacturer_country=pick_text(deal.get("manufacturer_country")) or None,
            status_code=pick_text(deal.get("deal_status") or deal.get("deal_status_id")) or None,
            product_code=pick_text(deal.get("product_code")) or None,
            category_id=maybe_int(deal.get("category_id")),
        )

    def build_evidence(self, deal: dict[str, Any]) -> Evidence:
        return self._build_evidence(deal)

    def is_successful_deal(self, deal: dict[str, Any]) -> bool:
        return self._is_successful_deal(deal)
