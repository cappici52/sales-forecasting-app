"""History-only sparse/dense routing check on the existing M5 research cohort."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import benchmark_m5 as m5, benchmark_m5_robustness as robust, benchmark_weekly_direct as weekly


OUT = m5.ROOT / "outputs/m5_routing_2026-10-22"
METHODS = ("original", "weekly_naive", "mean4", "direct_absolute")
SEGMENTS = ("sparse", "dense")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def segments_at_origin(frame, origin):
    history = frame.loc[frame.date.le(origin)]
    result = {}
    for key, group in history.groupby(["store_id", "sku_id", "channel"]):
        recent = group.sort_values("date").tail(56)
        if len(recent) != 56 or recent.date.iloc[-1] != origin:
            raise ValueError("Each product needs 56 observed days at the origin")
        result["/".join(key)] = "dense" if recent.quantity_sold.gt(0).sum() >= 28 else "sparse"
    return result


def restrict(rows, labels, segment):
    return {method: [row for row in values if labels[row[1]] == segment]
            for method, values in rows.items()}


def select_methods(calibration):
    choices, diagnostics = {}, {}
    for segment in SEGMENTS:
        values = calibration[segment]
        metrics = weekly.scores(values)
        original = metrics["original"]
        challenger = min(METHODS, key=lambda method: metrics[method]["weekly_wape"])
        candidate = metrics[challenger]
        choices[segment] = (challenger if candidate["weekly_wape"] <= original["weekly_wape"] - .02
                            and candidate["sku_28day_wape"] <= original["sku_28day_wape"] else "original")
        diagnostics[segment] = {"series_windows": len(values["original"]) // 28,
                                "metrics": metrics, "choice": choices[segment]}
    return choices, diagnostics


def apply_route(rows, labels, choices):
    return [row for method in METHODS for row in rows[method]
            if choices[labels[row[1]]] == method]


def check_gate(scores, by_segment, ci):
    chosen, original = scores["routed"], scores["original"]
    return {
        "weekly_gain_2pp": chosen["weekly_wape"] <= original["weekly_wape"] - .02,
        "product_28day_no_regression": chosen["sku_28day_wape"] <= original["sku_28day_wape"],
        "daily_no_material_regression": chosen["daily_wape"] <= original["daily_wape"] + .02,
        "all_segments_weekly_no_material_regression": all(
            group["routed"]["weekly_wape"] <= group["original"]["weekly_wape"] + .02
            for group in by_segment.values()),
        "weekly_gain_ci_above_zero": ci["lower"] > 0,
    }


def calibrate():
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "protocol.json").exists():
        raise ValueError("Calibration already frozen")
    source = json.loads((robust.OUT / "protocol.json").read_text())
    if {path.name: m5.md5(path) for path in (m5.CALENDAR, m5.SALES, m5.PRICES)} != source["source_md5"]:
        raise ValueError("M5 source changed")
    if sha256(Path(m5.__file__)) != source["m5_code_sha256"] or sha256(Path(weekly.__file__)) != source["weekly_code_sha256"]:
        raise ValueError("Frozen M5 model implementation changed")
    frame = m5.load_frame(source["cohort"], m5.TRAIN_END - 28)
    origins = [frame.date.max() - pd.Timedelta(days=56), frame.date.max() - pd.Timedelta(days=28)]
    combined = {segment: {method: [] for method in METHODS} for segment in SEGMENTS}
    for origin in origins:
        labels = segments_at_origin(frame, origin)
        scored = weekly.evaluate(frame, origin, METHODS)
        for segment in SEGMENTS:
            for method, values in restrict(scored, labels, segment).items():
                combined[segment][method].extend(values)
        print(json.dumps({"calibration_origin": str(origin.date()),
                          "segments": {segment: sum(value == segment for value in labels.values()) for segment in SEGMENTS}}), flush=True)
    if any(not combined[segment]["original"] for segment in SEGMENTS):
        raise ValueError("Both sparse and dense segments need calibration examples")
    choices, diagnostics = select_methods(combined)
    protocol = {"choices": choices, "calibration": diagnostics,
                "calibration_origins": [str(origin.date()) for origin in origins],
                "check_origin": str(frame.date.max().date()),
                "source_md5": source["source_md5"], "cohort_sha256": sha256(robust.OUT / "protocol.json"),
                "script_sha256": sha256(Path(__file__)), "m5_sha256": sha256(Path(m5.__file__)),
                "weekly_sha256": sha256(Path(weekly.__file__)),
                "rule": "Dense if at least 28 of prior 56 days had positive units; per segment choose lowest weekly WAPE on two calibration windows only if >=2-point gain over original and product-28-day WAPE no worse; otherwise original",
                "interpretation": "Third rolling window is an internal check on an already-studied retailer, not an independent dataset or untouched external holdout"}
    with (OUT / "protocol.json").open("x", encoding="utf-8") as handle:
        json.dump(protocol, handle, indent=2)
    print(json.dumps({"choices": choices, "check_origin": protocol["check_origin"]}), flush=True)


def check():
    protocol = json.loads((OUT / "protocol.json").read_text())
    if (OUT / "result.json").exists():
        raise ValueError("Check already consumed")
    source = json.loads((robust.OUT / "protocol.json").read_text())
    if sha256(robust.OUT / "protocol.json") != protocol["cohort_sha256"]:
        raise ValueError("Cohort changed")
    if {path.name: m5.md5(path) for path in (m5.CALENDAR, m5.SALES, m5.PRICES)} != protocol["source_md5"]:
        raise ValueError("M5 source changed")
    if any(sha256(path) != protocol[label] for label, path in (
        ("script_sha256", Path(__file__)), ("m5_sha256", Path(m5.__file__)),
        ("weekly_sha256", Path(weekly.__file__)))):
        raise ValueError("Frozen implementation changed")
    with (OUT / "check_started.json").open("x", encoding="utf-8") as handle:
        json.dump({"status": "consumed"}, handle)
    frame = m5.load_frame(source["cohort"], m5.TRAIN_END)
    origin = pd.Timestamp(protocol["check_origin"])
    labels = segments_at_origin(frame, origin)
    rows = weekly.evaluate(frame, origin, METHODS)
    routed = apply_route(rows, labels, protocol["choices"])
    if len(routed) != len(rows["original"]):
        raise ValueError("Routing changed evaluation coverage")
    scores = weekly.scores({**rows, "routed": routed})
    by_segment = {}
    for segment in SEGMENTS:
        group = restrict({**rows, "routed": routed}, labels, segment)
        by_segment[segment] = {"series": sum(value == segment for value in labels.values()),
                               "metrics": weekly.scores(group)}
    ci = robust.bootstrap_gain(routed, rows["original"])
    checks = check_gate(scores, {segment: result["metrics"] for segment, result in by_segment.items()}, ci)
    result = {"choices": protocol["choices"], "origin": protocol["check_origin"],
              "overall": scores, "by_segment": by_segment, "weekly_gain_ci95": ci,
              "checks": checks, "accepted": all(checks.values()), "production_changed": False,
              "scope": "Internal chronological check on previously studied M5 retailer; no claim of fresh external validation"}
    with (OUT / "result.json").open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
    print(json.dumps({"choices": result["choices"], "accepted": result["accepted"],
                      "overall": result["overall"], "checks": checks}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("calibrate", "check"))
    {"calibrate": calibrate, "check": check}[parser.parse_args().phase]()
