"""Read-only, pre-specified 28-day benchmark on UCI Online Retail II (2009-2010).

Download the UCI archive to ``backend/data/uploads/uci_online_retail_ii.zip``.
This benchmark uses only the first workbook sheet and never writes to the app DB.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from zipfile import ZipFile

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import forecasting
from scripts import benchmark_olist


ARCHIVE = Path(__file__).resolve().parents[1] / "data" / "uploads" / "uci_online_retail_ii.zip"
START = pd.Timestamp("2010-01-04")
TRAIN_END = pd.Timestamp("2010-10-31")
TEST_END = TRAIN_END + pd.Timedelta(days=28)
METHODS = benchmark_olist.METHODS


def prepare_transactions(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Build six dense daily series; all SKU selection uses pre-holdout rows."""
    sales = raw.copy()
    sales["date"] = pd.to_datetime(sales.InvoiceDate, errors="coerce").dt.normalize()
    sales["sku_id"] = sales.StockCode.astype(str).str.strip()
    sales = sales.loc[
        sales.Country.eq("United Kingdom")
        & ~sales.Invoice.astype(str).str.upper().str.startswith("C")
        & sales.sku_id.str.fullmatch(r"\d{5}[A-Z]?")
        & sales.Quantity.gt(0)
        & sales.Price.gt(0)
        & sales.date.between(START, TEST_END)
    ].copy()
    sales["revenue"] = sales.Quantity * sales.Price
    training = sales.loc[sales.date.le(TRAIN_END)]
    candidates = training.groupby("sku_id").agg(
        revenue=("revenue", "sum"), active_days=("date", "nunique"),
        first=("date", "min"), last=("date", "max"),
    )
    candidates = candidates.loc[
        candidates.active_days.ge(100)
        & candidates["first"].le(START)
        & candidates["last"].ge(TRAIN_END - pd.Timedelta(days=7))
    ]
    sku_ids = candidates.sort_values("revenue", ascending=False).head(6).index.tolist()
    if len(sku_ids) != 6:
        raise ValueError("Need six sufficiently active SKUs with a price on the start date")
    daily = sales.loc[sales.sku_id.isin(sku_ids)].groupby(["sku_id", "date"]).agg(
        quantity_sold=("Quantity", "sum"), revenue=("revenue", "sum"),
    )
    daily["unit_price"] = daily.revenue / daily.quantity_sold
    calendar = pd.date_range(START, TEST_END, freq="D", name="date")
    series = []
    for sku_id in sku_ids:
        group = daily.loc[sku_id].reindex(calendar)
        group["quantity_sold"] = group.quantity_sold.fillna(0)
        group["unit_price"] = group.unit_price.ffill()
        if group.unit_price.isna().any():
            raise ValueError(f"Missing initial price for {sku_id}")
        group["store_id"] = "uci-uk"
        group["sku_id"] = sku_id
        group["channel"] = "retail"
        series.append(group.reset_index()[forecasting.GRAIN + ["date", "quantity_sold", "unit_price"]])
    frame = pd.concat(series, ignore_index=True).sort_values(forecasting.GRAIN + ["date"])
    return frame, sku_ids


def load_frame(archive: Path = ARCHIVE) -> tuple[pd.DataFrame, list[str]]:
    with ZipFile(archive) as zipped:
        raw = pd.read_excel(
            zipped.open("online_retail_II.xlsx"), sheet_name="Year 2009-2010",
            usecols=["Invoice", "StockCode", "Quantity", "InvoiceDate", "Price", "Country"],
        )
    return prepare_transactions(raw)


def main() -> None:
    frame, sku_ids = load_frame()
    results = []
    for method in METHODS:
        validation = []
        for fold in (3, 2, 1):
            origin = TRAIN_END - pd.Timedelta(days=28 * fold)
            validation.extend(benchmark_olist.evaluate(frame.loc[frame.date.le(TRAIN_END)], origin, method))
        holdout = benchmark_olist.evaluate(frame, TRAIN_END, method)
        results.append({
            "method": method,
            "validation_unit_wape": benchmark_olist.wape(validation, 0, 1),
            "holdout_unit_wape": benchmark_olist.wape(holdout, 0, 1),
            "validation_revenue_wape": benchmark_olist.wape(validation, 2, 3),
            "holdout_revenue_wape": benchmark_olist.wape(holdout, 2, 3),
            "holdout_revenue_wape_with_actual_future_price_diagnostic": benchmark_olist.wape(holdout, 2, 4),
            "holdout_revenue_wape_with_actual_future_units_diagnostic": benchmark_olist.wape(holdout, 2, 5),
            "validation_rows": len(validation), "holdout_rows": len(holdout),
        })
    print(json.dumps({
        "source": "UCI Online Retail II, 2009-2010 sheet", "currency": "GBP",
        "sku_ids": sku_ids, "start": str(START.date()),
        "train_end": str(TRAIN_END.date()), "holdout_end": str(TEST_END.date()),
        "zero_sale_days": int(frame.quantity_sold.eq(0).sum()),
        "selection": "Top training revenue among UK SKUs active >=100 days, first seen on start date, recent sale",
        "results": results,
    }, indent=2))


if __name__ == "__main__":
    main()
