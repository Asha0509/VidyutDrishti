"""Day-ahead feeder forecast benchmark on real London smart-meter data.

A "feeder" is the sum of 50 randomly chosen real households (half-hourly kWh).
Each model forecasts the next 24 h (48 slots) from the history before it, at 28
rolling daily origins at the end of the 112-day window. Nothing is fitted on the
scored days.

Models: the shipped 4-week seasonal mean (app.forecast.engine), naive (yesterday), seasonal naive (same slot
last week) and Chronos-Bolt (optional;
needs torch + chronos-forecasting).

Metrics: WAPE (sum|err| / sum|actual|) and MASE (scaled by weekly seasonal-naive
MAE on the history).

    python evals/forecast_benchmark.py [--chronos tiny,small]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evals"))

from real_data import load_households  # noqa: E402

SLOTS = 48
FEEDERS = 20
HOUSEHOLDS_PER_FEEDER = 50
ORIGINS = 28


def feeders(seed: int = 0) -> np.ndarray:
    """(FEEDERS, days*48) summed half-hourly kWh."""
    hh = load_households()
    order = np.random.default_rng(seed).permutation(len(hh))
    groups = order[: FEEDERS * HOUSEHOLDS_PER_FEEDER].reshape(FEEDERS, HOUSEHOLDS_PER_FEEDER)
    return np.stack([hh[g].sum(axis=0).reshape(-1) for g in groups])


def naive_day(hist: np.ndarray) -> np.ndarray:
    return hist[-SLOTS:]


def seasonal_week(hist: np.ndarray) -> np.ndarray:
    return hist[-7 * SLOTS : -6 * SLOTS]


def shipped_engine(hist: np.ndarray, _start: pd.Timestamp) -> np.ndarray:
    from app.forecast.engine import seasonal_mean

    return seasonal_mean(hist, SLOTS, SLOTS)


def band_coverage(hist: np.ndarray, actual: np.ndarray) -> float:
    """Share of actual slots inside the shipped 10th-90th percentile band."""
    from app.forecast.engine import _relative_band, seasonal_mean

    pred = seasonal_mean(hist, SLOTS, SLOTS)
    lo, hi = _relative_band(hist, SLOTS)
    return float(np.mean((actual >= pred * (1 + lo)) & (actual <= pred * (1 + hi))))


def chronos_model(size: str):
    import torch
    from chronos import BaseChronosPipeline

    pipe = BaseChronosPipeline.from_pretrained(f"amazon/chronos-bolt-{size}", device_map="cpu", torch_dtype=torch.float32)

    def run(hist: np.ndarray, _start: pd.Timestamp) -> np.ndarray:
        ctx = torch.tensor(hist[-28 * SLOTS :], dtype=torch.float32)
        _, mean = pipe.predict_quantiles(ctx, prediction_length=SLOTS, quantile_levels=[0.5])
        return mean[0].numpy()

    return run


def score(actual: np.ndarray, pred: np.ndarray, scale: float) -> tuple[float, float]:
    err = np.abs(actual - pred)
    return float(err.sum() / actual.sum()), float(err.mean() / scale)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chronos", default="", help="comma-separated Chronos-Bolt sizes, e.g. tiny,small")
    ap.add_argument("--out", default=str(ROOT / "evals" / "results" / "forecast_benchmark.json"))
    args = ap.parse_args()

    models = {
        "shipped_seasonal_mean": shipped_engine,
        "naive_yesterday": lambda h, _s: naive_day(h),
        "seasonal_naive_week": lambda h, _s: seasonal_week(h),
    }
    for size in filter(None, args.chronos.split(",")):
        models[f"chronos_bolt_{size}"] = chronos_model(size)

    data = feeders()
    total = data.shape[1]
    t0 = pd.Timestamp("2021-01-04")  # Monday; only weekday alignment matters
    results = {name: {"wape": [], "mase": []} for name in models}
    coverage: list[float] = []
    for f in data:
        for k in range(ORIGINS):
            end = total - (ORIGINS - k) * SLOTS
            hist, actual = f[:end], f[end : end + SLOTS]
            scale = np.abs(hist[7 * SLOTS :] - hist[: -7 * SLOTS]).mean()
            start = t0 + pd.Timedelta(minutes=30 * end)
            coverage.append(band_coverage(hist, actual))
            for name, fn in models.items():
                w, m = score(actual, fn(hist, start), scale)
                results[name]["wape"].append(w)
                results[name]["mase"].append(m)
    summary = {
        n: {"wape": round(float(np.mean(r["wape"])), 4), "mase": round(float(np.mean(r["mase"])), 3)}
        for n, r in results.items()
    }
    out = {"feeders": FEEDERS, "households_per_feeder": HOUSEHOLDS_PER_FEEDER, "origins": ORIGINS, "band_coverage_80": round(float(np.mean(coverage)), 3), "results": summary}
    Path(args.out).write_text(json.dumps(out, indent=2) + "\n")
    print(f"shipped 80% band coverage: {out['band_coverage_80']:.3f}")
    for n, s in sorted(summary.items(), key=lambda kv: kv[1]["mase"]):
        print(f"{n:24s} WAPE {s['wape']:.3f}  MASE {s['mase']:.3f}")


if __name__ == "__main__":
    main()
