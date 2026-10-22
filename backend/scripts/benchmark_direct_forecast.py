"""Explore direct multi-horizon models using earlier windows before final evaluation."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from xgboost import XGBRegressor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import forecasting
from scripts import benchmark_olist, benchmark_retail_ii, benchmark_rossmann

FEATURES = ["last", "lag7", "lag14", "lag28", "mean7", "mean28", "median28", "std28",
            "zero_fraction", "weekday_mean", "weekday_last", "horizon", "weekday", "month", "price"]
METHODS = ("poisson", "log", "normalized_poisson")


def features(recent, origin, horizon, price, normalized=False):
    day = origin + pd.Timedelta(days=horizon)
    weekday_values = recent[(np.arange(28) + origin.dayofweek - 27) % 7 == day.dayofweek]
    scale = max(float(np.mean(recent)), 1.) if normalized else 1.
    values = [recent[-1], recent[-7], recent[-14], recent[-28], np.mean(recent[-7:]),
              np.mean(recent), np.median(recent), np.std(recent)]
    return [float(v / scale) for v in values] + [float(np.mean(recent == 0)),
             float(np.mean(weekday_values) / scale), float(weekday_values[-1] / scale),
             horizon, day.dayofweek, day.month, price], scale


def fit_direct(frame, method):
    rows, targets = [], []
    for _, group in frame.groupby(forecasting.GRAIN, sort=False):
        group = group.sort_values("date")
        qty = group.quantity_sold.to_numpy(dtype=float)
        prices = group.unit_price.to_numpy(dtype=float)
        dates = group.date.tolist()
        for index in range(27, len(group) - 1, 7):
            recent = qty[index - 27:index + 1]
            if not np.isfinite(recent).all() or not np.isfinite(prices[index]):
                continue
            for horizon in range(1, min(28, len(group) - index - 1) + 1):
                target = qty[index + horizon]
                if not np.isfinite(target):
                    continue
                row, scale = features(recent, dates[index], horizon, prices[index], method == "normalized_poisson")
                rows.append(row)
                targets.append(np.log1p(target) if method == "log" else target / scale)
    if len(rows) < 30:
        raise ValueError("Insufficient direct training rows")
    model = XGBRegressor(n_estimators=220, max_depth=3, learning_rate=.05, subsample=.85,
                         colsample_bytree=.8, min_child_weight=5, reg_lambda=5,
                         objective="reg:squarederror" if method == "log" else "count:poisson",
                         n_jobs=2, random_state=42)
    model.fit(pd.DataFrame(rows, columns=FEATURES), targets)
    return model


def project(frame, origin, model, method, days=28):
    result = {}
    for key, group in frame[frame.date <= origin].groupby(forecasting.GRAIN, sort=False):
        recent = group.sort_values("date").tail(28)
        if len(recent) != 28 or recent.date.iloc[-1] != origin or recent.quantity_sold.isna().any():
            continue
        qty = recent.quantity_sold.to_numpy(dtype=float)
        price = float(recent.unit_price.iloc[-1])
        values = [features(qty, origin, horizon, price, method == "normalized_poisson") for horizon in range(1, days + 1)]
        predictions = model.predict(pd.DataFrame([row for row, _ in values], columns=FEATURES))
        predictions = np.expm1(predictions) if method == "log" else predictions * values[0][1]
        result[key] = (np.maximum(predictions, 0).tolist(), price)
    return result


def load_source(source):
    if source == "postgres":
        from app.database import SessionLocal
        from app.models import SalesRecord
        with SessionLocal() as db:
            orgs = db.query(SalesRecord.organization_id).distinct().all()
            if len(orgs) != 1:
                raise ValueError("Expected one organization with sales")
            frame = forecasting.prepare(db.query(SalesRecord).filter_by(organization_id=orgs[0][0]).all())
        return frame
    return {"olist": benchmark_olist, "retail_ii": benchmark_retail_ii, "rossmann": benchmark_rossmann}[source].load_frame()[0]


def evaluate(frame, origin, methods):
    history = frame[frame.date <= origin]
    actual = {(row.store_id, row.sku_id, row.channel, row.date): row for row in frame.itertuples()}
    projections = {method: project(history, origin, fit_direct(history, method), method) for method in methods}
    original = forecasting.forecast_series(history, forecasting.fit(forecasting.feature_rows(history)), origin, 28)
    projections["original"] = {key: (values[0], values[2]) for key, values in original.items()}
    common = set.intersection(*(set(values) for values in projections.values()))
    results = {method: [] for method in projections}
    for key in sorted(common):
        future = [actual.get((*key, origin + pd.Timedelta(days=i))) for i in range(1, 29)]
        if any(row is None or pd.isna(row.quantity_sold) for row in future):
            continue
        for method, projection in projections.items():
            predictions, price = projection[key]
            results[method].extend((i + 1, row.quantity_sold * row.unit_price, predictions[i] * price)
                                   for i, row in enumerate(future))
    return results


def scores(rows, days):
    rows = np.asarray([row for row in rows if row[0] <= days])
    return float(np.abs(rows[:, 1] - rows[:, 2]).sum() / rows[:, 1].sum())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=("postgres", "olist", "retail_ii", "rossmann"))
    parser.add_argument("--holdout", action="store_true", help="Evaluate final period only after freezing the candidates")
    args = parser.parse_args()
    frame = load_source(args.source)
    end = frame.date.max() - pd.Timedelta(days=28)
    combined = {method: [] for method in (*METHODS, "original")}
    origins = [end] if args.holdout else [end - pd.Timedelta(days=28 * fold) for fold in (3, 2, 1)]
    fold_scores = []
    for origin in origins:
        results = evaluate(frame if args.holdout else frame[frame.date <= end], origin, METHODS)
        fold_scores.append({"origin": str(origin.date()), "wape28": {method: scores(rows, 28) for method, rows in results.items()}})
        for method, rows in results.items():
            combined[method].extend(rows)
    print(json.dumps({"source": args.source, "phase": "exploratory_holdout" if args.holdout else "development",
                      "folds": fold_scores,
                      "wape": {days: {method: scores(rows, days) for method, rows in combined.items()} for days in (7, 14, 28)}}, indent=2))


if __name__ == "__main__":
    main()
