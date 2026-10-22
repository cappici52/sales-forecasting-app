"""Read-only transaction diagnosis and frozen regular/bulk demand experiment.

Prepare with bundled Python/pandas; develop/confirm with the backend ML runtime.
No app database or production artifact is read or written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "bulk_orders_2026-10-22"
ARCHIVE = ROOT / "backend/data/uploads/uci_online_retail_ii.zip"
START = pd.Timestamp("2011-04-05")
ORIGIN = pd.Timestamp("2011-11-02")
END = ORIGIN + pd.Timedelta(days=28)
DEVELOPMENT_SKUS = ["85099B", "85123A", "20725", "20727", "20728", "22423"]
EXCLUDE = set(DEVELOPMENT_SKUS + ["47566", "21621", "48138", "21843"])
METHODS = ["original", "weekly_naive", "split_rate", "split_xgboost"]


def invoice_orders(raw):
    """Aggregate split invoice lines before identifying unusually large orders."""
    sales = raw.copy()
    sales["date"] = pd.to_datetime(sales.InvoiceDate, errors="coerce").dt.normalize()
    sales["sku_id"] = sales.StockCode.astype(str).str.strip()
    sales["invoice"] = sales.Invoice.astype(str).str.strip()
    sales = sales.loc[
        sales.Country.eq("United Kingdom") & ~sales.invoice.str.upper().str.startswith("C")
        & sales.sku_id.str.fullmatch(r"\d{5}[A-Z]?")
        & sales.Quantity.gt(0) & sales.Price.gt(0) & sales.date.le(END)
    ].copy()
    sales["revenue"] = sales.Quantity * sales.Price * 40.0
    return sales.groupby(["sku_id", "date", "invoice"], as_index=False).agg(
        quantity=("Quantity", "sum"), revenue=("revenue", "sum"), lines=("Quantity", "size"))


def select_cohort(orders):
    # Selection sees no holdout outcomes. Require activity before START for price seeding.
    past = orders.loc[orders.date.le(ORIGIN) & ~orders.sku_id.isin(EXCLUDE)]
    stats = past.groupby("sku_id").agg(first=("date", "min"), last=("date", "max"))
    recent = past.loc[past.date.ge(START)].groupby("sku_id").agg(
        revenue=("revenue", "sum"), active=("date", "nunique"))
    stats = stats.join(recent).reset_index()
    eligible = stats.loc[stats["first"].le(START) & stats["last"].ge(ORIGIN - pd.Timedelta(days=7))
                         & stats.active.ge(100)]
    chosen = eligible.sort_values(["revenue", "sku_id"], ascending=[False, True]).head(12).sku_id.tolist()
    if len(chosen) != 12:
        raise ValueError("Need 12 previously unused eligible SKUs")
    return chosen


def thresholds(orders, origin):
    past = orders.loc[orders.date.between(START, origin)]
    return past.groupby("sku_id").quantity.quantile(.95).to_dict()


def daily_frame(orders, sku_ids, end, limits=None, component="total"):
    """A large invoice contributes its entire quantity to bulk, never disappears."""
    selected = orders.loc[orders.sku_id.isin(sku_ids) & orders.date.le(end)].copy()
    selected["bulk"] = selected.quantity.gt(selected.sku_id.map(limits or {}).fillna(np.inf))
    selected["target"] = selected.quantity
    if component != "total":
        selected["target"] = selected.quantity.where(selected.bulk.eq(component == "bulk"), 0)
    daily = selected.groupby(["sku_id", "date"]).agg(
        quantity_sold=("target", "sum"), total=("quantity", "sum"), revenue=("revenue", "sum"))
    daily["unit_price"] = daily.revenue / daily.total
    frames = []
    for sku in sku_ids:
        group = daily.loc[sku]
        # Seed only from known prices; never backward-fill a future price.
        calendar = pd.date_range(min(group.index.min(), START), end, name="date")
        group = group.reindex(calendar)
        group["quantity_sold"] = group.quantity_sold.fillna(0)
        # Match real_data_e2e's import precision, including XGBoost feature values.
        group["unit_price"] = group.unit_price.ffill().round(6)
        group = group.loc[START:]
        if group.unit_price.isna().any():
            raise ValueError(f"No initial price for {sku}")
        frames.append(group.assign(store_id="UK_ONLINE", sku_id=sku, channel="online").reset_index())
    return pd.concat(frames, ignore_index=True).sort_values(["store_id", "sku_id", "channel", "date"]).reset_index(drop=True)


def metrics(rows):
    """Rows: fold, SKU, day offset, actual revenue, predicted revenue."""
    frame = pd.DataFrame(rows, columns=["fold", "sku", "day", "actual", "predicted"])
    result = {}
    for width, label in [(1, "daily"), (7, "weekly"), (28, "sku_28day")]:
        grouped = frame.assign(bucket=(frame.day - 1) // width).groupby(
            ["fold", "sku", "bucket"])[["actual", "predicted"]].sum()
        denominator = grouped.actual.sum()
        result[label + "_wape"] = float(abs(grouped.actual - grouped.predicted).sum() / denominator) if denominator else None
    totals = frame.groupby("fold")[["actual", "predicted"]].sum()
    result["business_28day_wape"] = float(abs(totals.actual - totals.predicted).sum() / totals.actual.sum()) if totals.actual.sum() else None
    result.update(rows=len(frame), actual=float(frame.actual.sum()), predicted=float(frame.predicted.sum()))
    return result


def bulk_rate(group, origin):
    """56-day weekday occurrence probability times conditional mean size.

    Shrink weekday expectation halfway to overall expectation (fixed, not tuned).
    Equivalent to the mean of all days, including days with no bulk orders.
    """
    recent = group.loc[group.date.between(origin - pd.Timedelta(days=55), origin)]
    all_mean = float(recent.quantity_sold.mean())
    output = []
    for offset in range(1, 29):
        weekday = (origin + pd.Timedelta(days=offset)).dayofweek
        values = recent.loc[recent.date.dt.dayofweek.eq(weekday), "quantity_sold"]
        positives = values[values.gt(0)]
        expected = float(values.gt(0).mean() * positives.mean()) if len(positives) else 0.0
        output.append(.5 * expected + .5 * all_mean)
    return np.array(output)


def evaluate(orders, sku_ids, origin, methods):
    sys.path.insert(0, str(ROOT / "backend"))
    from app import forecasting

    history = daily_frame(orders, sku_ids, origin)
    original = forecasting.forecast_series(history, forecasting.fit(forecasting.feature_rows(history)), origin, 28)
    projections = {"original": {k: np.array(v[0]) for k, v in original.items()},
                   "weekly_naive": {k: np.array(v[1]) for k, v in original.items()}}
    limits = thresholds(orders.loc[orders.sku_id.isin(sku_ids)], origin)
    if any(method.startswith("split_") for method in methods):
        regular = daily_frame(orders, sku_ids, origin, limits, "regular")
        bulk = daily_frame(orders, sku_ids, origin, limits, "bulk")
        if not np.allclose(regular.quantity_sold + bulk.quantity_sold, history.quantity_sold):
            raise AssertionError("Components must reconstruct full demand")
        regular_predictions = forecasting.forecast_series(
            regular, forecasting.fit(forecasting.feature_rows(regular)), origin, 28)
        if "split_rate" in methods:
            projections["split_rate"] = {key: np.array(regular_predictions[key][0]) + bulk_rate(group, origin)
                                         for key, group in bulk.groupby(forecasting.GRAIN)}
        if "split_xgboost" in methods:
            bulk_predictions = forecasting.forecast_series(bulk, forecasting.fit(forecasting.feature_rows(bulk)), origin, 28)
            projections["split_xgboost"] = {key: np.array(regular_predictions[key][0]) + bulk_predictions[key][0]
                                            for key in original}
    # Actuals are accessed only after fitting and forecasting, and include ALL invoices.
    actuals = daily_frame(orders, sku_ids, origin + pd.Timedelta(days=28))
    rows = {method: [] for method in methods}
    details = []
    for key, group in actuals.groupby(forecasting.GRAIN):
        future = group.loc[group.date.gt(origin)].sort_values("date")
        if len(future) != 28 or key not in original:
            raise ValueError("Incomplete evaluation coverage")
        price = original[key][2]
        for offset, row in enumerate(future.itertuples(), 1):
            actual = row.quantity_sold * row.unit_price
            for method in methods:
                predicted = float(projections[method][key][offset - 1] * price)
                rows[method].append((str(origin.date()), key[1], offset, actual, predicted))
            details.append({"sku_id": key[1], "date": str(row.date.date()), "actual": actual,
                            "original": float(projections["original"][key][offset - 1] * price)})
    return rows, details


def diagnose(orders, details, origin):
    limits = thresholds(orders, origin)
    result = []
    for row in sorted(details, key=lambda r: abs(r["actual"] - r["original"]), reverse=True)[:10]:
        invoices = orders.loc[orders.sku_id.eq(row["sku_id"]) & orders.date.eq(pd.Timestamp(row["date"]))]
        qty = float(invoices.quantity.sum())
        big = invoices.loc[invoices.quantity.gt(limits[row["sku_id"]])]
        result.append({**row, "absolute_error": abs(row["actual"] - row["original"]),
                       "invoices": len(invoices), "quantity": qty, "bulk_threshold": limits[row["sku_id"]],
                       "largest_invoice_quantity": float(invoices.quantity.max()),
                       "largest_invoice_share": float(invoices.quantity.max() / qty) if qty else 0,
                       "bulk_quantity_share": float(big.quantity.sum() / qty) if qty else 0})
    return result


def write_json(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare", "develop", "confirm"])
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    data = OUT / "orders.jsonl"
    if args.phase == "prepare":
        if (OUT / "protocol.json").exists():
            raise SystemExit("Protocol already frozen; use existing prepared data")
        with ZipFile(ARCHIVE) as zipped:
            raw = pd.read_excel(zipped.open("online_retail_II.xlsx"), sheet_name="Year 2010-2011",
                                usecols=["Invoice", "StockCode", "Quantity", "InvoiceDate", "Price", "Country"])
        orders = invoice_orders(raw)
        cohort = select_cohort(orders)
        orders = orders.loc[orders.sku_id.isin(DEVELOPMENT_SKUS + cohort)]
        orders.to_json(data, orient="records", lines=True, date_format="iso")
        write_json("protocol.json", {
            "source": "UCI Online Retail II, Year 2010-2011", "source_sha256": hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(),
            "currency": "GBP x 40 demonstration units, not historic THB FX", "start": str(START.date()),
            "origin": str(ORIGIN.date()), "end": str(END.date()), "development_skus": DEVELOPMENT_SKUS,
            "confirmation_skus": cohort, "excluded_previously_used_skus": sorted(EXCLUDE),
            "threshold": "Per-SKU 95th percentile of training invoice quantities; strictly greater is bulk",
            "candidates": METHODS, "selection": "Lowest pooled daily revenue WAPE over three earlier 28-day folds",
            "promotion_gate": "Challenger must improve original daily WAPE by >=2 percentage points in development and confirmation; weekly and SKU-28-day WAPE must not regress; >=2/3 development folds must improve",
            "confirmation_limit": "Previously unused SKUs, same retailer and familiar period; not independent business or future-period proof",
        })
        print(json.dumps({"prepared_orders": len(orders), "confirmation_skus": cohort}))
        return
    protocol = json.loads((OUT / "protocol.json").read_text())
    orders = pd.read_json(data, lines=True, dtype={"sku_id": str, "invoice": str})
    orders["date"] = pd.to_datetime(orders.date)
    if args.phase == "develop":
        combined = {method: [] for method in METHODS}
        folds = []
        known = orders.loc[orders.sku_id.isin(DEVELOPMENT_SKUS)]
        for fold in (3, 2, 1):
            origin = ORIGIN - pd.Timedelta(days=fold * 28)
            rows, _ = evaluate(known, DEVELOPMENT_SKUS, origin, METHODS)
            folds.append({"origin": str(origin.date()), "metrics": {m: metrics(r) for m, r in rows.items()}})
            for method in METHODS:
                combined[method].extend(rows[method])
            print(json.dumps(folds[-1]), flush=True)
        scores = {m: metrics(r) for m, r in combined.items()}
        selected = min(["split_rate", "split_xgboost"], key=lambda m: scores[m]["daily_wape"])
        write_json("selection.json", {"selected_challenger": selected, "metrics": scores, "folds": folds,
                                      "experiment_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
        # Familiar final period is diagnostic only, never changes selected challenger.
        rows, details = evaluate(known, DEVELOPMENT_SKUS, ORIGIN, ["original", "weekly_naive", selected])
        write_json("known_period.json", {"metrics": {m: metrics(r) for m, r in rows.items()},
                                        "top_errors": diagnose(known, details, ORIGIN)})
        print(json.dumps({"selected": selected, "development": scores, "known_period": {m: metrics(r) for m, r in rows.items()}}))
    else:
        if (OUT / "confirmation.json").exists():
            raise SystemExit("Confirmation already inspected; do not retune and call it fresh")
        selection = json.loads((OUT / "selection.json").read_text())
        if selection["experiment_sha256"] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
            raise SystemExit("Experiment changed since selection; freeze and document a new protocol")
        selected = selection["selected_challenger"]
        cohort = protocol["confirmation_skus"]
        rows, _ = evaluate(orders.loc[orders.sku_id.isin(cohort)], cohort, ORIGIN, ["original", "weekly_naive", selected])
        scores = {m: metrics(r) for m, r in rows.items()}
        dev = selection["metrics"]
        wins = sum(f["metrics"][selected]["daily_wape"] < f["metrics"]["original"]["daily_wape"] for f in selection["folds"])
        gate = wins >= 2 and all(
            phase[selected]["daily_wape"] <= phase["original"]["daily_wape"] - .02
            and all(phase[selected][key] <= phase["original"][key] for key in ["weekly_wape", "sku_28day_wape"])
            for phase in [dev, scores])
        report = {"selected_challenger": selected, "metrics": scores, "promotion_gate_passed": gate,
                  "development_fold_wins": wins, "production_changed": False,
                  "per_sku": {m: {sku: metrics([r for r in records if r[1] == sku]) for sku in cohort} for m, records in rows.items()}}
        write_json("confirmation.json", report)
        print(json.dumps(report))


if __name__ == "__main__":
    main()
