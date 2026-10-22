"""Test adding earlier same-retailer observations without changing app sales."""
import argparse
import json
from zipfile import ZipFile

import numpy as np
import pandas as pd

from benchmark_direct_forecast import load_source, evaluate, scores
from benchmark_retail_ii import ARCHIVE
from app import forecasting


def extend_history(current):
    if set(current.store_id) != {"UK_ONLINE"} or set(current.channel) != {"online"} or current.date.min() != pd.Timestamp("2011-04-05"):
        raise ValueError("Historical extension is only for the known UCI demo, not arbitrary business data")
    cutoff = current.date.min()
    sku_ids = set(current.sku_id)
    chunks = []
    with ZipFile(ARCHIVE) as zipped:
        for sheet in ("Year 2009-2010", "Year 2010-2011"):
            with zipped.open("online_retail_II.xlsx") as workbook:
                data = pd.read_excel(workbook, sheet_name=sheet,
                                     usecols=["Invoice", "StockCode", "Quantity", "InvoiceDate", "Price", "Country"],
                                     dtype={"Invoice": str, "StockCode": str})
            data["date"] = pd.to_datetime(data.InvoiceDate).dt.normalize()
            data = data.loc[data.Country.eq("United Kingdom") & data.StockCode.isin(sku_ids)
                            & ~data.Invoice.str.upper().str.startswith("C", na=True)
                            & data.Quantity.gt(0) & data.Price.gt(0) & data.date.lt(cutoff)]
            chunks.append(data)
    # The two sheets overlap in December 2010; keep the first year's coverage
    # through 2010-11-30 and the second from 2010-12-01 onward.
    old = pd.concat([chunks[0].loc[chunks[0].date.lt("2010-12-01")],
                     chunks[1].loc[chunks[1].date.ge("2010-12-01")]], ignore_index=True)
    old["revenue"] = old.Quantity * old.Price
    daily = old.groupby(["StockCode", "date"]).agg(quantity_sold=("Quantity", "sum"), revenue=("revenue", "sum"))
    additions = []
    for key, group in current.groupby(forecasting.GRAIN):
        sku = key[1]
        if sku not in daily.index.get_level_values(0):
            continue
        history = daily.loc[sku].sort_index()
        history = history.reindex(pd.date_range(history.index.min(), cutoff - pd.Timedelta(days=1), name="date"))
        history["unit_price"] = (history.revenue / history.quantity_sold).ffill() * 40.0
        history["quantity_sold"] = history.quantity_sold.fillna(0)
        for column, value in zip(forecasting.GRAIN, key):
            history[column] = value
        additions.append(history.reset_index()[current.columns])
    return pd.concat([*additions, current], ignore_index=True).sort_values(forecasting.GRAIN + ["date"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdout", action="store_true")
    args = parser.parse_args()
    current = load_source("postgres")
    extended = extend_history(current)
    end = current.date.max() - pd.Timedelta(days=28)
    origins = [end] if args.holdout else [end - pd.Timedelta(days=28 * fold) for fold in (3, 2, 1)]
    combined = {name: [] for name in ("current", "extended", "direct_log_extended")}
    fold_scores = []
    for origin in origins:
        old = evaluate(current, origin, ())
        new = evaluate(extended, origin, ("log",))
        values = {"current": old["original"], "extended": new["original"], "direct_log_extended": new["log"]}
        fold_scores.append({"origin": str(origin.date()), "wape28": {name: scores(rows, 28) for name, rows in values.items()}})
        for name, rows in values.items():
            combined[name].extend(rows)
    print(json.dumps({"first_date": str(extended.date.min().date()), "current_rows": len(current),
                      "extended_rows": len(extended), "phase": "holdout" if args.holdout else "development",
                      "folds": fold_scores,
                      "wape": {days: {name: scores(rows, days) for name, rows in combined.items()} for days in (7, 14, 28)}}, indent=2))


if __name__ == "__main__":
    main()
