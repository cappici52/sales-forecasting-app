"""Compare direct revenue targets, retaining quantity forecasting as a separate task."""
import json
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import benchmark_bulk_orders as bulk, benchmark_weekly_direct as weekly

OUT = bulk.ROOT / "outputs/weekly_revenue_2026-10-22"
METHODS = ["original", "weekly_naive", "revenue_daily", "revenue_naive", "revenue_mean4", "revenue_median4",
           "revenue_direct_absolute", "revenue_direct_poisson", "revenue_blend", "revenue_blend_weekly"]


def evaluate(frame, origin):
    history = frame.loc[frame.date.le(origin)].copy()
    original = weekly.projections(history, origin, ["original", "weekly_naive"])
    revenue = history.copy()
    revenue["quantity_sold"] = revenue.quantity_sold * revenue.unit_price
    revenue["unit_price"] = 1.
    pred = weekly.projections(revenue, origin, ["original", "weekly_naive", "mean4", "median4", "direct_absolute", "direct_poisson"])
    mapping = {"revenue_daily": "original", "revenue_naive": "weekly_naive", "revenue_mean4": "mean4", "revenue_median4": "median4",
               "revenue_direct_absolute": "direct_absolute", "revenue_direct_poisson": "direct_poisson"}
    projections = {m: {k: q * p for k, (q, p) in v.items()} for m, v in original.items()}
    projections.update({name: {k: q for k, (q, _) in pred[method].items()} for name, method in mapping.items()})
    projections["revenue_blend"] = {k: .5 * projections["original"][k] + .5 * projections["revenue_direct_absolute"][k] for k in projections["original"]}
    projections["revenue_blend_weekly"] = {k: .5 * projections["revenue_naive"][k] + .5 * projections["revenue_direct_absolute"][k] for k in projections["original"]}
    rows = {m: [] for m in METHODS}
    for key, group in frame.groupby(weekly.forecasting.GRAIN):
        future = group.loc[group.date.between(origin + pd.Timedelta(days=1), origin + pd.Timedelta(days=28))].sort_values("date")
        if len(future) != 28 or future.quantity_sold.isna().any():
            raise ValueError("Incomplete holdout")
        for m in METHODS:
            rows[m].extend((str(origin.date()), "/".join(key), i, float(r.quantity_sold * r.unit_price), float(projections[m][key][i - 1]))
                           for i, r in enumerate(future.itertuples(), 1))
    return rows


def main():
    sources = [bulk.OUT / "orders.jsonl", weekly.OUT / "confirmation_orders.jsonl"]
    orders = pd.concat([pd.read_json(p, lines=True, dtype={"sku_id": str}) for p in sources], ignore_index=True)
    frame = bulk.daily_frame(orders, sorted(orders.sku_id.unique()), bulk.END)
    pooled = {m: [] for m in METHODS}
    folds = []
    for fold in (3, 2, 1):
        rows = evaluate(frame.loc[frame.date.le(bulk.ORIGIN)], bulk.ORIGIN - pd.Timedelta(days=28 * fold))
        scores = weekly.scores(rows)
        folds.append(scores)
        for m in METHODS:
            pooled[m].extend(rows[m])
        print(json.dumps({"fold": fold, "metrics": scores}), flush=True)
    scores = weekly.scores(pooled)
    selected = min(METHODS, key=lambda m: sum(scores[m][k] for k in ["daily_wape", "weekly_wape", "sku_28day_wape"]))
    result = {"selected": selected, "development": scores, "folds": folds, "used_skus": sorted(orders.sku_id.unique())}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "development.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"selected": selected, "metrics": scores}), flush=True)


if __name__ == "__main__":
    main()
