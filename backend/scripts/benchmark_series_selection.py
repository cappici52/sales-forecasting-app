"""Read-only experiment: choose one of four methods per series on earlier windows."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import forecasting
from app.config import settings
from app.database import SessionLocal
from app.models import SalesRecord
from scripts import benchmark_models, benchmark_olist


def score(rows: list[tuple[float, float]]) -> float:
    actual = np.array([row[0] for row in rows])
    predicted = np.array([row[1] for row in rows])
    return round(float(np.abs(actual - predicted).sum() / actual.sum()), 4)


def evaluate(frame: pd.DataFrame, origin: pd.Timestamp, method: str, project) -> dict:
    actual = {(row.store_id, row.sku_id, row.channel, row.date): row
              for row in frame.itertuples() if pd.notna(row.quantity_sold)}
    result = {}
    for key, (quantities, price) in project(frame, origin, method).items():
        future = [actual.get((*key, origin + pd.Timedelta(days=offset))) for offset in range(1, 29)]
        if any(item is None for item in future):
            continue
        result[key] = [(float(item.quantity_sold * item.unit_price), float(quantity * price))
                       for item, quantity in zip(future, quantities)]
    return result


def compare(frame: pd.DataFrame, methods: tuple[str, ...], project) -> dict:
    holdout_origin = frame.date.max() - pd.Timedelta(days=28)
    training = frame.loc[frame.date.le(holdout_origin)]
    validation = {method: {} for method in methods}
    for fold in (3, 2, 1):
        origin = holdout_origin - pd.Timedelta(days=28 * fold)
        for method in methods:
            for key, rows in evaluate(training, origin, method, project).items():
                validation[method].setdefault(key, []).extend(rows)
    common = set.intersection(*(set(series) for series in validation.values()))
    common = {key for key in common if all(len(validation[method][key]) == 84 for method in methods)}
    if not common:
        raise ValueError("No series has three complete validation windows")
    choices = {key: min(methods, key=lambda method: score(validation[method][key])) for key in common}
    holdout = {method: evaluate(frame, holdout_origin, method, project) for method in methods}
    common = {key for key in common if all(key in holdout[method] for method in methods)}
    if not common:
        raise ValueError("No common complete holdout series")
    selected = [row for key in sorted(common) for row in holdout[choices[key]][key]]
    baseline = [row for key in sorted(common) for row in holdout[methods[0]][key]]
    return {
        "validation_origins": [str((holdout_origin - pd.Timedelta(days=28 * fold)).date()) for fold in (3, 2, 1)],
        "holdout_start": str((holdout_origin + pd.Timedelta(days=1)).date()),
        "series_evaluated": len(common),
        "per_series_choices": {"/".join(key): choices[key] for key in sorted(common)},
        "holdout_revenue_wape_selected": score(selected),
        "holdout_revenue_wape_xgboost": score(baseline),
        "note": "Exploratory: these public datasets' final periods were inspected before this experiment.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=("olist", "postgres"))
    args = parser.parse_args()
    methods = ("poisson_xgb", "weekly_naive", "weekday_4week_mean", "last_28_mean")
    if args.source == "olist":
        frame, _ = benchmark_olist.load_frame()
        project = benchmark_olist.project
    else:
        if not make_url(settings.database_url).drivername.startswith("postgresql"):
            raise SystemExit("Configure PostgreSQL in backend/.env")
        with SessionLocal() as db:
            organization_id = db.query(SalesRecord.organization_id).group_by(SalesRecord.organization_id).first()
            if not organization_id:
                raise SystemExit("No sales records")
            records = db.query(SalesRecord).filter_by(organization_id=organization_id[0]).all()
            frame = forecasting.prepare(records)
        methods = ("current_xgb", *methods[1:])
        project = benchmark_models.projections
    print(json.dumps({"source": args.source, **compare(frame, methods, project)}, indent=2))


if __name__ == "__main__":
    main()
