import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts import benchmark_weekly_direct as weekly
from scripts import prepare_weekly_cohort as cohort


class WeeklyDirectTests(unittest.TestCase):
    def frame(self):
        dates = pd.date_range("2020-01-01", periods=140)
        return pd.DataFrame({"date": dates, "store_id": "s", "sku_id": "a", "channel": "c",
                             "quantity_sold": np.arange(1, 141, dtype=float), "unit_price": 2.})

    def test_week_features_and_target_scaling(self):
        qty = np.arange(1, 57, dtype=float)
        values, scale = weekly.features(qty, pd.Timestamp("2020-03-01"), 1)
        self.assertEqual(scale, qty[-28:].sum() / 4)
        self.assertEqual(values[0], qty[-7:].sum() / scale)
        self.assertEqual(values[7], qty[:7].sum() / scale)
        self.assertEqual(values[-2], 1)

    def test_targets_are_complete_future_weeks_within_training(self):
        frame = self.frame()
        rows, targets, weights = weekly.training_rows(frame)
        # First origin is seven days before the final training day.
        _, scale = weekly.features(frame.quantity_sold.iloc[:-7], frame.date.iloc[-8], 1)
        self.assertAlmostEqual(targets[0] * scale, frame.quantity_sold.tail(7).sum())
        self.assertEqual(rows.iloc[0].horizon, 1)
        self.assertTrue(np.isfinite(targets).all())
        self.assertAlmostEqual(weights.mean(), 1)

    def test_disaggregation_preserves_every_week_and_known_zero_day(self):
        origin = pd.Timestamp("2020-03-01")
        shares = np.array([.2, .2, .2, .2, .1, 0, .1])
        daily = weekly.distribute([70, 140, 210, 280], shares, origin)
        np.testing.assert_allclose(daily.reshape(4, 7).sum(axis=1), [70, 140, 210, 280])
        self.assertEqual(daily[5], 0)
        self.assertTrue((daily >= 0).all())

    def test_weekday_shares_ignore_future_and_zero_history_is_finite(self):
        frame = self.frame()
        origin = frame.date.iloc[-29]
        expected = weekly.weekday_shares(frame, origin)
        frame.loc[frame.date.gt(origin), "quantity_sold"] = 1e9
        np.testing.assert_allclose(weekly.weekday_shares(frame, origin), expected)
        frame["quantity_sold"] = 0
        np.testing.assert_allclose(weekly.weekday_shares(frame, origin), np.full(7, 1 / 7))

    def test_projection_training_never_receives_future_rows(self):
        frame = self.frame()
        origin = frame.date.iloc[-29]
        with patch.object(weekly.forecasting, "fit") as fit, patch.object(weekly.forecasting, "forecast_series") as forecast:
            forecast.return_value = {("s", "a", "c"): (np.ones(28), np.ones(28), 2.)}
            before = weekly.projections(frame, origin, ["median4"])
            self.assertLessEqual(fit.call_args.args[0].date.max(), origin)
            frame.loc[frame.date.gt(origin), "quantity_sold"] = 1e12
            after = weekly.projections(frame, origin, ["median4"])
        np.testing.assert_allclose(before["median4"][("s", "a", "c")][0], after["median4"][("s", "a", "c")][0])

    def test_per_series_selection_uses_matching_product_rows(self):
        rows = {m: [("fold", "a", 1, 10., 10. if m == "median4" else 0.),
                    ("fold", "b", 1, 10., 10. if m == "mean4" else 0.)] for m in weekly.METHODS}
        choices = weekly.choose_rules(rows)["per_series"]
        self.assertEqual(choices, {"a": "median4", "b": "mean4"})
        self.assertEqual(weekly.bulk.metrics(weekly.apply_rule(rows, choices))["weekly_wape"], 0)

    def test_gate_requires_strong_baseline_and_daily_guard(self):
        base = {"daily_wape": .6, "weekly_wape": .4, "sku_28day_wape": .3}
        candidate = {"daily_wape": .6, "weekly_wape": .35, "sku_28day_wape": .25}
        result = {"selected": candidate, "original": base, "weekly_naive": base}
        self.assertTrue(weekly.gate(result))
        candidate["daily_wape"] = .62
        self.assertFalse(weekly.gate(result))
        candidate["daily_wape"] = .6
        result["weekly_naive"] = {**base, "weekly_wape": .34}
        self.assertFalse(weekly.gate(result))

    def test_identical_predictions_have_zero_bootstrap_gain(self):
        rows = [("f", str(i), j, 10., 12.) for i in range(4) for j in range(1, 29)]
        interval = weekly.bootstrap_gain(rows, rows)
        self.assertEqual(interval["lower"], 0)
        self.assertEqual(interval["upper"], 0)

    def test_new_cohort_excludes_used_products_and_future_ranking(self):
        dates = pd.date_range(weekly.bulk.START, weekly.bulk.ORIGIN)
        rows = [(str(10000 + i), day, i + 1.) for i in range(26) for day in dates]
        data = pd.DataFrame(rows, columns=["sku_id", "date", "revenue"])
        selected = cohort.select(data, {"10025"})
        self.assertNotIn("10025", selected)
        self.assertNotIn("10000", selected)
        data = pd.concat([data, pd.DataFrame([("10000", weekly.bulk.END, 1e12)], columns=data.columns)])
        self.assertEqual(selected, cohort.select(data, {"10025"}))


if __name__ == "__main__":
    unittest.main()
