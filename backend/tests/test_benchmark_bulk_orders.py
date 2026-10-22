import unittest

import numpy as np
import pandas as pd

from scripts import benchmark_bulk_orders as bulk


class BulkOrderTests(unittest.TestCase):
    def raw(self):
        return pd.DataFrame([
            ["1", "12345", 4, "2011-04-05", 2, "United Kingdom"],
            ["1", "12345", 6, "2011-04-05", 3, "United Kingdom"],
            ["2", "12345", 2, "2011-04-05", 2, "United Kingdom"],
            ["C3", "12345", -10, "2011-04-06", 2, "United Kingdom"],
            ["4", "12345", 10000, "2011-11-03", 2, "United Kingdom"],
        ], columns=["Invoice", "StockCode", "Quantity", "InvoiceDate", "Price", "Country"])

    def test_invoice_lines_aggregate_without_dropping_sales(self):
        orders = bulk.invoice_orders(self.raw())
        first = orders.loc[orders.invoice.eq("1")].iloc[0]
        self.assertEqual(first.quantity, 10)
        self.assertEqual(first.revenue, (4 * 2 + 6 * 3) * 40)
        self.assertEqual(first.lines, 2)
        self.assertNotIn("C3", orders.invoice.tolist())

    def test_future_large_orders_do_not_set_threshold(self):
        orders = bulk.invoice_orders(self.raw())
        past = orders.loc[orders.date.le(bulk.ORIGIN)]
        self.assertEqual(bulk.thresholds(orders, bulk.ORIGIN), bulk.thresholds(past, bulk.ORIGIN))
        self.assertAlmostEqual(bulk.thresholds(orders, bulk.ORIGIN)["12345"], 9.6)

    def test_components_reconcile_and_price_uses_only_past(self):
        orders = bulk.invoice_orders(self.raw())
        end = pd.Timestamp("2011-04-07")
        regular = bulk.daily_frame(orders, ["12345"], end, {"12345": 9.6}, "regular")
        big = bulk.daily_frame(orders, ["12345"], end, {"12345": 9.6}, "bulk")
        total = bulk.daily_frame(orders, ["12345"], end)
        np.testing.assert_allclose(regular.quantity_sold + big.quantity_sold, total.quantity_sold)
        self.assertEqual(big.quantity_sold.tolist(), [10, 0, 0])
        self.assertEqual(regular.quantity_sold.tolist(), [2, 0, 0])
        np.testing.assert_allclose(total.unit_price, [100, 100, 100])
        boundary = bulk.daily_frame(orders, ["12345"], end, {"12345": 10}, "bulk")
        self.assertEqual(boundary.quantity_sold.sum(), 0)

    def test_aggregation_keeps_zero_sales_and_does_not_mix_skus(self):
        rows = [("fold", "a", 1, 10, 0), ("fold", "a", 2, 0, 10),
                ("fold", "b", 1, 20, 10)]
        result = bulk.metrics(rows)
        self.assertAlmostEqual(result["daily_wape"], 1)
        self.assertAlmostEqual(result["weekly_wape"], 1 / 3)
        self.assertAlmostEqual(result["sku_28day_wape"], 1 / 3)
        self.assertEqual(result["rows"], 3)
        self.assertEqual(result["actual"], 30)

    def test_bulk_rate_includes_zero_days(self):
        dates = pd.date_range(bulk.ORIGIN - pd.Timedelta(days=55), bulk.ORIGIN)
        values = np.zeros(56)
        values[-1] = 56
        result = bulk.bulk_rate(pd.DataFrame({"date": dates, "quantity_sold": values}), bulk.ORIGIN)
        self.assertAlmostEqual(result.sum(), 28)
        empty = bulk.bulk_rate(pd.DataFrame({"date": dates, "quantity_sold": np.zeros(56)}), bulk.ORIGIN)
        self.assertTrue((empty == 0).all())

    def test_cohort_ignores_future_and_previously_used_skus(self):
        rows = []
        dates = pd.date_range(bulk.START, bulk.ORIGIN)
        for i in range(13):
            rows.extend((str(10000 + i), day, 100 + i) for day in dates)
        past = pd.DataFrame(rows, columns=["sku_id", "date", "revenue"])
        future = pd.DataFrame([("10000", bulk.END, 1e12)], columns=past.columns)
        self.assertEqual(bulk.select_cohort(past), bulk.select_cohort(pd.concat([past, future])))
        self.assertNotIn("10000", bulk.select_cohort(past))
        excluded = past.copy()
        excluded["sku_id"] = "85099B"
        self.assertEqual(bulk.select_cohort(past), bulk.select_cohort(pd.concat([past, excluded])))


if __name__ == "__main__":
    unittest.main()
