import unittest
from datetime import date, timedelta
from types import SimpleNamespace

from app.quality import assess


def records(include_gap=False):
    start = date(2026, 9, 1)
    return [SimpleNamespace(date=start + timedelta(days=offset), store_id="BKK", sku_id=sku,
                            channel="online")
            for sku in ("A", "B") for offset in range(28)
            if not (include_gap and sku == "B" and offset == 10)]


class QualityTests(unittest.TestCase):
    def test_clean_comparison_does_not_claim_guaranteed_accuracy(self):
        metrics = {"backtests": [{"days": 28, "folds": 3, "test_rows": 168,
                                  "wape": 0.20, "baseline_wape": 0.40}]}
        result = assess(metrics, records(), date(2026, 10, 2))
        self.assertEqual(result["status"], "no_flags")
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["coverage"], {"series_used": 2, "series_total": 2})
        self.assertEqual(result["data_age_days"], 4)

    def test_review_flags_are_independent_and_missing_days_reduce_coverage(self):
        metrics = {"backtests": [{"days": 28, "folds": 2, "test_rows": 112,
                                  "wape": 0.50, "baseline_wape": 0.30}]}
        result = assess(metrics, records(include_gap=True), date(2026, 10, 29))
        self.assertEqual(result["status"], "review")
        self.assertEqual(result["reasons"], ["limited_backtest", "not_better_than_baseline",
                                              "high_revenue_error", "stale_data", "partial_coverage"])
        self.assertEqual(result["coverage"], {"series_used": 1, "series_total": 2})

    def test_missing_evaluation_is_not_presented_as_good(self):
        result = assess({"backtests": []}, records(), date(2026, 9, 28))
        self.assertEqual(result["reasons"], ["missing_backtest"])
        invalid = {"backtests": [{"days": 28, "folds": 3, "test_rows": 10,
                                   "wape": float("nan"), "baseline_wape": 0.2}]}
        self.assertEqual(assess(invalid, records(), date(2026, 9, 28))["reasons"], ["missing_backtest"])

    def test_quality_checks_selected_method_and_latest_confirmation(self):
        item = {"days": 28, "folds": 3, "test_rows": 168, "wape": .6,
                "selected_wape": .2, "baseline_wape": .4, "confirmation_wape": .25,
                "confirmation_baseline_wape": .4}
        self.assertEqual(assess({"backtests": [item]}, records(), date(2026, 9, 28))["reasons"], [])
        item["confirmation_wape"] = .5
        self.assertEqual(assess({"backtests": [item]}, records(), date(2026, 9, 28))["reasons"],
                         ["not_better_than_baseline", "high_revenue_error"])


if __name__ == "__main__":
    unittest.main()
