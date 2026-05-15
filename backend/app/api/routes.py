"""VidyutDrishti API (v1).

Detection runs through app.detection.scoring via the in-memory store. Every
number returned here is computed from the ingested data; nothing is
hardcoded. Evaluation metrics are measured against the simulator's ground
truth and against a held-out set of unseen synthetic networks.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from typing import Any, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.store import store

router = APIRouter()

DETECTION_REPORT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "evals", "results", "detection.json")


# ── Models ──────────────────────────────────────────────────────────────

class BatchIngestRequest(BaseModel):
    """One 15-minute meter reading."""
    meter_id: str
    timestamp: str
    kwh: float
    voltage: float | None = None
    pf: float | None = None


class DTIngestRequest(BaseModel):
    """One 15-minute transformer input reading."""
    dt_id: str
    timestamp: str
    kwh_in: float = Field(ge=0)


class BatchIngestResponse(BaseModel):
    records_received: int
    records_valid: int
    records_written: int


class FeedbackRequest(BaseModel):
    meter_id: str
    inspection_date: date
    was_anomaly: bool
    actual_kwh_observed: float | None = None
    notes: str | None = Field(None, max_length=1000)


class FeedbackResponse(BaseModel):
    success: bool
    message: str


def _need_data() -> None:
    if not store.dates():
        detail = "Demo data is still loading. Try again in a minute." if not store.ready else "No meter data ingested yet."
        raise HTTPException(status_code=503, detail=detail)


# ── Ingestion ───────────────────────────────────────────────────────────

@router.post("/ingest/batch", response_model=BatchIngestResponse)
async def ingest_batch(readings: list[BatchIngestRequest]) -> BatchIngestResponse:
    """Ingest 15-minute meter readings."""
    received, valid, written = store.add_readings(r.model_dump() for r in readings)
    return BatchIngestResponse(records_received=received, records_valid=valid, records_written=written)


@router.post("/ingest/dt-batch", response_model=BatchIngestResponse)
async def ingest_dt_batch(readings: list[DTIngestRequest]) -> BatchIngestResponse:
    """Ingest 15-minute transformer input readings (enables the energy-balance layer)."""
    if readings:
        store.add_dt_frame(pd.DataFrame([{"dt_id": r.dt_id, "ts": r.timestamp, "kwh_in": r.kwh_in} for r in readings]))
    return BatchIngestResponse(records_received=len(readings), records_valid=len(readings),
                               records_written=len(readings))


# ── Detection views ─────────────────────────────────────────────────────

@router.get("/overview")
async def overview(target_date: Optional[date] = None) -> dict[str, Any]:
    """Headline numbers for the dashboard."""
    _need_data()
    return store.overview(target_date)


@router.get("/queue/daily")
async def daily_queue(target_date: Optional[date] = None, limit: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    """Meters to inspect, highest expected recoverable rupees first."""
    _need_data()
    items = store.queue(target_date, limit)
    return {"date": store.resolve_date(target_date), "total_items": len(items),
            "pending_items": sum(1 for i in items if i["status"] == "pending"), "items": items}


@router.get("/meters")
async def list_meters(target_date: Optional[date] = None) -> dict[str, Any]:
    """Every meter with its score summary (for search and the copilot)."""
    _need_data()
    return {"meters": [{"meter_id": s.meter_id, "dt_id": s.dt_id, "zone": s.zone, "category": s.category,
                        "confidence": s.confidence, "tier": s.tier, "pattern": s.pattern, "drop_pct": s.drop_pct,
                        "flagged": s.flagged} for s in store.scores(target_date)]}


@router.get("/meters/{meter_id}/status")
async def meter_status(meter_id: str, target_date: Optional[date] = None) -> dict[str, Any]:
    """Full explanation for one meter: score, each layer's evidence, daily series vs peers."""
    _need_data()
    m = store.meter(meter_id.upper(), target_date)
    if m is None:
        raise HTTPException(status_code=404, detail=f"No meter called {meter_id}. Meter ids look like DT1-M03.")
    return m


@router.get("/zones/summary")
async def zones_summary(target_date: Optional[date] = None) -> dict[str, Any]:
    _need_data()
    return {"date": store.resolve_date(target_date), "zones": store.zones(target_date)}


@router.get("/dt/balance")
async def dt_balance(target_date: Optional[date] = None, days: int = Query(30, ge=7, le=90)) -> dict[str, Any]:
    """Transformer input vs metered energy per day (the Layer 0 evidence)."""
    _need_data()
    return {"rows": store.dt_balance(target_date, days)}


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(feedback: FeedbackRequest) -> FeedbackResponse:
    """Record an inspection outcome. Shown on the queue and counted in field metrics."""
    _need_data()
    if feedback.meter_id not in store.topology:
        raise HTTPException(status_code=404, detail=f"No meter called {feedback.meter_id}.")
    store.record_feedback(feedback.model_dump(mode="json"))
    outcome = "theft confirmed" if feedback.was_anomaly else "no theft found"
    return FeedbackResponse(success=True, message=f"Recorded for {feedback.meter_id}: {outcome}.")


# ── Forecast ────────────────────────────────────────────────────────────

@router.get("/forecast/{feeder_id}")
async def forecast(feeder_id: str) -> dict[str, Any]:
    """24-hour feeder demand forecast from the seasonal baseline model."""
    _need_data()
    from app.forecast.engine import FeederForecaster

    r = store.readings()
    r = r.assign(feeder_id=r["meter_id"].map(lambda m: store.topology.get(m, {}).get("feeder_id")))
    feeder = r[r["feeder_id"] == feeder_id]
    if feeder.empty:
        raise HTTPException(status_code=404, detail=f"No feeder called {feeder_id}.")
    hist = (feeder.groupby("ts")["kwh"].sum().reset_index()
            .rename(columns={"ts": "timestamp", "kwh": "kw"}).assign(feeder_id=feeder_id))
    if len(hist) < 96 * 7:
        raise HTTPException(status_code=422, detail="At least 7 days of readings are needed to forecast.")
    # Readings use the simulator's per-slot daily-rate convention (kWh/day);
    # divide by 24 to express demand in kW.
    hist["kw"] = hist["kw"] / (store.slot_scale / 4.0) if store.slot_scale > 1 else hist["kw"] * 4.0
    try:
        result = FeederForecaster(history_days=90).fit(hist).predict(feeder_id).to_dict()
    except Exception as exc:  # report it instead of inventing a curve
        raise HTTPException(status_code=500, detail=f"Forecast model failed: {type(exc).__name__}")
    history = hist.set_index("timestamp")["kw"].iloc[-96:]
    return {
        "feeder_id": feeder_id,
        "created_at": result["created_at"],
        "peak_forecast_kw": result["peak_forecast_kw"],
        # Demand can't be negative; the model's symmetric band can dip below zero at night.
        "points": [{**p, "lower_kw": max(0.0, p["lower_kw"])} for p in result["points"]],
        "history": [{"timestamp": ts.isoformat(), "kw": round(float(v), 2)} for ts, v in history.items()],
        "source": "Seasonal baseline: same weekday and time of day over the last 4 weeks, plus a 30-day trend.",
    }


# ── Metrics ─────────────────────────────────────────────────────────────

@router.get("/metrics/evaluation")
async def evaluation() -> dict[str, Any]:
    """Measured detection quality.

    `demo`: this dataset scored against the simulator's own ground truth
    (the scoring was developed on it, so treat as optimistic).
    `held_out`: mean over unseen randomly generated networks
    (evals/detection_eval.py), the number to quote.
    """
    _need_data()
    held_out = None
    if os.path.isfile(DETECTION_REPORT):
        with open(DETECTION_REPORT) as f:
            rep = json.load(f)
        held_out = {k: rep[k] for k in ("run_at", "networks", "setup", "precision", "recall", "f1_score",
                                        "precision_at_10", "decoys_flagged_rate", "by_theft_kind", "threshold_sweep")}
    return {"demo": store.evaluation(), "held_out": held_out}


class ROIProjection(BaseModel):
    bescom_consumers: int
    current_atc_loss_pct: float
    detection_rate: float
    avg_monthly_theft_inr: int
    monthly_recovery_inr: int
    annual_recovery_inr: int
    inspector_cost_saved_pct: float
    payback_months: float
    five_year_npv_cr: float
    assumptions: list[str]


@router.get("/metrics/roi", response_model=ROIProjection)
async def roi(
    detection_rate: float = Query(0.85, ge=0.0, le=1.0),
    avg_monthly_theft_inr: int = Query(3500, ge=0),
    atc_loss_pct: float = Query(17.0, ge=0.0, le=100.0),
) -> ROIProjection:
    """Illustrative ROI for a BESCOM-scale rollout. Every input is an assumption, listed in the response."""
    consumers = 8_500_000
    theft_prevalence = 0.015
    detected = int(consumers * theft_prevalence * detection_rate)
    monthly = detected * avg_monthly_theft_inr
    annual = monthly * 12
    platform_cost_cr = 15.0
    annual_cr = annual / 1e7
    npv = sum((annual_cr - platform_cost_cr) / (1.10 ** y) for y in range(1, 6))
    return ROIProjection(
        bescom_consumers=consumers, current_atc_loss_pct=atc_loss_pct, detection_rate=detection_rate,
        avg_monthly_theft_inr=avg_monthly_theft_inr, monthly_recovery_inr=monthly, annual_recovery_inr=annual,
        inspector_cost_saved_pct=65.0,
        payback_months=round(platform_cost_cr * 12 / max(annual_cr, 0.01), 2), five_year_npv_cr=round(npv, 2),
        assumptions=[
            "8.5 million consumers (BESCOM scale)",
            "1.5% of consumers stealing (audits suggest 1-2%)",
            "Platform cost ₹15 crore a year",
            "65% fewer wasted inspections from a ranked queue (assumed, not measured)",
            "10% discount rate over 5 years",
        ],
    )
