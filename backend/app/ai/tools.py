"""Data tools the AI agents can call. Every number they return comes from the store.

Outputs are kept compact (rounded, truncated) to keep prompts small.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional

from app import store as store_mod

DETECTION_REPORT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "evals", "results", "detection.json")


def _store():
    return store_mod.store


def get_overview() -> Dict[str, Any]:
    o = _store().overview()
    return {k: o[k] for k in ("date", "meters", "dts", "flagged", "pending", "estimated_monthly_loss_inr",
                              "zones_at_risk", "zones", "by_tier", "by_pattern")}


def list_zones() -> Dict[str, Any]:
    return {"zones": [{"zone": z["id"], "place": z["place"], "dt_id": z["dt_id"], "risk": z["risk"],
                       "meters": z["meter_count"], "flagged": z["flagged"], "high_risk": z["high"],
                       "estimated_monthly_loss_inr": z["estimated_inr_lost"]} for z in _store().zones()]}


def get_queue(limit: int = 10, zone: Optional[str] = None, tier: Optional[str] = None) -> Dict[str, Any]:
    items = _store().queue(limit=1000)
    if zone:
        items = [i for i in items if i["zone"].lower() == zone.lower() or i["dt_id"].lower() == zone.lower()]
    if tier:
        items = [i for i in items if i["tier"] == tier.upper()]
    return {"total": len(items), "items": [
        {"rank": i["rank"], "meter_id": i["meter_id"], "zone": i["zone"], "dt_id": i["dt_id"], "tier": i["tier"],
         "confidence": i["confidence"], "pattern": i["pattern"], "drop_pct": i["drop_pct"],
         "estimated_monthly_loss_inr": i["estimated_inr_lost"], "status": i["status"]}
        for i in items[:max(1, min(int(limit), 50))]]}


def find_meters(zone: Optional[str] = None, tier: Optional[str] = None, pattern: Optional[str] = None,
                min_drop_pct: Optional[float] = None, flagged_only: bool = False) -> Dict[str, Any]:
    out = []
    for s in _store().scores():
        if zone and zone.lower() not in (s.zone.lower(), s.dt_id.lower()):
            continue
        if tier and s.tier != tier.upper():
            continue
        if pattern and s.pattern != pattern:
            continue
        if min_drop_pct is not None and s.drop_pct < float(min_drop_pct):
            continue
        if flagged_only and not s.flagged:
            continue
        out.append({"meter_id": s.meter_id, "zone": s.zone, "category": s.category, "tier": s.tier,
                    "confidence": s.confidence, "pattern": s.pattern, "drop_pct": s.drop_pct})
    return {"count": len(out), "meters": out[:40]}


def get_meter(meter_id: str, days: int = 42) -> Dict[str, Any]:
    m = _store().meter(str(meter_id).upper())
    if m is None:
        return {"error": f"no meter called {meter_id}; ids look like DT1-M03"}
    series = m["series"][-days:]
    return {
        "meter_id": m["meter_id"], "dt_id": m["dt_id"], "zone": m["zone"], "category": m["category"],
        "confidence": m["confidence"], "tier": m["tier"], "flagged": m["flagged"], "pattern": m["pattern"],
        "baseline_kwh_per_day": m["baseline_kwh"], "recent_kwh_per_day": m["recent_kwh"], "drop_pct": m["drop_pct"],
        "estimated_monthly_loss_inr": m["est_monthly_loss_inr"], "inspection_status": m["status"],
        "layers": [{"layer": l["name"], "fired": l["fired"], "detail": l["detail"]} for l in m["layers"]],
        "daily_kwh": [s["kwh"] for s in series],
        "peer_median_kwh": [s["peer_median"] for s in series],
        "first_date": series[0]["date"] if series else None,
    }


def get_dt_balance(dt_id: str, days: int = 28) -> Dict[str, Any]:
    rows = [r for r in _store().dt_balance(days=max(7, min(int(days), 60))) if r["dt_id"].lower() == str(dt_id).lower()]
    if not rows:
        return {"error": f"no transformer called {dt_id}; ids look like DT3"}
    return {"dt_id": rows[0]["dt_id"], "first_date": rows[0]["date"],
            "input_kwh": [r["kwh_in"] for r in rows], "metered_kwh": [r["kwh_metered"] for r in rows],
            "unmetered_pct": [r["unmetered_pct"] for r in rows]}


def detection_quality() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if os.path.isfile(DETECTION_REPORT):
        with open(DETECTION_REPORT) as f:
            r = json.load(f)
        out["held_out"] = {"networks": r["networks"], "precision": r["precision"]["mean"],
                           "recall": r["recall"]["mean"], "f1": r["f1_score"]["mean"],
                           "note": "mean over unseen random synthetic networks"}
    ev = _store().evaluation()
    if ev:
        out["this_dataset"] = {k: ev[k] for k in ("precision", "recall", "f1_score", "precision_at_10",
                                                 "decoys_flagged", "missed_thefts")}
        lag = ev.get("detection_lag_days") or {}
        out["this_dataset"]["mean_detection_lag_days"] = lag.get("mean")
    return out


def get_alerts(days: int = 7) -> Dict[str, Any]:
    from app.ai import alerts
    items = alerts.alerts(days=max(1, min(int(days), 14)))
    return {"count": len(items), "alerts": [{k: a[k] for k in ("date", "type", "severity", "title")} for a in items[:25]]}


TOOLS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "get_overview": get_overview, "list_zones": list_zones, "get_queue": get_queue, "find_meters": find_meters,
    "get_meter": get_meter, "get_dt_balance": get_dt_balance, "detection_quality": detection_quality,
    "get_alerts": get_alerts,
}

_TIER = {"type": "string", "enum": ["HIGH", "MEDIUM", "REVIEW", "NORMAL"]}
_PATTERN = {"type": "string", "enum": ["flatline", "sudden_drop", "gradual_decline", "consumption_drop", "normal"]}


def _fn(name: str, description: str, props: Dict[str, Any] | None = None, required: List[str] | None = None) -> Dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": props or {}, "required": required or []}}}


SPECS = {
    "get_overview": _fn("get_overview", "Network headline numbers: meters, flagged, pending inspections, "
                        "estimated monthly loss (INR), counts by risk tier and pattern."),
    "list_zones": _fn("list_zones", "Every zone (one transformer each) with risk, flagged meters and estimated loss."),
    "get_queue": _fn("get_queue", "The inspection queue, highest expected recoverable rupees first.",
                     {"limit": {"type": "integer"}, "zone": {"type": "string", "description": "e.g. ZoneC or DT3"},
                      "tier": _TIER}),
    "find_meters": _fn("find_meters", "Filter meters by zone, risk tier, pattern or minimum drop.",
                       {"zone": {"type": "string"}, "tier": _TIER, "pattern": _PATTERN,
                        "min_drop_pct": {"type": "number"}, "flagged_only": {"type": "boolean"}}),
    "get_meter": _fn("get_meter", "One meter in detail: score, each detection layer's evidence, and its daily "
                     "kWh for the last weeks next to the median of its transformer peers.",
                     {"meter_id": {"type": "string", "description": "e.g. DT1-M03"}}, ["meter_id"]),
    "get_dt_balance": _fn("get_dt_balance", "Daily energy entering a transformer vs energy its meters recorded, "
                          "and the unmetered percentage.", {"dt_id": {"type": "string", "description": "e.g. DT3"}},
                          ["dt_id"]),
    "detection_quality": _fn("detection_quality", "Measured precision, recall and F1 of the detector."),
    "get_alerts": _fn("get_alerts", "Recent alerts (new flags, escalations, transformer balance jumps).",
                      {"days": {"type": "integer"}}),
}


def run(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    fn = TOOLS.get(name)
    if fn is None:
        return {"error": f"unknown tool {name}"}
    try:
        return fn(**{k: v for k, v in (args or {}).items() if not k.startswith("_")})
    except TypeError as exc:
        return {"error": f"bad arguments for {name}: {exc}"}
