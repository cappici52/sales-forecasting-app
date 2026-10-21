"""Descriptive sales insights and cautious, traceable planning prompts."""
from collections import defaultdict
from datetime import date, timedelta


def build_insights(records: list, projected: list[dict], today: date, review_needed: bool,
                   model_available: bool = False, price_complete: bool = True,
                   product_limit: int | None = 8) -> dict:
    if not records:
        return {"as_of": None, "products": [], "product_count": 0, "channels": [], "channel_count": 0,
                "weekday": {"status": "no_data", "values": []},
                "forecast_coverage": {"series_used": 0, "series_total": 0}, "actions": []}

    as_of = max(row.date for row in records)
    recent_start = as_of - timedelta(days=27)
    previous_start = as_of - timedelta(days=55)
    expected = {previous_start + timedelta(days=offset) for offset in range(56)}
    series_days: dict[tuple, set[date]] = defaultdict(set)
    product_series: dict[str, set[tuple]] = defaultdict(set)
    channel_series: dict[str, set[tuple]] = defaultdict(set)
    products: dict[str, dict] = {}
    channels: dict[str, dict] = {}
    daily_revenue: dict[date, float] = defaultdict(float)
    missing_price = False

    for row in records:
        key = (row.store_id, row.sku_id, row.channel)
        product_series[row.sku_id].add(key)
        channel_series[row.channel].add(key)
        product = products.setdefault(row.sku_id, {"sku_id": row.sku_id, "sku_name": None,
                                                    "category": None, "recent_units": 0.0, "previous_units": 0.0,
                                                    "recent_revenue": 0.0, "forecast_units": None,
                                                    "forecast_revenue": None})
        if getattr(row, "sku_name", None):
            product["sku_name"] = row.sku_name
        if getattr(row, "category", None):
            product["category"] = row.category
        if row.date < previous_start or row.date > as_of:
            continue
        series_days[key].add(row.date)
        channel = channels.setdefault(row.channel, {"channel": row.channel, "recent_revenue": 0.0,
                                                     "forecast_revenue": None})
        if row.unit_price is None:
            missing_price = True
            revenue = 0.0
        else:
            revenue = row.quantity_sold * row.unit_price
        if row.date >= recent_start:
            product["recent_units"] += row.quantity_sold
            product["recent_revenue"] += revenue
            channel["recent_revenue"] += revenue
        else:
            product["previous_units"] += row.quantity_sold
        daily_revenue[row.date] += revenue

    all_series = set().union(*product_series.values())
    projected_keys = {(row["store_id"], row["sku_id"], row["channel"]) for row in projected}
    for row in projected:
        product = products.get(row["sku_id"])
        channel = channels.get(row["channel"])
        if product is not None:
            product["forecast_units"] = (product["forecast_units"] or 0) + row["forecast_units"]
            product["forecast_revenue"] = (product["forecast_revenue"] or 0) + row["forecast_revenue"]
        if channel is not None:
            channel["forecast_revenue"] = (channel["forecast_revenue"] or 0) + row["forecast_revenue"]

    def complete(keys: set[tuple]) -> bool:
        return bool(keys) and all(expected.issubset(series_days[key]) for key in keys)

    product_rows = []
    for sku_id, product in products.items():
        eligible = complete(product_series[sku_id])
        previous = product["previous_units"]
        product["change_pct"] = round(product["recent_units"] / previous - 1, 4) if eligible and previous > 0 else None
        product["history_complete"] = eligible
        product["series_used"] = len(product_series[sku_id] & projected_keys)
        product["series_total"] = len(product_series[sku_id])
        for field in ("recent_units", "previous_units", "recent_revenue", "forecast_units", "forecast_revenue"):
            if product[field] is not None:
                product[field] = round(product[field], 2)
        if missing_price:
            product["recent_revenue"] = None
        product_rows.append(product)
    product_rows.sort(key=lambda item: (item["forecast_revenue"] if item["forecast_revenue"] is not None
                                        else item["recent_revenue"] if item["recent_revenue"] is not None
                                        else item["recent_units"], item["sku_id"]), reverse=True)

    channel_rows = []
    for channel_name, channel in channels.items():
        channel["history_complete"] = complete(channel_series[channel_name])
        channel["recent_revenue"] = round(channel["recent_revenue"], 2)
        if missing_price:
            channel["recent_revenue"] = None
        if channel["forecast_revenue"] is not None:
            channel["forecast_revenue"] = round(channel["forecast_revenue"], 2)
        channel_rows.append(channel)
    channel_rows.sort(key=lambda item: (item["forecast_revenue"] if item["forecast_revenue"] is not None
                                        else item["recent_revenue"] if item["recent_revenue"] is not None else 0,
                                        item["channel"]), reverse=True)

    all_complete = complete(all_series)
    if missing_price:
        weekday = {"status": "missing_price", "values": []}
    elif not all_complete:
        weekday = {"status": "incomplete_history", "values": []}
    else:
        weekday = {"status": "ready", "values": [
            {"day": day, "average_revenue": round(sum(value for observed, value in daily_revenue.items() if observed.weekday() == day) / 8, 2)}
            for day in range(7)
        ]}

    age_days = max(0, (today - as_of).days)
    actions = []
    if age_days > 30:
        actions.append({"kind": "refresh_data", "days": age_days})
    if len(projected_keys) < len(all_series) and model_available and price_complete:
        actions.append({"kind": "check_coverage", "series_used": len(projected_keys),
                        "series_total": len(all_series)})
    declining = next((item for item in product_rows if item["change_pct"] is not None
                      and item["change_pct"] <= -0.2 and item["previous_units"] >= 10), None)
    if declining:
        actions.append({"kind": "inspect_decline", "sku_id": declining["sku_id"], "change_pct": declining["change_pct"]})
    if projected and review_needed:
        actions.append({"kind": "review_model"})
    elif projected and age_days <= 30:
        rising = next((item for item in product_rows if item["history_complete"] and item["recent_units"] > 0
                       and item["forecast_units"] is not None and item["forecast_units"] >= item["recent_units"] * 1.2), None)
        if rising:
            actions.append({"kind": "check_stock", "sku_id": rising["sku_id"],
                            "forecast_units": rising["forecast_units"]})
    if not price_complete:
        actions.append({"kind": "fix_prices"})
    elif not model_available:
        actions.append({"kind": "train_model"})

    return {"as_of": as_of.isoformat(), "recent_start": recent_start.isoformat(),
            "previous_start": previous_start.isoformat(), "products": product_rows[:product_limit], "product_count": len(product_rows),
            "channels": channel_rows[:8], "channel_count": len(channel_rows),
            "weekday": weekday, "forecast_coverage": {"series_used": len(projected_keys),
                                                      "series_total": len(all_series)},
            "actions": actions}
