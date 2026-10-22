"""Read-only forecast audit: select on rolling windows, then score the last 28 days."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import forecasting
from app.services import missing_calendar_days, validate_content


def evaluate(frame: pd.DataFrame, origin: pd.Timestamp) -> list[tuple]:
    training = forecasting.feature_rows(frame.loc[frame.date.le(origin)])
    if len(training) < 30 or training.date.nunique() < 28:
        return []
    model = forecasting.fit(training)
    actual = {(row.store_id, row.sku_id, row.channel, row.date): row
              for row in frame.itertuples() if pd.notna(row.quantity_sold)}
    rows = []
    for key, (predicted, baseline, price) in forecasting.forecast_series(frame, model, origin, 28).items():
        future = [actual.get((*key, origin + pd.Timedelta(days=offset))) for offset in range(1, 29)]
        if any(item is None for item in future):
            continue
        rows.extend((float(item.quantity_sold * item.unit_price), predicted[index] * price,
                     baseline[index] * price, key[0], key[1], key[2])
                    for index, item in enumerate(future))
    return rows


def report(frame: pd.DataFrame) -> dict:
    end = frame.date.max()
    holdout_origin = end - pd.Timedelta(days=28)
    history = frame.loc[frame.date.le(holdout_origin)].dropna(subset=["quantity_sold", "unit_price"])
    if history.date.nunique() < 90:
        raise ValueError("ข้อมูลก่อนช่วงทดสอบล่าสุดไม่พอสำหรับประเมินย้อนหลัง")
    records = [SimpleNamespace(**row) for row in history.to_dict("records")]
    # Exercise the same training/selection path as the app, with disposable artifacts.
    with tempfile.TemporaryDirectory() as directory, patch.object(forecasting, "ARTIFACTS", Path(directory)):
        metrics = forecasting.train(records)
        all_projections = {}
        for days in forecasting.HORIZONS:
            model, selected = forecasting.selected_model(metrics["_artifact_id"], days)
            all_projections[days] = (selected, forecasting.forecast_series(history, model, holdout_origin, days))
    actual = {(row.store_id, row.sku_id, row.channel, row.date): row
              for row in frame.itertuples() if pd.notna(row.quantity_sold)}
    horizon_holdouts = []
    for days, (selected, projections) in all_projections.items():
        selected_rows = []
        for key, (predictions, baseline, price) in projections.items():
            future = [actual.get((*key, holdout_origin + pd.Timedelta(days=i))) for i in range(1, days + 1)]
            if any(row is None for row in future):
                continue
            values = baseline if selected == "weekly_naive" else predictions
            selected_rows.extend((float(row.quantity_sold * row.unit_price), values[i] * price,
                                  baseline[i] * price, key[0], key[1], key[2]) for i, row in enumerate(future))
        if selected_rows:
            horizon_holdouts.append({"days": days, "method": selected, **forecasting.measure(selected_rows)})
    holdout = evaluate(frame, holdout_origin)
    if not holdout:
        raise ValueError("ช่วงทดสอบล่าสุดไม่มีชุดข้อมูลรายวันที่ต่อเนื่องครบ 28 วัน")
    total_series = frame[forecasting.GRAIN].drop_duplicates().shape[0]
    return {
        "period": {"first": str(frame.date.min().date()), "last": str(end.date()),
                   "holdout_start": str((holdout_origin + pd.Timedelta(days=1)).date()),
                   "holdout_end": str(end.date())},
        "data": {"rows": int(frame.quantity_sold.notna().sum()), "series_total": total_series,
                 "zero_sale_rows": int(frame.quantity_sold.eq(0).sum()),
                 "missing_calendar_days": missing_calendar_days(frame.dropna(subset=["quantity_sold"]))},
        "validation": {"origins": metrics["selection_origins"],
                       "confirmation_origin": metrics["confirmation_origin"],
                       "metrics": metrics["backtests"][-1]},
        "holdout": {"selected_method": selected, "selected_metrics": forecasting.measure(selected_rows),
                    "xgboost_metrics": forecasting.measure(holdout),
                    "series_evaluated": len(holdout) // 28, "series_total": total_series,
                    "by_sku": forecasting.segment_scores(selected_rows, 4)},
        "horizon_holdouts": horizon_holdouts,
        "note": "Holdout scores apply only to this file. Review data provenance and business loss before deployment.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="Local CSV/XLSX sales file; no database writes")
    args = parser.parse_args()
    if args.file.stat().st_size > 20_000_000:
        parser.error("ไฟล์ต้องมีขนาดไม่เกิน 20 MB")
    data = validate_content(args.file.read_bytes(), args.file.name)
    records = [SimpleNamespace(**row) for row in data.to_dict("records")]
    print(json.dumps(report(forecasting.prepare(records)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
