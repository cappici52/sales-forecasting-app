import json
import unittest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.main import forecast, summary
from app.models import ModelRun, Organization, SalesRecord, User


class ApiContractTests(unittest.TestCase):
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
