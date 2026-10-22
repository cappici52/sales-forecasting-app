import asyncio
import csv
import io
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import numpy as np
from fastapi import HTTPException, UploadFile

from app import forecasting
from app.services import missing_calendar_days, read_and_validate


def sales(days=150, missing=None):
    start = date(2026, 1, 1)
    records = []
    for offset in range(days):
        for channel, price in (("in_store", 10), ("online", 20)):
            if (offset, channel) == missing:
                continue
            records.append(SimpleNamespace(
                date=start + timedelta(days=offset), store_id="BKK01", sku_id="SKU01",
                channel=channel, quantity_sold=0 if offset == 20 else 10 + offset % 7,
                unit_price=price,
            ))
    return records


class ConstantModel:
    def __init__(self, value=5.0):
        self.value = value

    def predict(self, features):
        return [self.value]


class ForecastingTests(unittest.TestCase):
    def test_calendar_gaps_are_unknown_and_channels_have_separate_lags(self):
        records = sales(days=70, missing=(40, "online"))
        frame = forecasting.prepare(records)
        online_gap = frame[(frame.channel == "online") & (frame.date == pd.Timestamp("2026-02-10"))]
        self.assertTrue(pd.isna(online_gap.iloc[0].quantity_sold))
        zero_day = frame[(frame.channel == "online") & (frame.date == pd.Timestamp("2026-01-21"))]
        self.assertEqual(zero_day.iloc[0].quantity_sold, 0)
        rows = forecasting.feature_rows(frame)
        self.assertFalse(((rows.channel == "online") & (rows.date == pd.Timestamp("2026-02-11"))).any())
        store_row = rows[(rows.channel == "in_store") & (rows.date == pd.Timestamp("2026-02-11"))].iloc[0]
        self.assertEqual(store_row.lag_1, 10 + 40 % 7)
        self.assertEqual(missing_calendar_days(frame.dropna(subset=["quantity_sold"])), 1)

    def test_recent_gap_excludes_only_affected_channel(self):
        frame = forecasting.prepare(sales(days=40, missing=(38, "online")))
        result = forecasting.forecast_series(frame, ConstantModel(), frame.date.max(), 7)
        self.assertEqual(list(result), [("BKK01", "SKU01", "in_store")])
        self.assertEqual(result[("BKK01", "SKU01", "in_store")][0], [5.0] * 7)

    def test_training_evaluates_three_horizons_and_retrains_on_all_dates(self):
        records = sales()
        fit_dates = []
        original_fit = forecasting.fit

        def tracked_fit(rows, price_weighted=False, absolute_error=False):
            fit_dates.append(rows.date.max().date())
            return original_fit(rows, price_weighted=price_weighted, absolute_error=absolute_error)

        with tempfile.TemporaryDirectory() as directory, patch.object(forecasting, "ARTIFACTS", Path(directory)), patch.object(forecasting, "fit", side_effect=tracked_fit):
            metrics = forecasting.train(records)
            self.assertEqual(metrics["objective"], "count:poisson")
            self.assertEqual([item["days"] for item in metrics["backtests"]], [7, 14, 28])
            self.assertEqual([item["folds"] for item in metrics["backtests"]], [2, 2, 2])
            self.assertEqual(metrics["confirmation_origin"], "2026-05-02")
            self.assertTrue(all(origin < metrics["confirmation_origin"] for origin in metrics["selection_origins"]))
            self.assertEqual(metrics["wape"], metrics["backtests"][-1]["wape"])
            self.assertEqual(metrics["by_store"][0]["id"], "BKK01")
            self.assertEqual(metrics["by_sku"][0]["id"], "SKU01")
            self.assertTrue(forecasting.artifact_path(metrics["_artifact_id"]).is_file())
            forecast = forecasting.predict(records, metrics["_artifact_id"], 7)
            self.assertEqual(len(forecast["items"]), 7)
            self.assertEqual(forecast["items"][0]["date"], "2026-05-31")
            self.assertEqual(forecast["coverage"], {"series_used": 2, "series_total": 2})
            segments = forecasting.segment_forecasts(records, metrics["_artifact_id"], 7)
            self.assertEqual({item["channel"] for item in segments}, {"in_store", "online"})
            self.assertAlmostEqual(sum(item["forecast_revenue"] for item in segments),
                                   sum(item["forecast"] for item in forecast["items"]), places=1)
            snapshots = forecasting.snapshot_predictions(records, metrics["_artifact_id"])
            self.assertEqual(len(snapshots), 56)
            self.assertEqual(snapshots[0]["target_date"], date(2026, 5, 31))
            self.assertEqual({item["channel"] for item in snapshots}, {"in_store", "online"})
        self.assertEqual(fit_dates, [day for day in (date(2026, 3, 7), date(2026, 4, 4),
                                                    date(2026, 5, 2), date(2026, 5, 30)) for _ in range(3)])

    def test_poisson_fit_predicts_nonnegative_quantities(self):
        rows = forecasting.feature_rows(forecasting.prepare(sales(days=90)))
        model = forecasting.fit(rows)
        self.assertEqual(model.get_params()["objective"], "count:poisson")
        self.assertTrue((model.predict(rows[forecasting.FEATURES]) >= 0).all())

    def test_price_weighted_fit_gives_high_price_rows_more_weight(self):
        rows = forecasting.feature_rows(forecasting.prepare(sales(days=90)))
        with patch.object(forecasting, "XGBRegressor") as regressor:
            forecasting.fit(rows)
            self.assertNotIn("sample_weight", regressor.return_value.fit.call_args.kwargs)
            forecasting.fit(rows, price_weighted=True)
            weights = regressor.return_value.fit.call_args.kwargs["sample_weight"]
        self.assertAlmostEqual(float(np.mean(weights)), 1)
        self.assertGreater(float(weights[rows.channel.eq("online").to_numpy()].mean()),
                           float(weights[rows.channel.eq("in_store").to_numpy()].mean()))

    def test_weak_model_uses_weekly_baseline_for_forecast_and_snapshot(self):
        records = sales()
        with tempfile.TemporaryDirectory() as directory, patch.object(forecasting, "ARTIFACTS", Path(directory)), patch.object(forecasting, "fit", return_value=ConstantModel()):
            metrics = forecasting.train(records)
            self.assertEqual(metrics["forecast_methods"], {"7": "weekly_naive", "14": "weekly_naive", "28": "weekly_naive"})
            artifact_id = metrics["_artifact_id"]
            forecast = forecasting.predict(records, artifact_id, 28)
            self.assertEqual(forecast["method"], "weekly_naive")
            frame = forecasting.prepare(records)
            series = forecasting.forecast_series(frame, ConstantModel(), frame.date.max(), 28)
            expected = sum(baseline[0] * price for _, baseline, price in series.values())
            self.assertAlmostEqual(forecast["items"][0]["forecast"], expected, places=2)
            segments = forecasting.segment_forecasts(records, artifact_id)
            self.assertAlmostEqual(sum(item["forecast_revenue"] for item in segments),
                                   sum(item["forecast"] for item in forecast["items"]), places=1)
            snapshots = forecasting.snapshot_predictions(records, artifact_id)
            self.assertEqual(len(snapshots), 56)
            self.assertAlmostEqual(sum(item["forecast_revenue"] for item in snapshots),
                                   sum(item["forecast"] for item in forecast["items"]), places=1)

    def test_old_artifact_stays_compatible_and_tie_uses_baseline(self):
        self.assertEqual(forecasting.choose_method({"wape": 0.4, "baseline_wape": 0.4}), "weekly_naive")
        self.assertEqual(forecasting.choose_method({"wape": 0.3, "baseline_wape": 0.4}), "xgboost")
        self.assertEqual(forecasting.choose_method({"wape": 0.3, "baseline_wape": 0.4,
                                                   "weighted_wape": 0.2}), "price_weighted_xgboost")
        with tempfile.TemporaryDirectory() as directory, patch.object(forecasting, "ARTIFACTS", Path(directory)):
            artifact_id = "a" * 32
            forecasting.joblib.dump(ConstantModel(), forecasting.artifact_path(artifact_id))
            model, methods, weighted_model, absolute_model = forecasting.load_artifact(artifact_id)
            self.assertIsInstance(model, ConstantModel)
            self.assertEqual(methods, {})
            self.assertIsNone(weighted_model)
            self.assertIsNone(absolute_model)
            forecasting.joblib.dump({"version": 2, "model": ConstantModel(),
                                     "methods": {28: "weekly_naive"}},
                                    forecasting.artifact_path(artifact_id))
            _, methods, weighted_model, _ = forecasting.load_artifact(artifact_id)
            self.assertEqual(methods, {28: "weekly_naive"})
            self.assertIsNone(weighted_model)

    def test_weighted_artifact_drives_forecast_segments_and_snapshot(self):
        records = sales()
        with tempfile.TemporaryDirectory() as directory, patch.object(forecasting, "ARTIFACTS", Path(directory)):
            artifact_id = "b" * 32
            forecasting.joblib.dump({"version": 3, "model": ConstantModel(),
                                     "weighted_model": ConstantModel(10),
                                     "methods": {28: "price_weighted_xgboost"}},
                                    forecasting.artifact_path(artifact_id))
            forecast = forecasting.predict(records, artifact_id, 28)
            self.assertEqual(forecast["method"], "price_weighted_xgboost")
            self.assertEqual(forecast["items"][0]["forecast"], 300)
            self.assertEqual(sum(item["forecast_revenue"] for item in forecasting.segment_forecasts(records, artifact_id)),
                             sum(item["forecast"] for item in forecast["items"]))
            self.assertEqual(sum(item["forecast_revenue"] for item in forecasting.snapshot_predictions(records, artifact_id)),
                             sum(item["forecast"] for item in forecast["items"]))

    def test_missing_price_is_rejected_and_zero_price_is_preserved(self):
        records = sales(days=90)
        records[0].unit_price = None
        with self.assertRaisesRegex(ValueError, "unit_price"):
            forecasting.prepare(records)
        lines = ["date,store_id,sku_id,channel,quantity_sold,unit_price"]
        for offset in range(90):
            lines.append(f"{date(2026, 1, 1) + timedelta(days=offset)},BKK01,SKU01,online,0,{'' if offset == 0 else 0}")
        upload = UploadFile(file=io.BytesIO("\n".join(lines).encode()), filename="sales.csv")
        with self.assertRaises(HTTPException):
            asyncio.run(read_and_validate(upload))
        lines[1] = lines[1] + "0"
        upload = UploadFile(file=io.BytesIO("\n".join(lines).encode()), filename="sales.csv")
        frame = asyncio.run(read_and_validate(upload))
        self.assertEqual(frame.unit_price.iloc[0], 0)
        lines[1] = lines[1][:-1] + "inf"
        upload = UploadFile(file=io.BytesIO("\n".join(lines).encode()), filename="sales.csv")
        with self.assertRaises(HTTPException):
            asyncio.run(read_and_validate(upload))

    def test_downloadable_sample_supports_rolling_backtest(self):
        sample = Path(__file__).resolve().parents[2] / "ex_sales" / "projecta-sample-sales.csv"
        with sample.open(newline="", encoding="utf-8") as source:
            records = [SimpleNamespace(
                date=date.fromisoformat(row["date"]), store_id=row["store_id"], sku_id=row["sku_id"],
                channel=row["channel"], quantity_sold=float(row["quantity_sold"]), unit_price=float(row["unit_price"]),
            ) for row in csv.DictReader(source)]
        with tempfile.TemporaryDirectory() as directory, patch.object(forecasting, "ARTIFACTS", Path(directory)):
            metrics = forecasting.train(records)
            self.assertEqual(metrics["backtests"][-1]["folds"], 2)
            self.assertEqual(len(metrics["by_store"]), 2)
            self.assertEqual(len(metrics["by_sku"]), 4)

    def test_challenger_requires_earlier_and_latest_window_improvement(self):
        earlier = {"wape": .6, "baseline_wape": .8, "weighted_wape": .7, "absolute_wape": .5}
        method, check = forecasting.confirm_method(earlier, {"wape": .4, "absolute_wape": .55})
        self.assertEqual(method, "xgboost")
        self.assertFalse(check["promoted"])
        self.assertEqual(forecasting.confirm_method(earlier, {"wape": .4, "absolute_wape": .3})[0],
                         "absolute_error_xgboost")
        self.assertEqual(forecasting.confirm_method(earlier, None)[0], "xgboost")
        self.assertEqual(forecasting.confirm_method(earlier, {"wape": .4, "absolute_wape": .4})[0], "xgboost")
        self.assertEqual(forecasting.confirm_method({**earlier, "absolute_wape": .9},
                                                   {"wape": .4, "absolute_wape": .1})[0], "xgboost")
        weighted = {**earlier, "absolute_wape": .9, "weighted_wape": .3}
        self.assertEqual(forecasting.confirm_method(weighted, {"wape": .4, "weighted_wape": .5})[0], "xgboost")
        self.assertEqual(forecasting.confirm_method(weighted, {"wape": .4, "weighted_wape": .3})[0], "price_weighted_xgboost")

    def test_absolute_model_is_used_consistently_and_clamps_negative_units(self):
        records = sales()
        with tempfile.TemporaryDirectory() as directory, patch.object(forecasting, "ARTIFACTS", Path(directory)):
            artifact_id = "c" * 32
            for value in (-3, 12):
                forecasting.joblib.dump({"version": 4, "model": ConstantModel(),
                                         "weighted_model": ConstantModel(8), "absolute_model": ConstantModel(value),
                                         "methods": {28: "absolute_error_xgboost"}}, forecasting.artifact_path(artifact_id))
                result = forecasting.predict(records, artifact_id, 28)
                expected = max(0, value) * 30 * 28
                self.assertEqual(result["method"], "absolute_error_xgboost")
                self.assertEqual(sum(row["forecast"] for row in result["items"]), expected)
                self.assertEqual(sum(row["forecast_revenue"] for row in forecasting.segment_forecasts(records, artifact_id)), expected)
                self.assertEqual(sum(row["forecast_revenue"] for row in forecasting.snapshot_predictions(records, artifact_id)), expected)

    def test_short_history_cannot_promote_without_confirmation(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(forecasting, "ARTIFACTS", Path(directory)), patch.object(forecasting, "fit", return_value=ConstantModel()):
            metrics = forecasting.train(sales(days=90))
        self.assertIsNone(metrics["confirmation_origin"])
        self.assertTrue(all(not item["promotion_check"]["promoted"] for item in metrics["backtests"]))

    def test_absolute_objective_uses_price_weights(self):
        rows = forecasting.feature_rows(forecasting.prepare(sales(days=90)))
        with patch.object(forecasting, "XGBRegressor") as regressor:
            forecasting.fit(rows, price_weighted=True, absolute_error=True)
        self.assertEqual(regressor.call_args.kwargs["objective"], "reg:absoluteerror")
        self.assertAlmostEqual(float(np.mean(regressor.return_value.fit.call_args.kwargs["sample_weight"])), 1)


if __name__ == "__main__":
    unittest.main()
