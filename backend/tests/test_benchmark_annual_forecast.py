import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts import benchmark_annual_forecast as annual


class AnnualForecastTests(unittest.TestCase):
    def test_confirmation_rejects_changed_inputs_before_evaluation(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(annual, "OUT", Path(directory)), patch.object(annual, "input_hashes", return_value={"code": "new"}), patch.object(annual, "evaluate") as evaluate:
            (Path(directory) / "confirmation_protocol.json").write_text(json.dumps({"hashes": {"code": "old"}}))
            with self.assertRaisesRegex(ValueError, "changed after freeze"):
                annual.confirm(pd.DataFrame())
            evaluate.assert_not_called()
            self.assertFalse((Path(directory) / "confirmation_started.json").exists())

    def test_confirmation_cannot_reuse_consumed_cohort(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(annual, "OUT", Path(directory)), patch.object(annual, "input_hashes", return_value={}), patch.object(annual, "evaluate") as evaluate:
            (Path(directory) / "confirmation_protocol.json").write_text(json.dumps({"hashes": {}}))
            (Path(directory) / "confirmation_started.json").write_text("{}")
            with self.assertRaises(FileExistsError):
                annual.confirm(pd.DataFrame())
            evaluate.assert_not_called()

    def test_acceptance_requires_all_scales_baseline_and_confidence(self):
        scores = {"original": {"daily_wape": .7, "weekly_wape": .5, "sku_28day_wape": .4},
                  "weekly_naive": {"weekly_wape": .45},
                  "selected": {"daily_wape": .6, "weekly_wape": .4, "sku_28day_wape": .3}}
        self.assertTrue(all(annual.acceptance_checks(scores, {"lower": .01}).values()))
        self.assertFalse(all(annual.acceptance_checks(scores, {"lower": 0.}).values()))
        for metric, value in [("daily_wape", .69), ("weekly_wape", .49), ("sku_28day_wape", .41)]:
            changed = {**scores, "selected": {**scores["selected"], metric: value}}
            self.assertFalse(all(annual.acceptance_checks(changed, {"lower": .01}).values()))
        scores["weekly_naive"]["weekly_wape"] = .39
        self.assertFalse(all(annual.acceptance_checks(scores, {"lower": .01}).values()))

    def test_evaluation_passes_only_history_to_training(self):
        origin = pd.Timestamp("2011-11-02")
        frame = pd.DataFrame({"date": pd.date_range(origin - pd.Timedelta(days=60), periods=89),
                              "store_id": "s", "sku_id": "a", "channel": "c",
                              "quantity_sold": 10., "unit_price": 2.})
        with patch.object(annual, "project") as project:
            project.return_value = {"original": {("s", "a", "c"): (np.ones(28), 2.)}}
            rows = annual.evaluate(frame, origin, ["original"])
            self.assertEqual(project.call_args.args[0].date.max(), origin)
            self.assertEqual(len(rows["original"]), 28)

    def test_annual_features_match_past_calendar_and_never_current_target(self):
        count = 500
        frame = pd.DataFrame({"date": pd.date_range("2010-01-01", periods=count),
                              "store_id": "s", "sku_id": "a", "channel": "c",
                              "quantity_sold": np.arange(1, count + 1, dtype=float), "unit_price": 1.})
        rows = annual.annual_rows(frame)
        row = rows.loc[450]
        self.assertEqual(row.year_day, frame.quantity_sold.iloc[450 - 364])
        self.assertEqual(row.year_week, frame.quantity_sold.iloc[450 - 364:450 - 357].mean())
        self.assertEqual(row.year_month, frame.quantity_sold.iloc[450 - 364:450 - 336].mean())
        self.assertAlmostEqual(row.growth56, frame.quantity_sold.iloc[450 - 56:450].mean() / frame.quantity_sold.iloc[450 - 420:450 - 364].mean())
        frame.loc[450:, "quantity_sold"] = 1e10
        changed = annual.annual_rows(frame).loc[450]
        np.testing.assert_allclose(row[annual.FEATURES].to_numpy(float), changed[annual.FEATURES].to_numpy(float))

    def test_missing_annual_history_stays_unknown_not_zero(self):
        date = pd.Timestamp("2020-01-01")
        self.assertTrue(np.isnan(annual.historic_mean({date: 5.}, date, 7)))
        self.assertEqual(annual.historic_mean({date: 0.}, date, 1), 0.)

    def test_fixed_blends_use_nonnegative_component_predictions(self):
        class Constant:
            def __init__(self, value):
                self.value = value

            def predict(self, frame):
                return np.full(len(frame), self.value)

        dates = pd.date_range("2009-12-01", annual.bulk.ORIGIN)
        frame = pd.DataFrame({"date": dates, "store_id": "s", "sku_id": "a", "channel": "c",
                              "quantity_sold": 10., "unit_price": 2.})
        with patch.object(annual.forecasting, "fit"), patch.object(annual.forecasting, "forecast_series") as forecast, patch.object(annual, "fit") as fit:
            forecast.return_value = {("s", "a", "c"): ([8.] * 28, [10.] * 28, 2.)}
            fit.side_effect = lambda history, absolute: Constant(-2 if absolute else 3)
            output = annual.project(frame, annual.bulk.ORIGIN, ["blend_annual_model", "blend_annual_absolute", "annual_robust_blend"])
        for method, expected in [("blend_annual_model", 5.5), ("blend_annual_absolute", 4.), ("annual_robust_blend", 1.5)]:
            np.testing.assert_allclose(output[method][("s", "a", "c")][0], np.full(28, expected))
            self.assertEqual(output[method][("s", "a", "c")][1], 2.)


if __name__ == "__main__":
    unittest.main()
