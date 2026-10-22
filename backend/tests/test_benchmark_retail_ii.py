import unittest

import pandas as pd

from scripts import benchmark_retail_ii


class BenchmarkRetailIITest(unittest.TestCase):
    def test_sku_selection_uses_training_only_and_excludes_cancellations(self):
        dates = pd.date_range(benchmark_retail_ii.START, benchmark_retail_ii.TEST_END)
        rows = []
        for sku in range(1, 8):
            for date in dates:
                rows.append({
                    "Invoice": "123", "StockCode": f"{sku:05}",
                    "Quantity": 1, "InvoiceDate": date,
                    "Price": (1000 if sku == 7 else sku) if date > benchmark_retail_ii.TRAIN_END else
                    (0.1 if sku == 7 else sku),
                    "Country": "United Kingdom",
                })
        rows.append({
            "Invoice": "C999", "StockCode": "00007", "Quantity": 100000,
            "InvoiceDate": benchmark_retail_ii.START, "Price": 1000,
            "Country": "United Kingdom",
        })
        frame, skus = benchmark_retail_ii.prepare_transactions(pd.DataFrame(rows))
        self.assertEqual(skus, ["00006", "00005", "00004", "00003", "00002", "00001"])
        self.assertNotIn("00007", set(frame.sku_id))
        self.assertEqual(len(frame), len(dates) * 6)


if __name__ == "__main__":
    unittest.main()
