"""Baseline forecast models for comparison.

The naive baseline (yesterday's value) serves as the minimum acceptable
performance bar. Prophet must beat this to justify its complexity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from .metrics import mape


@dataclass
class BaselineResult:
    """Result of baseline vs model comparison."""

    model_mape: float
    baseline_mape: float
    improvement_percent: float  # How much better model is than baseline
    beats_baseline: bool


def _shift_one_day(df: pd.DataFrame, value_col: str = "y") -> pd.DataFrame:
    """Lag the value column by one day (naive baseline)."""
    df = df.sort_values("ds").copy()
    df["yhat_baseline"] = df[value_col].shift(1)
    return df


class NaiveBaseline:
    """Tomorrow = Today (persistence model)."""

    def __init__(self, df: pd.DataFrame) -> None:
        self.df = df.copy()
        self.df = _shift_one_day(self.df)

    def predict(self, target_date: date) -> float | None:
        """Return yesterday's value as today's forecast."""
        prev_date = target_date - timedelta(days=1)
        row = self.df[self.df["ds"] == pd.Timestamp(prev_date)]
        if row.empty:
            return None
        return float(row["y"].iloc[0])

    def forecast_all(self) -> pd.DataFrame:
        """Return DataFrame with yhat_baseline column."""
        return self.df.copy()


def baseline_comparison(
    df: pd.DataFrame,
    model_yhat_col: str = "yhat",
    actual_col: str = "y",
) -> BaselineResult:
    """Compare model forecasts against naive baseline.

    Args:
        df: DataFrame with columns 'ds' (datetime), actual_col, model_yhat_col
        model_yhat_col: Column name for model predictions
        actual_col: Column name for actual values

    Returns:
        BaselineResult with MAPEs and improvement metrics.
    """
    df = df.copy()
    df = _shift_one_day(df, actual_col)

    # Drop rows where either prediction is missing
    valid = df.dropna(subset=[model_yhat_col, "yhat_baseline", actual_col])
    if len(valid) < 2:
        return BaselineResult(
            model_mape=float("inf"),
            baseline_mape=float("inf"),
            improvement_percent=0.0,
            beats_baseline=False,
        )

    model_m = mape(valid[actual_col], valid[model_yhat_col])
    baseline_m = mape(valid[actual_col], valid["yhat_baseline"])

    # Calculate improvement: positive means model is better (lower MAPE)
    if baseline_m == float("inf"):
        improvement = 0.0
    elif baseline_m == 0.0:
        # Baseline is perfect; any model error is worse
        improvement = -100.0 if model_m > 0 else 0.0
    else:
        improvement = (baseline_m - model_m) / baseline_m * 100.0

    return BaselineResult(
        model_mape=model_m,
        baseline_mape=baseline_m,
        improvement_percent=improvement,
        beats_baseline=model_m < baseline_m,
    )
