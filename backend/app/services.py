from __future__ import annotations
import io
import re
import pandas as pd
from fastapi import HTTPException, UploadFile

REQUIRED = {"date", "store_id", "sku_id", "quantity_sold", "unit_price"}
OPTIONAL = {"store_name", "sku_name", "category", "channel", "discount", "promotion_flag", "holiday_flag"}
PII_TERMS = {"name", "customer", "email", "phone", "mobile", "address", "person", "customer_name", "first_name", "last_name"}

async def read_and_validate(file: UploadFile) -> pd.DataFrame:
    if not file.filename or not file.filename.lower().endswith((".csv", ".xlsx")):
        raise HTTPException(422, "รองรับเฉพาะไฟล์ CSV หรือ XLSX")
    raw = await file.read(20_000_001)
    return validate_content(raw, file.filename)


def validate_content(raw: bytes, filename: str) -> pd.DataFrame:
    if not raw or len(raw) > 20_000_000:
        raise HTTPException(413, "ไฟล์ต้องมีขนาดไม่เกิน 20 MB")
    try:
        frame = pd.read_excel(io.BytesIO(raw)) if filename.lower().endswith(".xlsx") else pd.read_csv(io.BytesIO(raw))
    except Exception as exc:
        raise HTTPException(422, "อ่านไฟล์ไม่สำเร็จ: รองรับ CSV และ XLSX") from exc
    frame.columns = [str(c).strip().lower().replace(" ", "_") for c in frame.columns]
    detected = [c for c in frame.columns if c in PII_TERMS or re.search(r"email|phone|address|customer", c)]
    if detected: raise HTTPException(422, f"พบคอลัมน์ข้อมูลส่วนบุคคล: {', '.join(detected)} กรุณาลบหรือทำให้ไม่สามารถระบุตัวบุคคลได้ก่อนอัปโหลด")
    missing = REQUIRED - set(frame.columns)
    if missing: raise HTTPException(422, f"ขาดคอลัมน์จำเป็น: {', '.join(sorted(missing))}")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    if frame["date"].isna().any(): raise HTTPException(422, "พบวันที่ที่ไม่ถูกต้อง")
    frame["date"] = frame["date"].dt.normalize()
    frame["quantity_sold"] = pd.to_numeric(frame["quantity_sold"], errors="coerce").replace([float("inf"), float("-inf")], float("nan"))
    if frame["quantity_sold"].isna().any() or (frame["quantity_sold"] < 0).any(): raise HTTPException(422, "quantity_sold ต้องเป็นตัวเลขและห้ามติดลบ")
    if frame["date"].nunique() < 90: raise HTTPException(422, "ต้องมีข้อมูลอย่างน้อย 90 วันเพื่อประเมินย้อนหลัง")
    if frame[["store_id", "sku_id"]].isna().any().any() or frame[["store_id", "sku_id"]].astype(str).apply(lambda col: col.str.strip().eq("")).any().any():
        raise HTTPException(422, "store_id และ sku_id ห้ามว่าง")
    for field in ("unit_price", "discount"):
        if field in frame:
            original = frame[field]
            frame[field] = pd.to_numeric(original, errors="coerce").replace([float("inf"), float("-inf")], float("nan"))
            if (original.notna() & frame[field].isna()).any(): raise HTTPException(422, f"{field} ต้องเป็นตัวเลข")
            if (frame[field].dropna() < 0).any(): raise HTTPException(422, f"{field} ห้ามติดลบ")
    if frame["unit_price"].isna().any(): raise HTTPException(422, "unit_price ห้ามว่าง เพราะระบบแสดงผลเป็นบาท")
    for field in ("promotion_flag", "holiday_flag"):
        if field in frame:
            values = frame[field].astype(str).str.strip().str.lower()
            allowed = {"true", "false", "1", "0", "yes", "no", "nan", ""}
            if not values.isin(allowed).all(): raise HTTPException(422, f"{field} ต้องเป็น true/false หรือ 1/0")
            frame[field] = values.isin({"true", "1", "yes"})
    if "channel" not in frame: frame["channel"] = "unknown"
    for col in OPTIONAL - set(frame.columns): frame[col] = None
    frame["channel"] = frame["channel"].fillna("unknown")
    if frame.duplicated(subset=["date", "store_id", "sku_id", "channel"]).any():
        raise HTTPException(422, "พบข้อมูลซ้ำในวัน/สาขา/SKU/ช่องทางเดียวกัน")
    frame = frame.astype(object).where(pd.notna(frame), None)
    return frame[list(REQUIRED | OPTIONAL)]


def missing_calendar_days(frame: pd.DataFrame) -> int:
    """Count absent dates inside each store/SKU/channel series; zero-sale rows are present."""
    missing = 0
    for _, group in frame.groupby(["store_id", "sku_id", "channel"]):
        missing += (group.date.max() - group.date.min()).days + 1 - len(group)
    return int(missing)
