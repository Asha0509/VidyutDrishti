"""Typed configuration objects for the simulator.

Keeping these as plain dataclasses (rather than Pydantic models) so the
simulator has zero runtime dependency on pydantic. Validation is kept
light and focused on the handful of invariants the generator truly
relies on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class TheftScenario:
    meter_id: str
    kind: str          # hook_bypass | gradual_tampering | meter_stop
    start_day: int
    end_day: int
    severity: float


@dataclass
class Decoy:
    meter_id: str
    kind: str          # vacancy | equipment_fault
    start_day: int
    end_day: int
    severity: float


@dataclass
class SimConfig:
    seed: int
    dt_count: int
    meters_per_dt: int
    category_mix: dict[str, float]

    start_date: date
    days: int
    slot_minutes: int

    daily_kwh_mean: dict[str, float]
    daily_kwh_std: dict[str, float]
    diurnal_weights: dict[str, list[float]]

    summer_months: list[int]
    summer_multiplier: float
    monsoon_months: list[int]
    monsoon_multiplier: float
    weekend_multiplier: dict[str, float]
    holiday_multiplier: float
    holiday_dates: list[str] | None

    voltage_mean: float
    voltage_std: float
    voltage_min: float
    voltage_max: float
    pf_range: dict[str, list[float]]

    dt_technical_loss_min: float
    dt_technical_loss_max: float

    noise_std_fraction: float

    missing_short_prob: float
    missing_medium_prob: float
    missing_long_prob: float

    theft_scenarios: list[TheftScenario] = field(default_factory=list)
    decoys: list[Decoy] = field(default_factory=list)
    # Optional realism knobs (see simulator/dataset.py). Empty means the original independent-day behaviour.
    realism: dict[str, float] = field(default_factory=dict)

    # -------------- Convenience --------------

    @property
    def slots_per_day(self) -> int:
        return (24 * 60) // self.slot_minutes

    def categories(self) -> list[str]:
        return list(self.category_mix.keys())

    # -------------- Factories --------------

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SimConfig:
        from datetime import datetime

        def _theft(d: dict[str, Any]) -> TheftScenario:
            return TheftScenario(**d)

        def _decoy(d: dict[str, Any]) -> Decoy:
            return Decoy(**d)

        start = raw["start_date"]
        if isinstance(start, str):
            start = datetime.strptime(start, "%Y-%m-%d").date()

        cfg = cls(
            seed=int(raw["seed"]),
            dt_count=int(raw["dt_count"]),
            meters_per_dt=int(raw["meters_per_dt"]),
            category_mix={k: float(v) for k, v in raw["category_mix"].items()},
            start_date=start,
            days=int(raw["days"]),
            slot_minutes=int(raw["slot_minutes"]),
            daily_kwh_mean={k: float(v) for k, v in raw["daily_kwh_mean"].items()},
            daily_kwh_std={k: float(v) for k, v in raw["daily_kwh_std"].items()},
            diurnal_weights={k: list(map(float, v)) for k, v in raw["diurnal_weights"].items()},
            summer_months=list(map(int, raw["summer_months"])),
            summer_multiplier=float(raw["summer_multiplier"]),
            monsoon_months=list(map(int, raw["monsoon_months"])),
            monsoon_multiplier=float(raw["monsoon_multiplier"]),
            weekend_multiplier={k: float(v) for k, v in raw["weekend_multiplier"].items()},
            holiday_multiplier=float(raw["holiday_multiplier"]),
            holiday_dates=raw.get("holiday_dates"),
            voltage_mean=float(raw["voltage_mean"]),
            voltage_std=float(raw["voltage_std"]),
            voltage_min=float(raw["voltage_min"]),
            voltage_max=float(raw["voltage_max"]),
            pf_range={k: list(map(float, v)) for k, v in raw["pf_range"].items()},
            dt_technical_loss_min=float(raw["dt_technical_loss_min"]),
            dt_technical_loss_max=float(raw["dt_technical_loss_max"]),
            noise_std_fraction=float(raw["noise_std_fraction"]),
            missing_short_prob=float(raw["missing_short_prob"]),
            missing_medium_prob=float(raw["missing_medium_prob"]),
            missing_long_prob=float(raw["missing_long_prob"]),
            theft_scenarios=[_theft(x) for x in raw.get("theft_scenarios", [])],
            decoys=[_decoy(x) for x in raw.get("decoys", [])],
            realism={k: float(v) for k, v in (raw.get("realism") or {}).items()},
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if abs(sum(self.category_mix.values()) - 1.0) > 1e-6:
            raise ValueError(f"category_mix must sum to 1.0, got {sum(self.category_mix.values())}")
        for cat, weights in self.diurnal_weights.items():
            if len(weights) != 24:
                raise ValueError(f"diurnal_weights[{cat}] must have 24 entries, got {len(weights)}")
        if self.slot_minutes <= 0 or (60 % self.slot_minutes) != 0:
            raise ValueError("slot_minutes must be a positive divisor of 60")
        if self.days <= 0 or self.dt_count <= 0 or self.meters_per_dt <= 0:
            raise ValueError("days / dt_count / meters_per_dt must be positive")
