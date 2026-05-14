import json
from datetime import date

import httpx
import pytest
import pytest_asyncio

from app.ai import agents, alerts, llm, observability, tools
from tests.test_store_api import slots_from_daily


def tc(name, args, cid=None):
    return {"id": cid or f"c_{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def reply(content="", calls=None):
    m = {"role": "assistant", "content": content}
    if calls:
        m["tool_calls"] = calls
    return {"choices": [{"message": m}], "usage": {"prompt_tokens": 50, "completion_tokens": 10}}


class Script:
    def __init__(self, replies, fail=()):
        self.replies, self.fail, self.requests = list(replies), set(fail), []

    def __call__(self, provider, payload):
        self.requests.append((provider.name, payload))
        if provider.name in self.fail:
            raise RuntimeError("down")
        return self.replies.pop(0)


@pytest.fixture(autouse=True)
def obs(tmp_path):
    observability.reset_for_tests(str(tmp_path / "obs.db"))


@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_NIM_API_KEY", raising=False)


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k1")
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "k2")

    def install(replies, fail=()):
        s = Script(replies, fail)
        monkeypatch.setattr(llm, "transport", s)
        return s
    return install


@pytest.fixture
def data(network, monkeypatch):
    from app.store import Store
    import app.store as store_mod
    import app.api.routes as routes
    daily, dt, topo = network(thefts={"DT1-M02": (25, 0.9, "step"), "DT2-M03": (20, 0.9, "ramp")},
                              vacancies={"DT3-M05": (25, 0.9)}, days=45, dts=3)
    s = Store()
    s.add_meter_frame(slots_from_daily(daily, "kwh", "meter_id"))
    s.add_dt_frame(slots_from_daily(dt, "kwh_in", "dt_id"))
    s.ready = True
    monkeypatch.setattr(store_mod, "store", s)
    monkeypatch.setattr(routes, "store", s)
    return s


def test_tools_return_store_numbers(data):
    ov = tools.get_overview()
    assert ov["flagged"] >= 2 and ov["meters"] == 18
    q = tools.get_queue(limit=1)
    assert len(q["items"]) == 1 and q["total"] >= 2
    m = tools.get_meter("dt1-m02")
    assert m["meter_id"] == "DT1-M02" and len(m["daily_kwh"]) == len(m["peer_median_kwh"]) and m["layers"]
    assert "error" in tools.get_meter("XX-1")
    assert tools.get_dt_balance("DT1")["unmetered_pct"]
    assert tools.find_meters(flagged_only=True)["count"] == ov["flagged"]
    assert tools.run("drop_tables", {})["error"].startswith("unknown")
    assert "bad arguments" in tools.run("get_meter", {"nope": 1})["error"]


def test_copilot_agent_uses_tools_and_answers(data, fake):
    script = fake([
        reply(calls=[tc("list_zones", {}, "a")]),
        reply(calls=[tc("final_answer", {"answer": "ZoneA loses the most.", "follow_ups": ["Why?"]}, "b")]),
    ])
    r = agents.copilot("Which zone loses the most?", session_id="s1")
    assert r["mode"] == "agent" and r["answer"] == "ZoneA loses the most." and r["tools_used"] == ["list_zones"]
    assert r["follow_ups"] == ["Why?"] and r["provider"] == "groq"
    sent = script.requests[1][1]["messages"]
    assert any(m.get("role") == "tool" and "zones" in m["content"] for m in sent), "tool output fed back"
    calls = observability.recent_calls(5)
    assert {c["purpose"] for c in calls} == {"copilot"} and all(c["session_id"] == "s1" for c in calls)


def test_copilot_failover_and_fallback(data, fake):
    fake([reply(calls=[tc("final_answer", {"answer": "ok"})])], fail={"groq"})
    assert agents.copilot("anything at all")["provider"] == "nvidia_nim"
    fake([], fail={"groq", "nvidia_nim"})
    r = agents.copilot("Which meters should we inspect first?")
    assert r["mode"] == "rules" and r["fallback_reason"] == "agent_failed" and "Inspect these first" in r["answer"]


def test_copilot_rules_without_key(data, no_key):
    r = agents.copilot("Tell me about dt1-m02")
    assert r["mode"] == "rules" and r["fallback_reason"] == "no_llm_provider" and "DT1-M02" in r["answer"]
    assert "ZoneA" in agents.copilot("which zone is losing the most?")["answer"]
    assert "DT2" in agents.copilot("energy balance for zone B")["answer"]
    assert "set questions" in agents.copilot("tell me a joke")["answer"]


def test_brief_agent_and_validation(data, fake):
    fake([reply(calls=[tc("get_dt_balance", {"dt_id": "DT2"}, "x")]),
          reply(calls=[tc("submit_brief", {"likely_cause": "gradual_tampering", "confidence": "high",
                                           "summary": "Ramp.", "evidence": ["e1"], "field_checks": ["c1"]}, "y")])])
    b = agents.inspection_brief("DT2-M03")
    assert b["mode"] == "agent" and b["likely_cause"] == "gradual_tampering" and b["cause_name"].startswith("Gradual")
    fake([reply(calls=[tc("submit_brief", {"likely_cause": "aliens", "confidence": "high", "summary": "",
                                           "evidence": [], "field_checks": []})])])
    b = agents.inspection_brief("DT2-M03")
    assert b["mode"] == "rules" and b["fallback_reason"] == "agent_failed", "invalid cause falls back"
    assert agents.inspection_brief("NOPE") is None


def test_brief_rules(data, no_key):
    assert agents.inspection_brief("DT1-M02")["likely_cause"] == "hook_bypass"
    assert agents.inspection_brief("DT2-M03")["likely_cause"] == "gradual_tampering"
    assert agents.inspection_brief("DT3-M05")["likely_cause"] == "genuine_drop"


def test_alerts_and_digest(data, no_key):
    items = alerts.alerts(days=21)   # window starts before the thefts begin
    flagged = {a["meter_id"] for a in items if a["type"] == "new_flag"}
    assert {"DT1-M02"} <= flagged
    assert len({(a["meter_id"], a["type"]) for a in items if a["type"] == "new_flag"}) == \
        sum(1 for a in items if a["type"] == "new_flag"), "no duplicate new_flag alerts"
    d = alerts.digest(days=14)
    assert d["mode"] == "rules" and "alerts in the last 14 days" in d["digest"]


def test_digest_with_llm(data, fake):
    fake([reply(content="Two meters need inspection today.")])
    d = alerts.digest(days=14)
    assert d["mode"] == "agent" and d["digest"] == "Two meters need inspection today."


@pytest_asyncio.fixture
async def client(data):
    from app.main import app
    import app.api.ai as ai_api
    ai_api._hits.clear()
    ai_api._brief_cache.clear()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest.mark.asyncio
async def test_ai_api(client, no_key):
    s = (await client.get("/api/v1/ai/status")).json()
    assert s["agent_enabled"] is False and s["data_ready"]
    r = await client.post("/api/v1/ai/copilot", json={"question": "how many meters are flagged?"})
    assert r.status_code == 200 and r.json()["steps"]
    assert (await client.post("/api/v1/ai/copilot", json={"question": "hi"})).status_code == 422
    b1 = (await client.post("/api/v1/ai/brief/DT1-M02")).json()
    b2 = (await client.post("/api/v1/ai/brief/dt1-m02")).json()
    assert b1["cached"] is False and b2["cached"] is True
    assert (await client.post("/api/v1/ai/brief/NOPE")).status_code == 404
    assert (await client.get("/api/v1/ai/alerts")).json()["alerts"] is not None
    assert (await client.get("/api/v1/ai/alerts/digest?days=7")).json()["digest"]
    assert (await client.get("/api/v1/ai/ops/summary")).json()["triage"]["runs"] >= 3
    assert "calls" in (await client.get("/api/v1/ai/ops/calls")).json()


@pytest.mark.asyncio
async def test_rate_limit(client, fake):
    import app.api.ai as ai_api
    fake([reply(calls=[tc("final_answer", {"answer": "x"})])] * 30)
    for _ in range(ai_api.RATE_LIMIT):
        assert (await client.post("/api/v1/ai/copilot", json={"question": "anything"})).status_code == 200
    assert (await client.post("/api/v1/ai/copilot", json={"question": "anything"})).status_code == 429
