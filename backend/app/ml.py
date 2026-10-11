"""Small, reproducible training pipeline for the initial XGBoost model."""
from __future__ import annotations
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from xgboost import XGBRegressor

MODEL_DIR = Path("artifacts")

def build_features(sales: pd.DataFrame) -> pd.DataFrame:
    """Create time-safe features: every sales feature uses prior observations only."""
    data = sales.sort_values(["store_id", "sku_id", "date"]).copy()
    group = data.groupby(["store_id", "sku_id"], group_keys=False)["quantity_sold"]
    for lag in (1, 7, 14, 28): data[f"lag_{lag}"] = group.shift(lag)
    for window in (7, 28): data[f"rolling_mean_{window}"] = group.transform(lambda s: s.shift(1).rolling(window, min_periods=3).mean())
    data["day_of_week"] = pd.to_datetime(data["date"]).dt.dayofweek
    data["month"] = pd.to_datetime(data["date"]).dt.month
    data["is_weekend"] = (data.day_of_week >= 5).astype(int)
    return data.dropna(subset=["lag_28"])

def train_xgboost(sales: pd.DataFrame) -> dict:
    data = build_features(sales)
    if len(data) < 100: raise ValueError("ข้อมูลหลังสร้าง feature ไม่เพียงพอ ต้องมีอย่างน้อย 100 แถว")
    features = [c for c in data.columns if c.startswith(("lag_", "rolling_"))] + ["day_of_week", "month", "is_weekend"]
    if "unit_price" in data: features.append("unit_price")
    data[features] = data[features].fillna(0)
    split = max(1, len(data) - 28)
    train, test = data.iloc[:split], data.iloc[split:]
    model = XGBRegressor(n_estimators=400, max_depth=7, learning_rate=.05, subsample=.85, colsample_bytree=.8, objective="reg:squarederror", n_jobs=2)
    model.fit(train[features], train.quantity_sold)
    prediction = np.maximum(0, model.predict(test[features]))
    actual = test.quantity_sold.to_numpy()
    wape = float(np.abs(actual - prediction).sum() / max(actual.sum(), 1))
    metrics = {"mae": round(float(mean_absolute_error(actual, prediction)), 3), "rmse": round(float(mean_squared_error(actual, prediction) ** .5), 3), "wape": round(wape, 4), "rows": len(data)}
    MODEL_DIR.mkdir(exist_ok=True)
    joblib.dump({"model": model, "features": features}, MODEL_DIR / "xgboost.joblib")
    (MODEL_DIR / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    return metrics
