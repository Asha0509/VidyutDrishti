"""Rolling-origin backtesting for time series forecasts.

Evaluates day-7 match accuracy (eval target: 85% within ±10%).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .baselines import baseline_comparison
from .metrics import mape


@dataclass
class Day7MatchResult:
    """Result of day-7 horizon accuracy check."""

    total_forecasts: int
    within_tolerance: int  # Within ±10%
    match_percent: float   # (within / total) * 100
    meets_target: bool     # >= 85%


@dataclass
class BacktestReport:
    """Comprehensive backtest results."""

    feeder_id: str
    model_version: str
    total_rows: int
    overall_mape: float
    baseline_result: BaselineResult  # Forward reference resolved at runtime
    day7_match: Day7MatchResult
    horizon_mapes: dict[int, float]  # MAPE by horizon day (1-7)


def _match_within_tolerance(actual: float, predicted: float, tolerance: float = 0.10) -> bool:
    """Check if prediction is within ±tolerance of actual."""
    if actual == 0:
        return False
    return abs((predicted - actual) / actual) <= tolerance


def day7_match_accuracy(
    df: pd.DataFrame,
    actual_col: str = "y",
    pred_col: str = "yhat",
    horizon_col: str = "horizon_days",
    tolerance: float = 0.10,
    target_percent: float = 85.0,
) -> Day7MatchResult:
    """Calculate day-7 match accuracy (forecasts within ±10% of actual).

    Args:
        df: DataFrame with actuals, predictions, and horizon info
        actual_col: Column name for actual values
        pred_col: Column name for predicted values
        horizon_col: Column name for horizon day (1-7)
        tolerance: Acceptable error margin (default 10%)
        target_percent: Target percentage to meet (default 85%)

    Returns:
        Day7MatchResult with match statistics
    """
    # Filter to day-7 forecasts if horizon column exists
    if horizon_col in df.columns:
        day7_df = df[df[horizon_col] == 7]
    else:
        # Assume all rows are day-7 if no horizon column
        day7_df = df

    if day7_df.empty:
        return Day7MatchResult(
            total_forecasts=0,
            within_tolerance=0,
            match_percent=0.0,
            meets_target=False,
        )

    within = day7_df.apply(
        lambda row: _match_within_tolerance(
            float(row[actual_col]), float(row[pred_col]), tolerance
        ),
        axis=1,
    )

    total = len(day7_df)
    within_count = int(within.sum())
    percent = (within_count / total) * 100.0 if total > 0 else 0.0

    return Day7MatchResult(
        total_forecasts=total,
        within_tolerance=within_count,
        match_percent=percent,
        meets_target=percent >= target_percent,
    )


def horizon_mapes(
    df: pd.DataFrame,
    actual_col: str = "y",
    pred_col: str = "yhat",
    horizon_col: str = "horizon_days",
) -> dict[int, float]:
    """Calculate MAPE for each horizon day (1-7)."""
    result: dict[int, float] = {}
    if horizon_col not in df.columns:
        # Single horizon case
        result[7] = mape(df[actual_col], df[pred_col])
        return result

    for h in range(1, 8):
        sub = df[df[horizon_col] == h]
        if len(sub) > 0:
            result[h] = mape(sub[actual_col], sub[pred_col])
        else:
            result[h] = float("nan")
    return result


class Backtester:
    """Rolling-origin backtest for feeder-level forecasts."""

    def __init__(
        self,
        df: pd.DataFrame,
        feeder_id: str,
        model_version: str,
        day7_target: float = 85.0,
        day7_tolerance: float = 0.10,
    ) -> None:
        self.df = df.copy()
        self.feeder_id = feeder_id
        self.model_version = model_version
        self.day7_target = day7_target
        self.day7_tolerance = day7_tolerance

    def run(self) -> BacktestReport:
        """Execute full backtest and produce report."""
        # Ensure required columns exist
        required = ["ds", "y", "yhat"]
        for col in required:
            if col not in self.df.columns:
                raise ValueError(f"Missing required column: {col}")

        # Overall MAPE
        overall_mape = mape(self.df["y"], self.df["yhat"])

        # Baseline comparison
        baseline = baseline_comparison(self.df, model_yhat_col="yhat", actual_col="y")

        # Day-7 match accuracy
        day7 = day7_match_accuracy(
            self.df,
            actual_col="y",
            pred_col="yhat",
            horizon_col="horizon_days" if "horizon_days" in self.df.columns else "",
            tolerance=self.day7_tolerance,
            target_percent=self.day7_target,
        )

        # MAPE by horizon
        h_mapes = horizon_mapes(
            self.df,
            actual_col="y",
            pred_col="yhat",
            horizon_col="horizon_days" if "horizon_days" in self.df.columns else "",
        )

        return BacktestReport(
            feeder_id=self.feeder_id,
            model_version=self.model_version,
            total_rows=len(self.df),
            overall_mape=overall_mape,
            baseline_result=baseline,
            day7_match=day7,
            horizon_mapes=h_mapes,
        )
