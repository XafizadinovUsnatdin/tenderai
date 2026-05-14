import asyncio
import json
from typing import Any

import httpx


BASE_API = "https://xarid-api-shop.uzex.uz"
TRADE_API = "https://xarid-api-trade.uzex.uz"


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


async def get_regions(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    response = await client.get(
        f"{TRADE_API}/Lib/GetRegions",
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


async def get_categories(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    response = await client.get(
        f"{TRADE_API}/Lib/GetCategories",
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


async def get_completed_deals(
    client: httpx.AsyncClient,
    keyword: str | None = None,
    year_id: int = 2026,
    from_row: int = 1,
    to_row: int = 12,
) -> list[dict[str, Any]]:
    url = f"{BASE_API}/Common/GetCompletedDeals"

    payload: dict[str, Any] = {
        "region_ids": [],
        "display_on_shop": 1,
        "display_on_national": 0,
        "year_id": year_id,
        "from": from_row,
        "to": to_row,
    }

    if keyword:
        payload["keyword"] = keyword

    response = await client.post(
        url,
        headers=HEADERS,
        json=payload,
        timeout=60,
    )

    print("STATUS:", response.status_code)
    print("PAYLOAD:", json.dumps(payload, ensure_ascii=False))

    if response.status_code >= 400:
        print("ERROR BODY:", response.text[:1000])
        response.raise_for_status()

    return response.json()


async def main():
    async with httpx.AsyncClient(follow_redirects=True) as client:
        print("\n1) Regions test")
        regions = await get_regions(client)
        print("Regions count:", len(regions))
        print("First region:", regions[0] if regions else None)

        print("\n2) Categories test")
        categories = await get_categories(client)
        print("Categories count:", len(categories))
        print("First category:", categories[0] if categories else None)

        print("\n3) Completed deals default test")
        deals = await get_completed_deals(client)
        print("Deals count:", len(deals))
        print("First deal:")
        print(json.dumps(deals[0], ensure_ascii=False, indent=2) if deals else None)

        print("\n4) Completed deals keyword test")
        deals_keyword = await get_completed_deals(client, keyword="printer")
        print("Keyword deals count:", len(deals_keyword))
        if deals_keyword:
            print(json.dumps(deals_keyword[0], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())