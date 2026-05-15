"""
Evals for the AI features, on synthetic networks the agents have never seen.

Inspection brief (RCA): every flagged meter and every decoy gets a brief; the
named cause is checked against the simulator's ground truth
(hook_bypass / gradual_tampering / meter_stop -> meter_stopped / vacancy and
false alarms -> genuine_drop). Reports cause accuracy and, more important for
the field team, theft-vs-genuine accuracy.

Copilot: templated questions whose answers are computed from the same data
(top zone by loss, number flagged, top queue meter, a meter's drop, ...). An
answer passes if it contains the expected value; it fails if it names a meter
that doesn't exist (a hallucination).

  python evals/ai_eval.py --mode rules            # deterministic baseline, no key
  python evals/ai_eval.py --mode agent --delay 2  # needs GROQ_API_KEY
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import UTC, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))
os.environ.setdefault("OBS_DB_PATH", os.path.join(HERE, ".ai-eval-obs.db"))

from app import store as store_mod  # noqa: E402
from app.ai import agents, llm  # noqa: E402
from app.store import Store  # noqa: E402
from detection_eval import random_network  # noqa: E402

from simulator.dataset import build_dataset  # noqa: E402

EXPECTED_CAUSE = {"hook_bypass": "hook_bypass", "gradual_tampering": "gradual_tampering", "meter_stop": "meter_stopped",
                  "vacancy": "genuine_drop", None: "genuine_drop"}
THEFT_CAUSES = {"hook_bypass", "gradual_tampering", "meter_stopped"}


def load_network(seed: int) -> tuple[Store, dict, dict]:
    cfg, thefts, decoys = random_network(seed)
    ds = build_dataset(cfg)
    s = Store()
    s.add_meter_frame(ds["meter_readings"][["meter_id", "ts", "kwh"]])
    s.add_dt_frame(ds["dt_readings"][["dt_id", "ts", "kwh_in"]])
    s.set_truth(thefts, decoys, cfg.start_date)
    s.ready = True
    store_mod.store = s
    return s, {t["meter_id"]: t["kind"] for t in thefts}, {d["meter_id"]: d["kind"] for d in decoys}


def eval_briefs(seeds, use_llm: bool, delay: float):
    rows = []
    for seed in seeds:
        s, theft, decoys = load_network(seed)
        flagged = {x.meter_id for x in s.scores() if x.flagged}
        for mid in sorted(flagged | set(decoys)):
            truth = theft.get(mid) or decoys.get(mid)
            expected = EXPECTED_CAUSE[truth]
            b = agents.inspection_brief(mid, use_llm=use_llm, session_id=f"eval-brief-{seed}")
            got = b["likely_cause"]
            rows.append({"seed": seed, "meter_id": mid, "truth": truth or "false_alarm", "expected": expected,
                         "got": got, "mode": b["mode"], "correct": got == expected,
                         "theft_call_correct": (got in THEFT_CAUSES) == (expected in THEFT_CAUSES),
                         "latency_ms": b["latency_ms"]})
            print(f"{'ok' if got == expected else 'XX'} brief seed {seed} {mid:8} truth={truth or 'false_alarm':18} "
                  f"got={got} ({b['mode']})", flush=True)
            if use_llm and delay:
                time.sleep(delay)
    n = len(rows)
    by_truth = {}
    for r in rows:
        k = by_truth.setdefault(r["truth"], {"n": 0, "correct": 0})
        k["n"] += 1
        k["correct"] += r["correct"]
    return {"cases": n, "cause_accuracy": round(sum(r["correct"] for r in rows) / n, 3) if n else None,
            "theft_vs_genuine_accuracy": round(sum(r["theft_call_correct"] for r in rows) / n, 3) if n else None,
            "by_truth": {k: {**v, "accuracy": round(v["correct"] / v["n"], 3)} for k, v in by_truth.items()},
            "fallbacks": sum(1 for r in rows if r["mode"] == "rules") if use_llm else None, "rows": rows}


def copilot_questions(s: Store):
    zones = s.zones()
    q = s.queue(limit=1000)
    scores = {x.meter_id: x for x in s.scores()}
    ov = s.overview()
    top_zone = max(zones, key=lambda z: z["estimated_inr_lost"])
    highs = [x for x in scores.values() if x.tier == "HIGH"]
    some = q[min(2, len(q) - 1)]
    bal = s.dt_balance(days=8)
    latest = max(r["date"] for r in bal)
    by_dt = {r["dt_id"]: r["unmetered_pct"] for r in bal if r["date"] == latest}
    worst_dt = max(by_dt, key=by_dt.get)
    zone_c = sorted(i["meter_id"] for i in q if i["zone"] == "ZoneC")
    return [
        ("Which zone has the highest estimated monthly loss?", [top_zone["id"]]),
        ("How many meters are flagged right now?", [str(ov["flagged"])]),
        ("Which meter is at the top of the inspection queue?", [q[0]["meter_id"]]),
        ("How many meters are high risk?", [str(len(highs))]),
        (f"By how much has {some['meter_id']}'s consumption dropped?", [f"{some['drop_pct']:.0f}"]),
        (f"What pattern does {some['meter_id']} show?", [some["pattern"].replace("_", " ").split()[0]]),
        ("Which transformer has the highest unmetered energy share on the latest day?", [worst_dt]),
        ("List the flagged meters in Zone C.", zone_c or ["no"]),
        ("What is the estimated monthly loss across all flagged meters?",
         [f"{ov['estimated_monthly_loss_inr']:,.0f}", f"{ov['estimated_monthly_loss_inr']:.0f}"]),
        ("How accurate is the detector on held-out data?", ["0.8", "0.9"]),
    ]


_IDS = re.compile(r"\bDT\d+-M\d{2}\b")


def eval_copilot(seeds, use_llm: bool, delay: float):
    rows = []
    for seed in seeds:
        s, _, _ = load_network(seed)
        known = set(s.topology)
        for question, expected in copilot_questions(s):
            r = agents.copilot(question, use_llm=use_llm, session_id=f"eval-copilot-{seed}")
            ans = r["answer"]
            norm = ans.replace(",", "")
            hit = all(e.replace(",", "") in norm for e in expected) if len(expected) > 1 and "Zone C" in question \
                else any(e.replace(",", "") in norm for e in expected)
            invented = sorted(set(_IDS.findall(ans)) - known)
            rows.append({"seed": seed, "question": question, "expected": expected, "answer": ans, "pass": hit and not invented,
                         "hallucinated_ids": invented, "mode": r["mode"], "latency_ms": r["latency_ms"]})
            print(f"{'ok' if hit and not invented else 'XX'} copilot seed {seed}: {question[:60]:60} ({r['mode']})", flush=True)
            if use_llm and delay:
                time.sleep(delay)
    n = len(rows)
    lat = sorted(r["latency_ms"] for r in rows)
    return {"cases": n, "pass_rate": round(sum(r["pass"] for r in rows) / n, 3),
            "hallucinated_answers": sum(1 for r in rows if r["hallucinated_ids"]),
            "latency_ms_p50": lat[len(lat) // 2] if lat else None, "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["rules", "agent"], default="rules")
    ap.add_argument("--networks", type=int, default=3)
    ap.add_argument("--first-seed", type=int, default=2000)
    ap.add_argument("--delay", type=float, default=0.0)
    ap.add_argument("--out")
    args = ap.parse_args()
    use_llm = args.mode == "agent"
    if use_llm and not llm.has_any_provider():
        print("agent mode needs GROQ_API_KEY or NVIDIA_NIM_API_KEY")
        return 2
    seeds = list(range(args.first_seed, args.first_seed + args.networks))
    report = {"mode": args.mode, "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
              "networks": seeds, "providers": llm.configured_providers() if use_llm else [],
              "brief": eval_briefs(seeds, use_llm, args.delay),
              "copilot": eval_copilot(seeds, use_llm, args.delay)}
    out = args.out or os.path.join(HERE, "results", f"ai-{args.mode}.json")
    with open(out, "w") as f:
        json.dump(report, f, indent=2)
    b, c = report["brief"], report["copilot"]
    print(f"\n{args.mode}: brief cause accuracy {b['cause_accuracy']} (theft vs genuine {b['theft_vs_genuine_accuracy']}, "
          f"{b['cases']} meters); copilot pass rate {c['pass_rate']} ({c['cases']} questions, "
          f"{c['hallucinated_answers']} with invented meter ids)")
    print("brief by truth:", {k: v["accuracy"] for k, v in b["by_truth"].items()})
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
