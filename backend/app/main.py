import io
import json
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, Response, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete, func
from sqlalchemy.orm import Session
from .auth import COOKIE_NAME, SignIn, SignUp, check_origin, current_user, hash_password, normalize_email, set_session, token_hash, verify_password, writable_user
from .config import settings
from .database import Base, engine, get_db
from .models import AuthSession, ForecastSnapshot, ModelRun, Organization, SalesRecord, User
from .services import missing_calendar_days, read_and_validate
from .forecasting import artifact_path, train as train_model, predict, segment_forecasts, snapshot_predictions
from .insights import build_insights
from .quality import assess

def run_metrics(run: ModelRun | None) -> dict:
    if not run or not run.metrics_json:
        return {}
    try:
        value = json.loads(run.metrics_json)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}

def active_artifact_id(run: ModelRun | None) -> str | None:
    """Trust only a completed run in the current database that names an existing artifact."""
    if not run or run.status != "completed":
        return None
    metrics = run_metrics(run)
    if not metrics.get("backtests"):
        return None  # Older artifacts used row-based lags and are not comparable.
    artifact_id = metrics.get("_artifact_id")
    if not isinstance(artifact_id, str):
        return None
    try:
        return artifact_id if artifact_path(artifact_id).is_file() else None
    except ValueError:
        return None

def public_metrics(run: ModelRun | None) -> dict:
    return {key: value for key, value in run_metrics(run).items() if key != "_artifact_id"}

@asynccontextmanager
async def lifespan(_: FastAPI):
    # SQLite remains a zero-setup demo; PostgreSQL schemas are managed by Alembic.
    if settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
    yield

app = FastAPI(title="ProjectA_1 API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","), allow_credentials=True, allow_methods=["GET", "POST"], allow_headers=["*"])

@app.get("/health")
def health(): return {"status": "ok"}

@app.post("/api/v1/auth/register")
def register(payload: SignUp, response: Response, request: Request, db: Session = Depends(get_db)):
    check_origin(request)
    email = normalize_email(payload.email)
    if db.query(User).filter_by(email=email).first(): raise HTTPException(409, "อีเมลนี้ถูกใช้แล้ว")
    org = Organization(name=payload.organization_name.strip())
    db.add(org)
    try: db.flush()
    except Exception:
        db.rollback(); raise HTTPException(409, "ชื่อองค์กรนี้ถูกใช้แล้ว")
    user = User(organization_id=org.id, email=email, display_name=payload.display_name.strip(), password_hash=hash_password(payload.password), role="owner")
    db.add(user); db.flush(); set_session(response, user, db)
    return {"id": user.id, "name": user.display_name, "email": user.email, "role": user.role, "organization": org.name}

@app.post("/api/v1/auth/login")
def login(payload: SignIn, response: Response, request: Request, db: Session = Depends(get_db)):
    check_origin(request)
    user = db.query(User).filter_by(email=normalize_email(payload.email)).first()
    if not user or not verify_password(payload.password, user.password_hash): raise HTTPException(401, "อีเมลหรือรหัสผ่านไม่ถูกต้อง")
    set_session(response, user, db)
    org = db.get(Organization, user.organization_id)
    return {"id": user.id, "name": user.display_name, "email": user.email, "role": user.role, "organization": org.name}

@app.get("/api/v1/auth/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = db.get(Organization, user.organization_id)
    return {"id": user.id, "name": user.display_name, "email": user.email, "role": user.role, "organization": org.name}

@app.post("/api/v1/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    check_origin(request)
    token = request.cookies.get(COOKIE_NAME)
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(token))); db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}

@app.get("/api/v1/summary")
def summary(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(SalesRecord).filter_by(organization_id=user.organization_id).all()
    latest = db.query(ModelRun).filter_by(organization_id=user.organization_id).order_by(ModelRun.created_at.desc(), ModelRun.id.desc()).first()
    price_missing_count = sum(r.unit_price is None for r in rows)
    model_status = latest.status if latest else None
    if model_status == "completed":
        if price_missing_count:
            model_status = "invalid_data"
        elif not run_metrics(latest).get("backtests"):
            model_status = "needs_retrain"
        elif not active_artifact_id(latest):
            model_status = "missing"
    errors = {
        "invalid_data": "ข้อมูลบางแถวไม่มี unit_price กรุณานำเข้าใหม่",
        "needs_retrain": "โมเดลเดิมใช้วิธีประเมินเก่า กรุณาเทรนใหม่",
        "missing": "ไฟล์โมเดลไม่พร้อม กรุณาเทรนใหม่",
        "superseded": "นำเข้าข้อมูลชุดใหม่แล้ว กรุณาเทรนโมเดลใหม่",
    }
    metrics = {"error": errors[model_status]} if model_status in errors else public_metrics(latest)
    quality = assess(metrics, rows, datetime.now(ZoneInfo("Asia/Bangkok")).date()) if model_status == "completed" and rows else None
    return {"record_count": len(rows), "store_count": len({r.store_id for r in rows}), "sku_count": len({r.sku_id for r in rows}), "latest_date": max((r.date.isoformat() for r in rows), default=None), "total_revenue": round(sum(r.quantity_sold * r.unit_price for r in rows), 2) if not price_missing_count else None, "price_missing_count": price_missing_count, "model": {"status": model_status, "created_at": latest.created_at.isoformat(), "metrics": metrics, "quality": quality} if latest else None, "stores": sorted({r.store_id for r in rows}), "skus": sorted({r.sku_id for r in rows}), "categories": sorted({r.category for r in rows if r.category}), "channels": sorted({r.channel for r in rows})}

@app.get("/api/v1/forecast")
def forecast(days: int = 28, store_id: str | None = None, sku_id: str | None = None, category: str | None = None, channel: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if days not in (7, 14, 28): raise HTTPException(422, "เลือกระยะเวลา 7, 14 หรือ 28 วัน")
    if db.query(SalesRecord).filter_by(organization_id=user.organization_id, unit_price=None).first():
        return {"source": "needs_price", "items": [], "history": [], "coverage": {"series_used": 0, "series_total": 0}}
    query = db.query(SalesRecord).filter_by(organization_id=user.organization_id)
    if store_id: query = query.filter_by(store_id=store_id)
    if sku_id: query = query.filter_by(sku_id=sku_id)
    if category: query = query.filter_by(category=category)
    if channel: query = query.filter_by(channel=channel)
    rows = query.all()
    history = {}
    for r in rows:
        day = r.date.isoformat(); history[day] = history.get(day, 0) + r.quantity_sold * r.unit_price
    latest = db.query(ModelRun).filter_by(organization_id=user.organization_id).order_by(ModelRun.created_at.desc(), ModelRun.id.desc()).first()
    artifact_id = active_artifact_id(latest)
    result = predict(rows, artifact_id, days) if rows and artifact_id else {"items": [], "coverage": {"series_used": 0, "series_total": len({(r.store_id, r.sku_id, r.channel) for r in rows})}}
    return {"source": "trained" if result["items"] else "empty", **result, "history": [{"date": day, "actual": round(value, 2)} for day, value in sorted(history.items())[-28:]]}


@app.get("/api/v1/insights")
def sales_insights(store_id: str | None = None, sku_id: str | None = None, category: str | None = None,
                   channel: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _sales_insights(store_id, sku_id, category, channel, user, db)


def _sales_insights(store_id: str | None, sku_id: str | None, category: str | None,
                    channel: str | None, user: User, db: Session, product_limit: int | None = 8):
    all_rows = db.query(SalesRecord).filter_by(organization_id=user.organization_id).all()
    rows = [row for row in all_rows if (not store_id or row.store_id == store_id)
            and (not sku_id or row.sku_id == sku_id) and (not category or row.category == category)
            and (not channel or row.channel == channel)]
    latest = db.query(ModelRun).filter_by(organization_id=user.organization_id).order_by(ModelRun.created_at.desc(), ModelRun.id.desc()).first()
    artifact_id = active_artifact_id(latest)
    today = datetime.now(ZoneInfo("Asia/Bangkok")).date()
    quality = assess(public_metrics(latest), all_rows, today) if artifact_id and all_rows else None
    price_complete = all(row.unit_price is not None for row in all_rows)
    projected = segment_forecasts(rows, artifact_id) if rows and artifact_id and price_complete else []
    return build_insights(rows, projected, today, review_needed=quality is not None and quality["status"] == "review",
                          model_available=bool(artifact_id), price_complete=price_complete, product_limit=product_limit)


@app.get("/api/v1/products")
def products(query: str = "", sort: str = "recent_revenue", page: int = 1, store_id: str | None = None,
             category: str | None = None, channel: str | None = None,
             user: User = Depends(current_user), db: Session = Depends(get_db)):
    allowed = {"recent_revenue", "recent_units", "forecast_revenue", "change_pct", "name"}
    if sort not in allowed or page < 1 or page > 100_000 or len(query) > 100:
        raise HTTPException(422, "ตัวกรองรายการสินค้าไม่ถูกต้อง")
    insights = _sales_insights(store_id, None, category, channel, user, db, product_limit=None)
    matching = [item for item in insights["products"]
                if query.casefold().strip() in f'{item["sku_id"]} {item["sku_name"] or ""}'.casefold()]
    if sort == "name":
        matching.sort(key=lambda item: ((item["sku_name"] or item["sku_id"]).casefold(), item["sku_id"]))
    else:
        matching.sort(key=lambda item: (item[sort] is not None, item[sort] or 0, item["sku_id"]), reverse=True)
    page_size = 20
    return {"as_of": insights["as_of"], "recent_start": insights.get("recent_start"),
            "total": len(matching), "page": page, "page_size": page_size,
            "items": matching[(page - 1) * page_size:page * page_size]}

@app.get("/api/v1/reports/forecast-vs-actual")
def forecast_vs_actual(grain: str = "week", run_id: int | None = None, store_id: str | None = None,
                       sku_id: str | None = None, category: str | None = None, channel: str | None = None,
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    if grain not in ("week", "month"):
        raise HTTPException(422, "เลือกรายงานรายสัปดาห์หรือรายเดือน")
    runs = (db.query(ForecastSnapshot.model_run_id, ForecastSnapshot.origin_date)
            .filter_by(organization_id=user.organization_id).distinct()
            .order_by(ForecastSnapshot.origin_date.desc(), ForecastSnapshot.model_run_id.desc()).limit(20).all())
    available = {item.model_run_id for item in runs}
    if run_id is not None and run_id not in available:
        raise HTTPException(404, "ไม่พบชุดพยากรณ์นี้")
    selected = run_id if run_id is not None else (runs[0].model_run_id if runs else None)
    if selected is None:
        return {"runs": [], "run_id": None, "origin_date": None, "grain": grain, "periods": []}
    query = db.query(ForecastSnapshot).filter_by(organization_id=user.organization_id, model_run_id=selected)
    if store_id: query = query.filter_by(store_id=store_id)
    if sku_id: query = query.filter_by(sku_id=sku_id)
    if category: query = query.filter_by(category=category)
    if channel: query = query.filter_by(channel=channel)
    predictions = query.order_by(ForecastSnapshot.target_date).all()
    if predictions:
        first, last = predictions[0].target_date, predictions[-1].target_date
        actual_rows = (db.query(SalesRecord).filter(SalesRecord.organization_id == user.organization_id,
                       SalesRecord.date >= first, SalesRecord.date <= last).all())
    else:
        actual_rows = []
    actual = {(row.date, row.store_id, row.sku_id, row.channel): row for row in actual_rows}
    periods = {}
    for prediction in predictions:
        day = prediction.target_date
        period = (day.replace(day=1) if grain == "month" else day.fromordinal(day.toordinal() - day.weekday())).isoformat()
        bucket = periods.setdefault(period, {"period": period, "forecast_total": 0.0, "forecast_matched": 0.0,
                                              "actual": 0.0, "matched_count": 0, "forecast_count": 0})
        bucket["forecast_total"] += prediction.forecast_revenue
        bucket["forecast_count"] += 1
        observed = actual.get((day, prediction.store_id, prediction.sku_id, prediction.channel))
        if observed is not None and observed.unit_price is not None:
            bucket["forecast_matched"] += prediction.forecast_revenue
            bucket["actual"] += observed.quantity_sold * observed.unit_price
            bucket["matched_count"] += 1
    for bucket in periods.values():
        for key in ("forecast_total", "forecast_matched", "actual"):
            bucket[key] = round(bucket[key], 2)
        bucket["difference"] = round(bucket["actual"] - bucket["forecast_matched"], 2) if bucket["matched_count"] else None
    return {"runs": [{"run_id": item.model_run_id, "origin_date": item.origin_date.isoformat()} for item in runs],
            "run_id": selected, "origin_date": next(item.origin_date.isoformat() for item in runs if item.model_run_id == selected),
            "grain": grain, "periods": list(periods.values())}

@app.post("/api/v1/uploads/validate")
async def validate_upload(file: UploadFile = File(...), user: User = Depends(current_user)):
    frame = await read_and_validate(file)
    return {"valid": True, "rows": len(frame), "missing_days": missing_calendar_days(frame), "columns": list(frame.columns), "date_range": {"from": str(frame.date.min().date()), "to": str(frame.date.max().date())}, "message": "ไฟล์ผ่านการตรวจสอบและไม่พบคอลัมน์ PII"}

@app.post("/api/v1/uploads/import")
async def import_upload(request: Request, file: UploadFile = File(...), user: User = Depends(writable_user), db: Session = Depends(get_db)):
    check_origin(request)
    frame = await read_and_validate(file)
    db.execute(delete(SalesRecord).where(SalesRecord.organization_id == user.organization_id))
    records = []
    for row in frame.to_dict("records"):
        records.append(SalesRecord(organization_id=user.organization_id, date=row["date"].date(), store_id=str(row["store_id"]), store_name=row.get("store_name"), sku_id=str(row["sku_id"]), sku_name=row.get("sku_name"), category=row.get("category"), channel=str(row.get("channel") or "unknown"), quantity_sold=float(row["quantity_sold"]), unit_price=float(row["unit_price"]) if row.get("unit_price") is not None else None, discount=float(row["discount"]) if row.get("discount") is not None else None, promotion_flag=bool(row.get("promotion_flag") or False), holiday_flag=bool(row.get("holiday_flag") or False)))
    db.add_all(records); db.commit()
    previous_runs = db.query(ModelRun).filter_by(organization_id=user.organization_id).all()
    old_artifacts = []
    for run in previous_runs:
        artifact_id = run_metrics(run).get("_artifact_id")
        if isinstance(artifact_id, str):
            try:
                old_artifacts.append(artifact_path(artifact_id))
            except ValueError:
                pass
    # Keep run IDs stable: saved forecasts refer to them even after a dataset replacement.
    for run in previous_runs:
        run.status = "superseded"
        old_metrics = run_metrics(run)
        old_metrics.pop("_artifact_id", None)
        run.metrics_json = json.dumps(old_metrics)
    db.commit()
    for path in old_artifacts:
        path.unlink(missing_ok=True)
    return {"imported": len(records), "message": "นำเข้าข้อมูลสำเร็จ"}

@app.post("/api/v1/models/train")
def train(request: Request, user: User = Depends(writable_user), db: Session = Depends(get_db)):
    check_origin(request)
    run = ModelRun(organization_id=user.organization_id, model_name="XGBoost (validated selection)", status="running")
    db.add(run); db.commit(); db.refresh(run)
    records = db.query(SalesRecord).filter_by(organization_id=user.organization_id).all()
    if not records:
        run.status = "failed"; run.metrics_json = '{"error":"ยังไม่มีข้อมูลที่นำเข้า"}'; db.commit()
        return {"run_id": run.id, "status": run.status, "message": "กรุณานำเข้าข้อมูลก่อนเทรนโมเดล"}
    artifact_id = None
    try:
        metrics = train_model(records)
        artifact_id = metrics["_artifact_id"]
        snapshots = snapshot_predictions(records, artifact_id)
        db.add_all(ForecastSnapshot(organization_id=user.organization_id, model_run_id=run.id, **item) for item in snapshots)
        run.status = "completed"; run.metrics_json = json.dumps(metrics)
    except ValueError as exc:
        if artifact_id:
            artifact_path(artifact_id).unlink(missing_ok=True)
        run.status = "failed"; run.metrics_json = json.dumps({"error": str(exc)})
    except Exception:
        db.rollback()
        if artifact_id:
            artifact_path(artifact_id).unlink(missing_ok=True)
        run = db.get(ModelRun, run.id)
        if run:
            run.status = "failed"; run.metrics_json = json.dumps({"error": "เทรนโมเดลหรือสร้างผลพยากรณ์ไม่สำเร็จ"})
            db.commit()
        raise HTTPException(500, "เทรนโมเดลหรือสร้างผลพยากรณ์ไม่สำเร็จ")
    try:
        db.commit()
    except Exception:
        db.rollback()
        if artifact_id:
            artifact_path(artifact_id).unlink(missing_ok=True)
        run = db.get(ModelRun, run.id)
        if run:
            run.status = "failed"; run.metrics_json = json.dumps({"error": "บันทึกผลพยากรณ์ไม่สำเร็จ กรุณาลองเทรนใหม่"})
            db.commit()
        raise HTTPException(500, "บันทึกผลพยากรณ์ไม่สำเร็จ กรุณาลองเทรนใหม่")
    return {"run_id": run.id, "status": run.status, "metrics": public_metrics(run)}

@app.get("/api/v1/export")
def export_sales(user: User = Depends(current_user), db: Session = Depends(get_db)):
    import csv
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(["date", "store_id", "sku_id", "category", "channel", "quantity_sold", "unit_price"])
    for r in db.query(SalesRecord).filter_by(organization_id=user.organization_id).order_by(SalesRecord.date).all():
        writer.writerow([r.date.isoformat(), r.store_id, r.sku_id, r.category or "", r.channel, r.quantity_sold, r.unit_price if r.unit_price is not None else ""])
    return StreamingResponse(iter(["\ufeff" + output.getvalue()]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=projecta-sales.csv"})
