import asyncio
import json
import sys

from app.connectors.etender_uzex_connector import EtenderUzexConnector


async def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    connector = EtenderUzexConnector()

    results = await connector.search(
        query="kommutator",
        period_months=24,
        page_size=20,
        max_pages=5,
    )

    print("Evidence count:", len(results))

    for ev in results[:5]:
        print("\n--- EVIDENCE ---")
        print("Source:", ev.source_name)
        print("Lot:", ev.lot_display_no)
        print("URL:", ev.source_url)
        print("Unit price:", ev.unit_price, ev.currency)
        print("Deal cost:", ev.deal_cost, ev.currency)
        print("Date:", ev.deal_date)
        print("Provider:", ev.provider_name)
        print("Status:", ev.deal_status_name)
        print("Text:", ev.raw_text[:500])

    with open("etender_evidences_test.json", "w", encoding="utf-8") as f:
        json.dump(
            [ev.__dict__ for ev in results],
            f,
            ensure_ascii=False,
            indent=2,
        )

    print("\nSaved to etender_evidences_test.json")


if __name__ == "__main__":
    asyncio.run(main())
