import os
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, ROOT)


def make_network(thefts=None, vacancies=None, days=50, meters_per_dt=6, dts=2, seed=0, base=12.0,
                 industrial=None, tech_loss=0.04, loss_jitter=0.005):
    """Tiny synthetic network: daily kWh per meter and per-DT input.

    thefts:    {meter_id: (start_day, fraction_hidden, 'step'|'ramp')}
    vacancies: {meter_id: (start_day, fraction_reduced)}
    industrial: {meter_id: base_kwh}
    """
    rng = np.random.default_rng(seed)
    thefts, vacancies, industrial = thefts or {}, vacancies or {}, industrial or {}
    start = date(2026, 1, 1)
    rows, dt_rows, topo = [], [], []
    for d in range(1, dts + 1):
        dt_true = np.zeros(days)
        for m in range(1, meters_per_dt + 1):
            mid = f"DT{d}-M{m:02d}"
            topo.append({"meter_id": mid, "dt_id": f"DT{d}", "feeder_id": f"F{d}", "zone": f"Zone{chr(64 + d)}"})
            b = industrial.get(mid, base)
            true = b * (1 + 0.08 * rng.standard_normal(days))
            if mid in vacancies:
                s, frac = vacancies[mid]
                true[s:] *= (1 - frac)
            metered = true.copy()
            if mid in thefts:
                s, frac, shape = thefts[mid]
                if shape == "ramp":
                    metered[s:] *= 1 - np.linspace(0, frac, days - s)
                else:
                    metered[s:] *= (1 - frac)
            dt_true += true
            rows += [{"meter_id": mid, "date": start + timedelta(days=i), "kwh": float(metered[i])} for i in range(days)]
        loss = tech_loss + loss_jitter * rng.standard_normal(days)  # technical losses wobble day to day
        dt_rows += [{"dt_id": f"DT{d}", "date": start + timedelta(days=i), "kwh_in": float(dt_true[i] * (1 + loss[i]))}
                    for i in range(days)]
    return pd.DataFrame(rows), pd.DataFrame(dt_rows), pd.DataFrame(topo)


@pytest.fixture
def network():
    return make_network
