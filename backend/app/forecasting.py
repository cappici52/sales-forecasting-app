"""Daily, channel-aware sales forecasting with rolling-origin evaluation."""
from pathlib import Path
import re
import secrets

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from xgboost import XGBRegressor

ARTIFACTS = Path(__file__).resolve().parents[1] / "artifacts"
GRAIN = ["store_id", "sku_id", "channel"]
FEATURES = ["lag_1", "lag_7", "lag_14", "lag_28", "mean_7", "mean_28", "weekday", "month", "unit_price"]
HORIZONS = (7, 14, 28)

def artifact_path(artifact_id: str) -> Path:
    """Resolve only generated model identifiers, never a database-supplied path."""
    if not re.fullmatch(r"[0-9a-f]{32}", artifact_id):
        raise ValueError("รหัสไฟล์โมเดลไม่ถูกต้อง")
    return ARTIFACTS / f"model-{artifact_id}.joblib"

def prepare(records: list) -> pd.DataFrame:
    """Keep missing calendar days as NaN; only explicit zero sales are zero."""
    if any(r.unit_price is None for r in records):
        raise ValueError("ข้อมูลบางแถวไม่มี unit_price กรุณานำเข้าไฟล์ที่มีราคาครบ")
    frame = pd.DataFrame([{
        "date": r.date, "store_id": r.store_id, "sku_id": r.sku_id,
        "channel": r.channel, "quantity_sold": r.quantity_sold, "unit_price": r.unit_price,
    } for r in records])
    if frame.empty:
        return frame
    frame["date"] = pd.to_datetime(frame.date)
    daily = []
    for key, group in frame.groupby(GRAIN, sort=False):
        group = group.set_index("date").sort_index()
        if group.index.has_duplicates:
            raise ValueError("พบข้อมูลซ้ำในวัน/สาขา/SKU/ช่องทางเดียวกัน")
        group = group.reindex(pd.date_range(group.index.min(), group.index.max(), freq="D", name="date"))
        for column, value in zip(GRAIN, key):
            group[column] = value
        daily.append(group.reset_index())
    return pd.concat(daily, ignore_index=True).sort_values(GRAIN + ["date"])


def feature_rows(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    series = frame.groupby(GRAIN, sort=False)["quantity_sold"]
    for lag in (1, 7, 14, 28):
        frame[f"lag_{lag}"] = series.shift(lag)
    for window in (7, 28):
        frame[f"mean_{window}"] = series.transform(lambda values: values.shift(1).rolling(window, min_periods=window).mean())
    frame["weekday"] = frame.date.dt.dayofweek
    frame["month"] = frame.date.dt.month
    return frame.dropna(subset=FEATURES + ["quantity_sold"])


def fit(rows: pd.DataFrame, price_weighted: bool = False, absolute_error: bool = False) -> XGBRegressor:
    model = XGBRegressor(n_estimators=220, max_depth=3, learning_rate=.05, subsample=.85,
                         colsample_bytree=.8, min_child_weight=5, reg_lambda=5,
                         objective="reg:absoluteerror" if absolute_error else "count:poisson", n_jobs=2, random_state=42)
    if price_weighted:
        prices = rows.unit_price.to_numpy(dtype=float)
        weights = prices / prices.mean() if prices.mean() > 0 else np.ones(len(rows))
        model.fit(rows[FEATURES], rows.quantity_sold, sample_weight=weights)
    else:
        model.fit(rows[FEATURES], rows.quantity_sold)
    return model


def forecast_series(frame: pd.DataFrame, model: XGBRegressor, origin: pd.Timestamp, days: int) -> dict:
    """Forecast only series with 28 observed days ending exactly at the origin."""
    result = {}
    for key, group in frame[frame.date <= origin].groupby(GRAIN, sort=False):
        recent = group.sort_values("date").tail(28)
        if len(recent) != 28 or recent.date.iloc[-1] != origin or recent.quantity_sold.isna().any():
            continue
        history = recent.quantity_sold.astype(float).tolist()
        baseline_history = history.copy()
        price = float(recent.unit_price.iloc[-1])
        predicted, baseline = [], []
        for offset in range(1, days + 1):
            day = origin + pd.Timedelta(days=offset)
            features = pd.DataFrame([{
                "lag_1": history[-1], "lag_7": history[-7], "lag_14": history[-14],
                "lag_28": history[-28], "mean_7": float(np.mean(history[-7:])),
                "mean_28": float(np.mean(history[-28:])), "weekday": day.dayofweek,
                "month": day.month, "unit_price": price,
            }], columns=FEATURES)
            quantity = max(0.0, float(model.predict(features)[0]))
            naive = baseline_history[-7]
            predicted.append(quantity)
            baseline.append(naive)
            history.append(quantity)
            baseline_history.append(naive)
        result[key] = (predicted, baseline, price)
    return result


def measure(rows: list[tuple]) -> dict:
    actual = np.array([row[0] for row in rows])
    predicted = np.array([row[1] for row in rows])
    baseline = np.array([row[2] for row in rows])
    denominator = float(actual.sum())
    return {
        "wape": round(float(np.abs(actual - predicted).sum() / denominator), 4) if denominator else None,
        "baseline_wape": round(float(np.abs(actual - baseline).sum() / denominator), 4) if denominator else None,
        "mae": round(float(mean_absolute_error(actual, predicted)), 2),
        "rmse": round(float(mean_squared_error(actual, predicted) ** .5), 2),
        "test_rows": len(rows),
    }


def segment_scores(rows: list[tuple], index: int) -> list[dict]:
    groups = {}
    for row in rows:
        groups.setdefault(row[index], []).append(row)
    scores = [{"id": key, "wape": measure(values)["wape"], "test_rows": len(values)} for key, values in groups.items()]
    return sorted(scores, key=lambda item: item["wape"] if item["wape"] is not None else -1, reverse=True)[:10]


def choose_method(result: dict) -> str:
    """Choose the lowest rolling revenue WAPE; keep the simpler method on ties."""
    model_error = result.get("wape")
    baseline_error = result.get("baseline_wape")
    weighted_error = result.get("weighted_wape")
    absolute_error = result.get("absolute_wape")
    existing = [value for value in (model_error, baseline_error, weighted_error) if value is not None]
    if absolute_error is not None and existing and absolute_error < min(existing):
        return "absolute_error_xgboost"
    if (weighted_error is not None and model_error is not None and baseline_error is not None
            and weighted_error < min(model_error, baseline_error)):
        return "price_weighted_xgboost"
    if model_error is not None and baseline_error is not None and model_error >= baseline_error:
        return "weekly_naive"
    return "xgboost"


def load_artifact(artifact_id: str) -> tuple[XGBRegressor, dict[int, str], XGBRegressor | None, XGBRegressor | None]:
    artifact = joblib.load(artifact_path(artifact_id))
    if isinstance(artifact, dict) and artifact.get("version") == 4:
        return artifact["model"], artifact["methods"], artifact["weighted_model"], artifact["absolute_model"]
    if isinstance(artifact, dict) and artifact.get("version") == 3:
        return artifact["model"], artifact["methods"], artifact["weighted_model"], None
    if isinstance(artifact, dict) and artifact.get("version") == 2:
        return artifact["model"], artifact["methods"], None, None
    return artifact, {}, None, None  # Existing model-only artifacts remain usable.


def selected_model(artifact_id: str, days: int) -> tuple[XGBRegressor, str]:
    model, methods, weighted, absolute = load_artifact(artifact_id)
    method = methods.get(days, "xgboost")
    if method == "price_weighted_xgboost" and weighted is not None:
        model = weighted
    elif method == "absolute_error_xgboost" and absolute is not None:
        model = absolute
    return model, method


def candidate_scores(rows: list[tuple]) -> dict:
    """Rows contain actual, Poisson, baseline, weighted, store, SKU, absolute."""
    return {**measure(rows),
            "weighted_wape": measure([(row[0], row[3], row[2]) for row in rows])["wape"],
            "absolute_wape": measure([(row[0], row[6], row[2]) for row in rows])["wape"]}


def confirm_method(validation: dict, confirmation: dict | None) -> tuple[str, dict]:
    """Promote a weighted objective only if it wins earlier AND latest windows.

    The latest window is a promotion check, not an untouched accuracy estimate.
    Without a separate window, retain Poisson or the weekly baseline.
    """
    incumbent = choose_method({key: value for key, value in validation.items()
                               if key not in {"absolute_wape", "weighted_wape"}})
    candidate = choose_method(validation)
    promoted = False
    incumbent_key = {"xgboost": "wape", "weekly_naive": "baseline_wape",
                     "price_weighted_xgboost": "weighted_wape"}[incumbent]
    challenger_key = {"absolute_error_xgboost": "absolute_wape", "price_weighted_xgboost": "weighted_wape"}.get(candidate)
    if challenger_key and confirmation:
        challenger_error = confirmation.get(challenger_key)
        incumbent_error = confirmation.get(incumbent_key)
        promoted = (challenger_error is not None and incumbent_error is not None
                    and challenger_error < incumbent_error)
    return (candidate if promoted else incumbent), {
        "incumbent": incumbent, "candidate": candidate, "promoted": promoted,
        "confirmation_available": confirmation is not None,
        "incumbent_wape": confirmation.get(incumbent_key) if confirmation else None,
        "challenger_wape": confirmation.get(challenger_key) if confirmation and challenger_key else None,
    }

def train(records: list) -> dict:
    frame = prepare(records)
    if frame.empty or frame.date.nunique() < 90:
        raise ValueError("ต้องมีข้อมูลอย่างน้อย 90 วันเพื่อประเมินย้อนหลัง 28 วัน")
    eligible = feature_rows(frame)
    if len(eligible) < 30:
        raise ValueError("ข้อมูลรายวันที่ต่อเนื่องไม่พอสำหรับเทรนโมเดล")

    end = frame.date.max()
    actual = {(row.store_id, row.sku_id, row.channel, row.date): row for row in frame.itertuples() if pd.notna(row.quantity_sold)}
    buckets = {days: [] for days in HORIZONS}
    confirmation = {days: [] for days in HORIZONS}
    folds = 0
    validation_origins = []
    for fold in (4, 3, 2, 1):
        origin = end - pd.Timedelta(days=28 * fold)
        training = eligible[eligible.date <= origin]
        if len(training) < 30 or training.date.nunique() < 28:
            continue
        model = fit(training)
        weighted_model = fit(training, price_weighted=True)
        absolute_model = fit(training, price_weighted=True, absolute_error=True)
        projections = forecast_series(frame, model, origin, 28)
        weighted_projections = forecast_series(frame, weighted_model, origin, 28)
        absolute_projections = forecast_series(frame, absolute_model, origin, 28)
        valid = []
        for key, (predicted, baseline, price) in projections.items():
            weighted = weighted_projections.get(key)
            if weighted is None:
                continue
            future = [actual.get((*key, origin + pd.Timedelta(days=offset))) for offset in range(1, 29)]
            if any(row is None for row in future):
                continue
            for offset, row in enumerate(future):
                valid.append((offset, float(row.quantity_sold * row.unit_price), predicted[offset] * price,
                              baseline[offset] * price, weighted[0][offset] * price, key[0], key[1],
                              absolute_projections[key][0][offset] * price))
        if not valid:
            continue
        if fold != 1:
            folds += 1
            validation_origins.append(str(origin.date()))
        for days in HORIZONS:
            (confirmation if fold == 1 else buckets)[days].extend(row[1:] for row in valid if row[0] < days)
    if not folds and not confirmation[28]:
        raise ValueError("ไม่มีช่วงข้อมูลรายวันต่อเนื่องเพียงพอสำหรับประเมินย้อนหลัง กรุณาตรวจวันที่ที่ขาด")
    independent_confirmation = bool(folds and confirmation[28])
    if not folds:
        # Short histories support Poisson/baseline selection, but cannot promote a challenger.
        buckets = confirmation
        folds = 1
        validation_origins = [str((end - pd.Timedelta(days=28)).date())]

    backtests = [{"days": days, "folds": folds, **candidate_scores(buckets[days])}
                 for days in HORIZONS]
    methods = {}
    for item in backtests:
        days = item["days"]
        check = candidate_scores(confirmation[days]) if independent_confirmation else None
        methods[days], item["promotion_check"] = confirm_method(item, check)
        item["selected_method"] = methods[days]
        item["selected_wape"] = {"xgboost": item["wape"], "weekly_naive": item["baseline_wape"],
                                 "price_weighted_xgboost": item["weighted_wape"],
                                 "absolute_error_xgboost": item["absolute_wape"]}[methods[item["days"]]]
        if check:
            score_key = {"xgboost": "wape", "weekly_naive": "baseline_wape",
                         "price_weighted_xgboost": "weighted_wape", "absolute_error_xgboost": "absolute_wape"}[methods[days]]
            item["confirmation_wape"] = check[score_key]
            item["confirmation_baseline_wape"] = check["baseline_wape"]
    selected_index = {"xgboost": 1, "weekly_naive": 2, "price_weighted_xgboost": 3,
                      "absolute_error_xgboost": 6}[methods[28]]
    selected_rows = [(row[0], row[selected_index], row[2], row[4], row[5]) for row in buckets[28]]
    metrics = {**measure(buckets[28]), "objective": "count:poisson", "train_rows": len(eligible), "backtests": backtests,
               "selection_origins": validation_origins,
               "confirmation_origin": str((end - pd.Timedelta(days=28)).date()) if independent_confirmation else None,
               "evaluation_note": "Rolling scores select candidates; the latest window gates promotion and is not an untouched test.",
               "selected_metrics": measure(selected_rows),
               "by_store": segment_scores(selected_rows, 3), "by_sku": segment_scores(selected_rows, 4),
               "forecast_methods": {str(days): methods[days] for days in HORIZONS}}
    model = fit(eligible)  # Historical evaluation is complete; now use all known dates.
    weighted_model = fit(eligible, price_weighted=True)
    absolute_model = fit(eligible, price_weighted=True, absolute_error=True)
    artifact_id = secrets.token_hex(16)
    ARTIFACTS.mkdir(exist_ok=True)
    joblib.dump({"version": 4, "model": model, "weighted_model": weighted_model, "absolute_model": absolute_model,
                 "methods": methods}, artifact_path(artifact_id))
    metrics["_artifact_id"] = artifact_id
    return metrics

def predict(records: list, artifact_id: str, days: int) -> dict:
    path = artifact_path(artifact_id)
    if not path.exists():
        return {"items": [], "coverage": {"series_used": 0, "series_total": 0}}
    chosen_model, method = selected_model(artifact_id, days)
    frame = prepare(records)
    if frame.empty:
        return {"items": [], "coverage": {"series_used": 0, "series_total": 0}}
    origin = frame.date.max()
    total: dict[pd.Timestamp, float] = {}
    projections = forecast_series(frame, chosen_model, origin, days)
    for predicted, baseline, price in projections.values():
        for offset, quantity in enumerate(baseline if method == "weekly_naive" else predicted, start=1):
            day = origin + pd.Timedelta(days=offset)
            total[day] = total.get(day, 0) + quantity * price
    return {
        "items": [{"date": date.strftime("%Y-%m-%d"), "forecast": round(value, 2)} for date, value in sorted(total.items())],
        "coverage": {"series_used": len(projections), "series_total": frame[GRAIN].drop_duplicates().shape[0]},
        "method": method,
    }


def segment_forecasts(records: list, artifact_id: str, days: int = 28) -> list[dict]:
    """Return per-series totals from the same model and eligibility rule as /forecast."""
    path = artifact_path(artifact_id)
    if not path.exists():
        return []
    frame = prepare(records)
    if frame.empty:
        return []
    chosen_model, method = selected_model(artifact_id, days)
    projections = forecast_series(frame, chosen_model, frame.date.max(), days)
    return [{
        "store_id": key[0], "sku_id": key[1], "channel": key[2],
        "forecast_units": round(float(sum(baseline if method == "weekly_naive" else predicted)), 2),
        "forecast_revenue": round(float(sum(baseline if method == "weekly_naive" else predicted)) * price, 2),
    } for key, (predicted, baseline, price) in projections.items()]

def snapshot_predictions(records: list, artifact_id: str) -> list[dict]:
    """Persist the 28-day, per-series forecast before future actuals are imported."""
    frame = prepare(records)
    if frame.empty:
        return []
    origin = frame.date.max()
    chosen_model, method = selected_model(artifact_id, 28)
    projections = forecast_series(frame, chosen_model, origin, 28)
    categories = {(r.store_id, r.sku_id, r.channel): getattr(r, "category", None) for r in records}
    return [{
        "origin_date": origin.date(), "target_date": (origin + pd.Timedelta(days=offset)).date(),
        "store_id": key[0], "sku_id": key[1], "channel": key[2],
        "category": categories.get(key), "forecast_revenue": round(quantity * price, 2),
    } for key, (predicted, baseline, price) in projections.items()
      for offset, quantity in enumerate(baseline if method == "weekly_naive" else predicted, start=1)]
