import statistics
from typing import Any

from app.schemas import Evidence


class PriceAnalysisService:
    def analyze(self, evidences: list[Evidence]) -> dict[str, Any]:
        eligible = [ev for ev in evidences if isinstance(ev.unit_price, (int, float))]
        prices = [ev.unit_price for ev in eligible]  # type: ignore[misc]
        excluded_count = len(evidences) - len(eligible)

        if not prices:
            return {
                "count": 0,
                "excluded_count": excluded_count,
                "excluded_reason": "unit_price mavjud bo‘lmagan evidencelar narx tahliliga kiritilmadi.",
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

        for ev in eligible:
            if ev.unit_price <= avg_price * 0.7:
                suspicious.append(
                    {
                        "source_name": ev.source_name,
                        "source_url": ev.source_url,
                        "lot_display_no": ev.lot_display_no,
                        "product_name": ev.product_name,
                        "unit_price": round(ev.unit_price, 2),
                        "avg_price": round(avg_price, 2),
                        "reason": "Bitta dona narxi o‘rtacha narxdan 30% yoki undan ko‘proq past",
                    }
                )

        return {
            "count": len(prices),
            "excluded_count": excluded_count,
            "excluded_reason": "unit_price mavjud bo‘lmagan evidencelar narx tahliliga kiritilmadi.",
            "min_price": round(min(prices), 2),
            "max_price": round(max(prices), 2),
            "avg_price": round(avg_price, 2),
            "median_price": round(median_price, 2),
            "recommended_min_price": round(median_price * 0.9, 2),
            "recommended_max_price": round(median_price * 1.1, 2),
            "suspicious_prices": suspicious,
        }

    def analyze_by_source(
        self,
        evidences_by_source: dict[str, list[Evidence]],
    ) -> dict[str, Any]:
        all_evidences: list[Evidence] = []
        for items in evidences_by_source.values():
            all_evidences.extend(items)

        global_result = self.analyze(all_evidences)

        by_source: dict[str, Any] = {}

        for source, evidences in evidences_by_source.items():
            eligible_count = sum(
                1 for ev in evidences if isinstance(ev.unit_price, (int, float))
            )

            if eligible_count == 0:
                note = (
                    "Etender evidence does not include quantity/amount, therefore it is excluded from per-unit price analysis."
                    if source == "etender.uzex.uz"
                    else "unit_price mavjud bo‘lmagani uchun narx tahliliga qo‘shilmadi."
                )
                by_source[source] = {
                    "count": 0,
                    "excluded_count": len(evidences),
                    "excluded_reason": note,
                    "note": note,
                    "min_price": None,
                    "max_price": None,
                    "avg_price": None,
                    "median_price": None,
                    "recommended_min_price": None,
                    "recommended_max_price": None,
                    "suspicious_prices": [],
                }
                continue

            by_source[source] = self.analyze(evidences)

        return {
            "global": global_result,
            "by_source": by_source,
        }
