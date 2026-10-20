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
    def predict(self, features):
        return [5.0]


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

        def tracked_fit(rows):
            fit_dates.append(rows.date.max().date())
            return original_fit(rows)

        with tempfile.TemporaryDirectory() as directory, patch.object(forecasting, "ARTIFACTS", Path(directory)), patch.object(forecasting, "fit", side_effect=tracked_fit):
            metrics = forecasting.train(records)
            self.assertEqual(metrics["objective"], "count:poisson")
            self.assertEqual([item["days"] for item in metrics["backtests"]], [7, 14, 28])
            self.assertEqual([item["folds"] for item in metrics["backtests"]], [3, 3, 3])
            self.assertEqual(metrics["wape"], metrics["backtests"][-1]["wape"])
            self.assertEqual(metrics["by_store"][0]["id"], "BKK01")
            self.assertEqual(metrics["by_sku"][0]["id"], "SKU01")
            self.assertTrue(forecasting.artifact_path(metrics["_artifact_id"]).is_file())
            forecast = forecasting.predict(records, metrics["_artifact_id"], 7)
            self.assertEqual(len(forecast["items"]), 7)
            self.assertEqual(forecast["items"][0]["date"], "2026-05-31")
            self.assertEqual(forecast["coverage"], {"series_used": 2, "series_total": 2})
            snapshots = forecasting.snapshot_predictions(records, metrics["_artifact_id"])
            self.assertEqual(len(snapshots), 56)
            self.assertEqual(snapshots[0]["target_date"], date(2026, 5, 31))
            self.assertEqual({item["channel"] for item in snapshots}, {"in_store", "online"})
        self.assertEqual(fit_dates, [date(2026, 3, 7), date(2026, 4, 4), date(2026, 5, 2), date(2026, 5, 30)])

    def test_poisson_fit_predicts_nonnegative_quantities(self):
        rows = forecasting.feature_rows(forecasting.prepare(sales(days=90)))
        model = forecasting.fit(rows)
        self.assertEqual(model.get_params()["objective"], "count:poisson")
        self.assertTrue((model.predict(rows[forecasting.FEATURES]) >= 0).all())

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
            self.assertEqual(metrics["backtests"][-1]["folds"], 3)
            self.assertEqual(len(metrics["by_store"]), 2)
            self.assertEqual(len(metrics["by_sku"]), 4)


if __name__ == "__main__":
    unittest.main()
