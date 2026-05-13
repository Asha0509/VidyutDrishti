from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from app.detection import scoring as sc


def by_id(scores):
    return {s.meter_id: s for s in scores}


def test_theft_with_transformer_gap_is_flagged_high(network):
    daily, dt, topo = network(thefts={"DT1-M02": (25, 0.9, "step")})
    s = by_id(sc.score_meters(daily, topo, None, dt))["DT1-M02"]
    assert s.flagged and s.tier == "HIGH" and s.pattern == "sudden_drop"
    l0 = s.layers[0]
    assert l0.name == "dt_balance" and l0.fired and "still being drawn" in l0.detail


def test_vacancy_without_gap_is_not_flagged(network):
    daily, dt, topo = network(vacancies={"DT1-M02": (25, 0.9)})
    s = by_id(sc.score_meters(daily, topo, None, dt))["DT1-M02"]
    assert s.drop_pct > 80, "the drop is real"
    assert not s.flagged, "but the transformer isn't losing energy, so it's genuine"
    assert "looks genuine" in s.layers[0].detail


def test_theft_and_vacancy_on_same_transformer_are_told_apart(network):
    daily, dt, topo = network(thefts={"DT1-M02": (25, 0.9, "step")}, vacancies={"DT1-M05": (25, 0.5)})
    s = by_id(sc.score_meters(daily, topo, None, dt))
    assert s["DT1-M02"].flagged and not s["DT1-M05"].flagged


def test_small_theft_on_big_transformer_is_inconclusive_not_cleared(network):
    daily, dt, topo = network(thefts={"DT1-M02": (25, 0.9, "step")}, industrial={"DT1-M01": 3000.0}, seed=3)
    s = by_id(sc.score_meters(daily, topo, None, dt))["DT1-M02"]
    assert "inconclusive" in s.layers[0].detail
    assert s.flagged, "self-history and peers still carry it"


def test_without_dt_data_layer_is_skipped(network):
    daily, _, topo = network(thefts={"DT1-M02": (25, 0.9, "step")})
    s = by_id(sc.score_meters(daily, topo, None, None))["DT1-M02"]
    assert "skipped" in s.layers[0].detail and s.flagged


def test_flatline_and_ramp_patterns(network):
    daily, dt, topo = network(thefts={"DT1-M02": (25, 1.0, "step"), "DT2-M03": (20, 0.9, "ramp")})
    s = by_id(sc.score_meters(daily, topo, None, dt))
    assert s["DT1-M02"].pattern == "flatline"
    assert s["DT2-M03"].pattern == "gradual_decline" and s["DT2-M03"].flagged


def test_normal_meters_stay_quiet(network):
    daily, dt, topo = network()
    scores = sc.score_meters(daily, topo, None, dt)
    assert not any(s.flagged for s in scores)


def test_queue_ranks_by_expected_rupees(network):
    daily, dt, topo = network(thefts={"DT1-M02": (25, 0.9, "step"), "DT2-M01": (25, 0.9, "step")},
                              industrial={"DT2-M01": 150.0})
    q = sc.rank_queue(sc.score_meters(daily, topo, None, dt))
    assert [s.meter_id for s in q][:2] == ["DT2-M01", "DT1-M02"]
    assert q[0].category == "industrial" and q[0].est_monthly_loss_inr > q[1].est_monthly_loss_inr


def test_too_little_history_returns_nothing(network):
    daily, dt, topo = network(days=15)
    assert sc.score_meters(daily, topo, None, dt) == []


def test_target_date_scores_the_past(network):
    daily, dt, topo = network(thefts={"DT1-M02": (40, 0.9, "step")})
    before = sorted(daily["date"].unique())[35]
    assert not by_id(sc.score_meters(daily, topo, before, dt))["DT1-M02"].flagged
    assert by_id(sc.score_meters(daily, topo, None, dt))["DT1-M02"].flagged


def test_attribute_gap_picks_the_matching_subset():
    out = sc.attribute_gap(10.0, {"a": 10.0, "b": 4.0, "c": 0.0})
    assert out["a"] > 0.9 and out["b"] < 0.2 and out["c"] == 0
    tie = sc.attribute_gap(10.0, {"a": 10.0, "b": 10.0})
    assert 0.4 < tie["a"] < 0.6 and tie["a"] == tie["b"], "ambiguous cases get partial credit"
    assert sc.attribute_gap(0.0, {"a": 5.0}) == {"a": 0.0}


def test_classify_shape():
    step = np.r_[np.ones(15), np.full(20, 0.1)]
    ramp = np.r_[np.ones(10), np.linspace(1, 0.2, 25)]
    assert sc.classify_shape(step, 1.0) == "sudden_drop"
    assert sc.classify_shape(ramp, 1.0) == "gradual_decline"


def test_daily_from_slots_scales_for_missing():
    ts = [datetime(2026, 1, 1) + timedelta(minutes=15 * i) for i in range(96 * 2)]
    kwh = [1.0] * len(ts)
    for i in range(0, 48):           # half of day 1 missing
        kwh[i] = np.nan
    for i in range(96, 96 + 60):     # most of day 2 missing
        kwh[i] = np.nan
    d = sc.daily_from_slots(pd.DataFrame({"meter_id": "m", "ts": ts, "kwh": kwh})).set_index("date")["kwh"]
    assert d.iloc[0] == pytest.approx(96.0), "half a day observed -> scaled to a full day"
    assert np.isnan(d.iloc[1]), "under 50% coverage -> unknown, not zero"


def test_tiers():
    assert sc.tier_for(0.85) == "HIGH" and sc.tier_for(0.7) == "MEDIUM" and sc.tier_for(0.56) == "REVIEW"
    assert sc.tier_for(0.3) == "NORMAL"
