import json
import asyncio
import io
import unittest
from datetime import date
from unittest.mock import patch

from fastapi import UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.database import Base
from app.main import forecast, forecast_vs_actual, import_upload, summary
from app.models import ForecastSnapshot, ModelRun, Organization, SalesRecord, User


class ApiContractTests(unittest.TestCase):
    def test_summary_exposes_forecast_review_without_changing_model_status(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            org = Organization(name="Review Org")
            db.add(org); db.flush()
            user = User(organization_id=org.id, email="review@example.test", display_name="Owner", password_hash="x", role="owner")
            run = ModelRun(organization_id=org.id, status="completed", metrics_json=json.dumps({
                "backtests": [{"days": 28, "folds": 3, "test_rows": 84, "wape": .6, "baseline_wape": .4}],
                "_artifact_id": "a" * 32,
            }))
            db.add_all([user, run] + [SalesRecord(organization_id=org.id, date=date.fromordinal(date(2026, 1, 1).toordinal() + day),
                                                   store_id="BKK", sku_id="A", channel="online", quantity_sold=2, unit_price=10)
                                      for day in range(28)])
            db.commit()
            with patch("app.main.active_artifact_id", return_value="a" * 32):
                result = summary(user=user, db=db)
            self.assertEqual(result["model"]["status"], "completed")
            self.assertEqual(result["model"]["quality"]["status"], "review")
            self.assertIn("not_better_than_baseline", result["model"]["quality"]["reasons"])
            self.assertEqual(result["model"]["quality"]["coverage"], {"series_used": 1, "series_total": 1})
            self.assertNotIn("_artifact_id", result["model"]["metrics"])
        engine.dispose()

    def test_new_import_keeps_saved_forecast_and_run_identity(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            org = Organization(name="Import Org")
            db.add(org); db.flush()
            user = User(organization_id=org.id, email="import@example.test", display_name="Owner", password_hash="x", role="owner")
            run = ModelRun(organization_id=org.id, status="completed", metrics_json=json.dumps({"backtests": [{}]}))
            db.add_all([user, run]); db.flush()
            db.add(ForecastSnapshot(organization_id=org.id, model_run_id=run.id, origin_date=date(2026, 1, 1),
                                    target_date=date(2026, 4, 1), store_id="BKK", sku_id="A", channel="online",
                                    forecast_revenue=100))
            db.commit()
            old_id = run.id
            lines = ["date,store_id,sku_id,channel,quantity_sold,unit_price"]
            for index in range(90):
                lines.append(f"{date.fromordinal(date(2026, 1, 2).toordinal() + index)},BKK,A,online,5,20")
            upload = UploadFile(file=io.BytesIO("\n".join(lines).encode()), filename="new-sales.csv")
            request = Request({"type": "http", "headers": []})
            result = asyncio.run(import_upload(request=request, file=upload, user=user, db=db))
            self.assertEqual(result["imported"], 90)
            self.assertEqual(db.get(ModelRun, old_id).status, "superseded")
            self.assertEqual(db.query(ForecastSnapshot).filter_by(organization_id=org.id).count(), 1)
            db.add(ModelRun(organization_id=org.id, status="running")); db.flush()
            self.assertNotEqual(db.query(ModelRun).order_by(ModelRun.id.desc()).first().id, old_id)
        engine.dispose()

    def test_snapshot_report_matches_only_observed_series_and_is_tenant_scoped(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            org = Organization(name="Forecast Org")
            other = Organization(name="Other Org")
            db.add_all([org, other]); db.flush()
            user = User(organization_id=org.id, email="report@example.test", display_name="Owner", password_hash="x", role="owner")
            db.add_all([
                ForecastSnapshot(organization_id=org.id, model_run_id=17, origin_date=date(2026, 1, 4),
                                 target_date=date(2026, 1, 5), store_id="BKK", sku_id="A", channel="online",
                                 category="Food", forecast_revenue=100),
                ForecastSnapshot(organization_id=org.id, model_run_id=17, origin_date=date(2026, 1, 4),
                                 target_date=date(2026, 1, 6), store_id="BKK", sku_id="A", channel="online",
                                 category="Food", forecast_revenue=120),
                ForecastSnapshot(organization_id=other.id, model_run_id=18, origin_date=date(2026, 1, 4),
                                 target_date=date(2026, 1, 5), store_id="BKK", sku_id="A", channel="online",
                                 category="Food", forecast_revenue=999),
                SalesRecord(organization_id=org.id, date=date(2026, 1, 5), store_id="BKK", sku_id="A",
                            channel="online", category="Food", quantity_sold=5, unit_price=22),
            ]); db.commit()
            report = forecast_vs_actual(grain="week", run_id=None, store_id=None, sku_id=None,
                                        category=None, channel=None, user=user, db=db)
            self.assertEqual(report["run_id"], 17)
            self.assertEqual(report["runs"], [{"run_id": 17, "origin_date": "2026-01-04"}])
            self.assertEqual(report["periods"], [{"period": "2026-01-05", "forecast_total": 220.0,
                                                   "forecast_matched": 100.0, "actual": 110.0,
                                                   "matched_count": 1, "forecast_count": 2, "difference": 10.0}])
            month = forecast_vs_actual(grain="month", run_id=17, store_id="OTHER", sku_id=None,
                                       category=None, channel=None, user=user, db=db)
            self.assertEqual(month["periods"], [])
        engine.dispose()

    def test_legacy_missing_price_and_old_model_never_show_revenue_forecast(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            org = Organization(name="Test Org")
            db.add(org)
            db.flush()
            user = User(organization_id=org.id, email="owner@example.test", display_name="Owner", password_hash="test", role="owner")
            row = SalesRecord(organization_id=org.id, date=date(2026, 1, 1), store_id="BKK01", sku_id="SKU01",
                              channel="online", quantity_sold=5, unit_price=None)
            run = ModelRun(organization_id=org.id, model_name="XGBoost", status="completed",
                           metrics_json=json.dumps({"wape": .1, "_artifact_id": "a" * 32}))
            db.add_all([user, row, run])
            db.commit()

            first = summary(user=user, db=db)
            self.assertIsNone(first["total_revenue"])
            self.assertEqual(first["model"]["status"], "invalid_data")
            self.assertEqual(forecast(days=7, user=user, db=db)["source"], "needs_price")

            row.unit_price = 10
            db.commit()
            second = summary(user=user, db=db)
            self.assertEqual(second["total_revenue"], 50)
            self.assertEqual(second["model"]["status"], "needs_retrain")
            self.assertEqual(forecast(days=7, user=user, db=db)["source"], "empty")
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
