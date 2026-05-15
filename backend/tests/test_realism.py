import json
from pathlib import Path

CAL = Path(__file__).resolve().parents[2] / "simulator" / "calibrated_realism.json"


def test_calibrated_knobs_load_and_are_numeric():
    raw = json.loads(CAL.read_text())
    knobs = raw.get("knobs", raw)
    assert knobs and all(isinstance(v, (int, float)) for v in knobs.values())
