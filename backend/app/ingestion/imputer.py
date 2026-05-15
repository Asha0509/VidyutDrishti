"""Gap imputation for meter_reading and dt_reading time series.

Policy (matches Feature 04 in `docs/features.md`):
  * Gap < 1 hour  -> linear interpolation, mark imputed = True.
  * Gap 1-6 hour  -> carry-forward of the per-meter diurnal mean at
                      that slot (pragmatic prototype choice; Prophet
                      does a better job but is too heavy for the
                      ingestion path).
  * Gap > 6 hours -> leave NaN. Downstream layers will treat the meter
                      as having a data outage for that period and skip
                      detection rather than raise a false positive.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


SHORT_GAP_MAX_MINUTES = 60
MEDIUM_GAP_MAX_MINUTES = 6 * 60


@dataclass
class ImputeResult:
    frame: pd.DataFrame
    n_short_imputed: int
    n_medium_imputed: int
    n_long_left_nan: int


def _classify_gaps(mask: np.ndarray, slot_minutes: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return three boolean masks of the same length as ``mask``:
       short, medium, long. Every True in ``mask`` lands in exactly one.
    """
    short = np.zeros_like(mask)
    medium = np.zeros_like(mask)
    long_ = np.zeros_like(mask)
    if not mask.any():
        return short, medium, long_

    i = 0
    n = len(mask)
    while i < n:
        if not mask[i]:
            i += 1
            continue
        j = i
        while j < n and mask[j]:
            j += 1
        run_len = j - i
        minutes = run_len * slot_minutes
        if minutes <= SHORT_GAP_MAX_MINUTES:
            short[i:j] = True
        elif minutes <= MEDIUM_GAP_MAX_MINUTES:
            medium[i:j] = True
        else:
            long_[i:j] = True
        i = j
    return short, medium, long_


def _diurnal_mean(series: pd.Series, slots_per_day: int) -> np.ndarray:
    """Per-slot-of-day mean kWh, NaNs ignored."""
    n = len(series)
    slot_of_day = np.arange(n) % slots_per_day
    vals = series.to_numpy(dtype=np.float64)
    out = np.full(slots_per_day, np.nan)
    for s in range(slots_per_day):
        chunk = vals[slot_of_day == s]
        chunk = chunk[~np.isnan(chunk)]
        if len(chunk):
            out[s] = chunk.mean()
    return out


def impute_meter_series(
    df: pd.DataFrame,
    *,
    slot_minutes: int = 15,
    value_col: str = "kwh",
) -> ImputeResult:
    """Impute a single meter's long frame (already sorted by ts)."""
    if df.empty:
        return ImputeResult(df.copy(), 0, 0, 0)

    slots_per_day = (24 * 60) // slot_minutes
    frame = df.copy().reset_index(drop=True)
    if "imputed" not in frame.columns:
        frame["imputed"] = False

    vals = frame[value_col].to_numpy(dtype=np.float64)
    nan_mask = np.isnan(vals)
    short, medium, long_ = _classify_gaps(nan_mask, slot_minutes)

    # Short gaps: linear interpolation on the kwh series (pandas handles edges).
    if short.any():
        interp = frame[value_col].interpolate(method="linear", limit_direction="both")
        fill_short = short & ~np.isnan(interp.to_numpy())
        frame.loc[fill_short, value_col] = interp[fill_short].values
        frame.loc[fill_short, "imputed"] = True

    # Medium gaps: per-slot-of-day mean.
    if medium.any():
        slot_means = _diurnal_mean(frame[value_col], slots_per_day)
        idx = np.where(medium)[0]
        slot_of_day = idx % slots_per_day
        replacement = slot_means[slot_of_day]
        have_mean = ~np.isnan(replacement)
        fill_idx = idx[have_mean]
        frame.loc[fill_idx, value_col] = replacement[have_mean]
        frame.loc[fill_idx, "imputed"] = True

    # Long gaps: leave as NaN deliberately; record the count.
    return ImputeResult(
        frame=frame,
        n_short_imputed=int(short.sum()),
        n_medium_imputed=int(medium.sum()),
        n_long_left_nan=int(long_.sum()),
    )


def impute_meter_readings(
    df: pd.DataFrame,
    *,
    slot_minutes: int = 15,
) -> ImputeResult:
    """Vectorised over every meter_id. Expects columns meter_id, ts, kwh."""
    if df.empty:
        return ImputeResult(df.copy(), 0, 0, 0)

    total_short = total_medium = total_long = 0
    out_frames: list[pd.DataFrame] = []
    for meter_id, grp in df.sort_values(["meter_id", "ts"]).groupby("meter_id", sort=False):
        res = impute_meter_series(grp, slot_minutes=slot_minutes, value_col="kwh")
        total_short += res.n_short_imputed
        total_medium += res.n_medium_imputed
        total_long += res.n_long_left_nan
        out_frames.append(res.frame)

    merged = pd.concat(out_frames, ignore_index=True)
    return ImputeResult(
        frame=merged,
        n_short_imputed=total_short,
        n_medium_imputed=total_medium,
        n_long_left_nan=total_long,
    )
