"""Load-shape helpers: diurnal, seasonal, weekly, holiday multipliers."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np

from .models import SimConfig


def slot_timestamps(start: date, days: int, slot_minutes: int) -> np.ndarray:
    """Return a flat array of ``datetime`` objects for every slot in the window."""
    slots_per_day = (24 * 60) // slot_minutes
    total = days * slots_per_day
    base = datetime(start.year, start.month, start.day)
    return np.array(
        [base + timedelta(minutes=i * slot_minutes) for i in range(total)],
        dtype=object,
    )


def resolve_holidays(cfg: SimConfig) -> set[date]:
    """Resolve the holiday set.

    Priority:
      1. If ``cfg.holiday_dates`` is a non-null list, use it verbatim.
      2. Else try to import the ``holidays`` package and query IN / KA.
      3. Else return an empty set (generator still runs, just no holiday dips).
    """
    if cfg.holiday_dates:
        return {datetime.strptime(d, "%Y-%m-%d").date() for d in cfg.holiday_dates}

    try:
        import holidays as _hols  # type: ignore[import-not-found]
    except ImportError:
        return set()

    end = cfg.start_date + timedelta(days=cfg.days)
    years = list(range(cfg.start_date.year, end.year + 1))
    try:
        in_hols = _hols.country_holidays("IN", subdiv="KA", years=years)
    except Exception:
        in_hols = _hols.country_holidays("IN", years=years)
    return {d for d in in_hols if cfg.start_date <= d < end}


def build_daily_multiplier(
    cfg: SimConfig, category: str, dates: list[date], holidays_set: set[date]
) -> np.ndarray:
    """Per-day multiplier stacking season, weekday and holiday effects."""
    mult = np.ones(len(dates), dtype=np.float64)
    for i, d in enumerate(dates):
        m = 1.0
        if d.month in cfg.summer_months:
            m *= cfg.summer_multiplier
        if d.month in cfg.monsoon_months:
            m *= cfg.monsoon_multiplier
        if d.weekday() >= 5:  # Sat/Sun
            m *= cfg.weekend_multiplier[category]
        if d in holidays_set:
            m *= cfg.holiday_multiplier
        mult[i] = m
    return mult


def build_diurnal_profile(cfg: SimConfig, category: str) -> np.ndarray:
    """Return an array of length ``slots_per_day`` averaging to 1.0."""
    hourly = np.array(cfg.diurnal_weights[category], dtype=np.float64)
    hourly = hourly / hourly.mean()  # normalise
    slots_per_hour = 60 // cfg.slot_minutes
    slot_profile = np.repeat(hourly, slots_per_hour)
    # Final re-normalise so the *slot* profile averages 1.0 exactly.
    slot_profile = slot_profile / slot_profile.mean()
    return slot_profile
