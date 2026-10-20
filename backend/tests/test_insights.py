import unittest
from datetime import date, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.insights import build_insights
from app.main import sales_insights
from app.models import Organization, SalesRecord, User


def sample_rows(missing: tuple[int, str] | None = None):
    start = date(2026, 1, 1)
    rows = []
    for offset in range(56):
        for sku, channel, previous, recent in (("A", "online", 10, 5), ("B", "store", 2, 4)):
            if (offset, sku) == missing:
                continue
            rows.append(SimpleNamespace(date=start + timedelta(days=offset), store_id="BKK", sku_id=sku,
                                        sku_name=f"Product {sku}", channel=channel,
                                        quantity_sold=previous if offset < 28 else recent, unit_price=10.0))
    return rows


class InsightTests(unittest.TestCase):
    def test_comparison_seasonality_and_actions_are_traceable(self):
        rows = sample_rows()
        projected = [
            {"store_id": "BKK", "sku_id": "A", "channel": "online", "forecast_units": 168, "forecast_revenue": 1680},
            {"store_id": "BKK", "sku_id": "B", "channel": "store", "forecast_units": 140, "forecast_revenue": 1400},
        ]
        result = build_insights(rows, projected, rows[-1].date, review_needed=True, model_available=True)
        products = {item["sku_id"]: item for item in result["products"]}
        self.assertEqual(products["A"]["recent_units"], 140)
        self.assertEqual(products["A"]["change_pct"], -0.5)
        self.assertEqual(products["B"]["change_pct"], 1.0)
        self.assertEqual(result["forecast_coverage"], {"series_used": 2, "series_total": 2})
        self.assertEqual(result["weekday"]["status"], "ready")
        self.assertEqual(len(result["weekday"]["values"]), 7)
        self.assertIn("inspect_decline", [item["kind"] for item in result["actions"]])
        self.assertIn("review_model", [item["kind"] for item in result["actions"]])
        self.assertNotIn("check_stock", [item["kind"] for item in result["actions"]])

    def test_missing_day_is_not_assumed_to_be_zero_sales(self):
        rows = sample_rows(missing=(40, "A"))
        result = build_insights(rows, [], rows[-1].date, review_needed=False)
        product = next(item for item in result["products"] if item["sku_id"] == "A")
        self.assertFalse(product["history_complete"])
        self.assertIsNone(product["change_pct"])
        self.assertEqual(result["weekday"]["status"], "incomplete_history")
        self.assertEqual(result["weekday"]["values"], [])

    def test_uncovered_model_prompts_data_review_not_retraining(self):
        rows = sample_rows(missing=(40, "A"))
        result = build_insights(rows, [], rows[-1].date, review_needed=True, model_available=True)
        kinds = [item["kind"] for item in result["actions"]]
        self.assertIn("check_coverage", kinds)
        self.assertNotIn("train_model", kinds)

    def test_missing_prices_do_not_produce_revenue_planning_prompt(self):
        rows = sample_rows()
        rows[0].unit_price = None
        result = build_insights(rows, [], rows[-1].date, review_needed=False,
                                model_available=True, price_complete=False)
        kinds = [item["kind"] for item in result["actions"]]
        self.assertIn("fix_prices", kinds)
        self.assertNotIn("check_stock", kinds)
        self.assertEqual(result["weekday"]["status"], "missing_price")
        self.assertIsNone(result["channels"][0]["recent_revenue"])

    def test_endpoint_scopes_every_insight_to_signed_in_organization(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            own = Organization(name="Own Org")
            other = Organization(name="Other Org")
            db.add_all([own, other]); db.flush()
            user = User(organization_id=own.id, email="owner@example.test", display_name="Owner", password_hash="x", role="owner")
            db.add_all([user,
                        SalesRecord(organization_id=own.id, date=date(2026, 1, 1), store_id="BKK", sku_id="OWN", channel="online", quantity_sold=2, unit_price=10),
                        SalesRecord(organization_id=other.id, date=date(2026, 1, 1), store_id="CNX", sku_id="SECRET", channel="store", quantity_sold=5, unit_price=20)])
            db.commit()
            result = sales_insights(user=user, db=db)
            self.assertEqual([item["sku_id"] for item in result["products"]], ["OWN"])
            self.assertEqual([item["channel"] for item in result["channels"]], ["online"])
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
