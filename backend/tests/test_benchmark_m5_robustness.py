import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts import benchmark_m5_robustness as robustness


class M5RobustnessTests(unittest.TestCase):
    def test_bootstrap_keeps_zero_actual_products(self):
        chosen = [("origin", sku, day, actual, forecast)
                  for sku, actual, forecast in (("zero", 0., 1.), ("active", 10., 8.))
                  for day in range(1, 29)]
        baseline = [("origin", sku, day, actual, forecast)
                    for sku, actual, forecast in (("zero", 0., 2.), ("active", 10., 5.))
                    for day in range(1, 29)]
        interval = robustness.bootstrap_gain(chosen, baseline)
        self.assertTrue(np.isfinite(interval["lower"]))
        self.assertGreater(interval["lower"], 0)

    def test_stratified_selection_excludes_prior_cohort_and_future_days(self):
        identity = [(f"S{store}", category, f"{category}_{item}")
                    for store in range(10) for category in ("FOODS", "HOBBIES", "HOUSEHOLD")
                    for item in range(10)]
        frame = pd.DataFrame(identity, columns=["store_id", "cat_id", "item_id"])
        day_columns = [f"d_{day}" for day in range(robustness.m5.FIRST_DAY, robustness.m5.TRAIN_END + 1)]
        values = pd.DataFrame(np.repeat(np.tile(np.arange(1, 11), 30)[:, None], len(day_columns), axis=1), columns=day_columns)
        frame = pd.concat([frame, values], axis=1)

        def read_csv(_path, usecols):
            self.assertNotIn("d_1914", usecols)
            return frame[usecols]

        with patch.object(robustness.pd, "read_csv", side_effect=read_csv):
            cohort = robustness.select_cohort([{"store_id": "S0", "item_id": "FOODS_0"}])
        self.assertEqual(len(cohort), 90)
        self.assertEqual({label: sum(item["stratum"] == label for item in cohort) for label in robustness.STRATA},
                         {"low": 30, "medium": 30, "high": 30})
        self.assertNotIn(("S0", "FOODS_0"), {(item["store_id"], item["item_id"]) for item in cohort})

    def test_gate_rejects_weak_volume_group_even_when_overall_passes(self):
        base = {"original": {"daily_wape": .40, "weekly_wape": .30, "sku_28day_wape": .25},
                "weekly_naive": {"weekly_wape": .28, "sku_28day_wape": .23},
                "selected": {"daily_wape": .35, "weekly_wape": .24, "sku_28day_wape": .19}}
        strata = {name: {"original": {"weekly_wape": .30}, "weekly_naive": {"weekly_wape": .28},
                         "direct_absolute": {"weekly_wape": .26}} for name in robustness.STRATA}
        self.assertTrue(all(robustness.robustness_checks(base, strata, {"lower": .01}).values()))
        strata["low"]["direct_absolute"]["weekly_wape"] = .31
        self.assertFalse(robustness.robustness_checks(base, strata, {"lower": .01})["no_stratum_weekly_regression_over_2pp"])


if __name__ == "__main__":
    unittest.main()
