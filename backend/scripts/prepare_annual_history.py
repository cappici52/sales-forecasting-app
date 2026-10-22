"""Extract two-year public daily history with bundled pandas; never import to DB."""
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import benchmark_bulk_orders as bulk

OUT = bulk.ROOT / "outputs/annual_forecast_2026-10-22"


def main():
    if (OUT / "series.jsonl").exists():
        raise SystemExit("Prepared history already exists")
    used = json.loads((bulk.ROOT / "outputs/weekly_revenue_2026-10-22/development.json").read_text())["used_skus"]
    excluded = set(used) | bulk.EXCLUDE
    parts = []
    with ZipFile(bulk.ARCHIVE) as zipped:
        for sheet in ["Year 2009-2010", "Year 2010-2011"]:
            raw = pd.read_excel(zipped.open("online_retail_II.xlsx"), sheet_name=sheet,
                                usecols=["Invoice", "StockCode", "Quantity", "InvoiceDate", "Price", "Country"])
            orders = bulk.invoice_orders(raw)
            orders = orders.loc[orders.date.lt("2010-12-01") if sheet == "Year 2009-2010" else orders.date.ge("2010-12-01")]
            parts.append(orders)
    orders = pd.concat(parts, ignore_index=True)
    past = orders.loc[orders.date.le(bulk.ORIGIN) & ~orders.sku_id.isin(excluded)]
    stats = past.groupby("sku_id").agg(first=("date", "min"))
    recent = past.loc[past.date.ge(bulk.START)].groupby("sku_id").agg(
        revenue=("revenue", "sum"), active=("date", "nunique"), last=("date", "max"))
    eligible = stats.join(recent).reset_index()
    eligible = eligible.loc[eligible["first"].le("2010-04-05") & eligible.active.ge(100)
                            & eligible["last"].ge(bulk.ORIGIN - pd.Timedelta(days=7))]
    cohort = eligible.sort_values(["revenue", "sku_id"], ascending=[False, True]).head(24).sku_id.tolist()
    if len(cohort) != 24:
        raise ValueError("Need 24 unused products with prior-year history")
    daily = orders.loc[orders.sku_id.isin(used + cohort)].groupby(["sku_id", "date"]).agg(
        quantity_sold=("quantity", "sum"), revenue=("revenue", "sum"))
    result = []
    for sku in sorted(used + cohort):
        group = daily.loc[sku]
        group["unit_price"] = group.revenue / group.quantity_sold
        group = group.reindex(pd.date_range(group.index.min(), bulk.END, name="date"))
        group["quantity_sold"] = group.quantity_sold.fillna(0)
        group["unit_price"] = group.unit_price.ffill().round(6)
        result.append(group.assign(store_id="UK_ONLINE", sku_id=sku, channel="online").reset_index())
    OUT.mkdir(parents=True, exist_ok=True)
    pd.concat(result, ignore_index=True).to_json(OUT / "series.jsonl", orient="records", lines=True, date_format="iso")
    manifest = {"source_sha256": hashlib.sha256(bulk.ARCHIVE.read_bytes()).hexdigest(), "development_skus": used,
                "confirmation_skus": cohort, "excluded_skus": sorted(excluded), "overlap_rule": "First sheet before 2010-12-01, second on/after",
                "cohort_selection": "Training-only revenue/activity; first sale by 2010-04-05; last sale within seven days; >=100 active days since 2011-04-05"}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"daily_rows": sum(len(r) for r in result), "confirmation_skus": cohort}))


if __name__ == "__main__":
    main()
