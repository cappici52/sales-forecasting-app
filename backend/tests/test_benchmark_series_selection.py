import unittest

import pandas as pd

from scripts import benchmark_series_selection


class SeriesSelectionTests(unittest.TestCase):
    def test_holdout_is_not_used_to_select_method(self):
        dates = pd.date_range("2026-01-01", periods=200)
        frame = pd.DataFrame({"date": dates, "store_id": "one", "sku_id": "sku",
                              "channel": "online", "quantity_sold": 10.0, "unit_price": 1.0})
        holdout_origin = dates[-29]
        calls = []

        def project(source, origin, method):
            calls.append((source.date.max(), origin, method))
            is_holdout = origin == holdout_origin
            quantity = 0.0 if (method == "a") == is_holdout else 10.0
            return {("one", "sku", "online"): ([quantity] * 28, 1.0)}

        result = benchmark_series_selection.compare(frame, ("a", "b"), project)
        self.assertEqual(result["per_series_choices"], {"one/sku/online": "a"})
        self.assertEqual(result["holdout_revenue_wape_selected"], 1.0)
        self.assertTrue(all(source_end == holdout_origin for source_end, origin, _ in calls if origin < holdout_origin))


if __name__ == "__main__":
    unittest.main()
