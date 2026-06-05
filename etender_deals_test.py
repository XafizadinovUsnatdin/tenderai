import asyncio
import json
from typing import Any

import httpx


API_BASE = "https://apietender.uzex.uz/api"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://etender.uzex.uz",
    "Referer": "https://etender.uzex.uz/deals-list",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120 Safari/537.36"
    ),
}


async def get_deals_list(
    client: httpx.AsyncClient,
    keyword: str | None = None,
    from_row: int = 1,
    to_row: int = 20,
    currency_id: int | None = None,
) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {
        "From": from_row,
        "To": to_row,
        "currencyId": currency_id,
        "System_Id": 0,
    }

    if keyword:
        payload["Keyword"] = keyword

    response = await client.post(
        f"{API_BASE}/common/DealsList",
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


async def main():
    async with httpx.AsyncClient(follow_redirects=True) as client:
        print("\n1) Default deals test")
        deals = await get_deals_list(client)

        print("Deals count:", len(deals))
        if deals:
            print(json.dumps(deals[0], ensure_ascii=False, indent=2))

        print("\n2) Keyword search test: kommutator")
        keyword_deals = await get_deals_list(
            client=client,
            keyword="kommutator",
            from_row=1,
            to_row=20,
        )

        print("Keyword deals count:", len(keyword_deals))
        if keyword_deals:
            print(json.dumps(keyword_deals[0], ensure_ascii=False, indent=2))

        with open("etender_deals_kommutator.json", "w", encoding="utf-8") as f:
            json.dump(keyword_deals, f, ensure_ascii=False, indent=2)

        print("\nSaved to etender_deals_kommutator.json")


if __name__ == "__main__":
    asyncio.run(main())