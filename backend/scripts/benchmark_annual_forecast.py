"""Prior-year demand features, isolated from the production model and database."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from xgboost import XGBRegressor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import forecasting
from scripts import benchmark_bulk_orders as bulk, benchmark_weekly_direct as weekly

OUT = bulk.ROOT / "outputs/annual_forecast_2026-10-22"
FEATURES = forecasting.FEATURES + ["year_day", "year_week", "year_month", "growth56"]
METHODS = ["original", "weekly_naive", "extended", "annual_poisson", "annual_absolute", "annual_weekly", "blend_annual",
           "blend_annual_model", "blend_annual_absolute", "annual_robust_blend"]


def annual_rows(frame):
    rows = forecasting.feature_rows(frame)
    extras = []
    for _, group in frame.groupby(forecasting.GRAIN, sort=True):
        q = group.quantity_sold
        extra = pd.DataFrame(index=group.index)
        extra["year_day"] = q.shift(364)
        extra["year_week"] = q.shift(358).rolling(7).mean()
        extra["year_month"] = q.shift(337).rolling(28).mean()
        extra["growth56"] = q.shift(1).rolling(56).mean() / q.shift(365).rolling(56).mean().clip(lower=1.)
        extras.append(extra)
    return rows.join(pd.concat(extras)).loc[lambda d: d.date.ge(frame.date.max() - pd.Timedelta(days=364))]


def fit(frame, absolute=False):
    rows = annual_rows(frame)
    model = XGBRegressor(n_estimators=220, max_depth=3, learning_rate=.05, subsample=.85,
                         colsample_bytree=.8, min_child_weight=5, reg_lambda=5, n_jobs=2, random_state=42,
                         objective="reg:absoluteerror" if absolute else "count:poisson")
    weights = rows.unit_price.to_numpy(float)
    model.fit(rows[FEATURES], rows.quantity_sold, sample_weight=weights / weights.mean() if absolute else None)
    return model


def historic_mean(lookup, start, count):
    values = [lookup.get(start + pd.Timedelta(days=i), np.nan) for i in range(count)]
    return float(np.mean(values)) if np.isfinite(values).all() else np.nan


def project(history, origin, methods):
    requested = list(methods)
    methods = list(dict.fromkeys([*methods, *(["annual_poisson", "annual_absolute"] if any(m in methods for m in ["blend_annual_model", "blend_annual_absolute", "annual_robust_blend"]) else [])]))
    history = history.loc[history.date.le(origin)].sort_values(forecasting.GRAIN + ["date"]).reset_index(drop=True)
    recent = history.loc[history.date.ge(bulk.START)]
    original = forecasting.forecast_series(recent, forecasting.fit(forecasting.feature_rows(recent)), origin, 28)
    extended = forecasting.forecast_series(history, forecasting.fit(forecasting.feature_rows(history)), origin, 28) if "extended" in methods else {}
    models = {m: fit(history, m == "annual_absolute") for m in methods if m in ["annual_poisson", "annual_absolute"]}
    outputs = {m: {} for m in methods}
    for key, group in history.groupby(forecasting.GRAIN):
        observed = dict(zip(group.date, group.quantity_sold.astype(float)))
        qty = group.quantity_sold.to_numpy(float)
        price = float(group.unit_price.iloc[-1])
        old_mean = historic_mean(observed, origin - pd.Timedelta(days=419), 56)
        growth = float(qty[-56:].mean() / max(old_mean, 1.)) if np.isfinite(old_mean) else 1.
        prior = [historic_mean(observed, origin + pd.Timedelta(days=1 + 7 * h - 364), 7) * 7 * growth for h in range(4)]
        annual = weekly.distribute(prior, weekly.weekday_shares(group, origin), origin) if np.isfinite(prior).all() else np.array(original[key][0])
        for method in methods:
            if method in ["blend_annual_model", "blend_annual_absolute", "annual_robust_blend"]:
                continue
            if method == "original":
                prediction = np.array(original[key][0])
            elif method == "weekly_naive":
                prediction = np.array(original[key][1])
            elif method == "extended":
                prediction = np.array(extended[key][0])
            elif method == "annual_weekly":
                prediction = annual
            elif method == "blend_annual":
                prediction = .5 * annual + .5 * np.array(original[key][0])
            else:
                recursive = qty.tolist()
                prediction = []
                for offset in range(1, 29):
                    day = origin + pd.Timedelta(days=offset)
                    old = historic_mean(observed, day - pd.Timedelta(days=420), 56)
                    row = [recursive[-1], recursive[-7], recursive[-14], recursive[-28],
                           np.mean(recursive[-7:]), np.mean(recursive[-28:]), day.dayofweek, day.month, price,
                           observed.get(day - pd.Timedelta(days=364), np.nan),
                           historic_mean(observed, day - pd.Timedelta(days=364), 7),
                           historic_mean(observed, day - pd.Timedelta(days=364), 28),
                           np.mean(recursive[-56:]) / max(old, 1.) if np.isfinite(old) else np.nan]
                    value = max(0., float(models[method].predict(pd.DataFrame([row], columns=FEATURES))[0]))
                    recursive.append(value)
                    prediction.append(value)
                prediction = np.array(prediction)
            outputs[method][key] = (prediction, price)
        if "blend_annual_model" in methods:
            outputs["blend_annual_model"][key] = (.5 * np.array(original[key][0]) + .5 * outputs["annual_poisson"][key][0], price)
        if "blend_annual_absolute" in methods:
            outputs["blend_annual_absolute"][key] = (.5 * np.array(original[key][0]) + .5 * outputs["annual_absolute"][key][0], price)
        if "annual_robust_blend" in methods:
            outputs["annual_robust_blend"][key] = (.5 * outputs["annual_poisson"][key][0] + .5 * outputs["annual_absolute"][key][0], price)
    return {m: outputs[m] for m in requested}


def evaluate(frame, origin, methods=METHODS):
    predictions = project(frame.loc[frame.date.le(origin)], origin, methods)
    rows = {m: [] for m in methods}
    for key, group in frame.groupby(forecasting.GRAIN):
        future = group.loc[group.date.between(origin + pd.Timedelta(days=1), origin + pd.Timedelta(days=28))].sort_values("date")
        if len(future) != 28:
            raise ValueError("Incomplete evaluation")
        for m in methods:
            qty, price = predictions[m][key]
            rows[m].extend((str(origin.date()), "/".join(key), i, float(r.quantity_sold * r.unit_price), float(qty[i - 1] * price))
                           for i, r in enumerate(future.itertuples(), 1))
    return rows


def acceptance_checks(scores, confidence):
    """Fixed before confirmation: improve both resolutions without monthly harm."""
    candidate, original, naive = (scores[k] for k in ("selected", "original", "weekly_naive"))
    return {
        "daily_gain_at_least_2pp": candidate["daily_wape"] <= original["daily_wape"] - .02,
        "weekly_gain_at_least_2pp": candidate["weekly_wape"] <= original["weekly_wape"] - .02,
        "monthly_not_worse": candidate["sku_28day_wape"] <= original["sku_28day_wape"],
        "weekly_beats_naive": candidate["weekly_wape"] < naive["weekly_wape"],
        "weekly_gain_ci_above_zero": confidence["lower"] > 0,
    }


def input_hashes():
    paths = [Path(__file__), Path(forecasting.__file__), Path(weekly.__file__), Path(bulk.__file__),
             OUT / "manifest.json", OUT / "series.jsonl", OUT / "development.json"]
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def freeze(manifest):
    development = json.loads((OUT / "development.json").read_text())
    if development["selected"] != "annual_robust_blend":
        raise ValueError("Unexpected development winner; review before freezing")
    if set(manifest["confirmation_skus"]) & set(manifest["development_skus"]):
        raise ValueError("Confirmation overlaps development")
    protocol = {
        "candidate": development["selected"], "weights": [.5, .5], "hashes": input_hashes(),
        "origin": str(bulk.ORIGIN.date()), "days": 28,
        "confirmation_skus": manifest["confirmation_skus"],
        "gate": "Daily and weekly WAPE improve >=2 percentage points vs original; SKU28 not worse; weekly beats naive; paired SKU weekly gain 95% CI lower >0",
        "scope": "Unused products, same retailer and familiar dates; NOT an independent future test",
    }
    with (OUT / "confirmation_protocol.json").open("x", encoding="utf-8") as handle:
        json.dump(protocol, handle, indent=2)
    print(json.dumps(protocol), flush=True)


def confirm(frame):
    protocol = json.loads((OUT / "confirmation_protocol.json").read_text())
    if protocol["hashes"] != input_hashes():
        raise ValueError("Code or inputs changed after freeze")
    # Exclusive marker BEFORE evaluation prevents relabelling retries as fresh.
    with (OUT / "confirmation_started.json").open("x", encoding="utf-8") as handle:
        json.dump({"status": "consumed", "candidate": protocol["candidate"]}, handle)
    frame = frame.loc[frame.sku_id.isin(protocol["confirmation_skus"])]
    if set(frame.sku_id) != set(protocol["confirmation_skus"]):
        raise ValueError("Missing confirmation products")
    rows = evaluate(frame, bulk.ORIGIN, ["original", "weekly_naive", protocol["candidate"]])
    rows["selected"] = rows.pop(protocol["candidate"])
    scores = weekly.scores(rows)
    confidence = weekly.bootstrap_gain(rows["selected"], rows["original"])
    checks = acceptance_checks(scores, confidence)
    result = {"candidate": protocol["candidate"], "metrics": scores, "weekly_gain_ci95": confidence,
              "checks": checks, "accepted": all(checks.values()), "production_changed": False,
              "scope": protocol["scope"]}
    (OUT / "confirmation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (OUT / "confirmation_predictions.json").write_text(json.dumps(rows), encoding="utf-8")
    print(json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["develop", "known", "freeze", "confirm"])
    args = parser.parse_args()
    manifest = json.loads((OUT / "manifest.json").read_text())
    frame = pd.read_json(OUT / "series.jsonl", lines=True, dtype={"sku_id": str})
    if args.phase == "develop":
        frame = frame.loc[frame.sku_id.isin(manifest["development_skus"]) & frame.date.le(bulk.ORIGIN)]
        pooled = {m: [] for m in METHODS}
        folds = []
        for fold in (3, 2, 1):
            rows = evaluate(frame, bulk.ORIGIN - pd.Timedelta(days=28 * fold))
            folds.append(weekly.scores(rows))
            for m in METHODS:
                pooled[m].extend(rows[m])
            print(json.dumps({"fold": fold, "metrics": folds[-1]}), flush=True)
        scores = weekly.scores(pooled)
        selected = min(METHODS, key=lambda m: sum(scores[m][k] for k in ["daily_wape", "weekly_wape", "sku_28day_wape"]))
        result = {"selected": selected, "metrics": scores, "folds": folds, "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        (OUT / "development.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({"selected": selected, "metrics": scores}), flush=True)
    elif args.phase == "known":
        frame = frame.loc[frame.sku_id.isin(bulk.DEVELOPMENT_SKUS)]
        result = weekly.scores(evaluate(frame, bulk.ORIGIN))
        (OUT / "known_main_six.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result), flush=True)
    elif args.phase == "freeze":
        freeze(manifest)
    else:
        confirm(frame)


if __name__ == "__main__":
    main()
