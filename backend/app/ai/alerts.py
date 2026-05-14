"""Smart alerts: rules over day-to-day changes in the detector's output.

Rules (evaluated for each of the last N days against the day before):
  new_flag        a meter crosses the flag threshold
  escalation      a flagged meter moves up a tier (REVIEW, then MEDIUM, then HIGH)
  balance_jump    a transformer's unmetered share rises 5+ points vs a week earlier
  cleared         a flagged meter drops back below the threshold

Alerts are de-duplicated (one per meter per rule in the window; escalations
only when the tier actually rises) and grouped by zone in the digest. The
digest is written by the LLM when one is configured, otherwise from a template.
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any, Dict, List, Optional

from app import store as store_mod
from app.ai import llm, observability

TIER_RANK = {"NORMAL": 0, "REVIEW": 1, "MEDIUM": 2, "HIGH": 3}
SEVERITY = {"HIGH": "critical", "MEDIUM": "warning", "REVIEW": "info"}


def _balance_shares(rows: List[Dict]) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for r in rows:
        out.setdefault(r["dt_id"], {})[r["date"]] = r["unmetered_pct"]
    return out


def alerts(days: int = 7) -> List[Dict[str, Any]]:
    s = store_mod.store
    dates = s.dates()
    if len(dates) < 2:
        return []
    window = dates[-(days + 1):]
    items: List[Dict[str, Any]] = []
    seen = set()
    prev = {x.meter_id: x for x in s.scores(window[0])}
    # Highest tier already reported per meter, so a meter that wobbles
    # HIGH -> REVIEW -> MEDIUM doesn't re-alert on the way back up.
    peak = {m: TIER_RANK[x.tier] for m, x in prev.items()}
    shares = _balance_shares(s.dt_balance(days=days + 14))
    for d in window[1:]:
        cur = {x.meter_id: x for x in s.scores(d)}
        for mid, sc in cur.items():
            p = prev.get(mid)
            if sc.flagged and (p is None or not p.flagged) and (mid, "new_flag") not in seen:
                seen.add((mid, "new_flag"))
                items.append({"date": d.isoformat(), "type": "new_flag", "severity": SEVERITY.get(sc.tier, "info"),
                              "meter_id": mid, "zone": sc.zone, "dt_id": sc.dt_id, "tier": sc.tier,
                              "title": f"{mid} flagged {sc.tier} ({sc.pattern.replace('_', ' ')}, "
                                       f"{sc.drop_pct:.0f}% below baseline)",
                              "estimated_monthly_loss_inr": sc.est_monthly_loss_inr})
            elif p is not None and sc.flagged and p.flagged and TIER_RANK[sc.tier] > peak.get(mid, 0):
                items.append({"date": d.isoformat(), "type": "escalation", "severity": SEVERITY.get(sc.tier, "info"),
                              "meter_id": mid, "zone": sc.zone, "dt_id": sc.dt_id, "tier": sc.tier,
                              "title": f"{mid} risk rose from {p.tier.lower()} to {sc.tier.lower()}",
                              "estimated_monthly_loss_inr": sc.est_monthly_loss_inr})
            elif p is not None and p.flagged and not sc.flagged and (mid, "cleared") not in seen:
                seen.add((mid, "cleared"))
                items.append({"date": d.isoformat(), "type": "cleared", "severity": "info", "meter_id": mid,
                              "zone": sc.zone, "dt_id": sc.dt_id, "tier": sc.tier,
                              "title": f"{mid} no longer flagged", "estimated_monthly_loss_inr": 0})
        for dt_id, series in shares.items():
            today, week_ago = series.get(d.isoformat()), series.get((d - timedelta(days=7)).isoformat())
            if today is not None and week_ago is not None and today - week_ago >= 5 and (dt_id, "balance") not in seen:
                seen.add((dt_id, "balance"))
                items.append({"date": d.isoformat(), "type": "balance_jump",
                              "severity": "critical" if today - week_ago >= 15 else "warning",
                              "meter_id": None, "zone": next((z["id"] for z in s.zones() if z["dt_id"] == dt_id), dt_id),
                              "dt_id": dt_id, "tier": None,
                              "title": f"{dt_id} unmetered energy rose from {week_ago:.1f}% to {today:.1f}% in a week",
                              "estimated_monthly_loss_inr": 0})
        for mid, sc in cur.items():
            peak[mid] = max(peak.get(mid, 0), TIER_RANK[sc.tier])
        prev = cur
    order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(items, key=lambda a: (a["date"], -order[a["severity"]]), reverse=True)


def _period(days: int) -> str:
    return "last day" if days == 1 else f"last {days} days"


def _template_digest(items: List[Dict[str, Any]], days: int) -> str:
    if not items:
        return f"No new alerts in the {_period(days)}."
    crit = [a for a in items if a["severity"] == "critical"]
    zones: Dict[str, int] = {}
    for a in items:
        if a["type"] in ("new_flag", "escalation"):
            zones[a["zone"]] = zones.get(a["zone"], 0) + 1
    worst = sorted(zones.items(), key=lambda kv: -kv[1])[:3]
    best: Dict[str, Dict[str, Any]] = {}
    for a in items:
        if a.get("estimated_monthly_loss_inr") and a["estimated_monthly_loss_inr"] > best.get(a["meter_id"], {}).get("estimated_monthly_loss_inr", -1):
            best[a["meter_id"]] = a
    top = sorted(best.values(), key=lambda a: -a["estimated_monthly_loss_inr"])[:3]
    parts = [f"{len(items)} alert{'s' if len(items) != 1 else ''} in the {_period(days)}, {len(crit)} critical."]
    if worst:
        parts.append("Most activity: " + ", ".join(f"{z} ({n})" for z, n in worst) + ".")
    if top:
        parts.append("Inspect first: " + ", ".join(f"{a['meter_id']} (₹{a['estimated_monthly_loss_inr']:,.0f}/month)"
                                                  for a in top) + ".")
    return " ".join(parts)


def digest(days: int = 1, use_llm: bool = True) -> Dict[str, Any]:
    started = time.perf_counter()
    items = alerts(days=days)
    text, mode, provider, model, fallback = None, "rules", None, None, None
    if items and use_llm and llm.has_any_provider():
        lines = "\n".join(f"- [{a['severity']}] {a['date']} {a['title']} (zone {a['zone']}"
                          + (f", est. ₹{a['estimated_monthly_loss_inr']:,.0f}/month" if a.get("estimated_monthly_loss_inr") else "")
                          + ")" for a in items[:40])
        prompt = (f"Write a short morning digest (max 110 words) for the revenue-protection manager from these "
                  f"alerts of the last {days} day(s). Lead with what needs action today, group by zone, name the "
                  f"top meters to inspect with their rupee value, and mention transformer balance jumps. Use only "
                  f"facts from the list. Plain text, no headings.\n\nAlerts:\n{lines}")
        with observability.tagged(None, "alert_digest"):
            res = llm.chat([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=300)
        if res and res.content:
            text, mode, provider, model = res.content.strip(), "agent", res.provider, res.model
        else:
            fallback = "agent_failed"
    elif items:
        fallback = "no_llm_provider" if use_llm else "llm_disabled"
    if text is None:
        text = _template_digest(items, days)
    latency = (time.perf_counter() - started) * 1000
    observability.record_run(None, mode, "digest", False, [], fallback, latency, 1 if mode == "agent" else 0, 0)
    return {"days": days, "alert_count": len(items), "digest": text, "mode": mode, "provider": provider,
            "model": model, "fallback_reason": fallback, "latency_ms": round(latency)}
