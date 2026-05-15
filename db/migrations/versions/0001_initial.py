"""Initial VidyutDrishti schema - dimensions, hypertables, analytics tables.

Revision ID: 0001_initial
Revises:
Create Date: 2025-05-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Helper: ensure TimescaleDB extension
# ---------------------------------------------------------------------------

def _ensure_timescale() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;")


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    _ensure_timescale()

    # ---- Dimensions ------------------------------------------------------

    op.create_table(
        "feeder",
        sa.Column("feeder_id", sa.String(32), primary_key=True),
        sa.Column("substation_id", sa.String(32)),
        sa.Column("historical_peak_kw", sa.Float),
    )

    op.create_table(
        "dt",
        sa.Column("dt_id", sa.String(32), primary_key=True),
        sa.Column("feeder_id", sa.String(32), sa.ForeignKey("feeder.feeder_id"), nullable=False),
        sa.Column("capacity_kva", sa.Float),
        sa.Column("geo_lat", sa.Float),
        sa.Column("geo_lon", sa.Float),
    )

    op.create_table(
        "consumer",
        sa.Column("meter_id", sa.String(32), primary_key=True),
        sa.Column("dt_id", sa.String(32), sa.ForeignKey("dt.dt_id"), nullable=False, index=True),
        sa.Column("feeder_id", sa.String(32), sa.ForeignKey("feeder.feeder_id"),
                  nullable=False, index=True),
        sa.Column("tariff_category", sa.String(32), nullable=False),
        sa.Column("address", sa.Text),
        sa.Column("geo_lat", sa.Float),
        sa.Column("geo_lon", sa.Float),
    )

    op.create_table(
        "tariff_slab",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("category", sa.String(32), nullable=False, index=True),
        sa.Column("slab_from", sa.Float, nullable=False),
        sa.Column("slab_to", sa.Float),
        sa.Column("rate_inr", sa.Float, nullable=False),
    )

    op.create_table(
        "holiday",
        sa.Column("date", sa.Date, primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("region", sa.String(16), nullable=False, server_default="IN"),
    )

    # ---- Hypertables -----------------------------------------------------

    op.create_table(
        "meter_reading",
        sa.Column("meter_id", sa.String(32), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=False), nullable=False),
        sa.Column("kwh", sa.Float),
        sa.Column("voltage", sa.Float),
        sa.Column("power_factor", sa.Float),
        sa.Column("source", sa.String(16), nullable=False, server_default="ami"),
        sa.Column("imputed", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.PrimaryKeyConstraint("meter_id", "ts"),
    )
    op.execute(
        "SELECT create_hypertable('meter_reading', 'ts', "
        "chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_meter_reading_meter_ts "
        "ON meter_reading (meter_id, ts DESC);"
    )

    op.create_table(
        "dt_reading",
        sa.Column("dt_id", sa.String(32), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=False), nullable=False),
        sa.Column("kwh_in", sa.Float, nullable=False),
        sa.PrimaryKeyConstraint("dt_id", "ts"),
    )
    op.execute(
        "SELECT create_hypertable('dt_reading', 'ts', "
        "chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);"
    )

    # ---- Analytics -------------------------------------------------------

    op.create_table(
        "forecast",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("feeder_id", sa.String(32), nullable=False, index=True),
        sa.Column("ts", sa.DateTime, nullable=False, index=True),
        sa.Column("yhat", sa.Float, nullable=False),
        sa.Column("yhat_lower", sa.Float, nullable=False),
        sa.Column("yhat_upper", sa.Float, nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("generated_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "zone_risk",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("feeder_id", sa.String(32), nullable=False, index=True),
        sa.Column("ts", sa.DateTime, nullable=False, index=True),
        sa.Column("level", sa.String(8), nullable=False),
        sa.Column("predicted_peak_kw", sa.Float, nullable=False),
        sa.Column("computed_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "feature_daily",
        sa.Column("meter_id", sa.String(32), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("mean_kwh", sa.Float),
        sa.Column("peak_mean_ratio", sa.Float),
        sa.Column("night_ratio", sa.Float),
        sa.Column("trend_slope", sa.Float),
        sa.Column("pf_avg", sa.Float),
        sa.Column("zero_read_rate", sa.Float),
        sa.PrimaryKeyConstraint("meter_id", "date"),
    )

    op.create_table(
        "flag",
        sa.Column("flag_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("meter_id", sa.String(32), index=True),
        sa.Column("dt_id", sa.String(32), index=True),
        sa.Column("layer", sa.String(4), nullable=False),
        sa.Column("fired_at", sa.DateTime, nullable=False, index=True),
        sa.Column("score", sa.Float),
        sa.Column("evidence_json", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("model_version", sa.String(64)),
    )

    op.create_table(
        "confidence",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("meter_id", sa.String(32), nullable=False, index=True),
        sa.Column("computed_at", sa.DateTime, nullable=False, index=True),
        sa.Column("level", sa.String(8), nullable=False),
        sa.Column("layers_fired", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("behaviour", sa.String(32)),
        sa.Column("leakage_inr_monthly", sa.Float),
    )

    op.create_table(
        "inspection",
        sa.Column("inspection_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("meter_id", sa.String(32), nullable=False, index=True),
        sa.Column("dispatched_at", sa.DateTime),
        sa.Column("completed_at", sa.DateTime),
        sa.Column("outcome", sa.String(32)),
        sa.Column("notes", sa.Text),
        sa.Column("inspector_id", sa.String(64)),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime, nullable=False, index=True),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON, nullable=False, server_default="{}"),
    )

    op.create_table(
        "ingest_errors",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime, nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("reason", sa.Text, nullable=False),
    )

    op.create_table(
        "injected_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("meter_id", sa.String(32), nullable=False, index=True),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("start_day", sa.Integer, nullable=False),
        sa.Column("end_day", sa.Integer, nullable=False),
        sa.Column("severity", sa.Float, nullable=False),
    )

    op.create_table(
        "job_run",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), nullable=False, index=True),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("finished_at", sa.DateTime),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("rows", sa.Integer),
        sa.Column("error", sa.Text),
    )

    # ---- Continuous aggregates ------------------------------------------
    # Keep policies lenient for the prototype; tighten in Feature 22.

    op.execute(
        """
        CREATE MATERIALIZED VIEW IF NOT EXISTS meter_hourly
        WITH (timescaledb.continuous) AS
        SELECT meter_id,
               time_bucket(INTERVAL '1 hour', ts) AS bucket,
               AVG(kwh)          AS mean_kwh,
               SUM(kwh)          AS total_kwh,
               AVG(voltage)      AS mean_voltage,
               AVG(power_factor) AS mean_pf
        FROM meter_reading
        GROUP BY meter_id, bucket
        WITH NO DATA;
        """
    )

    op.execute(
        """
        CREATE MATERIALIZED VIEW IF NOT EXISTS meter_daily
        WITH (timescaledb.continuous) AS
        SELECT meter_id,
               time_bucket(INTERVAL '1 day', ts) AS bucket,
               SUM(kwh)          AS total_kwh,
               AVG(kwh)          AS mean_kwh,
               MAX(kwh)          AS peak_kwh,
               AVG(voltage)      AS mean_voltage,
               AVG(power_factor) AS mean_pf
        FROM meter_reading
        GROUP BY meter_id, bucket
        WITH NO DATA;
        """
    )

    op.execute(
        """
        CREATE MATERIALIZED VIEW IF NOT EXISTS dt_hourly
        WITH (timescaledb.continuous) AS
        SELECT dt_id,
               time_bucket(INTERVAL '1 hour', ts) AS bucket,
               SUM(kwh_in) AS kwh_in_total
        FROM dt_reading
        GROUP BY dt_id, bucket
        WITH NO DATA;
        """
    )

    # ---- Retention & compression (gentle prototype defaults) -------------

    op.execute(
        "SELECT add_compression_policy('meter_reading', INTERVAL '30 days', if_not_exists => TRUE);"
    )
    op.execute(
        "SELECT add_compression_policy('dt_reading', INTERVAL '30 days', if_not_exists => TRUE);"
    )
    op.execute(
        "SELECT add_retention_policy('meter_reading', INTERVAL '365 days', if_not_exists => TRUE);"
    )
    op.execute(
        "SELECT add_retention_policy('dt_reading', INTERVAL '365 days', if_not_exists => TRUE);"
    )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    for mv in ("dt_hourly", "meter_daily", "meter_hourly"):
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {mv};")

    for t in (
        "job_run", "injected_events", "ingest_errors", "audit_log",
        "inspection", "confidence", "flag", "feature_daily",
        "zone_risk", "forecast",
        "dt_reading", "meter_reading",
        "holiday", "tariff_slab", "consumer", "dt", "feeder",
    ):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE;")
