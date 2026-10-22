"""Frozen M5 product/store forecast check; never writes to the application DB."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import benchmark_weekly_direct as weekly


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "backend/data/uploads/m5_benchmark"
OUT = ROOT / "outputs/m5_benchmark_2026-10-22"
SALES = SOURCE / "sales_train_evaluation.csv"
PRICES = SOURCE / "sell_prices.csv"
CALENDAR = SOURCE / "calendar.csv"
TRAIN_END = 1913
FINAL_END = 1941
FIRST_DAY = 1400
METHODS = ["original", "weekly_naive", "mean4", "direct_absolute"]


def md5(path):
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def select_pairs():
    """Select by unit sales and active days that end before the reserved 28 days."""
    columns = ["store_id", "item_id", "cat_id"] + [f"d_{day}" for day in range(1549, TRAIN_END + 1)]
    sales = pd.read_csv(SALES, usecols=columns)
    values = sales[columns[3:]]
    sales = sales[["store_id", "item_id", "cat_id"]].assign(
        units=values.sum(axis=1).to_numpy(), active=values.gt(0).sum(axis=1).to_numpy())
    sales = sales.loc[sales.active.ge(180)].sort_values(
        ["store_id", "cat_id", "units", "item_id"], ascending=[True, True, False, True])
    selected = sales.groupby(["store_id", "cat_id"], sort=True).head(2)
    if selected.groupby(["store_id", "cat_id"]).ngroups != 30 or len(selected) != 60:
        raise ValueError("Expected two established products in each category and store")
    return selected[["store_id", "item_id"]].to_dict("records")


def load_frame(pairs, last_day):
    identifiers = {(pair["store_id"], pair["item_id"]) for pair in pairs}
    days = [f"d_{day}" for day in range(FIRST_DAY, last_day + 1)]
    sales = pd.read_csv(SALES, usecols=["store_id", "item_id", *days])
    sales = sales.loc[[tuple(row) in identifiers for row in sales[["store_id", "item_id"]].itertuples(index=False, name=None)]]
    if len(sales) != len(identifiers):
        raise ValueError("Selected product/store series are missing")
    daily = sales.melt(id_vars=["store_id", "item_id"], value_vars=days,
                       var_name="d", value_name="quantity_sold")
    calendar = pd.read_csv(CALENDAR, usecols=["d", "date", "wm_yr_wk"])
    daily = daily.merge(calendar, on="d", how="left", validate="many_to_one")
    if daily.date.isna().any():
        raise ValueError("Calendar is incomplete")
    prices = []
    for chunk in pd.read_csv(PRICES, chunksize=250_000):
        match = [tuple(row) in identifiers for row in chunk[["store_id", "item_id"]].itertuples(index=False, name=None)]
        if any(match):
            prices.append(chunk.loc[match])
    daily = daily.merge(pd.concat(prices), on=["store_id", "item_id", "wm_yr_wk"],
                        how="left", validate="many_to_one")
    daily["day_number"] = daily.d.str[2:].astype(int)
    daily = daily.sort_values(["store_id", "item_id", "day_number"])
    daily["sell_price"] = daily.groupby(["store_id", "item_id"]).sell_price.ffill()
    daily = daily.rename(columns={"item_id": "sku_id", "sell_price": "unit_price"})
    daily["date"] = pd.to_datetime(daily.date)
    daily["channel"] = "in_store"
    # A positive sale without its contemporaneous price cannot be evaluated as revenue.
    if daily.loc[daily.quantity_sold.gt(0), "unit_price"].isna().any():
        raise ValueError("Positive unit sales without a known price")
    daily = daily.dropna(subset=["unit_price"])
    return daily[["date", "store_id", "sku_id", "channel", "quantity_sold", "unit_price"]].reset_index(drop=True)


def write(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, indent=2), encoding="utf-8")


def evaluate_development(frame):
    result = {method: [] for method in METHODS}
    folds = []
    last = frame.date.max()
    for prior in (3, 2, 1):
        origin = last - pd.Timedelta(days=28 * prior)
        rows = weekly.evaluate(frame, origin, METHODS)
        folds.append({"origin": str(origin.date()), "metrics": weekly.scores(rows)})
        for method in METHODS:
            result[method].extend(rows[method])
        print(json.dumps({"origin": str(origin.date()), "metrics": folds[-1]["metrics"]}), flush=True)
    metrics = weekly.scores(result)
    selected = min(METHODS, key=lambda method: metrics[method]["weekly_wape"] + metrics[method]["sku_28day_wape"])
    return {"selected": selected, "metrics": metrics, "folds": folds}


def develop():
    if (OUT / "protocol.json").exists():
        raise SystemExit("Protocol already frozen")
    hashes = {path.name: md5(path) for path in (CALENDAR, SALES, PRICES)}
    expected = {"calendar.csv": "3ffeab2991b0c8e861d008b39ea4c95c",
                "sales_train_evaluation.csv": "b806dfc9f30a745102b708c09951f6aa",
                "sell_prices.csv": "08c591caa99e55daf3e0ccac913f7c85"}
    if hashes != expected:
        raise ValueError("Downloaded M5 files differ from the published checksums")
    pairs = select_pairs()
    write("cohort.json", {"pairs": pairs, "source_md5": hashes, "train_end": TRAIN_END,
                          "selection": "Two products with highest pre-holdout units and >=180 active days in last 365 days per category and store"})
    frame = load_frame(pairs, TRAIN_END)
    result = evaluate_development(frame)
    write("development.json", result)
    print(json.dumps({"selected": result["selected"], "metrics": result["metrics"]}), flush=True)


def freeze():
    development = json.loads((OUT / "development.json").read_text())
    cohort = json.loads((OUT / "cohort.json").read_text())
    protocol = {
        "selected": development["selected"], "pairs": cohort["pairs"],
        "source_md5": cohort["source_md5"],
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "weekly_sha256": hashlib.sha256(Path(weekly.__file__).read_bytes()).hexdigest(),
        "development_sha256": hashlib.sha256((OUT / "development.json").read_bytes()).hexdigest(),
        "holdout": "d_1914 through d_1941; 28 days; previously unused in this project",
        "gate": "Weekly and product-28-day revenue WAPE each >=2 points below both original and previous-week; daily WAPE <= original +2 points; paired product/store weekly 95% CI gain above zero",
    }
    with (OUT / "protocol.json").open("x", encoding="utf-8") as handle:
        json.dump(protocol, handle, indent=2)
    print(json.dumps({"selected": protocol["selected"], "holdout": protocol["holdout"]}))


def gate(scores, confidence):
    chosen, original, naive = (scores[method] for method in ("selected", "original", "weekly_naive"))
    return {"weekly_gain_2pp": chosen["weekly_wape"] <= min(original["weekly_wape"], naive["weekly_wape"]) - .02,
            "product_28day_gain_2pp": chosen["sku_28day_wape"] <= min(original["sku_28day_wape"], naive["sku_28day_wape"]) - .02,
            "daily_not_materially_worse": chosen["daily_wape"] <= original["daily_wape"] + .02,
            "weekly_gain_ci_above_zero": confidence["lower"] > 0}


def confirm():
    protocol = json.loads((OUT / "protocol.json").read_text())
    if {path.name: md5(path) for path in (CALENDAR, SALES, PRICES)} != protocol["source_md5"]:
        raise ValueError("M5 source files changed after freeze")
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != protocol["code_sha256"]:
        raise ValueError("Benchmark code changed after freeze")
    if hashlib.sha256(Path(weekly.__file__).read_bytes()).hexdigest() != protocol["weekly_sha256"]:
        raise ValueError("Forecast implementation changed after freeze")
    if hashlib.sha256((OUT / "development.json").read_bytes()).hexdigest() != protocol["development_sha256"]:
        raise ValueError("Development selection changed after freeze")
    with (OUT / "confirmation_started.json").open("x", encoding="utf-8") as handle:
        json.dump({"status": "consumed"}, handle)
    frame = load_frame(protocol["pairs"], FINAL_END)
    methods = list(dict.fromkeys(["original", "weekly_naive", protocol["selected"]]))
    rows = weekly.evaluate(frame, frame.date.max() - pd.Timedelta(days=28), methods)
    rows["selected"] = rows[protocol["selected"]]
    scores = weekly.scores(rows)
    comparator = min(("original", "weekly_naive"), key=lambda m: scores[m]["weekly_wape"])
    confidence = weekly.bootstrap_gain(rows["selected"], rows[comparator])
    checks = gate(scores, confidence)
    result = {"selected": protocol["selected"], "metrics": scores, "weekly_comparator": comparator,
              "weekly_gain_ci95": confidence, "checks": checks, "accepted": all(checks.values()),
              "production_changed": False}
    write("confirmation.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("develop", "freeze", "confirm"))
    phase = parser.parse_args().phase
    {"develop": develop, "freeze": freeze, "confirm": confirm}[phase]()
