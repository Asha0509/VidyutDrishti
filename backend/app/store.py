"""In-memory data store for the live demo API.

Holds 15-minute meter readings, transformer (DT) input readings, topology and,
for the synthetic demo, the simulator's ground truth. All detection goes
through app.detection.scoring; results are cached per data version and date.
"""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

from app.detection.scoring import (FLAG_THRESHOLD, MeterScore, daily_from_slots, rank_queue,
                                   score_meters)
from app.evaluation import live as live_eval

# Bengaluru localities used to place the synthetic DTs on the map.
DT_LOCATIONS = [
    ("Bengaluru Central", 12.9716, 77.5946), ("Koramangala", 12.9279, 77.6271), ("Hebbal", 13.0358, 77.5970),
    ("HSR Layout", 12.9141, 77.6411), ("Yeshwanthpur", 13.0098, 77.5680), ("Indiranagar", 12.9634, 77.6455),
    ("Rajajinagar", 12.9784, 77.5408), ("Electronic City", 12.8456, 77.6603),
]


def infer_topology(meter_id: str) -> Dict[str, str]:
    """DT / feeder / zone from the meter id convention DT<n>-M<nn>."""
    parts = meter_id.split("-")
    if len(parts) >= 2 and parts[0].upper().startswith("DT") and parts[0][2:].isdigit():
        n = int(parts[0][2:])
        return {"dt_id": f"DT{n}", "feeder_id": f"F{n}", "zone": f"Zone{chr(64 + n)}"}
    return {"dt_id": "DT0", "feeder_id": "F0", "zone": "Unassigned"}


def dt_place(dt_id: str) -> Dict[str, Any]:
    digits = "".join(c for c in dt_id if c.isdigit())
    n = int(digits) if digits else 1
    name, lat, lng = DT_LOCATIONS[(n - 1) % len(DT_LOCATIONS)]
    return {"place": name, "lat": lat, "lng": lng}


class Store:
    def __init__(self, slot_kwh_is_daily_rate: bool = True) -> None:
        # The simulator records each 15-minute value as daily_total x diurnal
        # factor, so a day's slots sum to 96 x the daily total.
        self.slot_scale = 96.0 if slot_kwh_is_daily_rate else 1.0
        self._meter_frames: List[pd.DataFrame] = []
        self._dt_frames: List[pd.DataFrame] = []
        self.topology: Dict[str, Dict[str, str]] = {}
        self.truth: Dict[str, Any] = {"theft": {}, "theft_start": {}, "decoys": {}}
        self.feedback: List[Dict[str, Any]] = []
        self.ready = False
        self._version = 0
        self._cache: Dict[Any, Any] = {}
        self._lock = threading.RLock()

    # ── ingestion ──────────────────────────────────────────────────────
    def _bump(self) -> None:
        self._version += 1
        self._cache.clear()

    def add_meter_frame(self, df: pd.DataFrame) -> int:
        df = df[["meter_id", "ts", "kwh"]].copy()
        df["ts"] = pd.to_datetime(df["ts"])
        df = df[df["kwh"].isna() | (df["kwh"] >= 0)]
        with self._lock:
            self._meter_frames.append(df)
            for m in df["meter_id"].unique():
                self.topology.setdefault(m, infer_topology(m))
            self._bump()
        return len(df)

    def add_dt_frame(self, df: pd.DataFrame) -> int:
        df = df[["dt_id", "ts", "kwh_in"]].copy()
        df["ts"] = pd.to_datetime(df["ts"])
        with self._lock:
            self._dt_frames.append(df)
            self._bump()
        return len(df)

    def add_readings(self, rows: Iterable[Dict[str, Any]]) -> tuple[int, int, int]:
        rows = list(rows)
        valid = [r for r in rows if r.get("meter_id") and r.get("kwh") is not None and r["kwh"] >= 0]
        if valid:
            self.add_meter_frame(pd.DataFrame([{"meter_id": r["meter_id"], "ts": r["timestamp"], "kwh": r["kwh"]}
                                               for r in valid]))
        return len(rows), len(valid), len(valid)

    def set_truth(self, thefts: List[Dict], decoys: List[Dict], start: date) -> None:
        self.truth = {
            "theft": {t["meter_id"]: t["kind"] for t in thefts},
            "theft_start": {t["meter_id"]: start + timedelta(days=t["start_day"]) for t in thefts},
            "decoys": {d["meter_id"]: d["kind"] for d in decoys},
        }
        self._cache.clear()

    # ── derived data ───────────────────────────────────────────────────
    def readings(self) -> pd.DataFrame:
        with self._lock:
            key = ("readings", self._version)
            if key not in self._cache:
                self._cache[key] = (pd.concat(self._meter_frames, ignore_index=True)
                                    if self._meter_frames else pd.DataFrame(columns=["meter_id", "ts", "kwh"]))
            return self._cache[key]

    def daily(self) -> pd.DataFrame:
        with self._lock:
            key = ("daily", self._version)
            if key not in self._cache:
                r = self.readings()
                d = daily_from_slots(r) if not r.empty else pd.DataFrame(columns=["meter_id", "date", "kwh"])
                d["kwh"] = d["kwh"] / self.slot_scale
                self._cache[key] = d
            return self._cache[key]

    def dt_daily(self) -> Optional[pd.DataFrame]:
        with self._lock:
            key = ("dt_daily", self._version)
            if key not in self._cache:
                if not self._dt_frames:
                    self._cache[key] = None
                else:
                    df = pd.concat(self._dt_frames, ignore_index=True)
                    df["date"] = df["ts"].dt.date
                    out = df.groupby(["dt_id", "date"])["kwh_in"].sum().reset_index()
                    out["kwh_in"] /= self.slot_scale
                    self._cache[key] = out
            return self._cache[key]

    def topology_df(self) -> pd.DataFrame:
        return pd.DataFrame([{"meter_id": m, **t} for m, t in self.topology.items()])

    def dates(self) -> List[date]:
        d = self.daily()
        return sorted(d["date"].unique()) if not d.empty else []

    def resolve_date(self, target: Optional[date]) -> Optional[date]:
        ds = self.dates()
        if not ds:
            return None
        if target is None or target > ds[-1]:
            return ds[-1]
        return max([d for d in ds if d <= target], default=ds[0])

    def scores(self, target: Optional[date] = None) -> List[MeterScore]:
        target = self.resolve_date(target)
        if target is None:
            return []
        with self._lock:
            key = ("scores", self._version, target)
            if key not in self._cache:
                self._cache[key] = score_meters(self.daily(), self.topology_df(), target, self.dt_daily())
            return self._cache[key]

    # ── views used by the API ─────────────────────────────────────────
    def _status(self, meter_id: str, on: date) -> str:
        for fb in reversed(self.feedback):
            if fb["meter_id"] == meter_id:
                return "confirmed" if fb["was_anomaly"] else "dismissed"
        return "pending"

    def queue(self, target: Optional[date] = None, limit: int = 20) -> List[Dict[str, Any]]:
        scores = self.scores(target)
        items = []
        for i, s in enumerate(rank_queue(scores, limit), 1):
            fired = [l.name for l in s.layers if l.fired]
            items.append({
                "rank": i, "meter_id": s.meter_id, "dt_id": s.dt_id, "feeder_id": s.feeder_id, "zone": s.zone,
                "confidence": s.confidence, "tier": s.tier, "pattern": s.pattern,
                "estimated_inr_lost": s.est_monthly_loss_inr, "drop_pct": s.drop_pct,
                "baseline_kwh": s.baseline_kwh, "recent_kwh": s.recent_kwh, "category": s.category,
                "layers_fired": fired,
                "description": f"{s.drop_pct:.0f}% below its own baseline; {len(fired)} of 4 layers agree",
                "status": self._status(s.meter_id, s.date), "date": s.date,
            })
        return items

    def meter(self, meter_id: str, target: Optional[date] = None) -> Optional[Dict[str, Any]]:
        s = next((x for x in self.scores(target) if x.meter_id == meter_id), None)
        if s is None:
            return None
        d = self.daily()
        mine = d[d["meter_id"] == meter_id].set_index("date")["kwh"]
        peers = [m for m, t in self.topology.items() if t["dt_id"] == s.dt_id and m != meter_id]
        peer_med = d[d["meter_id"].isin(peers)].groupby("date")["kwh"].median()
        base = s.baseline_kwh
        series = [{"date": dt.isoformat(), "kwh": None if pd.isna(v) else round(float(v), 2),
                   "peer_median": round(float(peer_med.get(dt, float("nan"))), 2) if dt in peer_med.index else None,
                   "baseline": base} for dt, v in mine.items() if dt <= s.date]
        return {**s.to_dict(), "status": self._status(meter_id, s.date), "series": series,
                "peers": peers, **dt_place(s.dt_id)}

    def zones(self, target: Optional[date] = None) -> List[Dict[str, Any]]:
        scores = self.scores(target)
        q = {i["meter_id"]: i for i in self.queue(target, limit=1000)}
        out: Dict[str, Dict[str, Any]] = {}
        for s in scores:
            z = out.setdefault(s.zone, {"id": s.zone, "name": f"{s.zone} ({dt_place(s.dt_id)['place']})",
                                        "dt_id": s.dt_id, "feeder_id": s.feeder_id, **dt_place(s.dt_id),
                                        "meter_count": 0, "flagged": 0, "high": 0, "estimated_inr_lost": 0.0,
                                        "max_confidence": 0.0, "total_kwh_today": 0.0})
            z["meter_count"] += 1
            z["total_kwh_today"] += s.recent_kwh
            z["max_confidence"] = max(z["max_confidence"], s.confidence)
            if s.meter_id in q:
                z["flagged"] += 1
                z["high"] += s.tier == "HIGH"
                z["estimated_inr_lost"] += s.est_monthly_loss_inr
        for z in out.values():
            z["risk"] = "HIGH" if z["high"] else ("MEDIUM" if z["flagged"] >= 2 else ("REVIEW" if z["flagged"] else "LOW"))
            z["risk_score"] = round(z["max_confidence"], 3)
            z["pending_inspections"] = sum(1 for i in q.values() if i["zone"] == z["id"] and i["status"] == "pending")
            z["total_kwh_today"] = round(z["total_kwh_today"], 1)
            z["estimated_inr_lost"] = round(z["estimated_inr_lost"], 0)
        return sorted(out.values(), key=lambda z: (-z["estimated_inr_lost"], z["id"]))

    def overview(self, target: Optional[date] = None) -> Dict[str, Any]:
        scores = self.scores(target)
        q = self.queue(target, limit=1000)
        tiers: Dict[str, int] = {}
        patterns: Dict[str, int] = {}
        for i in q:
            tiers[i["tier"]] = tiers.get(i["tier"], 0) + 1
            patterns[i["pattern"]] = patterns.get(i["pattern"], 0) + 1
        layers = {n: sum(1 for s in scores for l in s.layers if l.name == n and l.fired)
                  for n in ("dt_balance", "self_history", "peer_comparison", "isolation_forest")}
        zones = self.zones(target)
        return {
            "date": (scores[0].date.isoformat() if scores else None),
            "meters": len(scores), "dts": len({s.dt_id for s in scores}),
            "flagged": len(q), "pending": sum(1 for i in q if i["status"] == "pending"),
            "estimated_monthly_loss_inr": round(sum(i["estimated_inr_lost"] for i in q), 0),
            "zones_at_risk": sum(1 for z in zones if z["risk"] in ("HIGH", "MEDIUM")), "zones": len(zones),
            "by_tier": tiers, "by_pattern": patterns, "layers_fired": layers,
            "confidence_histogram": [
                {"bucket": f"{b / 10:.1f}-{(b + 1) / 10:.1f}",
                 "meters": sum(1 for s in scores if b / 10 <= s.confidence < (b + 1) / 10 or (b == 9 and s.confidence == 1))}
                for b in range(10)],
        }

    def dt_balance(self, target: Optional[date] = None, days: int = 30) -> List[Dict[str, Any]]:
        """Daily input vs metered energy per DT, for the transformer chart."""
        dtd = self.dt_daily()
        if dtd is None:
            return []
        d = self.daily().merge(self.topology_df()[["meter_id", "dt_id"]], on="meter_id")
        metered = d.groupby(["dt_id", "date"])["kwh"].sum().reset_index()
        m = dtd.merge(metered, on=["dt_id", "date"], how="left")
        last = self.resolve_date(target)
        m = m[m["date"] <= last]
        cutoff = sorted(m["date"].unique())[-days:]
        m = m[m["date"].isin(cutoff)]
        m["unmetered_pct"] = 100 * (m["kwh_in"] - m["kwh"]) / m["kwh_in"]
        return [{"dt_id": r.dt_id, "date": r.date.isoformat(), "kwh_in": round(r.kwh_in, 1),
                 "kwh_metered": round(r.kwh, 1), "unmetered_pct": round(r.unmetered_pct, 2)} for r in m.itertuples()]

    def evaluation(self) -> Optional[Dict[str, Any]]:
        if not self.truth["theft"]:
            return None
        scores = self.scores()
        queue_ids = [i["meter_id"] for i in self.queue(limit=1000)]
        result = live_eval.compute(scores, self.truth["theft"], self.truth["decoys"], queue_ids)
        fb_conf = sum(1 for f in self.feedback if f["was_anomaly"])
        result["field_feedback"] = {"confirmed": fb_conf, "dismissed": len(self.feedback) - fb_conf}
        result["detection_lag_days"] = self._cache.get(("lag", self._version))
        return result

    def compute_detection_lag(self, step_days: int = 2) -> Dict[str, Any]:
        """Days from theft start to first flag (scans past dates; run in background)."""
        ds = self.dates()
        starts = self.truth["theft_start"]
        if not starts or not ds:
            return {}
        first = min(starts.values())
        flagged_by_date = {}
        for d in [x for x in ds if x >= first][::step_days] + [ds[-1]]:
            flagged_by_date[d] = {s.meter_id for s in self.scores(d) if s.confidence >= FLAG_THRESHOLD}
        lags = live_eval.detection_lag_days(flagged_by_date, starts)
        caught = [v for v in lags.values() if v is not None]
        out = {"per_meter": lags, "mean": round(sum(caught) / len(caught), 1) if caught else None,
               "step_days": step_days}
        self._cache[("lag", self._version)] = out
        return out

    def record_feedback(self, item: Dict[str, Any]) -> None:
        self.feedback.append({**item, "recorded_at": datetime.utcnow().isoformat()})


store = Store()
