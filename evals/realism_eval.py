"""How close is the simulator to real households? (scale-free features, two tests)

Real data: London smart-meter households (see real_data.py), split into two disjoint
shards of 500 so that calibration (shard 0) and scoring (shard 1) never share a household.
Simulated data: domestic meters from the simulator, same 16-week window, same features.

Tests, both on the 10 scale-free features:
  * SDMetrics QualityReport: column-shape and pair-trend similarity, 0-100% (higher = closer).
  * Classifier two-sample test: cross-validated AUC of a gradient-boosted classifier trained to tell
    real from simulated (0.5 = indistinguishable, 1.0 = trivially different).

Usage:
  python evals/realism_eval.py                  # score default config vs calibrated config on shard 1
  python evals/realism_eval.py --out evals/results/realism.json
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "evals"))

from real_data import FEATURES, feature_table, load_households  # noqa: E402

from simulator.dataset import _simulate_meter  # noqa: E402
from simulator.models import SimConfig  # noqa: E402

CONFIG_PATH = ROOT / "simulator" / "config.yaml"
CALIBRATED_PATH = ROOT / "simulator" / "calibrated_realism.json"
WINDOW_DAYS = 112
START = date(2024, 1, 1)  # a Monday, like the real windows


def load_config(realism: dict[str, float] | None = None) -> SimConfig:
    raw = yaml.safe_load(CONFIG_PATH.read_text())
    raw["days"] = WINDOW_DAYS
    raw["start_date"] = START
    raw["summer_multiplier"] = raw["monsoon_multiplier"] = raw["holiday_multiplier"] = 1.0  # compare variability, not climate
    raw["holiday_dates"] = []
    raw["theft_scenarios"], raw["decoys"] = [], []
    raw["realism"] = realism or {}
    return SimConfig.from_dict(raw)


def simulate_features(cfg: SimConfig, n: int, seed: int) -> pd.DataFrame:
    from real_data import household_features

    rng = np.random.default_rng(seed)
    dates = [START + pd.Timedelta(days=i).to_pytimedelta() for i in range(cfg.days)]
    rows = []
    for _ in range(n):
        slots = _simulate_meter(cfg, rng, dates, set(), "domestic").reshape(cfg.days, cfg.slots_per_day)
        half_hourly = slots.reshape(cfg.days, 48, cfg.slots_per_day // 48).sum(axis=2)
        rows.append(household_features(half_hourly))
    return pd.DataFrame(rows)[FEATURES]


def clean(df: pd.DataFrame) -> pd.DataFrame:
    return df.replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)


def real_shards() -> tuple[pd.DataFrame, pd.DataFrame]:
    table = clean(feature_table(load_households()))
    half = len(table) // 2
    return table.iloc[:half].reset_index(drop=True), table.iloc[half:].reset_index(drop=True)


def quality_score(real: pd.DataFrame, sim: pd.DataFrame) -> dict[str, float]:
    from sdmetrics.reports.single_table import QualityReport

    n = min(len(real), len(sim))
    r, s = real.iloc[:n], sim.iloc[:n]
    metadata = {"columns": {c: {"sdtype": "numerical"} for c in FEATURES}}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        report = QualityReport()
        report.generate(r, s, metadata, verbose=False)
    shapes = report.get_details("Column Shapes")["Score"].mean()
    pairs = report.get_details("Column Pair Trends")["Score"].mean()
    return {"overall": float(report.get_score()), "column_shapes": float(shapes), "pair_trends": float(pairs)}


def classifier_auc(real: pd.DataFrame, sim: pd.DataFrame, seed: int = 0) -> float:
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import cross_val_predict

    n = min(len(real), len(sim))
    x = pd.concat([real.iloc[:n], sim.iloc[:n]], ignore_index=True)
    y = np.r_[np.ones(n), np.zeros(n)]
    model = GradientBoostingClassifier(n_estimators=100, max_depth=3, random_state=seed)
    prob = cross_val_predict(model, x, y, cv=5, method="predict_proba")[:, 1]
    return float(roc_auc_score(y, prob))


def distance(real: pd.DataFrame, sim: pd.DataFrame) -> float:
    """Mean per-feature Wasserstein distance after scaling by the real feature's interquartile range."""
    from scipy.stats import wasserstein_distance

    total = 0.0
    for c in FEATURES:
        iqr = float(real[c].quantile(0.75) - real[c].quantile(0.25)) or 1.0
        total += wasserstein_distance(real[c], sim[c]) / iqr
    return total / len(FEATURES)


def score(real: pd.DataFrame, realism: dict[str, float], seed: int) -> dict:
    sim = clean(simulate_features(load_config(realism), len(real), seed))
    return {"quality": quality_score(real, sim), "classifier_auc": classifier_auc(real, sim), "distance": distance(real, sim)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT / "evals" / "results" / "realism.json"))
    args = ap.parse_args()
    shard0, shard1 = real_shards()
    calibrated = json.loads(CALIBRATED_PATH.read_text())["knobs"] if CALIBRATED_PATH.exists() else {}
    result = {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "real_households": {"calibration_shard": len(shard0), "scoring_shard": len(shard1)},
        "features": FEATURES,
        "original_simulator": score(shard1, {}, seed=11),
        "calibrated_simulator": score(shard1, calibrated, seed=11),
        "knobs": calibrated,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2))
    print(json.dumps({k: result[k] for k in ("original_simulator", "calibrated_simulator", "knobs")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
