import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from scripts import benchmark_m5


class M5BenchmarkTests(unittest.TestCase):
    def test_product_selection_only_reads_pre_holdout_and_covers_categories(self):
        day_columns = [f"d_{day}" for day in range(1549, benchmark_m5.TRAIN_END + 1)]
        source_rows = []
        for store in range(10):
            for category in ("FOODS", "HOBBIES", "HOUSEHOLD"):
                for rank in range(3):
                    source_rows.append({"store_id": f"S{store}", "cat_id": category,
                                        "item_id": f"{category}_{rank}",
                                        **{day: rank + 1 for day in day_columns}})
        source = pd.DataFrame(source_rows)

        def read_csv(_path, usecols):
            self.assertNotIn("d_1914", usecols)
            return source[usecols]

        with patch.object(benchmark_m5.pd, "read_csv", side_effect=read_csv):
            selected = benchmark_m5.select_pairs()
        self.assertEqual(len(selected), 60)
        self.assertEqual({item["item_id"] for item in selected},
                         {f"{category}_{rank}" for category in ("FOODS", "HOBBIES", "HOUSEHOLD") for rank in (1, 2)})

    def test_gate_requires_gain_at_both_business_resolutions(self):
        scores = {"original": {"daily_wape": .50, "weekly_wape": .40, "sku_28day_wape": .35},
                  "weekly_naive": {"weekly_wape": .38, "sku_28day_wape": .33},
                  "selected": {"daily_wape": .49, "weekly_wape": .35, "sku_28day_wape": .30}}
        self.assertTrue(all(benchmark_m5.gate(scores, {"lower": .01}).values()))
        scores["selected"]["sku_28day_wape"] = .32
        self.assertFalse(all(benchmark_m5.gate(scores, {"lower": .01}).values()))

    def test_confirm_cannot_reuse_a_consumed_holdout(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(benchmark_m5, "OUT", Path(directory)), patch.object(benchmark_m5, "md5", return_value="fixture"):
            target = Path(directory)
            protocol = {"code_sha256": benchmark_m5.hashlib.sha256(Path(benchmark_m5.__file__).read_bytes()).hexdigest(),
                        "weekly_sha256": benchmark_m5.hashlib.sha256(Path(benchmark_m5.weekly.__file__).read_bytes()).hexdigest(),
                        "development_sha256": benchmark_m5.hashlib.sha256(b"{}").hexdigest(),
                        "source_md5": {"calendar.csv": "fixture", "sales_train_evaluation.csv": "fixture", "sell_prices.csv": "fixture"}}
            (target / "protocol.json").write_text(json.dumps(protocol))
            (target / "development.json").write_text("{}")
            (target / "confirmation_started.json").write_text("{}")
            with patch.object(benchmark_m5, "load_frame") as load_frame:
                with self.assertRaises(FileExistsError):
                    benchmark_m5.confirm()
                load_frame.assert_not_called()


if __name__ == "__main__":
    unittest.main()
