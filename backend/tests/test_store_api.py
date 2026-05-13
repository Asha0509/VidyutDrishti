from datetime import date, datetime, timedelta

import httpx
import pandas as pd
import pytest
import pytest_asyncio

from app.store import Store, infer_topology


def slots_from_daily(daily: pd.DataFrame, value_col: str, id_col: str) -> pd.DataFrame:
    """Expand daily kWh into 96 equal slots using the simulator convention (slot = daily rate)."""
    rows = []
    for r in daily.itertuples(index=False):
        d = getattr(r, "date")
        for i in range(96):
            rows.append({id_col: getattr(r, id_col), "ts": datetime.combine(d, datetime.min.time()) + timedelta(minutes=15 * i),
                         value_col: getattr(r, value_col)})
    return pd.DataFrame(rows)


@pytest.fixture
def seeded(network, monkeypatch):
    daily, dt, topo = network(thefts={"DT1-M02": (25, 0.9, "step")}, vacancies={"DT2-M04": (25, 0.9)}, days=40)
    s = Store()
    s.add_meter_frame(slots_from_daily(daily, "kwh", "meter_id"))
    s.add_dt_frame(slots_from_daily(dt, "kwh_in", "dt_id"))
    s.set_truth([{"meter_id": "DT1-M02", "kind": "hook_bypass", "start_day": 25}],
                [{"meter_id": "DT2-M04", "kind": "vacancy"}], date(2026, 1, 1))
    s.ready = True
    import app.store as store_mod
    import app.api.routes as routes
    monkeypatch.setattr(store_mod, "store", s)
    monkeypatch.setattr(routes, "store", s)
    return s


def test_infer_topology():
    assert infer_topology("DT3-M01") == {"dt_id": "DT3", "feeder_id": "F3", "zone": "ZoneC"}
    assert infer_topology("weird")["zone"] == "Unassigned"


def test_store_views(seeded):
    q = seeded.queue()
    assert [i["meter_id"] for i in q] == ["DT1-M02"]
    assert q[0]["status"] == "pending" and q[0]["tier"] in ("HIGH", "MEDIUM")
    ev = seeded.evaluation()
    assert ev["recall"] == 1.0 and ev["precision"] == 1.0 and ev["decoys_flagged"] == []
    lag = seeded.compute_detection_lag(step_days=1)
    assert lag["per_meter"]["DT1-M02"] is not None and lag["per_meter"]["DT1-M02"] <= 7
    m = seeded.meter("DT1-M02")
    assert m["series"][-1]["kwh"] < m["series"][0]["kwh"] and m["peers"] and m["place"]
    zones = {z["id"]: z for z in seeded.zones()}
    assert zones["ZoneA"]["flagged"] == 1 and zones["ZoneB"]["flagged"] == 0
    ov = seeded.overview()
    assert ov["flagged"] == 1 and ov["meters"] == 12
    bal = seeded.dt_balance()
    assert bal and bal[-1]["unmetered_pct"] > bal[0]["unmetered_pct"] - 100


def test_feedback_changes_status(seeded):
    seeded.record_feedback({"meter_id": "DT1-M02", "inspection_date": "2026-02-09", "was_anomaly": True})
    assert seeded.queue()[0]["status"] == "confirmed"
    assert seeded.evaluation()["field_feedback"] == {"confirmed": 1, "dismissed": 0}


def test_ingest_api_path_rejects_negative(network):
    s = Store()
    rec, valid, written = s.add_readings([
        {"meter_id": "DT1-M01", "timestamp": "2026-01-01T00:00:00", "kwh": 1.0},
        {"meter_id": "DT1-M01", "timestamp": "2026-01-01T00:15:00", "kwh": -3.0},
    ])
    assert (rec, valid, written) == (2, 1, 1)


@pytest_asyncio.fixture
async def client(seeded):
    from app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest.mark.asyncio
async def test_api_endpoints(client):
    assert (await client.get("/health")).status_code == 200
    ov = (await client.get("/api/v1/overview")).json()
    assert ov["flagged"] == 1
    q = (await client.get("/api/v1/queue/daily")).json()
    assert q["items"][0]["meter_id"] == "DT1-M02" and q["pending_items"] == 1
    m = (await client.get("/api/v1/meters/dt1-m02/status")).json()
    assert m["meter_id"] == "DT1-M02" and len(m["layers"]) == 4
    assert (await client.get("/api/v1/meters/NOPE/status")).status_code == 404
    assert len((await client.get("/api/v1/meters")).json()["meters"]) == 12
    assert (await client.get("/api/v1/zones/summary")).json()["zones"]
    assert (await client.get("/api/v1/dt/balance")).json()["rows"]
    ev = (await client.get("/api/v1/metrics/evaluation")).json()
    assert ev["demo"]["recall"] == 1.0
    roi = (await client.get("/api/v1/metrics/roi")).json()
    assert roi["assumptions"]
    fb = await client.post("/api/v1/feedback", json={"meter_id": "DT1-M02", "inspection_date": "2026-02-09",
                                                     "was_anomaly": False})
    assert fb.status_code == 200 and "no theft found" in fb.json()["message"]
    assert (await client.post("/api/v1/feedback", json={"meter_id": "ZZ", "inspection_date": "2026-02-09",
                                                        "was_anomaly": True})).status_code == 404
    f = await client.get("/api/v1/forecast/F1")
    assert f.status_code == 200 and len(f.json()["points"]) == 96 and f.json()["peak_forecast_kw"] < 50


@pytest.mark.asyncio
async def test_empty_store_says_loading(monkeypatch):
    import app.api.routes as routes
    s = Store()
    monkeypatch.setattr(routes, "store", s)
    from app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/overview")
        assert r.status_code == 503 and "loading" in r.json()["detail"]
