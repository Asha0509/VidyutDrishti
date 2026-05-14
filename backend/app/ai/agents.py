"""Tool-calling agents: the analytics copilot and the inspection brief (RCA).

Both run the same loop: the model calls data tools, sees their JSON, and
finishes with a final tool call (``final_answer`` / ``submit_brief``). Every
step is traced and every model call is logged. When no LLM provider is
configured, or the agent fails, a deterministic fallback answers instead and
says why.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional

from app.ai import llm, observability, tools

MAX_TURNS = 6


def _short(obj: Any, n: int = 240) -> str:
    s = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return s if len(s) <= n else s[: n - 1] + "…"


def run_loop(system: str, user: str, tool_names: List[str], final_tool: Dict, trace: List[Dict],
             max_tokens: int = 900) -> Optional[Dict]:
    """Generic loop. Returns {'args': final tool arguments, provider, model, llm_calls, tool_calls, used}."""
    messages: List[Dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    specs = [tools.SPECS[n] for n in tool_names] + [final_tool]
    final_name = final_tool["function"]["name"]
    llm_calls = tool_calls = 0
    used: List[str] = []
    nudged = False
    last = None
    for _ in range(MAX_TURNS):
        res = llm.chat(messages, tools=specs, temperature=0.1, max_tokens=max_tokens)
        llm_calls += 1
        if res is None:
            trace.append({"kind": "llm", "name": "chat", "ok": False, "summary": "all providers failed"})
            return None
        last = res
        trace.append({"kind": "llm", "name": "chat", "provider": res.provider, "model": res.model,
                      "ms": round(res.latency_ms), "failovers": res.errors,
                      "summary": (f"requested {', '.join(c['name'] for c in res.tool_calls)}" if res.tool_calls
                                  else _short(res.content or "(empty)"))})
        msg: Dict[str, Any] = {"role": "assistant", "content": res.content or ""}
        if res.tool_calls:
            msg["tool_calls"] = [{"id": c["id"], "type": "function",
                                  "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
                                 for c in res.tool_calls]
        messages.append(msg)
        if not res.tool_calls:
            if nudged:
                break
            nudged = True
            messages.append({"role": "user", "content": f"Use the data tools if needed, then call {final_name}."})
            continue
        for c in res.tool_calls:
            tool_calls += 1
            if c["name"] == final_name:
                trace.append({"kind": "tool", "name": final_name, "summary": "final answer submitted"})
                return {"args": c["arguments"], "provider": res.provider, "model": res.model,
                        "llm_calls": llm_calls, "tool_calls": tool_calls, "used": used}
            started = time.perf_counter()
            out = tools.run(c["name"], c["arguments"])
            used.append(c["name"])
            trace.append({"kind": "tool", "name": c["name"], "args": c["arguments"],
                          "ms": round((time.perf_counter() - started) * 1000, 1), "summary": _short(out)})
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(out)})
    if last and last.content and used:
        # The model answered in plain text after using tools; accept it for the copilot.
        trace.append({"kind": "note", "name": "plain_text_answer", "summary": "model replied without the final tool"})
        return {"args": {"answer": last.content}, "provider": last.provider, "model": last.model,
                "llm_calls": llm_calls, "tool_calls": tool_calls, "used": used, "plain": True}
    trace.append({"kind": "note", "name": "no_answer", "summary": f"no final answer after {llm_calls} turns"})
    return None


# ── Copilot ──────────────────────────────────────────────────────────────

COPILOT_SYSTEM = """You are the analytics copilot for VidyutDrishti, an electricity-theft detection system for a
distribution utility in Bengaluru. Answer questions about the network using ONLY numbers returned by the tools.

- Call tools to fetch data before answering. Never guess or invent numbers, meters or zones.
- Zones map one-to-one to transformers (ZoneA = DT1 ... ZoneH = DT8). Money is INR per month.
- Keep answers short: 1-4 sentences, then up to 5 bullets if listing items. Plain language.
- If the tools can't answer the question, say so and suggest what you can answer.
- Finish by calling final_answer."""

FINAL_ANSWER = {"type": "function", "function": {
    "name": "final_answer", "description": "Submit the answer to the user's question.",
    "parameters": {"type": "object", "properties": {
        "answer": {"type": "string", "description": "The answer, in plain language, with the numbers you fetched."},
        "follow_ups": {"type": "array", "items": {"type": "string"}, "description": "Up to 3 useful next questions."},
    }, "required": ["answer"]}}}

COPILOT_TOOLS = ["get_overview", "list_zones", "get_queue", "find_meters", "get_meter", "get_dt_balance",
                 "detection_quality", "get_alerts"]

_METER = re.compile(r"\bdt\s?(\d+)\s?-\s?m\s?(\d+)\b", re.I)
_DT = re.compile(r"\b(?:dt|transformer)\s?(\d+)\b", re.I)
_ZONE = re.compile(r"\bzone\s?([a-h])\b", re.I)


def _inr(x: float) -> str:
    return f"₹{x:,.0f}"


def copilot_rules(question: str, trace: List[Dict]) -> Dict[str, Any]:
    """Deterministic answers for common questions (used without an LLM)."""
    q = question.lower()
    m = _METER.search(question)
    if m:
        mid = f"DT{int(m.group(1))}-M{int(m.group(2)):02d}"
        d = tools.get_meter(mid)
        trace.append({"kind": "tool", "name": "get_meter", "args": {"meter_id": mid}, "summary": _short(d)})
        if "error" in d:
            return {"answer": f"There's no meter called {mid}. Meter ids look like DT1-M03."}
        why = next((l["detail"] for l in d["layers"] if l["layer"] == "dt_balance"), "")
        return {"answer": (f"{mid} ({d['category']}, {d['zone']}) is {d['tier']} risk with confidence "
                           f"{d['confidence']:.2f}. It averaged {d['recent_kwh_per_day']} kWh/day over the last week "
                           f"against {d['baseline_kwh_per_day']} before ({-d['drop_pct']:+.0f}%), pattern "
                           f"{d['pattern'].replace('_', ' ')}. {why}")}
    if "zone" in q and any(w in q for w in ("most", "highest", "worst", "biggest", "top")):
        z = tools.list_zones()["zones"]
        trace.append({"kind": "tool", "name": "list_zones", "summary": f"{len(z)} zones"})
        top = max(z, key=lambda r: r["estimated_monthly_loss_inr"])
        return {"answer": (f"{top['zone']} ({top['place']}, {top['dt_id']}) has the highest estimated loss: "
                           f"{_inr(top['estimated_monthly_loss_inr'])} a month from {top['flagged']} flagged meters.")}
    if any(w in q for w in ("precision", "recall", "accuracy", "accurate", "f1", "how good", "how well")):
        d = tools.detection_quality()
        trace.append({"kind": "tool", "name": "detection_quality", "summary": _short(d)})
        h = d.get("held_out")
        if not h:
            return {"answer": "No evaluation results are available."}
        return {"answer": (f"On {h['networks']} unseen synthetic networks the detector averages precision "
                           f"{h['precision']:.2f}, recall {h['recall']:.2f} and F1 {h['f1']:.2f}.")}
    dt, zone = _DT.search(question), _ZONE.search(question)
    if dt or zone:
        n = int(dt.group(1)) if dt else ord(zone.group(1).upper()) - 64   # ZoneA = DT1
        d = tools.get_dt_balance(f"DT{n}")
        trace.append({"kind": "tool", "name": "get_dt_balance", "summary": _short(d)})
        if "error" in d:
            return {"answer": d["error"]}
        u = d["unmetered_pct"]
        return {"answer": (f"{d['dt_id']}: unmetered energy was {u[0]:.1f}% of input {len(u)} days ago and "
                           f"{u[-1]:.1f}% on the latest day.")}
    if any(w in q for w in ("inspect", "queue", "top", "priority", "suspicious", "which meters")):
        d = tools.get_queue(limit=5)
        trace.append({"kind": "tool", "name": "get_queue", "summary": _short(d)})
        lines = [f"{i['meter_id']} ({i['zone']}, {i['tier']}): {_inr(i['estimated_monthly_loss_inr'])}/month"
                 for i in d["items"]]
        return {"answer": f"{d['total']} meters are flagged. Inspect these first:\n- " + "\n- ".join(lines)}
    if any(w in q for w in ("how many", "overview", "summary", "loss", "total")):
        d = tools.get_overview()
        trace.append({"kind": "tool", "name": "get_overview", "summary": _short(d)})
        return {"answer": (f"{d['flagged']} of {d['meters']} meters are flagged ({d['pending']} awaiting inspection), "
                           f"estimated {_inr(d['estimated_monthly_loss_inr'])} a month. {d['zones_at_risk']} of "
                           f"{d['zones']} zones are at medium or high risk.")}
    return {"answer": ("Without the AI model I can only answer set questions, for example: 'Which zone is losing the "
                       "most?', 'Which meters should we inspect first?', 'Tell me about DT1-M03', 'How is DT3's "
                       "energy balance?' or 'How accurate is the detector?'")}


def copilot(question: str, history: Optional[List[Dict[str, str]]] = None, use_llm: bool = True,
            session_id: Optional[str] = None) -> Dict[str, Any]:
    started = time.perf_counter()
    trace: List[Dict] = []
    out = None
    fallback = None
    if use_llm and llm.has_any_provider():
        convo = "\n".join(f"{h['role']}: {h['content']}" for h in (history or [])[-6:])
        user = (f"Earlier in this conversation:\n{convo}\n\n" if convo else "") + f"Question: {question}"
        with observability.tagged(session_id, "copilot"):
            try:
                out = run_loop(COPILOT_SYSTEM, user, COPILOT_TOOLS, FINAL_ANSWER, trace)
            except Exception as exc:
                trace.append({"kind": "note", "name": "agent_error", "summary": type(exc).__name__})
        if out is None:
            fallback = "agent_failed"
    else:
        fallback = "no_llm_provider" if use_llm else "llm_disabled"

    if out:
        result = {"answer": str(out["args"].get("answer", "")).strip(),
                  "follow_ups": [str(f) for f in (out["args"].get("follow_ups") or [])][:3],
                  "mode": "agent", "provider": out["provider"], "model": out["model"],
                  "llm_calls": out["llm_calls"], "tool_calls": out["tool_calls"], "tools_used": out["used"]}
    else:
        r = copilot_rules(question, trace)
        result = {"answer": r["answer"], "follow_ups": [], "mode": "rules", "provider": None, "model": None,
                  "llm_calls": 0, "tool_calls": sum(1 for t in trace if t["kind"] == "tool"),
                  "tools_used": [t["name"] for t in trace if t["kind"] == "tool"]}
    latency = (time.perf_counter() - started) * 1000
    observability.record_run(session_id, result["mode"], "copilot", False, [], fallback, latency,
                             result["llm_calls"], result["tool_calls"])
    return {**result, "fallback_reason": fallback, "latency_ms": round(latency), "steps": trace}


# ── Inspection brief (RCA) ───────────────────────────────────────────────

CAUSES = ["hook_bypass", "gradual_tampering", "meter_stopped", "genuine_drop", "inconclusive"]
CAUSE_NAMES = {
    "hook_bypass": "Direct connection bypassing the meter (hooking)",
    "gradual_tampering": "Gradual meter tampering",
    "meter_stopped": "Meter stopped or disconnected",
    "genuine_drop": "Genuine drop in use (vacancy, reduced load)",
    "inconclusive": "Inconclusive",
}
FIELD_CHECKS = {
    "hook_bypass": ["Trace the service cable from the pole to the meter for taps or a second feed",
                    "Compare a clamp-meter reading on the incoming cable with the meter's live reading",
                    "Look for fresh joints, loose seals or wiring that skips the meter"],
    "gradual_tampering": ["Check the meter seals and casing for signs of opening",
                          "Run an accuracy test against a reference meter under known load",
                          "Look for magnets or devices near the meter"],
    "meter_stopped": ["Check whether the meter display and pulse LED are live",
                      "Check for a burnt or disconnected meter, or a bypassed terminal block",
                      "If the premises is occupied and using power, treat as bypass until proven otherwise"],
    "genuine_drop": ["Confirm occupancy with neighbours or the account holder",
                     "Check for a change of use (shop closed, tenants moved out)",
                     "No tampering checks needed unless occupancy is confirmed"],
    "inconclusive": ["Do a standard visual inspection of the meter and seals",
                     "Take a spot clamp-meter reading to compare with the meter"],
}
SAFETY = "Live-line work: inspect with a two-person crew, PPE and an isolation plan."

SUBMIT_BRIEF = {"type": "function", "function": {
    "name": "submit_brief", "description": "Submit the inspection brief for this meter.",
    "parameters": {"type": "object", "properties": {
        "likely_cause": {"type": "string", "enum": CAUSES},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "summary": {"type": "string", "description": "2 sentences for the field team."},
        "evidence": {"type": "array", "items": {"type": "string"}, "description": "3-5 facts from the data."},
        "field_checks": {"type": "array", "items": {"type": "string"}, "description": "3-5 things to check on site."},
    }, "required": ["likely_cause", "confidence", "summary", "evidence", "field_checks"]}}}

BRIEF_SYSTEM = """You write inspection briefs for electricity-theft field teams.
Work out the most likely cause of a meter's drop from its data, then call submit_brief.

Causes:
- hook_bypass: consumption fell suddenly (a step within a day or two) while the transformer kept supplying the
  energy (it shows up as unmetered at the transformer). Readings often fall to a small fraction, not exactly zero.
- gradual_tampering: consumption declines steadily over weeks (a ramp), with the transformer still supplying it.
- meter_stopped: readings are exactly or almost exactly zero for days while energy is still drawn.
- genuine_drop: the drop is real use falling (vacancy) - the transformer is NOT losing extra energy for it.
- inconclusive: the data doesn't support any of the above.

Use get_meter (daily kWh vs peers and each layer's evidence) and get_dt_balance. Look at the SHAPE of the daily
series to tell a step from a ramp. Cite numbers from the tools in the evidence. Be concise and practical."""


def brief_rules(meter: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic cause from the detector's own pattern and balance layer."""
    l0 = next((l for l in meter["layers"] if l["layer"] == "dt_balance"), {})
    genuine = "looks genuine" in l0.get("detail", "")
    p = meter["pattern"]
    if genuine:
        cause = "genuine_drop"
    elif p == "flatline":
        cause = "meter_stopped" if meter["recent_kwh_per_day"] <= 0.02 * max(meter["baseline_kwh_per_day"], 1e-9) else "hook_bypass"
    elif p == "sudden_drop":
        cause = "hook_bypass"
    elif p == "gradual_decline":
        cause = "gradual_tampering"
    else:
        cause = "inconclusive"
    conf = "high" if meter["confidence"] >= 0.8 else ("medium" if meter["confidence"] >= 0.6 else "low")
    return {"likely_cause": cause, "confidence": conf,
            "summary": (f"{meter['meter_id']} is down {meter['drop_pct']:.0f}% on its baseline "
                        f"({meter['baseline_kwh_per_day']} to {meter['recent_kwh_per_day']} kWh/day), "
                        f"pattern {p.replace('_', ' ')}. Most likely: {CAUSE_NAMES[cause].lower()}."),
            "evidence": [l["detail"] for l in meter["layers"] if l["fired"]][:4] or [l0.get("detail", "")],
            "field_checks": FIELD_CHECKS[cause]}


def inspection_brief(meter_id: str, use_llm: bool = True, session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    started = time.perf_counter()
    meter = tools.get_meter(meter_id)
    if "error" in meter:
        return None
    trace: List[Dict] = [{"kind": "tool", "name": "get_meter", "args": {"meter_id": meter["meter_id"]},
                          "summary": f"confidence {meter['confidence']}, pattern {meter['pattern']}"}]
    out = None
    fallback = None
    if use_llm and llm.has_any_provider():
        user = (f"Write the inspection brief for meter {meter['meter_id']} on {meter['dt_id']}. "
                f"Here is its data from get_meter:\n{json.dumps(meter)}")
        with observability.tagged(session_id, "inspection_brief"):
            try:
                out = run_loop(BRIEF_SYSTEM, user, ["get_meter", "get_dt_balance"], SUBMIT_BRIEF, trace, 700)
            except Exception as exc:
                trace.append({"kind": "note", "name": "agent_error", "summary": type(exc).__name__})
        if out is None or out.get("plain") or out["args"].get("likely_cause") not in CAUSES:
            fallback = "agent_failed"
            out = None
    else:
        fallback = "no_llm_provider" if use_llm else "llm_disabled"

    if out:
        a = out["args"]
        brief = {"likely_cause": a["likely_cause"],
                 "confidence": a.get("confidence") if a.get("confidence") in ("low", "medium", "high") else "low",
                 "summary": str(a.get("summary", "")).strip(),
                 "evidence": [str(e) for e in (a.get("evidence") or [])][:5],
                 "field_checks": [str(e) for e in (a.get("field_checks") or [])][:5] or FIELD_CHECKS[a["likely_cause"]]}
        meta = {"mode": "agent", "provider": out["provider"], "model": out["model"],
                "llm_calls": out["llm_calls"], "tool_calls": out["tool_calls"]}
    else:
        brief = brief_rules(meter)
        meta = {"mode": "rules", "provider": None, "model": None, "llm_calls": 0, "tool_calls": 1}
    latency = (time.perf_counter() - started) * 1000
    observability.record_run(session_id, meta["mode"], "brief", False, [], fallback, latency,
                             meta["llm_calls"], meta["tool_calls"])
    return {"meter_id": meter["meter_id"], "dt_id": meter["dt_id"], "zone": meter["zone"],
            "detector_pattern": meter["pattern"], "detector_confidence": meter["confidence"],
            **brief, "cause_name": CAUSE_NAMES[brief["likely_cause"]], "safety_note": SAFETY,
            **meta, "fallback_reason": fallback, "latency_ms": round(latency), "steps": trace}
