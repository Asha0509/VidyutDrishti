"""Calibrate the simulator's realism knobs against real households (shard 0 only).

Random search followed by local refinement, minimising the mean scaled Wasserstein distance
between real and simulated feature distributions on the calibration shard. The scoring shard
is never touched here; `realism_eval.py` scores the result on it.

Usage: python evals/calibrate_simulator.py [--trials 150] [--refine 120]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import realism_eval as ev

RANGES = {
    "ar1_phi": (0.0, 0.85),
    "cv_mult": (0.5, 3.5),
    "meter_cv_sigma": (0.0, 0.8),
    "base_load_frac": (0.0, 0.7),
    "shape_jitter": (0.0, 0.7),
    "timing_shift_hours": (0.0, 3.0),
    "spike_sigma": (0.0, 1.2),
    "lognormal_daily": (0.0, 1.0),
}


def evaluate(real, knobs, seed):
    sim = ev.clean(ev.simulate_features(ev.load_config(knobs), len(real), seed))
    return ev.distance(real, sim) if len(sim) > len(real) * 0.8 else 9.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--trials", type=int, default=150)
    ap.add_argument("--refine", type=int, default=120)
    args = ap.parse_args()
    shard0, _ = ev.real_shards()
    rng = np.random.default_rng(7)

    def draw():
        k = {name: float(rng.uniform(lo, hi)) for name, (lo, hi) in RANGES.items()}
        k["lognormal_daily"] = float(round(k["lognormal_daily"]))
        k["timing_shift_hours"] = float(round(k["timing_shift_hours"]))
        return k

    best_k, best_d = {}, evaluate(shard0, {}, 5)
    print("original distance", round(best_d, 3))
    for i in range(args.trials):
        k = draw()
        d = evaluate(shard0, k, 5)
        if d < best_d:
            best_k, best_d = k, d
            print(f"random {i}: {d:.3f}")
    for i in range(args.refine):
        step = 0.25 * (1 - i / args.refine) + 0.03
        k = {}
        for name, (lo, hi) in RANGES.items():
            v = best_k[name] + rng.normal(0, step * (hi - lo))
            k[name] = float(np.clip(v, lo, hi))
        k["lognormal_daily"] = float(round(k["lognormal_daily"]))
        k["timing_shift_hours"] = float(round(k["timing_shift_hours"]))
        d = evaluate(shard0, k, 5)
        if d < best_d:
            best_k, best_d = k, d
            print(f"refine {i}: {d:.3f}")
    out = {"calibrated_on": "shard 0 (first half of the real households)", "distance_on_shard0": best_d,
           "knobs": {k: round(v, 4) for k, v in best_k.items()}}
    ev.CALIBRATED_PATH.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
