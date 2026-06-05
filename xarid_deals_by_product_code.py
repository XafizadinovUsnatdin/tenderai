import asyncio
import json
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


async def get_completed_deals_by_product_code(
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

    print("STATUS:", response.status_code)
    print("PAYLOAD:", json.dumps(payload, ensure_ascii=False))

    if response.status_code != 200:
        print("ERROR:", response.text[:1000])
        return []

    return response.json()


async def main():
    # BU JOYLARNI product_matches.json dan topilgan qiymatlar bilan almashtirasiz
    category_id = 119460
    product_code = "PUT_PRODUCT_CODE_HERE"

    async with httpx.AsyncClient(follow_redirects=True) as client:
        deals = await get_completed_deals_by_product_code(
            client=client,
            category_id=category_id,
            product_code=product_code,
            year_id=2026,
            from_row=1,
            to_row=20,
        )

        print("Deals count:", len(deals))

        if deals:
            print(json.dumps(deals[0], ensure_ascii=False, indent=2))

        with open("deals_by_product_code.json", "w", encoding="utf-8") as f:
            json.dump(deals, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    asyncio.run(main())