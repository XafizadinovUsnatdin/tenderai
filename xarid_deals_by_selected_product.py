import asyncio
import json
from statistics import median
from typing import Any

import httpx


SHOP_API = "https://xarid-api-shop.uzex.uz"

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


PRODUCTS = {
    "kommutator": {
        "category_id": 119460,
        "product_code": "26.30.11.120-00012",
        "name": "Коммутатор",
    },
    "printer": {
        "category_id": 119460,
        "product_code": "26.20.16.120-00001",
        "name": "Принтер",
    },
}


async def get_completed_deals(
    client: httpx.AsyncClient,
    category_id: int,
    product_code: str,
    year_id: int = 2026,
    from_row: int = 1,
    to_row: int = 20,
) -> list[dict[str, Any]]:
    payload = {
        "region_ids": [],
        "display_on_shop": 1,
        "display_on_national": 0,
        "year_id": year_id,
        "from": from_row,
        "to": to_row,
        "category_id": category_id,
        "product_code": product_code,
    }

    response = await client.post(
        f"{SHOP_API}/Common/GetCompletedDeals",
        headers=HEADERS,
        json=payload,
        timeout=60,
    )

    print("\nSTATUS:", response.status_code)
    print("PAYLOAD:", json.dumps(payload, ensure_ascii=False))

    if response.status_code != 200:
        print("ERROR:", response.text[:1000])
        return []

    return response.json()


async def get_all_pages_for_product(
    product_key: str,
    year_id: int = 2026,
    page_size: int = 20,
    max_pages: int = 5,
) -> list[dict[str, Any]]:
    product = PRODUCTS[product_key]

    all_deals: list[dict[str, Any]] = []

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for page in range(max_pages):
            from_row = page * page_size + 1
            to_row = (page + 1) * page_size

            deals = await get_completed_deals(
                client=client,
                category_id=product["category_id"],
                product_code=product["product_code"],
                year_id=year_id,
                from_row=from_row,
                to_row=to_row,
            )

            if not deals:
                break

            all_deals.extend(deals)

            print(f"Page {page + 1}: {len(deals)} deals")

            # Saytga bosim bermaslik uchun
            await asyncio.sleep(0.5)

    return all_deals


def analyze_prices(deals: list[dict[str, Any]]) -> dict[str, Any]:
    prices = [
        deal.get("deal_cost")
        for deal in deals
        if isinstance(deal.get("deal_cost"), (int, float))
    ]

    if not prices:
        return {
            "count": 0,
            "min_price": None,
            "max_price": None,
            "avg_price": None,
            "median_price": None,
            "suspicious": [],
        }

    avg_price = sum(prices) / len(prices)

    suspicious = []

    for deal in deals:
        price = deal.get("deal_cost")

        if not isinstance(price, (int, float)):
            continue

        if price <= avg_price * 0.7:
            suspicious.append(
                {
                    "lot_id": deal.get("lot_id"),
                    "product_name": deal.get("product_name"),
                    "deal_cost": price,
                    "avg_price": round(avg_price, 2),
                    "reason": "Narx o‘rtacha narxdan 30% yoki undan ko‘proq past",
                }
            )

    return {
        "count": len(prices),
        "min_price": min(prices),
        "max_price": max(prices),
        "avg_price": round(avg_price, 2),
        "median_price": median(prices),
        "suspicious": suspicious,
    }


def print_deal_preview(deals: list[dict[str, Any]], limit: int = 5):
    print("\n--- DEAL PREVIEW ---")

    for deal in deals[:limit]:
        print("\nLOT:", deal.get("lot_display_no"))
        print("Product:", deal.get("product_name"))
        print("Category:", deal.get("category_name"))
        print("Cost:", deal.get("deal_cost"))
        print("Amount:", deal.get("amount"))
        print("Region:", deal.get("customer_region_name"))
        print("Date:", deal.get("deal_date"))
        print("Customer:", deal.get("customer_name"))
        print("Provider:", deal.get("provider_name"))
        print("Condition:", (deal.get("condition") or "")[:300])


async def main():
    # "kommutator" yoki "printer"
    product_key = "printer"

    deals = await get_all_pages_for_product(
        product_key=product_key,
        year_id=2026,
        page_size=20,
        max_pages=3,
    )

    print("\nTOTAL DEALS:", len(deals))

    print_deal_preview(deals)

    price_analysis = analyze_prices(deals)

    print("\n--- PRICE ANALYSIS ---")
    print(json.dumps(price_analysis, ensure_ascii=False, indent=2))

    output_file = f"{product_key}_deals_2026.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(deals, f, ensure_ascii=False, indent=2)

    print(f"\nSaved to {output_file}")


if __name__ == "__main__":
    asyncio.run(main())