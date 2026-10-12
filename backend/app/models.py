from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), default="owner")

class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)

class SalesRecord(Base):
    __tablename__ = "sales_records"
    __table_args__ = (UniqueConstraint("organization_id", "date", "store_id", "sku_id", "channel", name="uq_sales_grain"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    store_id: Mapped[str] = mapped_column(String(80), index=True)
    store_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    sku_id: Mapped[str] = mapped_column(String(100), index=True)
    sku_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    channel: Mapped[str] = mapped_column(String(80), default="unknown")
    quantity_sold: Mapped[float] = mapped_column(Float)
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    discount: Mapped[float | None] = mapped_column(Float, nullable=True)
    promotion_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    holiday_flag: Mapped[bool] = mapped_column(Boolean, default=False)

class ModelRun(Base):
    __tablename__ = "model_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    model_name: Mapped[str] = mapped_column(String(100), default="XGBoost")
    status: Mapped[str] = mapped_column(String(30), default="queued")
    metrics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ForecastSnapshot(Base):
    """Immutable prediction made at training time; retained when sales are re-imported."""
    __tablename__ = "forecast_snapshots"
    __table_args__ = (
        UniqueConstraint("organization_id", "model_run_id", "target_date", "store_id", "sku_id", "channel", name="uq_snapshot_grain"),
        Index("ix_snapshots_org_target", "organization_id", "target_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    # Deliberately no FK: a new upload removes obsolete model runs, not historical forecasts.
    model_run_id: Mapped[int] = mapped_column(Integer, index=True)
    origin_date: Mapped[date] = mapped_column(Date)
    target_date: Mapped[date] = mapped_column(Date)
    store_id: Mapped[str] = mapped_column(String(80))
    sku_id: Mapped[str] = mapped_column(String(100))
    channel: Mapped[str] = mapped_column(String(80))
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    forecast_revenue: Mapped[float] = mapped_column(Float)
