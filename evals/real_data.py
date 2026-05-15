"""Real household smart-meter data and the scale-free features used to compare it with the simulator.

Source: the London Smart Meters dataset (UK Power Networks "Low Carbon London" trial,
CC BY 4.0), as published in the Monash Time Series Forecasting Archive on Zenodo
(record 4656091). Half-hourly kWh for ~5,500 households.

London homes are not Bengaluru homes, so only scale-free features are compared:
shape and variability, not absolute kWh.
"""

from __future__ import annotations

import io
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "real"
ZIP_URL = "https://zenodo.org/api/records/4656091/files/london_smart_meters_dataset_without_missing_values.zip/content"
TSF_NAME = "london_smart_meters_dataset_without_missing_values.tsf"
WINDOW_DAYS = 112  # 16 whole weeks, starting on a Monday
HALF_HOURS = 48

FEATURES = [
    "cv_daily", "ac1", "ac7", "weekend_ratio", "night_share", "evening_share",
    "load_factor", "skew_daily", "low_day_ratio", "intraday_var",
]


def _tsf_path() -> Path:
    path = CACHE_DIR / TSF_NAME
    if not path.exists():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(ZIP_URL, timeout=600) as response:
            data = response.read()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            archive.extract(TSF_NAME, CACHE_DIR)
    return path


def _window(line: str) -> np.ndarray | None:
    """First Monday-aligned 112-day window of one series as a (days, 48) array, or None if too short."""
    _, stamp, values = line.rstrip("\n").split(":", 2)
    start = datetime.strptime(stamp, "%Y-%m-%d %H-%M-%S")
    offset_days = (7 - start.weekday()) % 7
    first = offset_days * HALF_HOURS - (start.hour * 2 + start.minute // 30)
    first = max(first, 0)
    need = WINDOW_DAYS * HALF_HOURS
    arr = np.fromstring(values, sep=",", dtype=np.float64)
    if len(arr) < first + need:
        return None
    return arr[first : first + need].reshape(WINDOW_DAYS, HALF_HOURS)


def load_households(count: int = 1000, stride: int = 5) -> np.ndarray:
    """(count, 112, 48) half-hourly kWh for evenly spread households; cached after the first call."""
    cache = CACHE_DIR / f"households_{count}_{stride}.npy"
    if cache.exists():
        return np.load(cache)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    picked: list[np.ndarray] = []
    with open(_tsf_path(), encoding="utf-8") as handle:
        index = -1
        for line in handle:
            if not line.startswith("T"):
                continue
            index += 1
            if index % stride:
                continue
            window = _window(line)
            if window is not None and window.sum() > 0:
                picked.append(window)
            if len(picked) == count:
                break
    out = np.stack(picked)
    np.save(cache, out)
    return out


def _acf(x: np.ndarray, lag: int) -> float:
    x = x - x.mean()
    denom = float((x * x).sum())
    return float((x[:-lag] * x[lag:]).sum() / denom) if denom > 0 else 0.0


def household_features(half_hourly: np.ndarray) -> dict[str, float]:
    """Scale-free features of one household from a (days, 48) array of half-hourly kWh."""
    daily = half_hourly.sum(axis=1)
    mean = daily.mean()
    weekday = np.arange(len(daily)) % 7
    std = daily.std()
    skew = float(((daily - mean) ** 3).mean() / std**3) if std > 0 else 0.0
    return {
        "cv_daily": float(std / mean),
        "ac1": _acf(daily, 1),
        "ac7": _acf(daily, 7),
        "weekend_ratio": float(daily[weekday >= 5].mean() / daily[weekday < 5].mean()),
        "night_share": float(half_hourly[:, 0:12].sum() / half_hourly.sum()),
        "evening_share": float(half_hourly[:, 34:44].sum() / half_hourly.sum()),
        "load_factor": float(half_hourly.mean() / half_hourly.max(axis=1).mean()),
        "skew_daily": skew,
        "low_day_ratio": float(np.percentile(daily, 5) / np.median(daily)),
        "intraday_var": float((half_hourly.std(axis=1) / half_hourly.mean(axis=1).clip(min=1e-9)).mean()),
    }


def feature_table(households: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame([household_features(h) for h in households])[FEATURES]
