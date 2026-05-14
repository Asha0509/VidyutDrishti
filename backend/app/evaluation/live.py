"""Measured detection metrics against simulator ground truth.

Replaces the precision/recall numbers that used to be hardcoded in the API.
The simulator records every injected theft and every decoy (a legitimate
drop, such as a vacant house), so the scores can be checked meter by meter.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from app.detection.scoring import FLAG_THRESHOLD, MeterScore


def compute(
    scores: List[MeterScore],
    theft: Dict[str, str],            # meter_id -> theft kind
    decoys: Dict[str, str],           # meter_id -> decoy kind
    queue_ids: List[str],
    threshold: float = FLAG_THRESHOLD,
) -> Dict:
    by_id = {s.meter_id: s for s in scores}
    flagged = {s.meter_id for s in scores if s.confidence >= threshold}
    positives = set(theft) & set(by_id)
    tp = len(flagged & positives)
    fp = len(flagged - positives)
    fn = len(positives - flagged)
    tn = len(set(by_id) - flagged - positives)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    def p_at(k: int) -> Optional[float]:
        top = queue_ids[:k]
        return round(sum(m in positives for m in top) / len(top), 3) if top else None

    sweep = []
    for th in (0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        f = {s.meter_id for s in scores if s.confidence >= th}
        t = len(f & positives)
        p = t / len(f) if f else 0.0
        r = t / len(positives) if positives else 0.0
        sweep.append({"threshold": th, "flagged": len(f), "precision": round(p, 3), "recall": round(r, 3),
                      "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0})

    kinds: Dict[str, Dict] = {}
    for m, kind in theft.items():
        k = kinds.setdefault(kind, {"meters": 0, "caught": 0, "pattern_match": 0})
        k["meters"] += 1
        k["caught"] += m in flagged
        expected = {"hook_bypass": "sudden_drop", "meter_stop": "flatline", "gradual_tampering": "gradual_decline"}
        k["pattern_match"] += by_id.get(m) is not None and by_id[m].pattern == expected.get(kind)

    return {
        "threshold": threshold,
        "meters": len(by_id),
        "theft_meters": len(positives),
        "decoy_meters": len(set(decoys) & set(by_id)),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1_score": round(f1, 3),
        "accuracy": round((tp + tn) / len(by_id), 3) if by_id else None,
        "precision_at_10": p_at(10),
        "precision_at_20": p_at(20),
        "decoys_flagged": sorted(set(decoys) & flagged),
        "missed_thefts": sorted(positives - flagged),
        "by_theft_kind": kinds,
        "threshold_sweep": sweep,
    }


def detection_lag_days(daily_scores_by_date: Dict, theft_start: Dict[str, object]) -> Dict[str, Optional[int]]:
    """Days from theft start to first flag, per theft meter (None = never flagged)."""
    lags: Dict[str, Optional[int]] = {}
    for m, start in theft_start.items():
        lag = None
        for d in sorted(daily_scores_by_date):
            if d < start:
                continue
            if m in daily_scores_by_date[d]:
                lag = (d - start).days
                break
        lags[m] = lag
    return lags
