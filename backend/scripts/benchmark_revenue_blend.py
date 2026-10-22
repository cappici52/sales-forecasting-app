"""Read-only comparison of original, price-weighted, and direct-revenue models."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import forecasting
from scripts import benchmark_olist, benchmark_retail_ii, benchmark_rossmann


def evaluate(frame: pd.DataFrame, origin: pd.Timestamp) -> list[tuple[float, float, float, float, float]]:
    history = frame.loc[frame.date.le(origin)]
    training = forecasting.feature_rows(history)
    quantity_model = forecasting.fit(training)
    weighted_model = forecasting.fit(training, price_weighted=True)
    quantity_forecast = forecasting.forecast_series(history, quantity_model, origin, 28)
    weighted_forecast = forecasting.forecast_series(history, weighted_model, origin, 28)
    revenue_history = history.copy()
    revenue_history["quantity_sold"] *= revenue_history.unit_price
    revenue_history["unit_price"] = 1.0
    revenue_model = forecasting.fit(forecasting.feature_rows(revenue_history))
    revenue_forecast = forecasting.forecast_series(revenue_history, revenue_model, origin, 28)
    actual = {(row.store_id, row.sku_id, row.channel, row.date): row
              for row in frame.itertuples() if pd.notna(row.quantity_sold)}
    rows = []
    for key in quantity_forecast.keys() & weighted_forecast.keys() & revenue_forecast.keys():
        units, _, price = quantity_forecast[key]
        weighted_units, _, _ = weighted_forecast[key]
        revenues, _, _ = revenue_forecast[key]
        future = [actual.get((*key, origin + pd.Timedelta(days=offset))) for offset in range(1, 29)]
        if any(item is None for item in future):
            continue
        for item, unit, weighted_unit, revenue in zip(future, units, weighted_units, revenues):
            current = float(unit * price)
            weighted = float(weighted_unit * price)
            direct = float(revenue)
            rows.append((float(item.quantity_sold * item.unit_price), current, weighted, direct,
                         (current + direct) / 2))
    return rows


def wape(rows: list[tuple], predicted: int) -> float:
    values = np.asarray(rows)
    return round(float(np.abs(values[:, 0] - values[:, predicted]).sum() / values[:, 0].sum()), 4)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=("olist", "retail_ii", "rossmann", "postgres"))
    args = parser.parse_args()
    if args.source == "olist":
        frame, _ = benchmark_olist.load_frame()
        end = benchmark_olist.TRAIN_END
    elif args.source == "retail_ii":
        frame, _ = benchmark_retail_ii.load_frame()
        end = benchmark_retail_ii.TRAIN_END
    elif args.source == "rossmann":
        frame, _, _ = benchmark_rossmann.load_frame()
        end = benchmark_rossmann.TRAIN_END
    else:
        from app.database import SessionLocal
        from app.models import SalesRecord
        with SessionLocal() as db:
            organization = db.query(SalesRecord.organization_id).group_by(SalesRecord.organization_id).first()
            if not organization:
                raise SystemExit("No sales records")
            frame = forecasting.prepare(db.query(SalesRecord).filter_by(organization_id=organization[0]).all())
        end = frame.date.max() - pd.Timedelta(days=28)
    training = frame.loc[frame.date.le(end)]
    validation = []
    for fold in (3, 2, 1):
        validation.extend(evaluate(training, end - pd.Timedelta(days=28 * fold)))
    holdout = evaluate(frame, end)
    print(json.dumps({"source": args.source, "holdout_start": str((end + pd.Timedelta(days=1)).date()),
                      "validation_rows": len(validation), "holdout_rows": len(holdout),
                      "validation_wape": {name: wape(validation, index) for index, name in
                                          ((1, "current"), (2, "price_weighted"),
                                           (3, "direct_revenue"), (4, "equal_blend"))},
                      "holdout_wape": {name: wape(holdout, index) for index, name in
                                       ((1, "current"), (2, "price_weighted"),
                                        (3, "direct_revenue"), (4, "equal_blend"))}}, indent=2))


if __name__ == "__main__":
    main()
