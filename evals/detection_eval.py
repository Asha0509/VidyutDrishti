"""
Detection eval on unseen synthetic networks.

The demo dataset was used while developing the scoring, so its numbers are
optimistic. This script generates N fresh networks (different random seeds),
each with randomly placed thefts (random meter, kind, start day, severity)
and decoys (vacant premises: a genuine drop), scores them, and reports the
mean and spread of precision, recall and F1 across networks.

  python evals/detection_eval.py --networks 20
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
from datetime import UTC, date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

import yaml  # noqa: E402
from app.detection.scoring import daily_from_slots, rank_queue, score_meters  # noqa: E402
from app.evaluation.live import compute  # noqa: E402

from simulator.dataset import build_dataset  # noqa: E402
from simulator.models import SimConfig  # noqa: E402

KINDS = ["hook_bypass", "gradual_tampering", "meter_stop"]


CALIBRATED = os.path.join(ROOT, "simulator", "calibrated_realism.json")


def random_network(seed: int, days: int = 60, dts: int = 8, per_dt: int = 6, realism: dict | None = None):
    rnd = random.Random(seed)
    meters = [f"DT{d}-M{m:02d}" for d in range(1, dts + 1) for m in range(1, per_dt + 1)]
    picks = rnd.sample(meters, 15)
    thefts, decoys = [], []
    for mid in picks[:11]:
        kind = rnd.choices(KINDS, weights=[0.5, 0.3, 0.2])[0]
        start = rnd.randint(18, 40)
        sev = {"hook_bypass": rnd.uniform(0.7, 0.97), "gradual_tampering": rnd.uniform(0.6, 0.9),
               "meter_stop": 1.0}[kind]
        thefts.append({"meter_id": mid, "kind": kind, "start_day": start, "end_day": days, "severity": round(sev, 2)})
    for mid in picks[11:]:
        decoys.append({"meter_id": mid, "kind": "vacancy", "start_day": rnd.randint(18, 40), "end_day": days,
                       "severity": round(rnd.uniform(0.7, 0.95), 2)})
    raw = yaml.safe_load(open(os.path.join(ROOT, "simulator", "config.yaml")))
    raw.update(seed=seed, days=days, start_date=(date(2026, 1, 1)).isoformat(), dt_count=dts, meters_per_dt=per_dt,
               theft_scenarios=thefts, decoys=decoys, realism=realism or {})
    return SimConfig.from_dict(raw), thefts, decoys


def score_network(cfg):
    ds = build_dataset(cfg)
    # The simulator stores per-slot kWh as daily_total * diurnal_factor, so a
    # day's slots sum to 96 x the daily total. Divide meters and DTs alike.
    daily = daily_from_slots(ds["meter_readings"])
    daily["kwh"] /= 96.0
    dr = ds["dt_readings"].copy()
    dr["date"] = dr["ts"].dt.date
    dt_daily = dr.groupby(["dt_id", "date"])["kwh_in"].sum().reset_index()
    dt_daily["kwh_in"] /= 96.0
    topo = ds["consumers"][["meter_id", "dt_id", "feeder_id"]].copy()
    topo["zone"] = ""
    return score_meters(daily, topo, None, dt_daily)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--networks", type=int, default=20)
    ap.add_argument("--first-seed", type=int, default=1000)
    ap.add_argument("--out", default=os.path.join(HERE, "results", "detection.json"))
    ap.add_argument("--simulator", choices=["original", "calibrated"], default="calibrated",
                    help="calibrated = realism knobs fitted to real households (simulator/calibrated_realism.json)")
    ap.add_argument("--gate-recall", type=float, default=None, help="Fail if mean recall is below this")
    args = ap.parse_args()

    realism = json.load(open(CALIBRATED))["knobs"] if args.simulator == "calibrated" else {}
    runs = []
    for seed in range(args.first_seed, args.first_seed + args.networks):
        cfg, thefts, decoys = random_network(seed, realism=realism)
        scores = score_network(cfg)
        queue = [s.meter_id for s in rank_queue(scores)]
        m = compute(scores, {t["meter_id"]: t["kind"] for t in thefts}, {d["meter_id"]: d["kind"] for d in decoys}, queue)
        runs.append({"seed": seed, **{k: m[k] for k in ("precision", "recall", "f1_score", "precision_at_10",
                                                       "decoys_flagged", "missed_thefts", "by_theft_kind", "threshold_sweep")}})
        print(f"seed {seed}: precision {m['precision']:.2f} recall {m['recall']:.2f} f1 {m['f1_score']:.2f} "
              f"decoys flagged {len(m['decoys_flagged'])}/4 missed {m['missed_thefts']}", flush=True)

    def stat(key):
        vals = [r[key] for r in runs if r[key] is not None]
        return {"mean": round(statistics.mean(vals), 3), "min": round(min(vals), 3), "max": round(max(vals), 3)}

    kinds = {}
    for r in runs:
        for k, v in r["by_theft_kind"].items():
            agg = kinds.setdefault(k, {"meters": 0, "caught": 0, "pattern_match": 0})
            for f in agg:
                agg[f] += v[f]
    sweep = []
    for i, row in enumerate(runs[0]["threshold_sweep"]):
        pts = [r["threshold_sweep"][i] for r in runs]
        sweep.append({"threshold": row["threshold"], **{k: round(statistics.mean(p[k] for p in pts), 3)
                                                         for k in ("precision", "recall", "f1")}})
    report = {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "networks": args.networks,
        "simulator": args.simulator,
        "first_seed": args.first_seed,
        "setup": "8 DTs x 6 meters, 60 days; per network 11 random thefts and 4 vacancy decoys",
        "precision": stat("precision"), "recall": stat("recall"), "f1_score": stat("f1_score"),
        "precision_at_10": stat("precision_at_10"),
        "threshold_sweep": sweep,
        "decoys_flagged_rate": round(sum(len(r["decoys_flagged"]) for r in runs) / (4 * len(runs)), 3),
        "by_theft_kind": {k: {**v, "recall": round(v["caught"] / v["meters"], 3),
                              "pattern_accuracy": round(v["pattern_match"] / v["meters"], 3)} for k, v in kinds.items()},
        "runs": runs,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nmean over {args.networks} unseen networks: precision {report['precision']['mean']}  "
          f"recall {report['recall']['mean']}  f1 {report['f1_score']['mean']}  "
          f"decoys flagged {report['decoys_flagged_rate']:.0%}")
    print("sweep:", [(p["threshold"], p["precision"], p["recall"], p["f1"]) for p in sweep])
    print("by kind:", {k: (v["recall"], v["pattern_accuracy"]) for k, v in report["by_theft_kind"].items()})
    if args.gate_recall is not None and report["recall"]["mean"] < args.gate_recall:
        print(f"GATE: mean recall {report['recall']['mean']} < {args.gate_recall}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
