"""Read-only fixed feature/price challengers for the existing recursive model."""
import argparse
import json

import numpy as np
import pandas as pd
from sklearn.base import clone

from benchmark_direct_forecast import load_source, scores
from app import forecasting

EXTRA = ["weekday_mean", "weekday_median", "zero_fraction", "trend", "variation"]


def extra_rows(frame):
    rows = forecasting.feature_rows(frame)
    groups = frame.groupby(forecasting.GRAIN, sort=False).quantity_sold
    shifts = pd.concat([groups.shift(lag) for lag in (7, 14, 21, 28)], axis=1)
    rows["weekday_mean"] = shifts.mean(axis=1).loc[rows.index]
    rows["weekday_median"] = shifts.median(axis=1).loc[rows.index]
    rows["zero_fraction"] = groups.transform(lambda x: x.shift(1).rolling(28).apply(lambda v: np.mean(v == 0), raw=True)).loc[rows.index]
    rows["trend"] = rows.mean_7 / rows.mean_28.clip(lower=1)
    rows["variation"] = groups.transform(lambda x: x.shift(1).rolling(28).std(ddof=0)).loc[rows.index] / rows.mean_28.clip(lower=1)
    return rows


def enhanced_forecast(frame, origin, model, columns):
    result = {}
    for key, group in frame[frame.date <= origin].groupby(forecasting.GRAIN, sort=False):
        recent = group.sort_values("date").tail(28)
        if len(recent) != 28 or recent.date.iloc[-1] != origin or recent.quantity_sold.isna().any():
            continue
        history = recent.quantity_sold.astype(float).tolist()
        price = float(recent.unit_price.iloc[-1])
        predictions = []
        for offset in range(1, 29):
            day = origin + pd.Timedelta(days=offset)
            same_weekday = [history[-i] for i in (7, 14, 21, 28)]
            row = {"lag_1": history[-1], "lag_7": history[-7], "lag_14": history[-14], "lag_28": history[-28],
                   "mean_7": np.mean(history[-7:]), "mean_28": np.mean(history[-28:]),
                   "weekday": day.dayofweek, "month": day.month, "unit_price": price,
                   "weekday_mean": np.mean(same_weekday), "weekday_median": np.median(same_weekday),
                   "zero_fraction": np.mean(np.asarray(history[-28:]) == 0),
                   "trend": np.mean(history[-7:]) / max(np.mean(history[-28:]), 1),
                   "variation": np.std(history[-28:]) / max(np.mean(history[-28:]), 1)}
            value = max(0., float(model.predict(pd.DataFrame([row], columns=columns))[0]))
            predictions.append(value)
            history.append(value)
        result[key] = (predictions, price)
    return result


def evaluate(frame, origin):
    history = frame[frame.date <= origin]
    training = extra_rows(history)
    base = forecasting.fit(training)
    projections = {"original": {key: (values[0], values[2]) for key, values in forecasting.forecast_series(history, base, origin, 28).items()}}
    for name, extra in (("weekday", EXTRA[:2]), ("patterns", EXTRA)):
        columns = forecasting.FEATURES + extra
        model = clone(base).fit(training[columns], training.quantity_sold)
        projections[name] = enhanced_forecast(history, origin, model, columns)
    for name, window, method in (("price_median7", 7, "median"), ("price_median28", 28, "median"), ("price_volume28", 28, "weighted")):
        projections[name] = {}
        for key, group in history.groupby(forecasting.GRAIN, sort=False):
            if key not in projections["original"]:
                continue
            recent = group.sort_values("date").tail(window)
            sold = recent[recent.quantity_sold > 0]
            price = projections["original"][key][1]
            if len(sold):
                price = float(sold.unit_price.median() if method == "median" else (sold.quantity_sold * sold.unit_price).sum() / sold.quantity_sold.sum())
            projections[name][key] = (projections["original"][key][0], price)
    actual = {(row.store_id, row.sku_id, row.channel, row.date): row for row in frame.itertuples()}
    results = {}
    for name, projection in projections.items():
        rows = []
        for key, (values, price) in projection.items():
            future = [actual.get((*key, origin + pd.Timedelta(days=i))) for i in range(1, 29)]
            if any(row is None or pd.isna(row.quantity_sold) for row in future):
                continue
            rows.extend((i + 1, row.quantity_sold * row.unit_price, values[i] * price) for i, row in enumerate(future))
        results[name] = rows
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=("postgres", "olist", "retail_ii", "rossmann"))
    parser.add_argument("--holdout", action="store_true")
    args = parser.parse_args()
    frame = load_source(args.source)
    end = frame.date.max() - pd.Timedelta(days=28)
    origins = [end] if args.holdout else [end - pd.Timedelta(days=28 * fold) for fold in (3, 2, 1)]
    totals, folds = {}, []
    for origin in origins:
        result = evaluate(frame if args.holdout else frame[frame.date <= end], origin)
        folds.append({"origin": str(origin.date()), "wape28": {name: scores(rows, 28) for name, rows in result.items()}})
        for name, rows in result.items():
            totals.setdefault(name, []).extend(rows)
    print(json.dumps({"source": args.source, "phase": "holdout" if args.holdout else "development", "folds": folds,
                      "wape": {days: {name: scores(rows, days) for name, rows in totals.items()} for days in (7, 14, 28)}}, indent=2))


if __name__ == "__main__":
    main()
