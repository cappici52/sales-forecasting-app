"""Read-only rolling/holdout benchmark for the migrated sales data."""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd
from sqlalchemy.engine import make_url
from xgboost import XGBRegressor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import forecasting
from app.config import settings
from app.database import SessionLocal
from app.models import SalesRecord


def score(rows: list[tuple], actual_index: int = 0, predicted_index: int = 1) -> float:
    actual = np.array([row[actual_index] for row in rows])
    predicted = np.array([row[predicted_index] for row in rows])
    return float(np.abs(actual - predicted).sum() / actual.sum())


def projections(frame: pd.DataFrame, origin: pd.Timestamp, method: str) -> dict:
    if method in {"current_xgb", "previous_xgb", "regularized_xgb", "poisson_xgb"}:
        training = forecasting.feature_rows(frame[frame.date <= origin])
        if method == "current_xgb":
            model = forecasting.fit(training)
        elif method == "previous_xgb":
            model = XGBRegressor(
                n_estimators=220, max_depth=6, learning_rate=.05, subsample=.85,
                colsample_bytree=.8, objective="reg:squarederror", n_jobs=2, random_state=42,
            )
            model.fit(training[forecasting.FEATURES], training.quantity_sold)
        else:
            model = XGBRegressor(
                n_estimators=220, max_depth=3, learning_rate=.05, subsample=.85,
                colsample_bytree=.8, min_child_weight=5, reg_lambda=5,
                objective="count:poisson" if method == "poisson_xgb" else "reg:squarederror",
                n_jobs=2, random_state=42,
            )
            model.fit(training[forecasting.FEATURES], training.quantity_sold)
        return {key: (values[0], values[2])
                for key, values in forecasting.forecast_series(frame, model, origin, 28).items()}
    result = {}
    for key, group in frame[frame.date <= origin].groupby(forecasting.GRAIN, sort=False):
        recent = group.sort_values("date").tail(28)
        if len(recent) != 28 or recent.date.iloc[-1] != origin or recent.quantity_sold.isna().any():
            continue
        values = recent.quantity_sold.to_numpy()
        if method == "weekly_naive":
            forecast = np.tile(values[-7:], 4)
        elif method == "weekday_4week_mean":
            forecast = np.tile(np.array([np.mean(values[offset::7]) for offset in range(7)]), 4)
        elif method == "last_28_mean":
            forecast = np.full(28, values.mean())
        else:
            raise ValueError(method)
        result[key] = (forecast, float(recent.unit_price.iloc[-1]))
    return result


def evaluate(frame: pd.DataFrame, origin: pd.Timestamp, method: str) -> list[tuple]:
    actual = {(row.store_id, row.sku_id, row.channel, row.date): row
              for row in frame.itertuples() if pd.notna(row.quantity_sold)}
    rows = []
    for key, (forecast, price) in projections(frame, origin, method).items():
        future = [actual.get((*key, origin + pd.Timedelta(days=offset))) for offset in range(1, 29)]
        if any(item is None for item in future):
            continue
        rows.extend((float(item.quantity_sold * item.unit_price), float(quantity * price),
                     float(item.quantity_sold), float(quantity),
                     float(quantity * item.unit_price), float(item.quantity_sold * price))
                    for item, quantity in zip(future, forecast))
    return rows


def main() -> None:
    if not make_url(settings.database_url).drivername.startswith("postgresql"):
        raise SystemExit("Configure PostgreSQL in backend/.env")
    with SessionLocal() as db:
        organization_id = db.query(SalesRecord.organization_id).group_by(SalesRecord.organization_id).first()
        if not organization_id:
            raise SystemExit("No sales records")
        records = db.query(SalesRecord).filter_by(organization_id=organization_id[0]).all()
        frame = forecasting.prepare(records)
    holdout_origin = frame.date.max() - pd.Timedelta(days=28)
    methods = ("current_xgb", "previous_xgb", "regularized_xgb", "poisson_xgb", "weekly_naive",
               "weekday_4week_mean", "last_28_mean")
    print(f"Training through {holdout_origin.date()}; independent holdout: next 28 days")
    training_frame = frame[frame.date <= holdout_origin]
    for method in methods:
        validation = []
        for fold in (3, 2, 1):
            origin = holdout_origin - pd.Timedelta(days=28 * fold)
            validation.extend(evaluate(training_frame, origin, method))
        holdout = evaluate(frame, holdout_origin, method)
        print(f"{method:22} validation_wape={score(validation):.4f} "
              f"holdout_wape={score(holdout):.4f} validation_rows={len(validation)} holdout_rows={len(holdout)}")
        if method == "current_xgb":
            print(f"  diagnostic: unit_wape={score(holdout, 2, 3):.4f} "
                  f"revenue_wape_if_future_price_known={score(holdout, 0, 4):.4f} "
                  f"revenue_wape_if_future_units_known={score(holdout, 0, 5):.4f}")


if __name__ == "__main__":
    main()
