import statistics
from typing import Any

from app.schemas import Evidence


class PriceAnalysisService:
    def analyze(self, evidences: list[Evidence]) -> dict[str, Any]:
        prices = [
            ev.unit_price
            for ev in evidences
            if isinstance(ev.unit_price, (int, float))
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

        suspicious = []

        for ev in evidences:
            if not isinstance(ev.unit_price, (int, float)):
                continue

            if ev.unit_price <= avg_price * 0.7:
                suspicious.append(
                    {
                        "lot_display_no": ev.lot_display_no,
                        "product_name": ev.product_name,
                        "unit_price": round(ev.unit_price, 2),
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
            "suspicious_prices": suspicious,
        }