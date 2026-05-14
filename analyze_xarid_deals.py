import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


INPUT_FILE = Path("printer_deals_2026.json")
OUTPUT_FILE = Path("printer_analysis_result.json")


SUCCESS_DEAL_STATUSES = {
    "Оплачена",
    "Поставлена",
}

SUCCESS_PAYMENT_STATUSES = {
    "Оплачен",
}


def is_successful_deal(deal: dict[str, Any]) -> bool:
    """
    Muvaffaqiyatli yakunlangan bitimlarni ajratadi.
    """
    deal_status = deal.get("deal_status_name")
    payment_status = deal.get("kazna_payment_status")

    return (
        deal_status in SUCCESS_DEAL_STATUSES
        or payment_status in SUCCESS_PAYMENT_STATUSES
    )


def get_unit_price(deal: dict[str, Any]) -> float | None:
    """
    deal_cost umumiy summa bo'lishi mumkin.
    Shuning uchun bitta dona narxini hisoblaymiz:
    unit_price = deal_cost / amount
    """
    deal_cost = deal.get("deal_cost")
    amount = deal.get("amount")

    if not isinstance(deal_cost, (int, float)):
        return None

    if not isinstance(amount, (int, float)) or amount <= 0:
        return deal_cost

    return deal_cost / amount


def build_evidence(deal: dict[str, Any]) -> dict[str, Any]:
    """
    LLM va audit uchun bitta evidence obyekt yaratadi.
    """
    unit_price = get_unit_price(deal)

    raw_text = f"""
Lot raqami: {deal.get("lot_display_no")}
Mahsulot: {deal.get("product_name")}
Kategoriya: {deal.get("category_name")}
Texnik tavsif / condition:
{deal.get("condition")}

Miqdor: {deal.get("amount")}
Umumiy bitim summasi: {deal.get("deal_cost")}
Bitta dona taxminiy narxi: {unit_price}
Buyurtmachi: {deal.get("customer_name")}
Buyurtmachi hududi: {deal.get("customer_region_name")}
Yetkazib beruvchi: {deal.get("provider_name")}
Yetkazib beruvchi hududi: {deal.get("provider_region_name")}
Bitim sanasi: {deal.get("deal_date")}
Bitim holati: {deal.get("deal_status_name")}
To‘lov holati: {deal.get("kazna_payment_status")}
""".strip()

    return {
        "source_name": "xarid.uzex.uz",
        "source_type": "government_completed_deals",
        "lot_id": deal.get("lot_id"),
        "lot_display_no": deal.get("lot_display_no"),
        "product_name": deal.get("product_name"),
        "category_name": deal.get("category_name"),
        "condition": deal.get("condition"),
        "amount": deal.get("amount"),
        "deal_cost": deal.get("deal_cost"),
        "unit_price": unit_price,
        "currency": "UZS",
        "customer_region_name": deal.get("customer_region_name"),
        "provider_name": deal.get("provider_name"),
        "deal_date": deal.get("deal_date"),
        "deal_status_name": deal.get("deal_status_name"),
        "kazna_payment_status": deal.get("kazna_payment_status"),
        "raw_text": raw_text,
    }


def analyze_prices(evidences: list[dict[str, Any]]) -> dict[str, Any]:
    prices = [
        ev["unit_price"]
        for ev in evidences
        if isinstance(ev.get("unit_price"), (int, float))
    ]

    if not prices:
        return {
            "count": 0,
            "min_price": None,
            "max_price": None,
            "avg_price": None,
            "median_price": None,
            "recommended_min_price": None,
            "recommended_max_price": None,
            "suspicious_prices": [],
        }

    avg_price = sum(prices) / len(prices)
    median_price = statistics.median(prices)

    suspicious_prices = []

    for ev in evidences:
        price = ev.get("unit_price")

        if not isinstance(price, (int, float)):
            continue

        if price <= avg_price * 0.7:
            suspicious_prices.append(
                {
                    "lot_display_no": ev.get("lot_display_no"),
                    "product_name": ev.get("product_name"),
                    "unit_price": round(price, 2),
                    "avg_price": round(avg_price, 2),
                    "reason": "Bitta dona narxi o‘rtacha narxdan 30% yoki undan ko‘proq past",
                }
            )

    return {
        "count": len(prices),
        "min_price": round(min(prices), 2),
        "max_price": round(max(prices), 2),
        "avg_price": round(avg_price, 2),
        "median_price": round(median_price, 2),
        "recommended_min_price": round(median_price * 0.9, 2),
        "recommended_max_price": round(median_price * 1.1, 2),
        "suspicious_prices": suspicious_prices,
    }


def group_by_region(evidences: list[dict[str, Any]]) -> dict[str, Any]:
    grouped = defaultdict(list)

    for ev in evidences:
        region = ev.get("customer_region_name") or "Noma’lum"
        price = ev.get("unit_price")

        if isinstance(price, (int, float)):
            grouped[region].append(price)

    result = {}

    for region, prices in grouped.items():
        result[region] = {
            "count": len(prices),
            "min_price": round(min(prices), 2),
            "max_price": round(max(prices), 2),
            "avg_price": round(sum(prices) / len(prices), 2),
            "median_price": round(statistics.median(prices), 2),
        }

    return result


def get_common_terms(evidences: list[dict[str, Any]], limit: int = 30) -> list[tuple[str, int]]:
    """
    Juda sodda keyword counter.
    Keyin buni LLM bilan yaxshilaymiz.
    """
    stop_words = {
        "для", "тип", "есть", "нет", "the", "and", "или", "мм", "dpi",
        "принтер", "печати", "печать", "сканер", "копир", "мфу",
        "формат", "максимальный", "максимальная",
    }

    counter = Counter()

    for ev in evidences:
        text = (ev.get("condition") or "").lower()
        words = (
            text.replace("\n", " ")
            .replace(",", " ")
            .replace(".", " ")
            .replace(":", " ")
            .replace(";", " ")
            .split()
        )

        for word in words:
            clean = word.strip("()[]{}«»\"'").lower()

            if len(clean) < 3:
                continue

            if clean in stop_words:
                continue

            counter[clean] += 1

    return counter.most_common(limit)


def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Fayl topilmadi: {INPUT_FILE}")

    deals = json.loads(INPUT_FILE.read_text(encoding="utf-8"))

    successful_deals = [
        deal for deal in deals
        if is_successful_deal(deal)
    ]

    evidences = [
        build_evidence(deal)
        for deal in successful_deals
    ]

    price_analysis = analyze_prices(evidences)
    region_analysis = group_by_region(evidences)
    common_terms = get_common_terms(evidences)

    result = {
        "source": "xarid.uzex.uz",
        "product": "Принтер",
        "raw_deals_count": len(deals),
        "successful_deals_count": len(successful_deals),
        "price_analysis": price_analysis,
        "region_analysis": region_analysis,
        "common_terms": common_terms,
        "evidences": evidences[:30],
    }

    OUTPUT_FILE.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n✅ Analysis finished")
    print("Raw deals:", len(deals))
    print("Successful deals:", len(successful_deals))

    print("\n--- PRICE ANALYSIS ---")
    print(json.dumps(price_analysis, ensure_ascii=False, indent=2))

    print("\n--- REGION ANALYSIS ---")
    print(json.dumps(region_analysis, ensure_ascii=False, indent=2))

    print(f"\nSaved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()