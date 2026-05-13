"""Seed the in-memory store with synthetic meter data at startup.

The prototype API keeps readings in memory (see ``MockDataStore`` in
``app.api.routes``), so a fresh deployment starts empty and every restart
wipes it. When ``DEMO_SEED=1`` the API generates the same 60-day demo
dataset that ``ingest_simulator_data.py`` posts over HTTP, but loads it
directly into the store in a background thread so ``/health`` answers
immediately while seeding runs.
"""

from __future__ import annotations

import gc
import logging
import os
import sys
import threading
from datetime import date, timedelta
from pathlib import Path

import yaml

log = logging.getLogger("uvicorn.error")
SEED_CHUNK = 10_000

# Same theft layout as ingest_simulator_data.py: theft starts after ~day 20
# so the z-score layer has a clean baseline to compare against.
THEFT_SCENARIOS = [
    {"meter_id": "DT1-M03", "kind": "hook_bypass", "start_day": 20, "end_day": 60, "severity": 0.95},
    {"meter_id": "DT1-M05", "kind": "hook_bypass", "start_day": 20, "end_day": 60, "severity": 0.92},
    {"meter_id": "DT1-M06", "kind": "meter_stop", "start_day": 22, "end_day": 60, "severity": 0.90},
    {"meter_id": "DT3-M01", "kind": "hook_bypass", "start_day": 18, "end_day": 60, "severity": 0.93},
    {"meter_id": "DT3-M03", "kind": "gradual_tampering", "start_day": 20, "end_day": 60, "severity": 0.88},
    {"meter_id": "DT5-M02", "kind": "hook_bypass", "start_day": 25, "end_day": 60, "severity": 0.85},
    {"meter_id": "DT5-M04", "kind": "gradual_tampering", "start_day": 25, "end_day": 60, "severity": 0.80},
    {"meter_id": "DT7-M05", "kind": "hook_bypass", "start_day": 20, "end_day": 60, "severity": 0.94},
    {"meter_id": "DT7-M03", "kind": "meter_stop", "start_day": 21, "end_day": 60, "severity": 0.91},
    {"meter_id": "DT2-M02", "kind": "gradual_tampering", "start_day": 30, "end_day": 60, "severity": 0.72},
    {"meter_id": "DT4-M02", "kind": "hook_bypass", "start_day": 28, "end_day": 60, "severity": 0.82},
    {"meter_id": "DT4-M04", "kind": "gradual_tampering", "start_day": 28, "end_day": 60, "severity": 0.78},
    {"meter_id": "DT6-M04", "kind": "hook_bypass", "start_day": 18, "end_day": 60, "severity": 0.93},
    {"meter_id": "DT8-M02", "kind": "hook_bypass", "start_day": 18, "end_day": 60, "severity": 0.96},
]


def _simulator_dir() -> Path:
    """Locate the simulator package: repo root locally, /app in the Docker image."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "simulator" / "config.yaml").exists():
            return parent / "simulator"
    raise FileNotFoundError("simulator/config.yaml not found above " + __file__)


def build_demo_frame():
    """Generate the 60-day demo dataset as a DataFrame of valid readings."""
    sim_dir = _simulator_dir()
    if str(sim_dir.parent) not in sys.path:
        sys.path.insert(0, str(sim_dir.parent))
    from simulator.dataset import build_dataset
    from simulator.models import SimConfig

    raw = yaml.safe_load((sim_dir / "config.yaml").read_text())
    raw["days"] = 60
    raw["start_date"] = (date.today() - timedelta(days=59)).isoformat()
    raw["dt_count"] = 8
    raw["meters_per_dt"] = 6
    raw["theft_scenarios"] = THEFT_SCENARIOS

    df = build_dataset(SimConfig.from_dict(raw))["meter_readings"][["meter_id", "ts", "kwh"]]
    return df[df["kwh"].notna() & (df["kwh"].abs() < 1e10)]


def _seed() -> None:
    from app.api.routes import BatchIngestRequest, store

    try:
        df = build_demo_frame()
        written = 0
        # Load in chunks so only one chunk of request objects is alive at a
        # time, which keeps peak memory down on a small instance.
        for start in range(0, len(df), SEED_CHUNK):
            chunk = [
                BatchIngestRequest(
                    meter_id=row.meter_id, timestamp=row.ts.isoformat(),
                    kwh=float(row.kwh), voltage=230.0, pf=0.95,
                )
                for row in df.iloc[start:start + SEED_CHUNK].itertuples(index=False)
            ]
            written += store.add_readings(chunk)[2]
        del df, chunk
        gc.collect()
        log.info("demo seed: loaded %d readings", written)
        store.get_queue(date.today())  # warm the queue cache before the first visitor
        gc.collect()
        log.info("demo seed: queue cache warmed")
    except Exception:
        log.exception("demo seed failed; the API is up but has no data")


def start_demo_seed_if_enabled() -> None:
    """Kick off background seeding when DEMO_SEED=1."""
    if os.environ.get("DEMO_SEED") != "1":
        return
    threading.Thread(target=_seed, name="demo-seed", daemon=True).start()
