"""Compare fixed seasonal candidates on earlier windows, then a final holdout."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import forecasting
from scripts import benchmark_olist, benchmark_retail_ii, benchmark_rossmann

METHODS = ("weekly_naive", "xgboost", "price_weighted_xgboost", "weekday_mean", "seasonal_blend", "absolute_error")


def evaluate(frame, origin):
    history = frame[frame.date <= origin]
    training = forecasting.feature_rows(history)
    projections = forecasting.forecast_series(history, forecasting.fit(training), origin, 28)
    weighted = forecasting.forecast_series(history, forecasting.fit(training, price_weighted=True), origin, 28)
    median_model = forecasting.fit(training, price_weighted=True, absolute_error=True)
    median = forecasting.forecast_series(history, median_model, origin, 28)
    actual = frame.set_index(forecasting.GRAIN + ["date"])
    rows = []
    for key, (predicted, naive, price) in projections.items():
        recent = history.set_index(forecasting.GRAIN).loc[key].sort_values("date").tail(28)
        means = recent.groupby(recent.date.dt.dayofweek).quantity_sold.mean()
        future = [(*key, origin + pd.Timedelta(days=i)) for i in range(1, 29)]
        if any(index not in actual.index for index in future):
            continue
        targets = actual.loc[future]
        if targets[["quantity_sold", "unit_price"]].isna().any().any():
            continue
        for i, index in enumerate(future):
            mean = means[index[-1].dayofweek]
            row = targets.loc[index]
            rows.append([i + 1, row.quantity_sold * row.unit_price,
                         naive[i] * price, predicted[i] * price, weighted[key][0][i] * price,
                         mean * price, (predicted[i] + mean) / 2 * price, median[key][0][i] * price])
    return np.asarray(rows)


def scores(rows, days):
    values = rows[rows[:, 0] <= days]
    denominator = values[:, 1].sum()
    if not denominator:
        raise ValueError("Evaluation has no positive actual revenue")
    return {name: float(np.abs(values[:, 1] - values[:, i + 2]).sum() / denominator)
            for i, name in enumerate(METHODS)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=("olist", "retail_ii", "rossmann", "postgres"))
    parser.add_argument("--audit", action="store_true", help="Evaluate the exact app selector on a separate final holdout")
    args = parser.parse_args()
    if args.source == "postgres":
        from app.database import SessionLocal
        from app.models import SalesRecord
        with SessionLocal() as db:
            organizations = db.query(SalesRecord.organization_id).distinct().all()
            if len(organizations) != 1:
                raise ValueError("Expected exactly one organization with sales for this local benchmark")
            frame = forecasting.prepare(db.query(SalesRecord).filter_by(organization_id=organizations[0][0]).all())
        end = frame.date.max() - pd.Timedelta(days=28)
    else:
        source = {"olist": benchmark_olist, "retail_ii": benchmark_retail_ii, "rossmann": benchmark_rossmann}[args.source]
        frame = source.load_frame()[0]
        end = source.TRAIN_END
    if args.audit:
        from scripts.evaluate_forecast_file import report
        print(json.dumps({"source": args.source, **report(frame)}, indent=2))
        return
    history = frame[frame.date <= end]
    validation = np.concatenate([evaluate(history, end - pd.Timedelta(days=28 * fold)) for fold in (3, 2, 1)])
    # Freeze choices before looking at the final period.
    choices = {days: min(scores(validation, days), key=scores(validation, days).get) for days in forecasting.HORIZONS}
    holdout = evaluate(frame, end)
    print(json.dumps({"source": args.source, "note": "Exploratory public periods already inspected in earlier experiments",
                      "horizons": [{"days": days, "selected": choices[days], "validation": scores(validation, days),
                                    "holdout": scores(holdout, days)} for days in forecasting.HORIZONS]}, indent=2))


if __name__ == "__main__":
    main()
