"""Initial ProjectA schema.

Revision ID: 0001_initial
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.String(300), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
    )
    op.create_index("ix_users_organization_id", "users", ["organization_id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True)
    op.create_table(
        "sales_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("store_id", sa.String(80), nullable=False),
        sa.Column("store_name", sa.String(160)),
        sa.Column("sku_id", sa.String(100), nullable=False),
        sa.Column("sku_name", sa.String(200)),
        sa.Column("category", sa.String(100)),
        sa.Column("channel", sa.String(80), nullable=False),
        sa.Column("quantity_sold", sa.Float(), nullable=False),
        sa.Column("unit_price", sa.Float()),
        sa.Column("discount", sa.Float()),
        sa.Column("promotion_flag", sa.Boolean(), nullable=False),
        sa.Column("holiday_flag", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("organization_id", "date", "store_id", "sku_id", "channel", name="uq_sales_grain"),
    )
    for column in ("organization_id", "date", "store_id", "sku_id"):
        op.create_index(f"ix_sales_records_{column}", "sales_records", [column])
    op.create_table(
        "model_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("metrics_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "forecast_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("model_run_id", sa.Integer(), nullable=False),
        sa.Column("origin_date", sa.Date(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("store_id", sa.String(80), nullable=False),
        sa.Column("sku_id", sa.String(100), nullable=False),
        sa.Column("channel", sa.String(80), nullable=False),
        sa.Column("category", sa.String(100)),
        sa.Column("forecast_revenue", sa.Float(), nullable=False),
        sa.UniqueConstraint("organization_id", "model_run_id", "target_date", "store_id", "sku_id", "channel", name="uq_snapshot_grain"),
    )
    op.create_index("ix_forecast_snapshots_organization_id", "forecast_snapshots", ["organization_id"])
    op.create_index("ix_forecast_snapshots_model_run_id", "forecast_snapshots", ["model_run_id"])
    op.create_index("ix_snapshots_org_target", "forecast_snapshots", ["organization_id", "target_date"])


def downgrade() -> None:
    op.drop_table("forecast_snapshots")
    op.drop_table("model_runs")
    op.drop_table("sales_records")
    op.drop_table("auth_sessions")
    op.drop_table("users")
    op.drop_table("organizations")
