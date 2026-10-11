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


def fit(rows: pd.DataFrame) -> XGBRegressor:
    model = XGBRegressor(n_estimators=220, max_depth=6, learning_rate=.05, subsample=.85,
                         colsample_bytree=.8, objective="reg:squarederror", n_jobs=2, random_state=42)
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
    folds = 0
    for fold in (3, 2, 1):
        origin = end - pd.Timedelta(days=28 * fold)
        training = eligible[eligible.date <= origin]
        if len(training) < 30 or training.date.nunique() < 28:
            continue
        model = fit(training)
        projections = forecast_series(frame, model, origin, 28)
        valid = []
        for key, (predicted, baseline, price) in projections.items():
            future = [actual.get((*key, origin + pd.Timedelta(days=offset))) for offset in range(1, 29)]
            if any(row is None for row in future):
                continue
            for offset, row in enumerate(future):
                valid.append((offset, float(row.quantity_sold * row.unit_price), predicted[offset] * price,
                              baseline[offset] * price, key[0], key[1]))
        if not valid:
            continue
        folds += 1
        for days in HORIZONS:
            buckets[days].extend((actual_value, prediction, naive, store, sku)
                                  for offset, actual_value, prediction, naive, store, sku in valid if offset < days)
    if not folds:
        raise ValueError("ไม่มีช่วงข้อมูลรายวันต่อเนื่องเพียงพอสำหรับประเมินย้อนหลัง กรุณาตรวจวันที่ที่ขาด")

    backtests = [{"days": days, "folds": folds, **measure(buckets[days])} for days in HORIZONS]
    metrics = {**measure(buckets[28]), "train_rows": len(eligible), "backtests": backtests,
               "by_store": segment_scores(buckets[28], 3), "by_sku": segment_scores(buckets[28], 4)}
    model = fit(eligible)  # Historical evaluation is complete; now use all known dates.
    artifact_id = secrets.token_hex(16)
    ARTIFACTS.mkdir(exist_ok=True)
    joblib.dump(model, artifact_path(artifact_id))
    metrics["_artifact_id"] = artifact_id
    return metrics

def predict(records: list, artifact_id: str, days: int) -> dict:
    path = artifact_path(artifact_id)
    if not path.exists():
        return {"items": [], "coverage": {"series_used": 0, "series_total": 0}}
    model = joblib.load(path)
    frame = prepare(records)
    if frame.empty:
        return {"items": [], "coverage": {"series_used": 0, "series_total": 0}}
    origin = frame.date.max()
    total: dict[pd.Timestamp, float] = {}
    projections = forecast_series(frame, model, origin, days)
    for predicted, _, price in projections.values():
        for offset, quantity in enumerate(predicted, start=1):
            day = origin + pd.Timedelta(days=offset)
            total[day] = total.get(day, 0) + quantity * price
    return {
        "items": [{"date": date.strftime("%Y-%m-%d"), "forecast": round(value, 2)} for date, value in sorted(total.items())],
        "coverage": {"series_used": len(projections), "series_total": frame[GRAIN].drop_duplicates().shape[0]},
    }
