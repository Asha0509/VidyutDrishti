import numpy as np
import pandas as pd
from app.forecast.engine import FeederForecaster, seasonal_mean


def _weekly(days: int, per_day: int = 96) -> np.ndarray:
    day = 10 + 5 * np.sin(np.linspace(0, 2 * np.pi, per_day, endpoint=False))
    return np.tile(np.concatenate([day * (1.0 if d % 7 < 5 else 0.6) for d in range(7)]), days // 7 + 1)[: days * per_day]


def test_seasonal_mean_recovers_a_pure_weekly_pattern():
    v = _weekly(35)
    assert np.allclose(seasonal_mean(v, 96, 96), _weekly(36)[35 * 96 :])


def test_forecaster_returns_a_full_day_with_ordered_nonnegative_band():
    v = _weekly(28)
    idx = pd.date_range("2026-01-05", periods=len(v), freq="15min")
    df = pd.DataFrame({"timestamp": idx, "feeder_id": "F1", "kw": v})
    out = FeederForecaster().fit(df).predict("F1").to_dict()
    assert len(out["points"]) == 96 and out["model"].startswith("seasonal")
    assert all(0 <= p["lower_kw"] <= p["forecast_kw"] <= p["upper_kw"] for p in out["points"])


def test_forecaster_refuses_under_a_week_of_history():
    idx = pd.date_range("2026-01-05", periods=96 * 3, freq="15min")
    df = pd.DataFrame({"timestamp": idx, "feeder_id": "F1", "kw": 1.0})
    try:
        FeederForecaster().fit(df).predict("F1")
    except ValueError as exc:
        assert "7 days" in str(exc)
    else:
        raise AssertionError("expected ValueError")
