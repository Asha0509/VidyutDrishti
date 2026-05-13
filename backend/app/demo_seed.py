"""Seed the in-memory store with synthetic meter data at startup.

The live API keeps readings in memory (``app.store``), so a fresh deploy
starts empty. When ``DEMO_SEED=1`` the API generates a 60-day synthetic
network (48 meters on 8 transformers, with injected thefts and decoys) in a
background thread so ``/health`` answers immediately while seeding runs.
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


# Legitimate drops (vacant premises) that a detector should NOT flag. Two sit
# on transformers that also have a theft, which makes them harder.
DECOYS = [
    {"meter_id": "DT2-M05", "kind": "vacancy", "start_day": 30, "end_day": 60, "severity": 0.85},
    {"meter_id": "DT5-M06", "kind": "vacancy", "start_day": 35, "end_day": 60, "severity": 0.90},
    {"meter_id": "DT8-M04", "kind": "vacancy", "start_day": 25, "end_day": 60, "severity": 0.80},
]


def build_demo_dataset():
    """Generate the 60-day demo network: meters, DT input and ground truth."""
    sim_dir = _simulator_dir()
    if str(sim_dir.parent) not in sys.path:
        sys.path.insert(0, str(sim_dir.parent))
    from simulator.dataset import build_dataset
    from simulator.models import SimConfig

    start = date.today() - timedelta(days=59)
    raw = yaml.safe_load((sim_dir / "config.yaml").read_text())
    raw.update(days=60, start_date=start.isoformat(), dt_count=8, meters_per_dt=6,
               theft_scenarios=THEFT_SCENARIOS, decoys=DECOYS)
    return build_dataset(SimConfig.from_dict(raw)), start


def _seed() -> None:
    from app.store import store

    try:
        ds, start = build_demo_dataset()
        store.add_meter_frame(ds["meter_readings"][["meter_id", "ts", "kwh"]])
        store.add_dt_frame(ds["dt_readings"][["dt_id", "ts", "kwh_in"]])
        store.set_truth(THEFT_SCENARIOS, DECOYS, start)
        del ds
        gc.collect()
        store.queue()  # warm the cache before the first visitor
        store.ready = True
        log.info("demo seed: %d meters, %d days loaded", len(store.topology), len(store.dates()))
        lag = store.compute_detection_lag()
        log.info("demo seed: detection lag computed (mean %s days)", lag.get("mean"))
    except Exception:
        store.ready = True
        log.exception("demo seed failed; the API is up but has no data")


def start_demo_seed_if_enabled() -> None:
    """Kick off background seeding when DEMO_SEED=1."""
    if os.environ.get("DEMO_SEED") != "1":
        return
    threading.Thread(target=_seed, name="demo-seed", daemon=True).start()
