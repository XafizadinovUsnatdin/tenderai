import asyncio
import json
from typing import Any
from urllib.parse import quote

import httpx


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


async def get_categories(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    response = await client.get(
        f"{TRADE_API}/Lib/GetCategories",
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


async def get_products(
    client: httpx.AsyncClient,
    category_id: int,
    keyword: str,
) -> list[dict[str, Any]]:
    encoded_keyword = quote(keyword)

    url = f"{TRADE_API}/Lib/GetProducts/{category_id}?keyword={encoded_keyword}"

    response = await client.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    if response.status_code != 200:
        print(f"Category {category_id} failed:", response.status_code)
        return []

    return response.json()


async def search_products_across_categories(keyword: str):
    async with httpx.AsyncClient(follow_redirects=True) as client:
        categories = await get_categories(client)

        print("Categories count:", len(categories))
        print("Searching product keyword:", keyword)

        all_matches = []

        for category in categories:
            category_id = category["id"]
            category_name = category["name"]

            products = await get_products(
                client=client,
                category_id=category_id,
                keyword=keyword,
            )

            if products:
                print("\nCATEGORY:", category_id, category_name)
                print("FOUND:", len(products))

                for product in products[:5]:
                    print(
                        "-",
                        product.get("name"),
                        "| code:",
                        product.get("product_code"),
                        "| id:",
                        product.get("id"),
                    )

                all_matches.extend(products)

            # Saytga bosim bermaslik uchun ozgina kutamiz
            await asyncio.sleep(0.2)

        print("\nTOTAL MATCHES:", len(all_matches))

        with open("product_matches.json", "w", encoding="utf-8") as f:
            json.dump(all_matches, f, ensure_ascii=False, indent=2)


async def main():
    # Inglizcha "printer" emas, ruscha/portal tilidagi so‘z bilan test qiling
    #await search_products_across_categories("принтер")
    await search_products_across_categories("коммутатор")

if __name__ == "__main__":
    asyncio.run(main())