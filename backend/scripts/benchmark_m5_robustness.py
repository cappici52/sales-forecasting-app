"""Fixed M5 challenger on unused low/medium/high-volume product-store series."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import benchmark_m5 as m5, benchmark_weekly_direct as weekly


OUT = m5.ROOT / "outputs/m5_robustness_2026-10-22"
METHODS = ["original", "weekly_naive", "direct_absolute"]
STRATA = ("low", "medium", "high")


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select_cohort(previous_pairs):
    """All selection inputs stop at d_1913; each store/category contributes three volumes."""
    columns = ["store_id", "item_id", "cat_id"] + [f"d_{day}" for day in range(m5.FIRST_DAY, m5.TRAIN_END + 1)]
    sales = pd.read_csv(m5.SALES, usecols=columns)
    prior = sales[[f"d_{day}" for day in range(m5.FIRST_DAY, 1549)]]
    recent = sales[[f"d_{day}" for day in range(1549, m5.TRAIN_END + 1)]]
    final_month = sales[[f"d_{day}" for day in range(m5.TRAIN_END - 27, m5.TRAIN_END + 1)]]
    sales = sales[["store_id", "item_id", "cat_id"]].assign(
        earlier=prior.gt(0).any(axis=1).to_numpy(),
        active=recent.gt(0).sum(axis=1).to_numpy(),
        units=recent.sum(axis=1).to_numpy(),
        last28=final_month.sum(axis=1).to_numpy())
    previous = {(row["store_id"], row["item_id"]) for row in previous_pairs}
    sales = sales.loc[sales.earlier & sales.active.ge(28) & sales.last28.gt(0)]
    sales = sales.loc[[key not in previous for key in sales[["store_id", "item_id"]].itertuples(index=False, name=None)]]
    chosen = []
    for (store, category), group in sales.groupby(["store_id", "cat_id"], sort=True):
        ordered = group.sort_values(["units", "item_id"]).reset_index(drop=True)
        if len(ordered) < 9:
            raise ValueError(f"Insufficient established products in {store}/{category}")
        for stratum, section in zip(STRATA, np.array_split(np.arange(len(ordered)), 3)):
            item = ordered.iloc[section[len(section) // 2]]
            chosen.append({"store_id": store, "item_id": item.item_id, "category": category,
                           "stratum": stratum, "selection_units": int(item.units),
                           "selection_active_days": int(item.active)})
    if len(chosen) != 90:
        raise ValueError("Expected 90 distinct product/store series")
    return chosen


def save(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, indent=2), encoding="utf-8")


def prepare():
    original = json.loads((m5.OUT / "protocol.json").read_text())
    if original["selected"] != "direct_absolute":
        raise ValueError("The original M5 selection changed")
    source = {path.name: m5.md5(path) for path in (m5.CALENDAR, m5.SALES, m5.PRICES)}
    if source != original["source_md5"]:
        raise ValueError("M5 source files changed")
    cohort = select_cohort(original["pairs"])
    protocol = {
        "method": "direct_absolute", "cohort": cohort, "source_md5": source,
        "code_sha256": file_hash(Path(__file__)),
        "m5_code_sha256": file_hash(Path(m5.__file__)),
        "weekly_code_sha256": file_hash(Path(weekly.__file__)),
        "original_protocol_sha256": file_hash(m5.OUT / "protocol.json"),
        "period": "d_1914 through d_1941; already viewed for the prior high-volume cohort",
        "gate": "Prior M5 overall gate, plus no volume stratum may be more than 2 percentage points worse than the better simple comparator on weekly WAPE",
        "selection": "One median product/store in each pre-cutoff volume tercile of each store/category, excluding prior cohort",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "protocol.json").open("x", encoding="utf-8") as handle:
        json.dump(protocol, handle, indent=2)
    print(json.dumps({"pairs": len(cohort), "per_stratum": {s: sum(r["stratum"] == s for r in cohort) for s in STRATA}}))


def robustness_checks(scores, strata, confidence):
    checks = m5.gate(scores, confidence)
    checks["no_stratum_weekly_regression_over_2pp"] = all(
        group["direct_absolute"]["weekly_wape"] <= min(
            group["original"]["weekly_wape"], group["weekly_naive"]["weekly_wape"]) + .02
        for group in strata.values())
    return checks


def bootstrap_gain(selected, baseline):
    """Keep zero-actual product series in the pooled paired bootstrap."""
    candidate = {key: sorted((r for r in selected if r[1] == key), key=lambda r: r[2])
                 for key in {row[1] for row in selected}}
    reference = {key: sorted((r for r in baseline if r[1] == key), key=lambda r: r[2])
                 for key in candidate}
    triples = []
    for key in sorted(candidate):
        chosen, original = candidate[key], reference[key]
        if len(chosen) != 28 or len(original) != 28:
            raise ValueError("Bootstrap requires a complete 28-day series")
        actual = np.array([row[3] for row in chosen]).reshape(4, 7).sum(axis=1)
        chosen_weeks = np.array([row[4] for row in chosen]).reshape(4, 7).sum(axis=1)
        original_weeks = np.array([row[4] for row in original]).reshape(4, 7).sum(axis=1)
        triples.append([np.abs(chosen_weeks - actual).sum(),
                        np.abs(original_weeks - actual).sum(), actual.sum()])
    values = np.asarray(triples)
    indices = np.random.default_rng(42).integers(0, len(values), size=(2000, len(values)))
    samples = values[indices].sum(axis=1)
    samples = samples[samples[:, 2] > 0]
    if len(samples) == 0:
        raise ValueError("No observed revenue in bootstrap samples")
    gains = (samples[:, 1] - samples[:, 0]) / samples[:, 2]
    return {"lower": float(np.quantile(gains, .025)), "upper": float(np.quantile(gains, .975)),
            "note": "95% paired product/store bootstrap of comparator minus selected weekly WAPE; zero-actual series retained"}


def confirm(repair=False):
    protocol = json.loads((OUT / "protocol.json").read_text())
    if {path.name: m5.md5(path) for path in (m5.CALENDAR, m5.SALES, m5.PRICES)} != protocol["source_md5"]:
        raise ValueError("M5 source files changed after cohort selection")
    checksums = {"m5_code_sha256": Path(m5.__file__), "weekly_code_sha256": Path(weekly.__file__),
                 "original_protocol_sha256": m5.OUT / "protocol.json"}
    if any(file_hash(path) != protocol[label] for label, path in checksums.items()):
        raise ValueError("Frozen implementation or selection changed")
    marker = OUT / "confirmation_started.json"
    if repair:
        if not marker.exists() or (OUT / "result.json").exists():
            raise ValueError("Repair only resumes a consumed run without a result")
    else:
        if file_hash(Path(__file__)) != protocol["code_sha256"]:
            raise ValueError("Frozen benchmark code changed")
        with marker.open("x", encoding="utf-8") as handle:
            json.dump({"status": "consumed"}, handle)
    frame = m5.load_frame(protocol["cohort"], m5.FINAL_END)
    origin = frame.date.max() - pd.Timedelta(days=28)
    rows = weekly.evaluate(frame, origin, METHODS)
    scores = weekly.scores(rows)
    scores["selected"] = scores[protocol["method"]]
    groups = {}
    for stratum in STRATA:
        keys = {f'{item["store_id"]}/{item["item_id"]}/in_store' for item in protocol["cohort"] if item["stratum"] == stratum}
        groups[stratum] = weekly.scores({method: [row for row in rows[method] if row[1] in keys] for method in METHODS})
    comparator = min(("original", "weekly_naive"), key=lambda method: scores[method]["weekly_wape"])
    confidence = bootstrap_gain(rows[protocol["method"]], rows[comparator])
    checks = robustness_checks(scores, groups, confidence)
    result = {"method": protocol["method"], "overall": scores, "by_volume": groups,
              "weekly_comparator": comparator, "weekly_gain_ci95": confidence,
              "checks": checks, "accepted": all(checks.values()), "production_changed": False,
              "repair": {"resumed_after": "Zero-actual product caused bootstrap denominator None",
                         "original_code_sha256": protocol["code_sha256"],
                         "repaired_code_sha256": file_hash(Path(__file__))} if repair else None,
              "scope": "Unused products, same retailer and already-inspected dates; robustness analysis, not a new temporal holdout"}
    save("result.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "confirm", "resume"))
    phase = parser.parse_args().phase
    {"prepare": prepare, "confirm": confirm, "resume": lambda: confirm(repair=True)}[phase]()
