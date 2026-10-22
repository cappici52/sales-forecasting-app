import unittest

import pandas as pd

from scripts import benchmark_rossmann


class BenchmarkRossmannTests(unittest.TestCase):
    @staticmethod
    def sample():
        rows = []
        for store in range(1, 8):
            for day in pd.date_range(benchmark_rossmann.START, benchmark_rossmann.TEST_END):
                rows.append({
                    "Store": store, "Date": day, "Sales":
                    (1000 if store == 7 else store) if day > benchmark_rossmann.TRAIN_END else
                    (0.1 if store == 7 else store),
                    "Open": 1, "Promo": 0,
                })
        return pd.DataFrame(rows)

    def test_store_selection_does_not_use_holdout_revenue(self):
        frame, stores, diagnostics = benchmark_rossmann.prepare_sales(self.sample())
        self.assertEqual(stores, ["6", "5", "4", "3", "2", "1"])
        self.assertNotIn("7", set(frame.store_id))
        self.assertEqual(len(frame), 6 * len(pd.date_range(benchmark_rossmann.START,
                                                          benchmark_rossmann.TEST_END)))
        self.assertEqual(diagnostics["holdout_closed_store_days"], 0)

    def test_missing_holdout_day_is_not_interpreted_as_zero(self):
        raw = self.sample()
        raw = raw.loc[~((raw.Store == 1) & (raw.Date == benchmark_rossmann.TEST_END))]
        with self.assertRaisesRegex(ValueError, "missing dates"):
            benchmark_rossmann.prepare_sales(raw)


if __name__ == "__main__":
    unittest.main()
