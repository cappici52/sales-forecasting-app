"""Read-only 28-day benchmark on Rossmann's public store-level sales history.

The source CSV is from the Rossmann Store Sales competition. Put train.csv at
backend/data/uploads/rossmann_train.csv; raw competition data is gitignored.
Sales is store-level revenue, not units, so this is a transfer stress test only.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import forecasting
from scripts import benchmark_olist


DATA = Path(__file__).resolve().parents[1] / "data" / "uploads" / "rossmann_train.csv"
START = pd.Timestamp("2014-07-01")
TRAIN_END = pd.Timestamp("2015-07-03")
TEST_END = TRAIN_END + pd.Timedelta(days=28)


def prepare_sales(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str], dict]:
    sales = raw.copy()
    sales["date"] = pd.to_datetime(sales.Date, errors="raise").dt.normalize()
    sales = sales.loc[sales.date.between(START, TEST_END)].copy()
    if sales.duplicated(["Store", "date"]).any():
        raise ValueError("Duplicate store/date in Rossmann data")
    if sales.Sales.lt(0).any():
        raise ValueError("Negative sales in Rossmann data")
    training = sales.loc[sales.date.le(TRAIN_END)]
    calendar = pd.date_range(START, TEST_END, freq="D", name="date")
    required_training_days = (TRAIN_END - START).days + 1
    candidates = training.groupby("Store").agg(
        days=("date", "nunique"), revenue=("Sales", "sum"),
    )
    store_ids = candidates.loc[candidates.days.eq(required_training_days)].sort_values(
        "revenue", ascending=False).head(6).index.tolist()
    if len(store_ids) != 6:
        raise ValueError("Need six stores with complete pre-holdout daily history")
    series = []
    for store_id in store_ids:
        group = sales.loc[sales.Store.eq(store_id)].set_index("date").reindex(calendar)
        if group.Sales.isna().any():
            raise ValueError(f"Store {store_id} has missing dates; do not treat them as zero sales")
        group["store_id"] = str(store_id)
        group["sku_id"] = "all-products"
        group["channel"] = "store"
        group["quantity_sold"] = group.Sales.astype(float)
        group["unit_price"] = 1.0
        series.append(group.reset_index()[forecasting.GRAIN + ["date", "quantity_sold", "unit_price"]])
    selected = sales.loc[sales.Store.isin(store_ids) & sales.date.gt(TRAIN_END)]
    diagnostics = {
        "holdout_closed_store_days": int(selected.Open.eq(0).sum()),
        "holdout_promotion_store_days": int(selected.Promo.eq(1).sum()),
    }
    frame = pd.concat(series, ignore_index=True).sort_values(forecasting.GRAIN + ["date"])
    return frame, [str(value) for value in store_ids], diagnostics


def load_frame(path: Path = DATA) -> tuple[pd.DataFrame, list[str], dict]:
    raw = pd.read_csv(path, usecols=["Store", "Date", "Sales", "Open", "Promo"])
    return prepare_sales(raw)


def main() -> None:
    frame, store_ids, diagnostics = load_frame()
    results = []
    for method in benchmark_olist.METHODS:
        validation = []
        for fold in (3, 2, 1):
            origin = TRAIN_END - pd.Timedelta(days=28 * fold)
            validation.extend(benchmark_olist.evaluate(frame.loc[frame.date.le(TRAIN_END)], origin, method))
        holdout = benchmark_olist.evaluate(frame, TRAIN_END, method)
        results.append({
            "method": method,
            "validation_revenue_wape": benchmark_olist.wape(validation, 2, 3),
            "holdout_revenue_wape": benchmark_olist.wape(holdout, 2, 3),
            "validation_rows": len(validation), "holdout_rows": len(holdout),
        })
    print(json.dumps({
        "source": "Rossmann Store Sales (German retailer)",
        "grain": "store-day revenue; no units or item prices available",
        "store_ids": store_ids, "start": str(START.date()),
        "train_end": str(TRAIN_END.date()), "holdout_end": str(TEST_END.date()),
        "zero_sale_days": int(frame.quantity_sold.eq(0).sum()),
        "selection": "Top six training revenue stores with complete training dates",
        **diagnostics, "results": results,
    }, indent=2))


if __name__ == "__main__":
    main()
