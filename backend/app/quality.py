"""Conservative, explainable forecast review flags (not a model selector)."""
from collections import defaultdict
from datetime import date, timedelta
from math import isfinite

MAX_REVENUE_WAPE = 0.30
MAX_DATA_AGE_DAYS = 30
EXPECTED_FOLDS = 3


def assess(metrics: dict, records: list, today: date) -> dict:
    latest = max(record.date for record in records)
    age = max(0, (today - latest).days)
    series = {(record.store_id, record.sku_id, record.channel) for record in records}
    recent = defaultdict(set)
    first_day = latest - timedelta(days=27)
    for record in records:
        if first_day <= record.date <= latest:
            recent[(record.store_id, record.sku_id, record.channel)].add(record.date)
    covered = sum(len(recent[key]) == 28 for key in series)

    result = next((item for item in metrics.get("backtests", []) if item.get("days") == 28), None)
    error = result.get("selected_wape", result.get("wape")) if result else None
    baseline_error = result.get("baseline_wape") if result else None
    # Use the selected method's earlier score; the promotion window is also checked
    # so a recent regression is not hidden by averaging older windows.
    confirmation_error = result.get("confirmation_wape") if result else None
    confirmation_baseline = result.get("confirmation_baseline_wape") if result else None
    reasons = []
    if (not result or not isinstance(error, (int, float))
            or not isinstance(baseline_error, (int, float))
            or not isfinite(error) or not isfinite(baseline_error)
            or not result.get("test_rows")):
        reasons.append("missing_backtest")
    else:
        if result.get("folds", 0) < EXPECTED_FOLDS:
            reasons.append("limited_backtest")
        if error >= baseline_error or (confirmation_error is not None and confirmation_baseline is not None
                                       and confirmation_error >= confirmation_baseline):
            reasons.append("not_better_than_baseline")
        if error >= MAX_REVENUE_WAPE or (confirmation_error is not None and confirmation_error >= MAX_REVENUE_WAPE):
            reasons.append("high_revenue_error")
    if age > MAX_DATA_AGE_DAYS:
        reasons.append("stale_data")
    if covered < len(series):
        reasons.append("partial_coverage")
    return {
        "status": "review" if reasons else "no_flags",
        "reasons": reasons,
        "data_age_days": age,
        "coverage": {"series_used": covered, "series_total": len(series)},
        "thresholds": {"revenue_wape": MAX_REVENUE_WAPE, "data_age_days": MAX_DATA_AGE_DAYS},
    }
