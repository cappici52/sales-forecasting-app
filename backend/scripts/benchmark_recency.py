"""Fixed recency/complexity candidates, ranked only on earlier rolling windows."""
import argparse
import json

import numpy as np
import pandas as pd
from sklearn.base import clone

from benchmark_direct_forecast import load_source, scores
from app import forecasting

CONFIGS = {
    "original": {},
    "recent28": {"half_life": 28},
    "recent56": {"half_life": 56},
    "recent112": {"half_life": 112},
    "shallow": {"max_depth": 2},
    "deeper": {"max_depth": 4},
    "recent56_deeper": {"half_life": 56, "max_depth": 4},
    "recent56_shallow": {"half_life": 56, "max_depth": 2},
}


def evaluate(frame, origin):
    history = frame[frame.date <= origin]
    training = forecasting.feature_rows(history)
    base = forecasting.fit(training)
    actual = {(row.store_id, row.sku_id, row.channel, row.date): row for row in frame.itertuples()}
    result = {}
    for name, config in CONFIGS.items():
        model = base
        if config:
            model = clone(base).set_params(**{k: v for k, v in config.items() if k != "half_life"})
            weights = np.exp2(-(training.date.max() - training.date).dt.days.to_numpy() / config["half_life"]) if "half_life" in config else np.ones(len(training))
            model.fit(training[forecasting.FEATURES], training.quantity_sold, sample_weight=weights / weights.mean())
        rows = []
        for key, (predicted, _, price) in forecasting.forecast_series(history, model, origin, 28).items():
            future = [actual.get((*key, origin + pd.Timedelta(days=i))) for i in range(1, 29)]
            if any(row is None or pd.isna(row.quantity_sold) for row in future):
                continue
            rows.extend((i + 1, row.quantity_sold * row.unit_price, predicted[i] * price) for i, row in enumerate(future))
        result[name] = rows
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=("postgres", "olist", "retail_ii", "rossmann"))
    parser.add_argument("--holdout", action="store_true")
    args = parser.parse_args()
    frame = load_source(args.source)
    end = frame.date.max() - pd.Timedelta(days=28)
    origins = [end] if args.holdout else [end - pd.Timedelta(days=28 * fold) for fold in (3, 2, 1)]
    totals = {name: [] for name in CONFIGS}
    folds = []
    for origin in origins:
        result = evaluate(frame if args.holdout else frame[frame.date <= end], origin)
        folds.append({"origin": str(origin.date()), "wape28": {name: scores(rows, 28) for name, rows in result.items()}})
        for name, rows in result.items():
            totals[name].extend(rows)
    print(json.dumps({"source": args.source, "phase": "holdout" if args.holdout else "development", "folds": folds,
                      "wape": {days: {name: scores(rows, days) for name, rows in totals.items()} for days in (7, 14, 28)}}, indent=2))


if __name__ == "__main__":
    main()
