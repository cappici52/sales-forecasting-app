"""Train on past sales and forecast future daily demand for one organization."""
from pathlib import Path
import re
import secrets

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from xgboost import XGBRegressor

ARTIFACTS = Path(__file__).resolve().parents[1] / "artifacts"
FEATURES = ["lag_1", "lag_7", "lag_14", "lag_28", "mean_7", "mean_28", "weekday", "month", "unit_price"]

def artifact_path(artifact_id: str) -> Path:
    """Resolve only generated model identifiers, never a database-supplied path."""
    if not re.fullmatch(r"[0-9a-f]{32}", artifact_id):
        raise ValueError("รหัสไฟล์โมเดลไม่ถูกต้อง")
    return ARTIFACTS / f"model-{artifact_id}.joblib"

def prepare(records: list) -> pd.DataFrame:
    frame = pd.DataFrame([{"date": r.date, "store_id": r.store_id, "sku_id": r.sku_id, "category": r.category, "channel": r.channel, "quantity_sold": r.quantity_sold, "unit_price": r.unit_price or 1} for r in records])
    if frame.empty: return frame
    frame["date"] = pd.to_datetime(frame.date)
    return frame.sort_values(["store_id", "sku_id", "date"])

def train(records: list) -> dict:
    frame = prepare(records)
    if frame.empty or frame.date.nunique() < 60:
        raise ValueError("ต้องมีข้อมูลอย่างน้อย 60 วันก่อนเทรนโมเดล")
    series = frame.groupby(["store_id", "sku_id"], group_keys=False)["quantity_sold"]
    for lag in (1, 7, 14, 28): frame[f"lag_{lag}"] = series.shift(lag)
    for window in (7, 28): frame[f"mean_{window}"] = series.transform(lambda s: s.shift(1).rolling(window, min_periods=3).mean())
    frame["weekday"] = frame.date.dt.dayofweek
    frame["month"] = frame.date.dt.month
    frame = frame.dropna(subset=["lag_28"]).copy()
    if len(frame) < 100: raise ValueError("ข้อมูลหลังสร้าง feature ไม่เพียงพอ ต้องมีอย่างน้อย 100 แถว")
    frame[FEATURES] = frame[FEATURES].fillna(0)
    dates = sorted(frame.date.unique())
    cutoff = dates[-min(28, max(7, len(dates) // 5))]
    train_set, test_set = frame[frame.date < cutoff], frame[frame.date >= cutoff]
    if train_set.empty or test_set.empty: raise ValueError("ข้อมูลสำหรับประเมินโมเดลไม่เพียงพอ")
    model = XGBRegressor(n_estimators=220, max_depth=6, learning_rate=.05, subsample=.85, colsample_bytree=.8, objective="reg:squarederror", n_jobs=2, random_state=42)
    model.fit(train_set[FEATURES], train_set.quantity_sold)
    predicted = np.maximum(0, model.predict(test_set[FEATURES]))
    actual = test_set.quantity_sold.to_numpy()
    baseline = test_set.lag_7.to_numpy()
    metrics = {"mae": round(float(mean_absolute_error(actual, predicted)), 3), "rmse": round(float(mean_squared_error(actual, predicted) ** .5), 3), "wape": round(float(np.abs(actual - predicted).sum() / max(actual.sum(), 1)), 4), "baseline_wape": round(float(np.abs(actual - baseline).sum() / max(actual.sum(), 1)), 4), "train_rows": len(train_set), "test_rows": len(test_set)}
    artifact_id = secrets.token_hex(16)
    ARTIFACTS.mkdir(exist_ok=True)
    joblib.dump(model, artifact_path(artifact_id))
    metrics["_artifact_id"] = artifact_id
    return metrics

def predict(records: list, artifact_id: str, days: int) -> list[dict]:
    path = artifact_path(artifact_id)
    if not path.exists(): return []
    model = joblib.load(path)
    frame = prepare(records)
    total: dict[pd.Timestamp, float] = {}
    for _, group in frame.groupby(["store_id", "sku_id"]):
        history = group.quantity_sold.astype(float).tolist()
        if len(history) < 28: continue
        price = float(group.unit_price.iloc[-1] or 1)
        day = group.date.iloc[-1] + pd.Timedelta(days=1)
        for _ in range(days):
            features = {"lag_1": history[-1], "lag_7": history[-7], "lag_14": history[-14], "lag_28": history[-28], "mean_7": float(np.mean(history[-7:])), "mean_28": float(np.mean(history[-28:])), "weekday": day.dayofweek, "month": day.month, "unit_price": price}
            quantity = max(0.0, float(model.predict(pd.DataFrame([features], columns=FEATURES))[0]))
            total[day] = total.get(day, 0) + quantity * price
            history.append(quantity); day += pd.Timedelta(days=1)
    return [{"date": date.strftime("%Y-%m-%d"), "forecast": round(value, 2)} for date, value in sorted(total.items())]
