"""Independent, read-only 28-day benchmark on Olist order history.

Download the three CSVs named below from https://github.com/olist/work-at-olist-data/tree/master/datasets
into backend/data/uploads/olist_benchmark/ before running. Raw data is gitignored.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import forecasting


DATA = Path(__file__).resolve().parents[1] / "data" / "uploads" / "olist_benchmark"
START = pd.Timestamp("2017-03-01")
TRAIN_END = pd.Timestamp("2018-06-30")
TEST_END = TRAIN_END + pd.Timedelta(days=28)
METHODS = ("poisson_xgb", "weekly_naive", "weekday_4week_mean", "last_28_mean")


def load_frame(data_dir: Path = DATA) -> tuple[pd.DataFrame, list[str]]:
    orders = pd.read_csv(data_dir / "olist_orders_dataset.csv", usecols=[
        "order_id", "order_status", "order_purchase_timestamp"])
    items = pd.read_csv(data_dir / "olist_order_items_dataset.csv", usecols=[
        "order_id", "product_id", "price"])
    products = pd.read_csv(data_dir / "olist_products_dataset.csv", usecols=[
        "product_id", "product_category_name"])
    orders["date"] = pd.to_datetime(orders.order_purchase_timestamp, errors="raise").dt.normalize()
    sales = items.merge(orders, on="order_id", validate="many_to_one").merge(
        products, on="product_id", validate="many_to_one")
    sales = sales.loc[
        sales.order_status.eq("delivered")
        & sales.date.between(START, TEST_END)
        & sales.product_category_name.notna()
        & sales.price.gt(0)
    ]
    # Choose the six busiest categories using training dates only, never the holdout.
    categories = (sales.loc[sales.date.le(TRAIN_END), "product_category_name"]
                  .value_counts().head(6).index.tolist())
    sales = sales.loc[sales.product_category_name.isin(categories)]
    daily = sales.groupby(["product_category_name", "date"], as_index=False).agg(
        quantity_sold=("price", "size"), revenue=("price", "sum"))
    daily["unit_price"] = daily.revenue / daily.quantity_sold
    calendar = pd.date_range(START, TEST_END, freq="D", name="date")
    series = []
    for category in categories:
        group = daily.loc[daily.product_category_name.eq(category)].set_index("date")
        group = group.reindex(calendar)
        group["quantity_sold"] = group.quantity_sold.fillna(0)
        group["unit_price"] = group.unit_price.ffill()
        if group.unit_price.isna().any():
            raise ValueError(f"No starting price for {category}; choose a later START date")
        group["store_id"] = "olist"
        group["sku_id"] = category  # Category proxy; the dataset has sparse individual products.
        group["channel"] = "ecommerce"
        series.append(group.reset_index()[forecasting.GRAIN + ["date", "quantity_sold", "unit_price"]])
    frame = pd.concat(series, ignore_index=True).sort_values(forecasting.GRAIN + ["date"])
    return frame, categories


def project(frame: pd.DataFrame, origin: pd.Timestamp, method: str) -> dict:
    history = frame.loc[frame.date.le(origin)]
    if method == "poisson_xgb":
        model = forecasting.fit(forecasting.feature_rows(history))
        return {key: (values[0], values[2]) for key, values in
                forecasting.forecast_series(history, model, origin, 28).items()}
    result = {}
    for key, group in history.groupby(forecasting.GRAIN, sort=False):
        recent = group.sort_values("date").tail(28)
        if len(recent) != 28 or recent.date.iloc[-1] != origin:
            continue
        values = recent.quantity_sold.to_numpy(dtype=float)
        if method == "weekly_naive":
            prediction = np.tile(values[-7:], 4)
        elif method == "weekday_4week_mean":
            prediction = np.tile(np.mean(values.reshape(4, 7), axis=0), 4)
        elif method == "last_28_mean":
            prediction = np.full(28, values.mean())
        else:
            raise ValueError(method)
        result[key] = (prediction, float(recent.unit_price.iloc[-1]))
    return result


def evaluate(frame: pd.DataFrame, origin: pd.Timestamp, method: str) -> list[tuple[float, float, float, float]]:
    actual = {(row.store_id, row.sku_id, row.channel, row.date): row for row in frame.itertuples()}
    rows = []
    for key, (prediction, price) in project(frame, origin, method).items():
        for offset, quantity in enumerate(prediction, start=1):
            row = actual.get((*key, origin + pd.Timedelta(days=offset)))
            if row is not None:
                rows.append((float(row.quantity_sold), float(quantity),
                             float(row.quantity_sold * row.unit_price), float(quantity * price)))
    return rows


def wape(rows: list[tuple], actual_index: int, predicted_index: int) -> float:
    values = np.asarray(rows)
    denominator = values[:, actual_index].sum()
    return round(float(np.abs(values[:, actual_index] - values[:, predicted_index]).sum() / denominator), 4)


def main() -> None:
    frame, categories = load_frame()
    results = []
    for method in METHODS:
        validation = []
        for fold in (3, 2, 1):
            origin = TRAIN_END - pd.Timedelta(days=28 * fold)
            validation.extend(evaluate(frame.loc[frame.date.le(TRAIN_END)], origin, method))
        holdout = evaluate(frame, TRAIN_END, method)
        results.append({
            "method": method,
            "validation_unit_wape": wape(validation, 0, 1),
            "holdout_unit_wape": wape(holdout, 0, 1),
            "validation_revenue_wape": wape(validation, 2, 3),
            "holdout_revenue_wape": wape(holdout, 2, 3),
            "validation_rows": len(validation), "holdout_rows": len(holdout),
        })
    print(json.dumps({"source": "Olist public e-commerce data", "grain": "daily category proxy",
                      "categories": categories, "start": str(START.date()),
                      "train_end": str(TRAIN_END.date()), "holdout_end": str(TEST_END.date()),
                      "validation_folds": 3, "horizon_days": 28,
                      "zero_sale_days": int(frame.quantity_sold.eq(0).sum()),
                      "results": results}, indent=2))


if __name__ == "__main__":
    main()
