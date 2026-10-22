"""Confirm a preselected challenger on 1-7 December 2011, beyond the app data."""
import json
from zipfile import ZipFile

import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor

from benchmark_direct_forecast import load_source
from benchmark_retail_ii import ARCHIVE
from app import forecasting


def future_rows(current):
    origin = current.date.max()
    if origin != pd.Timestamp("2011-11-30") or set(current.store_id) != {"UK_ONLINE"}:
        raise ValueError("This confirmation is only for the existing UCI demo ending 2011-11-30")
    with ZipFile(ARCHIVE) as zipped, zipped.open("online_retail_II.xlsx") as workbook:
        raw = pd.read_excel(workbook, sheet_name="Year 2010-2011",
                            usecols=["Invoice", "StockCode", "Quantity", "InvoiceDate", "Price", "Country"],
                            dtype={"Invoice": str, "StockCode": str})
    raw["date"] = pd.to_datetime(raw.InvoiceDate).dt.normalize()
    raw = raw.loc[raw.Country.eq("United Kingdom") & raw.StockCode.isin(set(current.sku_id))
                  & ~raw.Invoice.str.upper().str.startswith("C", na=True)
                  & raw.Quantity.gt(0) & raw.Price.gt(0)
                  & raw.date.between(origin + pd.Timedelta(days=1), origin + pd.Timedelta(days=7))].copy()
    raw["revenue"] = raw.Quantity * raw.Price * 40.0
    totals = raw.groupby(["StockCode", "date"]).revenue.sum()
    return {(row.sku_id, day): float(totals.get((row.sku_id, day), 0.))
            for row in current[["sku_id"]].drop_duplicates().itertuples()
            for day in pd.date_range(origin + pd.Timedelta(days=1), periods=7)}


def main():
    current = load_source("postgres")
    rows = forecasting.feature_rows(current)
    # Candidate/parameters frozen using earlier development, before reading this week.
    models = {"original": forecasting.fit(rows),
              "extra_trees": ExtraTreesRegressor(n_estimators=200, min_samples_leaf=5, max_features=.8, random_state=42, n_jobs=1).fit(rows[forecasting.FEATURES], rows.quantity_sold)}
    predictions = {name: forecasting.forecast_series(current, model, current.date.max(), 7) for name, model in models.items()}
    predictions["equal_blend"] = {key: ([(a + b) / 2 for a, b in zip(values[0], predictions["extra_trees"][key][0])],
                                        values[1], values[2]) for key, values in predictions["original"].items()}
    actual = future_rows(current)
    result = {}
    for name, series in predictions.items():
        error = total = predicted_total = 0.
        for key, (values, _, price) in series.items():
            for offset, value in enumerate(values, 1):
                observed = actual[(key[1], current.date.max() + pd.Timedelta(days=offset))]
                error += abs(observed - value * price)
                total += observed
                predicted_total += value * price
        result[name] = {"wape": error / total, "actual_total": total, "forecast_total": predicted_total,
                        "rows": len(series) * 7}
    print(json.dumps({"origin": "2011-11-30", "period": "2011-12-01/2011-12-07", "results": result}, indent=2))


if __name__ == "__main__":
    main()
