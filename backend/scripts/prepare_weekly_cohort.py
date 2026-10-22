"""Read UCI workbook with bundled Python; freeze an unused 24-product cohort."""
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import benchmark_bulk_orders as bulk

OUT = bulk.ROOT / "outputs/weekly_direct_2026-10-22"


def select(orders, excluded):
    past = orders.loc[orders.date.le(bulk.ORIGIN) & ~orders.sku_id.isin(excluded)]
    stats = past.groupby("sku_id").agg(first=("date", "min"), last=("date", "max"))
    recent = past.loc[past.date.ge(bulk.START)].groupby("sku_id").agg(
        revenue=("revenue", "sum"), active=("date", "nunique"))
    eligible = stats.join(recent).reset_index()
    eligible = eligible.loc[eligible["first"].le(bulk.START)
                            & eligible["last"].ge(bulk.ORIGIN - pd.Timedelta(days=7)) & eligible.active.ge(100)]
    chosen = eligible.sort_values(["revenue", "sku_id"], ascending=[False, True]).head(24).sku_id.tolist()
    if len(chosen) != 24:
        raise ValueError("Need 24 unused eligible SKUs")
    return chosen


def main():
    path = OUT / "protocol.json"
    if path.exists():
        raise SystemExit("Cohort already frozen; preserve it")
    development = json.loads((OUT / "development.json").read_text())
    excluded = sorted(set(development["used_skus"]) | bulk.EXCLUDE)
    with ZipFile(bulk.ARCHIVE) as zipped:
        raw = pd.read_excel(zipped.open("online_retail_II.xlsx"), sheet_name="Year 2010-2011",
                            usecols=["Invoice", "StockCode", "Quantity", "InvoiceDate", "Price", "Country"])
    orders = bulk.invoice_orders(raw)
    chosen = select(orders, excluded)
    orders.loc[orders.sku_id.isin(chosen)].to_json(OUT / "confirmation_orders.jsonl", orient="records", lines=True, date_format="iso")
    result = {"source_sha256": hashlib.sha256(bulk.ARCHIVE.read_bytes()).hexdigest(),
              "excluded_skus": excluded, "confirmation_skus": chosen,
              "rule": development["selected_rule"], "weekly_code_sha256": hashlib.sha256((Path(__file__).parent / "benchmark_weekly_direct.py").read_bytes()).hexdigest(),
              "selection": "Top pre-cutoff revenue, >=100 active training days, initial price and recent sale",
              "limits": "New SKUs, same retailer and familiar dates, not independent future-period confirmation",
              "gate": "At least 2pp weekly WAPE improvement over both original and weekly-naive; no SKU-28-day regression versus original; daily <= original +1pp; same conditions on latest calibration fold and final test"}
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"cohort": chosen, "rule": result["rule"]}))


if __name__ == "__main__":
    main()
