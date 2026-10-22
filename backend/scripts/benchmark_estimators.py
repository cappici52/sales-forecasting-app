"""Fixed alternative estimators with the same data, features, and recursive forecast."""
import argparse
import json

import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor, HistGradientBoostingRegressor

from benchmark_direct_forecast import load_source, scores
from app import forecasting


def fit_candidates(training):
    models = {
        "original": forecasting.fit(training),
        "extra_trees": ExtraTreesRegressor(n_estimators=200, min_samples_leaf=5, max_features=.8, random_state=42, n_jobs=1),
        "random_forest": RandomForestRegressor(n_estimators=200, min_samples_leaf=5, max_features=.8, random_state=42, n_jobs=1),
        "hist_poisson": HistGradientBoostingRegressor(loss="poisson", max_iter=220, max_leaf_nodes=15, learning_rate=.05,
                                                     l2_regularization=5, early_stopping=False, random_state=42),
        "tweedie": forecasting.XGBRegressor(n_estimators=220, max_depth=3, learning_rate=.05, subsample=.85,
                                           colsample_bytree=.8, min_child_weight=5, reg_lambda=5, objective="reg:tweedie",
                                           tweedie_variance_power=1.5, n_jobs=2, random_state=42),
    }
    for name, model in models.items():
        if name != "original":
            model.fit(training[forecasting.FEATURES], training.quantity_sold)
    return models


def evaluate(frame, origin):
    history = frame[frame.date <= origin]
    training = forecasting.feature_rows(history)
    actual = {(row.store_id, row.sku_id, row.channel, row.date): row for row in frame.itertuples()}
    result = {}
    for name, model in fit_candidates(training).items():
        rows = []
        for key, (values, _, price) in forecasting.forecast_series(history, model, origin, 28).items():
            future = [actual.get((*key, origin + pd.Timedelta(days=i))) for i in range(1, 29)]
            if any(row is None or pd.isna(row.quantity_sold) for row in future):
                continue
            rows.extend((i + 1, row.quantity_sold * row.unit_price, values[i] * price) for i, row in enumerate(future))
        result[name] = rows
    result["equal_blend"] = [(left[0], left[1], (left[2] + right[2]) / 2)
                             for left, right in zip(result["original"], result["extra_trees"])]
    return result


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
