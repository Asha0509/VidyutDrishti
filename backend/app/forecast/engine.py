"""Feeder demand forecast: 24 h ahead, with an 80% band.

Default model: the mean of the same weekday and time of day over the last four
weeks. On real London smart-meter feeders it beat the earlier blended trend model
by a wide margin (see docs/FORECAST_BENCHMARK.md). An optional pretrained
Chronos-Bolt backend (`FORECAST_MODEL=chronos`, needs torch and
chronos-forecasting) was more accurate still but is too heavy for the small
server, so it is off by default and falls back to the seasonal model if it cannot
load.

The band comes from the model's own past errors: the 10th and 90th percentile of
relative error over the last two weeks of backtest, applied to each point.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

WEEKS = 4
BAND = (0.10, 0.90)
CAPACITY_KW = 5000.0  # placeholder until the asset registry supplies real ratings


@dataclass
class ForecastResult:
    ds: datetime
    yhat: float
    yhat_lower: float
    yhat_upper: float


@dataclass
class FeederForecast:
    feeder_id: str
    model: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    horizon_hours: int = 24
    resolution_minutes: int = 15
    points: list[ForecastResult] = field(default_factory=list)
    zone_risk: str = "LOW"
    risk_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        peak = max((p.yhat for p in self.points), default=0.0)
        return {
            "feeder_id": self.feeder_id,
            "model": self.model,
            "created_at": self.created_at.isoformat(),
            "zone_risk": self.zone_risk,
            "risk_score": round(self.risk_score, 3),
            "peak_forecast_kw": round(peak, 1),
            "max_capacity_kw": CAPACITY_KW,
            "utilization_pct": round(peak / CAPACITY_KW * 100, 1),
            "points": [
                {
                    "timestamp": p.ds.isoformat(),
                    "forecast_kw": round(p.yhat, 2),
                    "lower_kw": round(p.yhat_lower, 2),
                    "upper_kw": round(p.yhat_upper, 2),
                }
                for p in self.points
            ],
        }


def seasonal_mean(values: np.ndarray, slots_per_day: int, steps: int, weeks: int = WEEKS) -> np.ndarray:
    """Mean of the same slot 1..weeks weeks earlier, for the next `steps` slots (needs >= 7 days)."""
    week = 7 * slots_per_day
    out = np.empty(steps)
    for i in range(steps):
        lags = [len(values) + i - k * week for k in range(1, weeks + 1)]
        out[i] = np.mean([values[j] for j in lags if 0 <= j < len(values)])
    return out


def _relative_band(values: np.ndarray, slots_per_day: int) -> tuple[float, float]:
    """10th/90th percentile of relative error from replaying the model on the last 14 days."""
    errs: list[np.ndarray] = []
    for d in range(1, 15):
        end = len(values) - d * slots_per_day
        if end < 7 * slots_per_day:
            break
        pred = seasonal_mean(values[:end], slots_per_day, slots_per_day)
        actual = values[end : end + slots_per_day]
        keep = pred > 0
        errs.append((actual[keep] - pred[keep]) / pred[keep])
    if not errs:
        return -0.2, 0.2  # too little history to measure: a flat, stated fallback
    rel = np.concatenate(errs)
    return float(np.quantile(rel, BAND[0])), float(np.quantile(rel, BAND[1]))


def _chronos_mean(values: np.ndarray, steps: int) -> np.ndarray | None:
    try:
        import torch
        from chronos import BaseChronosPipeline

        pipe = BaseChronosPipeline.from_pretrained(
            os.getenv("CHRONOS_MODEL", "amazon/chronos-bolt-tiny"), device_map="cpu", torch_dtype=torch.float32
        )
        _, mean = pipe.predict_quantiles(
            torch.tensor(values[-28 * 96 :], dtype=torch.float32), prediction_length=steps, quantile_levels=[0.5]
        )
        return mean[0].numpy()
    except Exception:  # not installed, no weights, or out of memory: use the seasonal model
        return None


class FeederForecaster:
    def __init__(self, history_days: int = 90):
        self.history_days = history_days
        self._history: pd.DataFrame | None = None

    def fit(self, df: pd.DataFrame) -> FeederForecaster:
        """df columns: timestamp, feeder_id, kw (15-minute slots)."""
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        self._history = df.sort_values("timestamp").set_index("timestamp")
        return self

    def predict(self, feeder_id: str, horizon_hours: int = 24, resolution_minutes: int = 15) -> FeederForecast:
        if self._history is None:
            raise RuntimeError("Forecaster not fitted.")
        hist = self._history[self._history["feeder_id"] == feeder_id]
        if hist.empty:
            raise ValueError(f"No history for feeder {feeder_id}")
        per_day = 24 * 60 // resolution_minutes
        values = hist["kw"].to_numpy(dtype=float)[-self.history_days * per_day :]
        if len(values) < 7 * per_day:
            raise ValueError("At least 7 days of readings are needed to forecast.")
        steps = horizon_hours * 60 // resolution_minutes

        yhat, model = None, "seasonal mean of last 4 weeks"
        if os.getenv("FORECAST_MODEL", "seasonal") == "chronos":
            yhat = _chronos_mean(values, steps)
            model = "Chronos-Bolt" if yhat is not None else model
        if yhat is None:
            yhat = seasonal_mean(values, per_day, steps)
        lo, hi = _relative_band(values, per_day)
        start = hist.index.max()
        points = [
            ForecastResult(
                start + timedelta(minutes=resolution_minutes * (i + 1)),
                float(y),
                float(max(0.0, y * (1 + lo))),
                float(y * (1 + hi)),
            )
            for i, y in enumerate(yhat)
        ]
        peak = max(p.yhat for p in points)
        util = peak / CAPACITY_KW
        zone, score = ("HIGH", min(1.0, util)) if util >= 0.88 else ("MEDIUM", util) if util >= 0.75 else ("LOW", util * 0.5)
        return FeederForecast(
            feeder_id, model, horizon_hours=horizon_hours, resolution_minutes=resolution_minutes,
            points=points, zone_risk=zone, risk_score=score,
        )
