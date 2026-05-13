"""Top-level dataset builder.

`build_dataset` returns four DataFrames:
  * consumers     - one row per meter (dt_id, category, tariff_category)
  * dts           - one row per DT
  * meter_readings- long table (meter_id, ts, kwh, voltage, power_factor, missing)
  * dt_readings   - long table (dt_id, ts, kwh_in)
  * injected_events - ground truth used by the evaluation harness
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .load_model import build_daily_multiplier, build_diurnal_profile, resolve_holidays, slot_timestamps
from .models import SimConfig
from .scenarios import apply_decoy, apply_theft


# ---------------------------------------------------------------------------
# Topology
# ---------------------------------------------------------------------------

def _build_topology(cfg: SimConfig, rng: np.random.Generator) -> pd.DataFrame:
    rows: list[dict] = []
    categories = list(cfg.category_mix.keys())
    probs = np.array([cfg.category_mix[c] for c in categories], dtype=np.float64)

    for d in range(1, cfg.dt_count + 1):
        dt_id = f"DT{d}"
        chosen = rng.choice(categories, size=cfg.meters_per_dt, p=probs)
        for m in range(1, cfg.meters_per_dt + 1):
            rows.append({
                "meter_id": f"{dt_id}-M{m:02d}",
                "dt_id": dt_id,
                "feeder_id": f"F{d}",
                "tariff_category": chosen[m - 1],
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Load generation
# ---------------------------------------------------------------------------

def _simulate_meter(
    cfg: SimConfig,
    rng: np.random.Generator,
    dates: list[date],
    holidays_set: set[date],
    category: str,
) -> np.ndarray:
    """Return a 1-D kWh array of length ``days * slots_per_day`` for one meter."""
    slots = cfg.slots_per_day
    daily_mean = cfg.daily_kwh_mean[category]
    daily_std = cfg.daily_kwh_std[category]

    diurnal = build_diurnal_profile(cfg, category)                           # (slots,)
    day_mult = build_daily_multiplier(cfg, category, dates, holidays_set)    # (days,)

    # Per-day total energy (clipped to a small floor so the shape is never negative)
    daily_totals = rng.normal(loc=daily_mean, scale=daily_std, size=cfg.days)
    daily_totals = np.clip(daily_totals, a_min=0.1 * daily_mean, a_max=None)
    daily_totals = daily_totals * day_mult

    # Convert daily totals to per-slot energy using the diurnal profile.
    # Diurnal profile averages to 1.0, so slot energy = (daily_total / slots) * profile.
    per_slot = np.outer(daily_totals, diurnal / diurnal.sum() * slots).reshape(-1)
    # Equivalent: per_slot.reshape(days, slots).sum(axis=1) == daily_totals

    # Multiplicative Gaussian noise
    noise = rng.normal(loc=1.0, scale=cfg.noise_std_fraction, size=per_slot.shape)
    per_slot = np.clip(per_slot * noise, a_min=0.0, a_max=None)
    return per_slot


# ---------------------------------------------------------------------------
# Quality layer: voltage, PF, missing injection
# ---------------------------------------------------------------------------

def _sample_voltage(cfg: SimConfig, rng: np.random.Generator, n: int) -> np.ndarray:
    v = rng.normal(loc=cfg.voltage_mean, scale=cfg.voltage_std, size=n)
    return np.clip(v, cfg.voltage_min, cfg.voltage_max)


def _sample_pf(cfg: SimConfig, rng: np.random.Generator, category: str, n: int) -> np.ndarray:
    lo, hi = cfg.pf_range[category]
    return rng.uniform(low=lo, high=hi, size=n)


def _inject_missing(
    kwh: np.ndarray,
    cfg: SimConfig,
    rng: np.random.Generator,
) -> np.ndarray:
    """Return a boolean mask (True = missing) with approximate gap-length mix."""
    n = len(kwh)
    slots_per_hour = 60 // cfg.slot_minutes
    mask = np.zeros(n, dtype=bool)

    # Short gaps: single-slot events (< 1h means 1-3 slots)
    short = rng.random(n) < cfg.missing_short_prob
    mask |= short

    # Medium gaps: 1-6h, introduced as contiguous runs starting at random points.
    # Expected number of medium gap *starts* per meter.
    expected_medium = cfg.missing_medium_prob * n
    n_medium = int(rng.poisson(expected_medium))
    for _ in range(n_medium):
        start = int(rng.integers(0, max(n - 1, 1)))
        length = int(rng.integers(slots_per_hour, 6 * slots_per_hour + 1))
        mask[start : start + length] = True

    # Long gaps: >6h, rarer
    expected_long = cfg.missing_long_prob * n
    n_long = int(rng.poisson(expected_long))
    for _ in range(n_long):
        start = int(rng.integers(0, max(n - 1, 1)))
        length = int(rng.integers(6 * slots_per_hour + 1, 24 * slots_per_hour + 1))
        mask[start : start + length] = True

    return mask


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def _build_meter_readings(
    cfg: SimConfig,
    rng: np.random.Generator,
    topo: pd.DataFrame,
    dates: list[date],
    holidays_set: set[date],
    ts: np.ndarray,
) -> tuple[pd.DataFrame, list[dict], dict[str, np.ndarray]]:
    """Generate the long meter-reading frame and return it alongside the
    per-DT running sum of (nan-filled) kWh that the DT builder will
    consume. This avoids re-materialising the merge + group-by on the
    combined long frame.
    """
    theft_by_meter = {s.meter_id: s for s in cfg.theft_scenarios}
    decoy_by_meter = {d.meter_id: d for d in cfg.decoys}

    n_slots = cfg.days * cfg.slots_per_day
    dt_sum: dict[str, np.ndarray] = {
        dt_id: np.zeros(n_slots, dtype=np.float64) for dt_id in sorted(topo["dt_id"].unique())
    }

    meter_frames: list[pd.DataFrame] = []
    injected_rows: list[dict] = []

    for _, m in topo.iterrows():
        mid = m["meter_id"]
        cat = m["tariff_category"]
        dt_id = m["dt_id"]
        base_kwh = _simulate_meter(cfg, rng, dates, holidays_set, cat)

        # Decoys (vacancy etc.) genuinely reduce what the premises consumes,
        # so they apply before the transformer sees the load.
        if mid in decoy_by_meter:
            d = decoy_by_meter[mid]
            base_kwh = apply_decoy(base_kwh, cfg, d)
            injected_rows.append({"meter_id": mid, "event_type": "decoy", **asdict(d)})

        # Energy actually drawn through the transformer. Theft hides consumption
        # from the meter, not from the transformer, so it is captured here first.
        true_kwh = base_kwh.copy()

        if mid in theft_by_meter:
            s = theft_by_meter[mid]
            base_kwh = apply_theft(base_kwh, cfg, s)
            injected_rows.append({"meter_id": mid, "event_type": "theft", **asdict(s)})

        voltage = _sample_voltage(cfg, rng, len(base_kwh))
        pf = _sample_pf(cfg, rng, cat, len(base_kwh))
        missing = _inject_missing(base_kwh, cfg, rng)

        kwh = base_kwh.copy()
        kwh[missing] = np.nan
        voltage[missing] = np.nan
        pf[missing] = np.nan

        # DT input is the true load (unaffected by theft or by missing meter
        # reads), so stolen energy shows up as an energy-balance gap (Layer 0).
        dt_sum[dt_id] += true_kwh

        meter_frames.append(pd.DataFrame({
            "meter_id": mid,
            "ts": ts,
            "kwh": kwh,
            "voltage": voltage,
            "power_factor": pf,
            "missing": missing,
        }))

    return pd.concat(meter_frames, ignore_index=True), injected_rows, dt_sum


def _build_dt_readings(
    cfg: SimConfig,
    rng: np.random.Generator,
    ts: np.ndarray,
    dt_sum: dict[str, np.ndarray],
) -> pd.DataFrame:
    """DT-level `kwh_in` = true consumption * (1 + technical_loss), with loss
    drawn per DT and jittered per slot. Because the true consumption includes
    stolen energy, `kwh_in - sum(metered)` grows when theft starts.
    """
    jitter_std = 0.005
    frames: list[pd.DataFrame] = []
    for dt_id in sorted(dt_sum.keys()):
        meter_sum = dt_sum[dt_id]
        base_loss = float(rng.uniform(cfg.dt_technical_loss_min, cfg.dt_technical_loss_max))
        jitter = rng.normal(loc=0.0, scale=jitter_std, size=len(meter_sum))
        loss = np.clip(base_loss + jitter, 0.0, 0.15)
        kwh_in = meter_sum * (1.0 + loss)
        frames.append(pd.DataFrame({"dt_id": dt_id, "ts": ts, "kwh_in": kwh_in}))
    return pd.concat(frames, ignore_index=True)


def build_dataset(cfg: SimConfig) -> dict[str, pd.DataFrame]:
    """Generate the full synthetic dataset and return it as DataFrames."""
    rng = np.random.default_rng(cfg.seed)
    topo = _build_topology(cfg, rng)

    dates = [cfg.start_date + timedelta(days=i) for i in range(cfg.days)]
    holidays_set = resolve_holidays(cfg)
    ts = slot_timestamps(cfg.start_date, cfg.days, cfg.slot_minutes)

    meter_readings, injected_rows, dt_sum = _build_meter_readings(
        cfg, rng, topo, dates, holidays_set, ts
    )
    dt_readings = _build_dt_readings(cfg, rng, ts, dt_sum)

    dts = pd.DataFrame({
        "dt_id": sorted(topo["dt_id"].unique()),
        "feeder_id": [f"F{i+1}" for i in range(topo["dt_id"].nunique())],
    })

    injected_events = pd.DataFrame(injected_rows) if injected_rows else pd.DataFrame(
        columns=["meter_id", "event_type", "kind", "start_day", "end_day", "severity"]
    )

    return {
        "consumers": topo,
        "dts": dts,
        "meter_readings": meter_readings,
        "dt_readings": dt_readings,
        "injected_events": injected_events,
    }
