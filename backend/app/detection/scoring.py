"""Meter scoring v2: four explainable layers over a recent window.

For every meter, the last ``recent_days`` are compared against the meter's
own baseline (the first ``baseline_days`` of history):

  L0  DT energy balance - is energy entering the transformer going unmetered?
      Theft hides consumption from the meter but not from the transformer, so
      a real theft opens a gap between DT input and the metered sum. A genuine
      drop (an empty house) shrinks both and opens no gap.
  L1  Self-history     - how far recent consumption fell below the meter's own
      baseline (ratio and z-score), plus flat-zero days.
  L2  Peer comparison  - the drop relative to other meters on the same DT,
      which cancels weather, holidays and DT-wide outages.
  L3  Isolation Forest - multivariate outlier score on the features above.
      Supporting evidence only.

Confidence combines them so that a consumption drop needs corroboration from
the transformer balance to score high. Every layer returns a sentence that
explains its number.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

TARIFF_INR_PER_KWH = {"domestic": 6.0, "commercial": 9.0, "industrial": 8.0}
TIERS = [(0.80, "HIGH"), (0.65, "MEDIUM"), (0.55, "REVIEW")]
FLAG_THRESHOLD = 0.55
TREND_SIGNAL = True


@dataclass
class Layer:
    name: str
    fired: bool
    strength: float          # 0..1 contribution before weighting
    value: Optional[float]   # the headline number for this layer
    detail: str              # plain-language explanation


@dataclass
class MeterScore:
    meter_id: str
    dt_id: str
    feeder_id: str
    zone: str
    category: str
    date: date
    confidence: float
    tier: str
    flagged: bool
    pattern: str             # flatline | sudden_drop | gradual_decline | consumption_drop | normal
    baseline_kwh: float
    recent_kwh: float
    drop_pct: float
    est_monthly_loss_inr: float
    layers: List[Layer] = field(default_factory=list)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["date"] = self.date.isoformat()
        return d


def daily_from_slots(readings: pd.DataFrame, slots_per_day: int = 96, min_coverage: float = 0.5) -> pd.DataFrame:
    """Daily kWh per meter from 15-minute readings, scaling up for missing slots.

    Missing readings must not look like unmetered energy at the transformer,
    so each day is scaled by slots_per_day / observed_slots. Days with less
    than ``min_coverage`` of slots observed are left as NaN.

    readings: meter_id, ts (datetime), kwh (NaN for missing)
    """
    df = readings[["meter_id", "ts", "kwh"]].copy()
    df["date"] = pd.to_datetime(df["ts"]).dt.date
    g = df.groupby(["meter_id", "date"])["kwh"].agg(["sum", "count"]).reset_index()
    cover = g["count"] / slots_per_day
    g["kwh"] = np.where(cover >= min_coverage, g["sum"] / cover.clip(lower=1e-9), np.nan)
    return g[["meter_id", "date", "kwh"]]


def category_for(baseline_kwh: float) -> str:
    if baseline_kwh >= 100:
        return "industrial"
    if baseline_kwh >= 25:
        return "commercial"
    return "domestic"


def tier_for(conf: float) -> str:
    for cut, name in TIERS:
        if conf >= cut:
            return name
    return "NORMAL"


def _clip(x: float) -> float:
    return float(min(1.0, max(0.0, x)))


def attribute_gap(gap: float, drops: Dict[str, float], tolerance: float = 0.15) -> Dict[str, float]:
    """Which meters' drops account for a transformer's extra unmetered energy?

    A theft keeps drawing energy through the transformer, so its drop shows up
    in the gap; a genuine drop (vacancy) doesn't. We look for the subset of
    dropping meters whose drops best sum to the gap. A meter's score is the
    share of near-best subsets that include it, times how well the best subset
    fits. Ambiguous cases (two equally good explanations) get partial credit.
    """
    droppers = [m for m, d in drops.items() if d > 0]
    if gap <= 0 or not droppers:
        return {m: 0.0 for m in drops}
    if len(droppers) > 12:  # keep the search bounded; fall back to proportional
        total = sum(drops[m] for m in droppers)
        return {m: _clip(gap / total) if m in droppers else 0.0 for m in drops}
    from itertools import combinations
    fits = []
    for k in range(1, len(droppers) + 1):
        for combo in combinations(droppers, k):
            fits.append((abs(gap - sum(drops[m] for m in combo)), combo))
    best_err = min(f[0] for f in fits)
    near = [c for e, c in fits if e <= best_err + tolerance * gap]
    quality = _clip(1 - best_err / gap)
    return {m: round(quality * sum(m in c for c in near) / len(near), 3) for m in drops}


def classify_shape(series: np.ndarray, base: float) -> str:
    """Step (sudden) vs ramp (gradual) decline, by which model fits better."""
    y = np.asarray(series, dtype=float)
    y = y[~np.isnan(y)]
    if base <= 0 or len(y) < 10:
        return "consumption_drop"
    y = y / base
    n = len(y)
    best_step = best_ramp = np.inf
    for k in range(2, n - 2):
        a, b = y[:k], y[k:]
        best_step = min(best_step, float(((a - a.mean()) ** 2).sum() + ((b - b.mean()) ** 2).sum()))
        x = np.arange(n - k)
        coef = np.polyfit(x, b, 1)
        if coef[0] < 0:
            resid = b - np.polyval(coef, x)
            best_ramp = min(best_ramp, float(((a - a.mean()) ** 2).sum() + (resid ** 2).sum()))
    if best_ramp < best_step * 0.8:
        return "gradual_decline"
    return "sudden_drop"


def score_meters(
    daily: pd.DataFrame,
    topology: pd.DataFrame,
    target_date: Optional[date] = None,
    dt_input: Optional[pd.DataFrame] = None,
    baseline_days: int = 14,
    recent_days: int = 7,
) -> List[MeterScore]:
    """Score every meter.

    daily:     meter_id, date, kwh   (daily kWh per meter)
    topology:  meter_id, dt_id, feeder_id, zone
    dt_input:  dt_id, date, kwh_in   (daily kWh entering each DT); optional
    """
    if daily.empty:
        return []
    mat = daily.pivot_table(index="meter_id", columns="date", values="kwh", aggfunc="sum").sort_index(axis=1)
    dates = list(mat.columns)
    if target_date is None or target_date not in dates:
        target_date = dates[-1]
    end = dates.index(target_date) + 1
    if end < baseline_days + recent_days:
        return []
    mat = mat.iloc[:, :end].astype(float)
    base_block = mat.iloc[:, :baseline_days]
    recent_block = mat.iloc[:, end - recent_days:end]
    trend_block = mat.iloc[:, max(baseline_days, end - 42):end]

    topo = topology.set_index("meter_id")
    base_mean = base_block.mean(axis=1, skipna=True)
    base_std = base_block.std(axis=1, skipna=True).replace(0, np.nan)
    recent_mean = recent_block.mean(axis=1, skipna=True)
    ratio = (recent_mean / base_mean.replace(0, np.nan)).fillna(1.0)
    zscore = ((recent_mean - base_mean) / base_std).fillna(0.0)
    zero_frac = (recent_block.lt(0.05 * base_mean, axis=0) | recent_block.isna()).mean(axis=1)

    # ── L2: ratio relative to DT peers (median of the other meters) ──
    rel = pd.Series(1.0, index=mat.index)
    peer_med = pd.Series(1.0, index=mat.index)
    for dt_id, members in topo.groupby("dt_id").groups.items():
        ids = [m for m in members if m in ratio.index]
        for m in ids:
            peers = ratio[[x for x in ids if x != m]]
            med = float(peers.median()) if len(peers) else 1.0
            peer_med[m] = med
            rel[m] = ratio[m] / med if med > 0 else ratio[m]

    # ── L0: unmetered energy per DT, recent vs baseline ──
    dt_gap: Dict[str, Dict[str, float]] = {}
    if dt_input is not None and not dt_input.empty:
        din = dt_input.pivot_table(index="dt_id", columns="date", values="kwh_in", aggfunc="sum")
        for dt_id, members in topo.groupby("dt_id").groups.items():
            if dt_id not in din.index:
                continue
            ids = [m for m in members if m in mat.index]
            metered = mat.loc[ids].fillna(0.0).sum(axis=0)
            row = din.loc[dt_id].reindex(metered.index)
            # Unmetered share of input: technical losses scale with load, so
            # compare shares (not kWh) and convert the change back to kWh/day.
            share = ((row - metered) / row.replace(0, np.nan))
            base_share = float(share.iloc[:baseline_days].mean())
            rec_share = float(share.iloc[end - recent_days:end].mean())
            rec_in = float(row.iloc[end - recent_days:end].mean())
            # Only meaningful drops (>20% of baseline) are candidates to explain the gap.
            drops = {m: (max(0.0, float(base_mean[m] - recent_mean[m]))
                         if float(base_mean[m] - recent_mean[m]) > 0.2 * float(base_mean[m]) else 0.0) for m in ids}
            extra = max(0.0, (rec_share - base_share) * rec_in)
            # Smallest change in unmetered energy we can tell apart from noise
            # (day-to-day spread of the share, for a recent_days average).
            noise = float(share.iloc[:baseline_days].std()) * rec_in / np.sqrt(recent_days)
            dt_gap[dt_id] = {
                "noise_kwh": 3 * noise,
                "extra_unmetered_kwh": extra,
                "loss_pct_base": 100 * base_share,
                "loss_pct_recent": 100 * rec_share,
                "explained": attribute_gap(extra, drops),
            }

    # ── L3: Isolation Forest on the engineered features ──
    slope = pd.Series(0.0, index=mat.index)
    if trend_block.shape[1] >= 5:
        x = np.arange(trend_block.shape[1])
        for m in mat.index:
            y = trend_block.loc[m].to_numpy(dtype=float)
            ok = ~np.isnan(y)
            if ok.sum() >= 5 and base_mean[m] > 0:
                slope[m] = float(np.polyfit(x[ok], y[ok], 1)[0] / base_mean[m])
    feats = pd.DataFrame({"ratio": ratio, "rel": rel, "zero": zero_frac, "slope": slope, "z": zscore.clip(-20, 20)})
    iso = pd.Series(0.0, index=mat.index)
    if len(feats) >= 10:
        from sklearn.ensemble import IsolationForest
        model = IsolationForest(n_estimators=200, contamination="auto", random_state=0).fit(feats.to_numpy())
        raw = -model.score_samples(feats.to_numpy())          # higher = more anomalous
        lo, hi = float(np.percentile(raw, 50)), float(raw.max())
        iso = pd.Series([_clip((r - lo) / (hi - lo)) if hi > lo else 0.0 for r in raw], index=mat.index)

    results: List[MeterScore] = []
    for m in mat.index:
        t = topo.loc[m] if m in topo.index else None
        dt_id = str(t["dt_id"]) if t is not None else ""
        bm, rm = float(base_mean[m]), float(recent_mean[m])
        drop = _clip(1 - float(ratio[m]))
        category = category_for(bm)

        # L1
        flat = float(zero_frac[m])
        l1_strength = max(_clip((drop - 0.2) / 0.6) if float(zscore[m]) <= -1.5 else 0.0, _clip((flat - 0.3) / 0.5))
        l1 = Layer("self_history", l1_strength >= 0.25, l1_strength, round(float(zscore[m]), 2),
                   (f"Last {recent_days} days average {rm:.1f} kWh/day vs {bm:.1f} before "
                    f"({-100 * drop:+.0f}%, z = {float(zscore[m]):.1f})"
                    + (f"; {flat * recent_days:.0f} of {recent_days} days near zero." if flat > 0 else ".")))
        # L2
        r = float(rel[m])
        l2_strength = _clip((0.85 - r) / 0.6)
        l2 = Layer("peer_comparison", l2_strength >= 0.25, l2_strength, round(100 * (r - 1), 1),
                   f"Relative to the other meters on {dt_id} (median change {100 * (float(peer_med[m]) - 1):+.0f}%), "
                   f"this meter is {100 * (r - 1):+.0f}%.")
        # L0
        g = dt_gap.get(dt_id)
        if g is not None and max(0.0, bm - rm) < g["noise_kwh"]:
            explained = None
            l0 = Layer("dt_balance", False, 0.0, round(g["loss_pct_recent"] - g["loss_pct_base"], 1),
                       f"This meter's drop ({bm - rm:.1f} kWh/day) is too small to see in {dt_id}'s energy balance "
                       f"(noise about {g['noise_kwh']:.1f} kWh/day), so this layer is inconclusive.")
        elif g is not None:
            my_drop = max(0.0, bm - rm)
            explained = float(g["explained"].get(m, 0.0))
            l0 = Layer("dt_balance", explained >= 0.5 and my_drop > 0, explained,
                       round(g["loss_pct_recent"] - g["loss_pct_base"], 1),
                       (f"{dt_id} unmetered energy {g['loss_pct_base']:.1f}% -> {g['loss_pct_recent']:.1f}% of input "
                        f"(+{g['extra_unmetered_kwh']:.1f} kWh/day). "
                        + ("That missing energy accounts for this meter's drop, so the load is still being drawn."
                           if explained >= 0.5 and my_drop > 0 else
                           "The transformer is not losing extra energy, so the drop looks genuine." if my_drop > 0
                           else "No drop at this meter to explain.")))
        else:
            explained = None
            l0 = Layer("dt_balance", False, 0.0, None, "No transformer input data, so this layer was skipped.")
        # L3
        l3s = float(iso[m])
        l3 = Layer("isolation_forest", l3s >= 0.6, l3s, round(l3s, 2),
                   f"Multivariate outlier score {l3s:.2f} (ratio, peer gap, zero days, trend).")

        # Gradual tampering: a steady decline over the last three weeks, even
        # before the weekly average has fallen far below baseline.
        recent_trend = mat.loc[m].iloc[max(0, end - 21):end].to_numpy(dtype=float)
        trend_drop = 0.0
        ok = ~np.isnan(recent_trend)
        if ok.sum() >= 10 and bm > 0:
            xs = np.arange(len(recent_trend))[ok]
            fit = np.polyfit(xs, recent_trend[ok], 1)
            resid_sd = float(np.std(recent_trend[ok] - np.polyval(fit, xs))) or 1e-9
            decline = -fit[0] * (len(recent_trend) - 1) / bm            # fraction lost over 3 weeks
            t_stat = -fit[0] * np.sqrt(((xs - xs.mean()) ** 2).sum()) / resid_sd
            if TREND_SIGNAL and t_stat > 3:
                trend_drop = _clip((decline - 0.15) / 0.35)
        if trend_drop > l1_strength:
            l1.strength = max(l1.strength, trend_drop)
            l1.fired = l1.strength >= 0.25
            l1.detail += f" Steady decline of about {100 * (trend_drop * 0.35 + 0.15):.0f}% over the last 3 weeks."
            l1_strength = l1.strength
        evidence = max(l1_strength, l2_strength * 0.8)
        if explained is not None:
            conf = evidence * (0.3 + 0.5 * explained) + 0.1 * l2_strength + 0.1 * l3s
        else:
            conf = evidence * 0.6 + 0.25 * l2_strength + 0.15 * l3s
        conf = round(_clip(conf), 3)

        if flat >= 0.6:
            pattern = "flatline"
        elif drop >= 0.3:
            pattern = classify_shape(mat.loc[m].iloc[baseline_days // 2:].to_numpy(dtype=float), bm)
        else:
            pattern = "normal"

        loss = max(0.0, bm - rm) * 30 * TARIFF_INR_PER_KWH[category]
        results.append(MeterScore(
            meter_id=m, dt_id=dt_id, feeder_id=str(t["feeder_id"]) if t is not None else "",
            zone=str(t["zone"]) if t is not None and "zone" in t else "", category=category, date=target_date,
            confidence=conf, tier=tier_for(conf), flagged=conf >= FLAG_THRESHOLD, pattern=pattern,
            baseline_kwh=round(bm, 2), recent_kwh=round(rm, 2), drop_pct=round(100 * drop, 1),
            est_monthly_loss_inr=round(loss * conf, 0), layers=[l0, l1, l2, l3],
        ))
    return results


def rank_queue(scores: List[MeterScore], limit: int = 20) -> List[MeterScore]:
    """Flagged meters, highest expected recoverable rupees first."""
    flagged = [s for s in scores if s.flagged]
    return sorted(flagged, key=lambda s: (-s.est_monthly_loss_inr, -s.confidence))[:limit]
