"""Isolated direct-week forecasting; no database or production artifact writes."""
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
from scripts import benchmark_bulk_orders as bulk

OUT = bulk.ROOT / "outputs/weekly_direct_2026-10-22"
FEATURES = [*[f"week_{i}" for i in range(1, 9)], "mean4", "median4", "cv8", "zero28", "horizon", "month"]
METHODS = ["original", "weekly_naive", "mean4", "median4", "direct_poisson", "direct_absolute", "blend_median", "blend_weekly"]


def features(qty, origin, horizon):
    recent = np.asarray(qty[-56:], dtype=float)
    if len(recent) != 56 or not np.isfinite(recent).all():
        raise ValueError("Need 56 observed daily quantities")
    weeks = recent.reshape(8, 7).sum(axis=1)[::-1]
    scale = max(float(weeks[:4].mean()), 1.)
    return ([float(x / scale) for x in weeks]
            + [float(weeks[:4].mean() / scale), float(np.median(weeks[:4]) / scale),
               float(weeks.std() / max(weeks.mean(), 1.)), float((recent[-28:] == 0).mean()),
               horizon, (origin + pd.Timedelta(days=7 * horizon)).month]), scale


def training_rows(frame):
    values, targets, weights = [], [], []
    for _, group in frame.groupby(forecasting.GRAIN, sort=True):
        group = group.sort_values("date")
        qty = group.quantity_sold.to_numpy(dtype=float)
        # Origins aligned with the current forecast weekday, labels wholly in history.
        for index in range(len(group) - 8, 54, -7):
            history = qty[:index + 1]
            if not np.isfinite(history[-56:]).all():
                continue
            for horizon in range(1, min(4, (len(qty) - index - 1) // 7) + 1):
                target = qty[index + 1 + 7 * (horizon - 1):index + 1 + 7 * horizon]
                if not np.isfinite(target).all():
                    continue
                row, scale = features(history, group.date.iloc[index], horizon)
                values.append(row)
                targets.append(float(target.sum() / scale))
                weights.append(scale * float(group.unit_price.iloc[index]))
    if len(targets) < 30:
        raise ValueError("Insufficient complete weekly training targets")
    weights = np.array(weights)
    return pd.DataFrame(values, columns=FEATURES), np.array(targets), weights / weights.mean()


def fit_weekly(frame, absolute=False):
    rows, target, weights = training_rows(frame)
    model = XGBRegressor(n_estimators=160, max_depth=2, learning_rate=.05, subsample=.85,
                         colsample_bytree=.8, min_child_weight=8, reg_lambda=5,
                         objective="reg:absoluteerror" if absolute else "count:poisson", n_jobs=2, random_state=42)
    model.fit(rows, target, sample_weight=weights)
    return model


def weekday_shares(group, origin):
    recent = group.loc[group.date.between(origin - pd.Timedelta(days=55), origin)]
    amounts = recent.groupby(recent.date.dt.dayofweek).quantity_sold.sum().reindex(range(7), fill_value=0).to_numpy(float)
    # Preserve known zero-demand weekdays. No actual future weekday mix is used.
    return amounts / amounts.sum() if amounts.sum() else np.full(7, 1 / 7)


def distribute(weekly, shares, origin):
    pattern = np.array([shares[(origin + pd.Timedelta(days=i)).dayofweek] for i in range(1, 8)])
    return np.concatenate([float(total) * pattern for total in weekly])


def projections(history, origin, methods=METHODS):
    history = history.loc[history.date.le(origin)].copy()
    original = forecasting.forecast_series(history, forecasting.fit(forecasting.feature_rows(history)), origin, 28)
    needed = {name for name in methods if name.startswith("direct_")}
    if "blend_weekly" in methods:
        needed.add("direct_absolute")
    models = {name: fit_weekly(history, name == "direct_absolute") for name in sorted(needed)}
    output = {name: {} for name in methods}
    for key, group in history.groupby(forecasting.GRAIN, sort=True):
        group = group.sort_values("date")
        if len(group) < 56 or group.date.iloc[-1] != origin or group.tail(56).quantity_sold.isna().any():
            raise ValueError("Ineligible weekly series; do not silently change evaluation coverage")
        qty = group.quantity_sold.to_numpy(float)
        price = float(group.unit_price.iloc[-1])
        share = weekday_shares(group, origin)
        weeks = qty[-28:].reshape(4, 7).sum(axis=1)
        median = distribute(np.repeat(np.median(weeks), 4), share, origin)
        prepared = [features(qty, origin, horizon) for horizon in range(1, 5)]
        vectors = pd.DataFrame([row for row, _ in prepared], columns=FEATURES)
        for method in methods:
            if method == "original":
                pred = np.array(original[key][0])
            elif method == "weekly_naive":
                pred = np.array(original[key][1])
            elif method == "mean4":
                pred = distribute(np.repeat(weeks.mean(), 4), share, origin)
            elif method == "median4":
                pred = median
            elif method == "blend_median":
                pred = .5 * median + .5 * np.array(original[key][0])
            elif method == "blend_weekly":
                totals = np.maximum(models["direct_absolute"].predict(vectors), 0) * prepared[0][1]
                pred = .5 * distribute(totals, share, origin) + .5 * np.array(original[key][1])
            else:
                totals = np.maximum(models[method].predict(vectors), 0) * prepared[0][1]
                pred = distribute(totals, share, origin)
            output[method][key] = (pred, price)
    return output


def evaluate(frame, origin, methods=METHODS):
    predictions = projections(frame.loc[frame.date.le(origin)], origin, methods)
    rows = {method: [] for method in methods}
    for key, group in frame.groupby(forecasting.GRAIN, sort=True):
        future = group.loc[group.date.between(origin + pd.Timedelta(days=1), origin + pd.Timedelta(days=28))].sort_values("date")
        if len(future) != 28 or future.quantity_sold.isna().any():
            raise ValueError("Incomplete holdout")
        for method in methods:
            qty, price = predictions[method][key]
            rows[method].extend((str(origin.date()), "/".join(key), i, float(row.quantity_sold * row.unit_price), float(qty[i - 1] * price))
                                for i, row in enumerate(future.itertuples(), 1))
    return rows


def scores(rows):
    return {method: bulk.metrics(values) for method, values in rows.items()}


def choose_rules(earlier):
    """Selection on earlier folds only, not on the latest check or final test."""
    global_method = min(METHODS, key=lambda m: bulk.metrics(earlier[m])["weekly_wape"])
    choices = {}
    for sku in sorted({row[1] for row in earlier["original"]}):
        series = {m: [r for r in earlier[m] if r[1] == sku] for m in METHODS}
        candidate = min(METHODS, key=lambda m: bulk.metrics(series[m])["weekly_wape"])
        base_error = bulk.metrics(series[global_method])["weekly_wape"]
        candidate_error = bulk.metrics(series[candidate])["weekly_wape"]
        choices[sku] = candidate if candidate_error < .95 * base_error else global_method
    return {"global": {sku: global_method for sku in choices}, "per_series": choices}


def apply_rule(rows, choices):
    return [row for sku, method in sorted(choices.items()) for row in rows[method] if row[1] == sku]


def write(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def gate(result):
    candidate, original, naive = (result[k] for k in ["selected", "original", "weekly_naive"])
    return (candidate["weekly_wape"] <= min(original["weekly_wape"], naive["weekly_wape"]) - .02
            and candidate["sku_28day_wape"] <= original["sku_28day_wape"]
            and candidate["daily_wape"] <= original["daily_wape"] + .01)


def bootstrap_gain(selected, original):
    """Paired SKU bootstrap; preserve all within-SKU weeks and their dependence."""
    skus = sorted({r[1] for r in selected})
    triples = []
    for sku in skus:
        candidate = bulk.metrics([r for r in selected if r[1] == sku])
        base = bulk.metrics([r for r in original if r[1] == sku])
        triples.append([candidate["weekly_wape"] * candidate["actual"], base["weekly_wape"] * base["actual"], base["actual"]])
    values = np.array(triples)
    indices = np.random.default_rng(42).integers(0, len(skus), size=(2000, len(skus)))
    samples = values[indices].sum(axis=1)
    gains = (samples[:, 1] - samples[:, 0]) / samples[:, 2]
    return {"lower": float(np.quantile(gains, .025)), "upper": float(np.quantile(gains, .975)),
            "note": "95% paired SKU bootstrap of original minus selected weekly WAPE; same retailer, not independent stores"}


def confirm():
    if (OUT / "confirmation.json").exists():
        raise SystemExit("Confirmation already consumed; do not retune and relabel fresh")
    protocol = json.loads((OUT / "protocol.json").read_text())
    if protocol["weekly_code_sha256"] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise SystemExit("Implementation differs from frozen protocol")
    orders = pd.read_json(OUT / "confirmation_orders.jsonl", lines=True, dtype={"sku_id": str})
    frame = bulk.daily_frame(orders, protocol["confirmation_skus"], bulk.END)
    history = frame.loc[frame.date.le(bulk.ORIGIN)]
    folds = [evaluate(history, bulk.ORIGIN - pd.Timedelta(days=28 * fold)) for fold in (3, 2, 1)]
    earlier = {m: folds[0][m] + folds[1][m] for m in METHODS}
    choices = choose_rules(earlier)[protocol["rule"]]
    check = {"selected": bulk.metrics(apply_rule(folds[2], choices)),
             **{m: bulk.metrics(folds[2][m]) for m in ["original", "weekly_naive"]}}
    write("calibration.json", {"choices": choices, "metrics": check, "gate_passed": gate(check)})
    # Choices are persisted before final-period actuals are scored.
    rows = evaluate(frame, bulk.ORIGIN, list(dict.fromkeys(["original", "weekly_naive", *choices.values()])))
    selected = apply_rule(rows, choices)
    final = {"selected": bulk.metrics(selected), **{m: bulk.metrics(rows[m]) for m in ["original", "weekly_naive"]}}
    report = {"metrics": final, "calibration": check, "choices": choices,
              "promotion_gate_passed": gate(check) and gate(final),
              "weekly_gain_bootstrap": bootstrap_gain(selected, rows["original"]), "production_changed": False}
    write("confirmation.json", report)
    print(json.dumps(report), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["develop", "known", "confirm"])
    args = parser.parse_args()
    if args.phase == "confirm":
        confirm()
        return
    orders = pd.read_json(bulk.OUT / "orders.jsonl", lines=True, dtype={"sku_id": str})
    frame = bulk.daily_frame(orders, sorted(orders.sku_id.unique()), bulk.END)
    if args.phase == "develop":
        pooled = {m: [] for m in METHODS}
        folds, raw_folds = [], []
        for fold in (3, 2, 1):
            origin = bulk.ORIGIN - pd.Timedelta(days=28 * fold)
            rows = evaluate(frame.loc[frame.date.le(bulk.ORIGIN)], origin)
            raw_folds.append(rows)
            folds.append({"origin": str(origin.date()), "metrics": scores(rows)})
            for method, values in rows.items():
                pooled[method].extend(values)
            print(json.dumps(folds[-1]), flush=True)
        results = scores(pooled)
        challenger = min([m for m in METHODS if m not in ["original", "weekly_naive"]], key=lambda m: results[m]["weekly_wape"])
        early = {m: raw_folds[0][m] + raw_folds[1][m] for m in METHODS}
        rules = choose_rules(early)
        checks = {name: bulk.metrics(apply_rule(raw_folds[2], choices)) for name, choices in rules.items()}
        rule = min(checks, key=lambda name: checks[name]["weekly_wape"])
        result = {"selected": challenger, "metrics": results, "folds": folds,
                  "rules": rules, "rule_checks": checks, "selected_rule": rule,
                  "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  "selection_metric": "Per-SKU weekly revenue WAPE, not business total", "used_skus": sorted(orders.sku_id.unique())}
        write("development.json", result)
        print(json.dumps(result), flush=True)
    else:
        selection = json.loads((OUT / "development.json").read_text())
        rows = evaluate(frame, bulk.ORIGIN)
        result = {"status": "Previously inspected dates and SKUs, exploratory only", "metrics": scores(rows),
                  "rules": {name: bulk.metrics(apply_rule(rows, choices)) for name, choices in selection["rules"].items()}}
        write("known_period.json", result)
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
