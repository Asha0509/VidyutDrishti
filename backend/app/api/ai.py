"""AI endpoints: analytics copilot, inspection briefs, smart alerts, and the LLM ops view."""

from __future__ import annotations

import json
import os
import time
import uuid
from collections import defaultdict, deque
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app import store as store_mod
from app.ai import agents, alerts, llm, observability

router = APIRouter(prefix="/ai", tags=["AI"])

# Public demo: cap model-backed requests per client so a shared API key can't be drained.
RATE_LIMIT, RATE_WINDOW_S = 20, 600
_hits: Dict[str, deque] = defaultdict(deque)
_brief_cache: Dict[tuple, Dict[str, Any]] = {}
EVAL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "evals", "results")


def _limit(request: Request) -> None:
    if not llm.has_any_provider():
        return
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
    q, now = _hits[ip], time.time()
    while q and now - q[0] > RATE_WINDOW_S:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many AI requests from you in the last 10 minutes. Try again shortly.")
    q.append(now)


def _need_data() -> None:
    if not store_mod.store.dates():
        raise HTTPException(status_code=503, detail="Demo data is still loading. Try again in a minute.")


class Turn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=2000)


class CopilotRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    history: List[Turn] = Field(default_factory=list, max_length=12)
    use_llm: bool = True


@router.get("/status")
async def status() -> Dict[str, Any]:
    return {"llm_providers": llm.configured_providers(),
            "llm_models": {p.name: p.model() for p in llm.PROVIDERS if p.key()},
            "agent_enabled": llm.has_any_provider(), "data_ready": bool(store_mod.store.dates()),
            "rate_limit": f"{RATE_LIMIT} AI requests per {RATE_WINDOW_S // 60} minutes per visitor"}


@router.post("/copilot")
async def copilot(req: CopilotRequest, request: Request) -> Dict[str, Any]:
    """Answer a question about the network; the agent fetches every number through data tools."""
    _need_data()
    _limit(request)
    sid = f"copilot-{uuid.uuid4().hex[:8]}"
    return await run_in_threadpool(agents.copilot, req.question, [t.model_dump() for t in req.history],
                                   req.use_llm, sid)


@router.post("/brief/{meter_id}")
async def brief(meter_id: str, request: Request, use_llm: bool = True, refresh: bool = False) -> Dict[str, Any]:
    """Inspection brief for one meter: likely cause, evidence and what to check on site."""
    _need_data()
    key = (meter_id.upper(), store_mod.store._version, use_llm and llm.has_any_provider())
    if key in _brief_cache and not refresh:
        return {**_brief_cache[key], "cached": True}
    _limit(request)
    out = await run_in_threadpool(agents.inspection_brief, meter_id, use_llm, f"brief-{uuid.uuid4().hex[:8]}")
    if out is None:
        raise HTTPException(status_code=404, detail=f"No meter called {meter_id}.")
    _brief_cache[key] = out
    return {**out, "cached": False}


@router.get("/alerts")
async def list_alerts(days: int = Query(7, ge=1, le=14)) -> Dict[str, Any]:
    _need_data()
    items = await run_in_threadpool(alerts.alerts, days)
    return {"days": days, "alerts": items}


@router.get("/alerts/digest")
async def alerts_digest(request: Request, days: int = Query(1, ge=1, le=14), use_llm: bool = True) -> Dict[str, Any]:
    _need_data()
    _limit(request)
    return await run_in_threadpool(alerts.digest, days, use_llm)


@router.get("/ops/summary")
async def ops_summary(hours: float = Query(168, gt=0, le=24 * 90)) -> Dict[str, Any]:
    return observability.summary(hours, include_eval=False)


@router.get("/ops/calls")
async def ops_calls(limit: int = Query(40, ge=1, le=500)) -> Dict[str, Any]:
    return {"calls": observability.recent_calls(limit)}


@router.get("/ops/runs")
async def ops_runs(limit: int = Query(40, ge=1, le=500)) -> Dict[str, Any]:
    return {"runs": observability.recent_runs(limit)}


@router.get("/ops/timeseries")
async def ops_timeseries(hours: float = Query(24, gt=0, le=24 * 30), bucket_minutes: int = Query(60, ge=5)) -> Dict[str, Any]:
    return {"points": observability.timeseries(hours, bucket_minutes)}


@router.get("/evals")
async def ai_evals() -> Dict[str, Any]:
    """Latest results of evals/ai_eval.py per mode (rules baseline, agent), without per-case rows."""
    out: Dict[str, Any] = {}
    for mode in ("rules", "agent"):
        path = os.path.join(EVAL_DIR, f"ai-{mode}.json")
        if not os.path.isfile(path):
            continue
        with open(path) as f:
            rep = json.load(f)
        out[mode] = {"run_at": rep["run_at"], "networks": rep["networks"], "providers": rep.get("providers", []),
                     **{part: {k: v for k, v in rep[part].items() if k != "rows"} for part in ("brief", "copilot")},
                     "copilot_failures": [{k: r[k] for k in ("question", "expected", "answer")}
                                          for r in rep["copilot"]["rows"] if not r["pass"]][:6]}
    return out
