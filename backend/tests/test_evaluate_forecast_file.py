import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import forecasting
from app.services import validate_content
from scripts import evaluate_forecast_file


class WeakModel:
    def predict(self, features):
        return [1.0]


def records(days=180, holdout_gap=False):
    start = date(2026, 1, 1)
    return [SimpleNamespace(date=start + timedelta(days=offset), store_id="BKK01", sku_id="SKU01",
                            channel="online", quantity_sold=10 + offset % 7, unit_price=100)
            for offset in range(days) if not (holdout_gap and offset == days - 4)]


class FileEvaluationTests(unittest.TestCase):
    def test_method_selection_uses_only_pre_holdout_dates(self):
        frame = forecasting.prepare(records())
        training_ends = []

        def fit(rows, **kwargs):
            training_ends.append(rows.date.max())
            return WeakModel()

        with patch.object(forecasting, "fit", side_effect=fit):
            result = evaluate_forecast_file.report(frame)
        holdout_origin = frame.date.max() - timedelta(days=28)
        self.assertTrue(all(day <= holdout_origin for day in training_ends))
        self.assertEqual(result["holdout"]["selected_method"], "weekly_naive")
        self.assertEqual(result["holdout"]["selected_metrics"]["wape"], 0)
        self.assertEqual(result["holdout"]["series_evaluated"], 1)
        self.assertEqual(len(result["validation"]["origins"]), 2)
        self.assertLess(result["validation"]["confirmation_origin"], str(holdout_origin.date()))
        self.assertEqual([item["days"] for item in result["horizon_holdouts"]], [7, 14, 28])
        self.assertTrue(all(item["wape"] == 0 for item in result["horizon_holdouts"]))

    def test_incomplete_holdout_is_not_scored_as_zero_sales(self):
        frame = forecasting.prepare(records(holdout_gap=True))
        with patch.object(forecasting, "fit", return_value=WeakModel()):
            with self.assertRaisesRegex(ValueError, "ต่อเนื่องครบ 28 วัน"):
                evaluate_forecast_file.report(frame)

    def test_csv_sample_runs_through_upload_validation_and_report(self):
        sample = Path(__file__).resolve().parents[2] / "ex_sales" / "projecta-sample-sales.csv"
        data = validate_content(sample.read_bytes(), sample.name)
        frame = forecasting.prepare([SimpleNamespace(**row) for row in data.to_dict("records")])
        with patch.object(forecasting, "fit", return_value=WeakModel()):
            result = evaluate_forecast_file.report(frame)
        self.assertEqual(result["data"]["rows"], 600)
        self.assertEqual(result["holdout"]["series_evaluated"], 4)
        self.assertEqual(result["holdout"]["selected_metrics"]["test_rows"], 112)


if __name__ == "__main__":
    unittest.main()
