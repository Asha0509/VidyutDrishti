"""
Observability store: every LLM call and every triage run, persisted to SQLite.

A small SQLite file, written from the synchronous LLM client (which runs in a
worker thread). The Ops page reads it through /api/v1/ai/ops/*.
"""

from __future__ import annotations

import contextvars
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from statistics import median
from typing import Any, Dict, Iterator, List, Optional

_DB_PATH = os.environ.get("OBS_DB_PATH", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                                                      "observability.db"))
_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None

# Which session / purpose the current LLM call belongs to (set by callers).
current_session: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("obs_session", default=None)
current_purpose: contextvars.ContextVar[str] = contextvars.ContextVar("obs_purpose", default="unspecified")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    session_id TEXT,
    purpose TEXT,
    provider TEXT,
    model TEXT,
    status TEXT,            -- ok | error | skipped
    error TEXT,
    latency_ms REAL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    tool_calls INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS triage_runs (  -- one row per agent run (copilot, brief, digest)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    session_id TEXT,
    decision_path TEXT,     -- agent | rules
    label TEXT,             -- feature: copilot | brief | digest
    escalated INTEGER,
    red_flags TEXT,         -- JSON list of rule ids
    fallback_reason TEXT,
    latency_ms REAL,
    llm_calls INTEGER,
    tool_calls INTEGER,
    source TEXT             -- web | eval | api
);
CREATE INDEX IF NOT EXISTS idx_llm_ts ON llm_calls(ts);
CREATE INDEX IF NOT EXISTS idx_runs_ts ON triage_runs(ts);
"""


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        _conn.executescript(_SCHEMA)
        _conn.commit()
    return _conn


def reset_for_tests(path: str) -> None:
    """Point the store at a fresh file (tests only)."""
    global _conn, _DB_PATH
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = None
        _DB_PATH = path


@contextmanager
def tagged(session_id: Optional[str], purpose: str) -> Iterator[None]:
    """Tag LLM calls made inside this block with a session and purpose."""
    t1 = current_session.set(session_id)
    t2 = current_purpose.set(purpose)
    try:
        yield
    finally:
        current_session.reset(t1)
        current_purpose.reset(t2)


def record_llm_call(
    provider: str,
    model: str,
    status: str,
    latency_ms: float,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    tool_calls: int = 0,
    error: Optional[str] = None,
) -> None:
    row = (time.time(), current_session.get(), current_purpose.get(), provider, model, status,
           (error or "")[:300] or None, round(latency_ms, 1), prompt_tokens, completion_tokens, tool_calls)
    try:
        with _lock:
            _db().execute(
                "INSERT INTO llm_calls (ts, session_id, purpose, provider, model, status, error, latency_ms,"
                " prompt_tokens, completion_tokens, tool_calls) VALUES (?,?,?,?,?,?,?,?,?,?,?)", row)
            _db().commit()
    except sqlite3.Error:
        pass  # observability must never break triage


def record_run(
    session_id: Optional[str],
    decision_path: str,
    label: str,
    escalated: bool,
    red_flags: List[str],
    fallback_reason: Optional[str],
    latency_ms: float,
    llm_calls: int,
    tool_calls: int,
    source: str = "web",
) -> None:
    row = (time.time(), session_id, decision_path, label, int(escalated), json.dumps(red_flags),
           fallback_reason, round(latency_ms, 1), llm_calls, tool_calls, source)
    try:
        with _lock:
            _db().execute(
                "INSERT INTO triage_runs (ts, session_id, decision_path, label, escalated, red_flags,"
                " fallback_reason, latency_ms, llm_calls, tool_calls, source) VALUES (?,?,?,?,?,?,?,?,?,?,?)", row)
            _db().commit()
    except sqlite3.Error:
        pass


def _pct(values: List[float], p: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, round(p / 100 * (len(s) - 1))))
    return round(s[k], 1)


def summary(window_hours: float = 24 * 7, include_eval: bool = False) -> Dict[str, Any]:
    since = time.time() - window_hours * 3600
    with _lock:
        calls = _db().execute(
            "SELECT provider, purpose, status, latency_ms, prompt_tokens, completion_tokens, tool_calls"
            " FROM llm_calls WHERE ts >= ?", (since,)).fetchall()
        src_filter = "" if include_eval else " AND source != 'eval'"
        runs = _db().execute(
            "SELECT decision_path, label, escalated, fallback_reason, latency_ms, llm_calls, tool_calls"
            f" FROM triage_runs WHERE ts >= ?{src_filter}", (since,)).fetchall()

    ok = [c for c in calls if c[2] == "ok"]
    errors = [c for c in calls if c[2] == "error"]
    by_provider: Dict[str, Dict[str, Any]] = {}
    for c in calls:
        d = by_provider.setdefault(c[0], {"calls": 0, "errors": 0, "latencies": []})
        d["calls"] += 1
        d["errors"] += c[2] == "error"
        if c[2] == "ok":
            d["latencies"].append(c[3])
    by_purpose: Dict[str, int] = {}
    for c in calls:
        by_purpose[c[1]] = by_purpose.get(c[1], 0) + 1

    lat = [c[3] for c in ok]
    run_lat = [r[4] for r in runs]
    paths: Dict[str, int] = {}
    labels: Dict[str, int] = {}
    for r in runs:
        paths[r[0]] = paths.get(r[0], 0) + 1
        labels[r[1]] = labels.get(r[1], 0) + 1
    fallback_runs = sum(1 for r in runs if r[3])

    return {
        "window_hours": window_hours,
        "llm": {
            "calls": len(calls),
            "errors": len(errors),
            "error_rate": round(len(errors) / len(calls), 3) if calls else None,
            "latency_ms_p50": _pct(lat, 50),
            "latency_ms_p95": _pct(lat, 95),
            "prompt_tokens": sum(c[4] or 0 for c in ok),
            "completion_tokens": sum(c[5] or 0 for c in ok),
            "tool_calls": sum(c[6] or 0 for c in ok),
            "by_provider": {
                k: {"calls": v["calls"], "errors": v["errors"],
                    "latency_ms_p50": round(median(v["latencies"]), 1) if v["latencies"] else None}
                for k, v in by_provider.items()
            },
            "by_purpose": by_purpose,
        },
        "triage": {
            "runs": len(runs),
            "by_decision_path": paths,
            "by_label": labels,
            "escalations": sum(r[2] for r in runs),
            "fallback_rate": round(fallback_runs / len(runs), 3) if runs else None,
            "latency_ms_p50": _pct(run_lat, 50),
            "latency_ms_p95": _pct(run_lat, 95),
            "avg_llm_calls": round(sum(r[5] for r in runs) / len(runs), 2) if runs else None,
        },
    }


def recent_calls(limit: int = 50) -> List[Dict[str, Any]]:
    with _lock:
        rows = _db().execute(
            "SELECT ts, session_id, purpose, provider, model, status, error, latency_ms, prompt_tokens,"
            " completion_tokens, tool_calls FROM llm_calls ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    keys = ["ts", "session_id", "purpose", "provider", "model", "status", "error", "latency_ms",
            "prompt_tokens", "completion_tokens", "tool_calls"]
    return [dict(zip(keys, r)) for r in rows]


def recent_runs(limit: int = 50) -> List[Dict[str, Any]]:
    with _lock:
        rows = _db().execute(
            "SELECT ts, session_id, decision_path, label, escalated, red_flags, fallback_reason, latency_ms,"
            " llm_calls, tool_calls, source FROM triage_runs ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    keys = ["ts", "session_id", "decision_path", "label", "escalated", "red_flags", "fallback_reason",
            "latency_ms", "llm_calls", "tool_calls", "source"]
    out = []
    for r in rows:
        d = dict(zip(keys, r))
        d["red_flags"] = json.loads(d["red_flags"] or "[]")
        d["escalated"] = bool(d["escalated"])
        out.append(d)
    return out


def timeseries(window_hours: float = 24, bucket_minutes: int = 60) -> List[Dict[str, Any]]:
    """LLM calls bucketed over time for the Ops chart."""
    since = time.time() - window_hours * 3600
    size = bucket_minutes * 60
    with _lock:
        rows = _db().execute("SELECT ts, status, latency_ms FROM llm_calls WHERE ts >= ?", (since,)).fetchall()
    buckets: Dict[int, Dict[str, Any]] = {}
    for ts, status, latency in rows:
        b = int(ts // size * size)
        d = buckets.setdefault(b, {"ts": b, "calls": 0, "errors": 0, "lat": []})
        d["calls"] += 1
        d["errors"] += status == "error"
        if status == "ok":
            d["lat"].append(latency)
    out = []
    for b in sorted(buckets):
        d = buckets[b]
        out.append({"ts": d["ts"], "calls": d["calls"], "errors": d["errors"],
                    "latency_ms_p50": round(median(d["lat"]), 1) if d["lat"] else None})
    return out
