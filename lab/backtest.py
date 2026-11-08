"""Rolling-origin backtest (滾動起點回測) for lab research."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd
from pydantic import BaseModel
from shiro_mlops.core.constants import DATETIME_COL, LOAD_MW_COL, SUBJECT_COL
from shiro_mlops.core.datetime_utils import TAIWAN_TZ, standardize_taiwan_datetime
from shiro_mlops.features.transformers import merge_weather_features
from shiro_mlops.models.evaluator import evaluate_forecast
from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.runner import fit_task
from shiro_mlops.tasks.types import get_task_type
from shiro_mlops.tasks.types.base import PredictionData, TrainingData

PREDICTION_COL = f"predicted_{LOAD_MW_COL}"


@dataclass(frozen=True)
class BacktestReport:
    """Summary of a rolling-origin backtest across a fixed origin set and horizon."""

    overall_mape: float
    mape_by_horizon: dict[int, float]
    origins: tuple[pd.Timestamp, ...]
    horizon_hours: int
    min_history_hours: int
    min_history_overridden: bool
    params: BaseModel

    @property
    def mape(self) -> float:
        """Alias for ``overall_mape``."""
        return self.overall_mape

    def _require_comparable(self, other: BacktestReport) -> None:
        if self.origins != other.origins:
            raise ValueError(
                "Cannot compare BacktestReport instances with different origins: "
                f"{self.origins} != {other.origins}."
            )
        if self.horizon_hours != other.horizon_hours:
            raise ValueError(
                "Cannot compare BacktestReport instances with different horizon_hours: "
                f"{self.horizon_hours} != {other.horizon_hours}."
            )

    def beats(self, baseline: BacktestReport) -> bool:
        """Return True when this report achieves strictly lower overall MAPE on the same origins and horizon."""
        self._require_comparable(baseline)
        return self.overall_mape < baseline.overall_mape

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, BacktestReport):
            return NotImplemented
        self._require_comparable(other)
        return self.overall_mape < other.overall_mape

    def __le__(self, other: object) -> bool:
        if not isinstance(other, BacktestReport):
            return NotImplemented
        self._require_comparable(other)
        return self.overall_mape <= other.overall_mape

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, BacktestReport):
            return NotImplemented
        self._require_comparable(other)
        return self.overall_mape > other.overall_mape

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, BacktestReport):
            return NotImplemented
        self._require_comparable(other)
        return self.overall_mape >= other.overall_mape


def _normalize_origin(origin: datetime | pd.Timestamp | str) -> pd.Timestamp:
    ts = pd.Timestamp(origin)
    if ts.tzinfo is not None:
        ts = ts.tz_convert(TAIWAN_TZ).tz_localize(None)
    return ts


def rolling_origin_backtest(
    task: TaskDefinition,
    data: TrainingData,
    origins: Sequence[datetime | pd.Timestamp | str],
    horizon_hours: int,
    *,
    min_history_hours: int | None = None,
) -> BacktestReport:
    """Evaluate ``task`` with rolling-origin backtesting over ``origins`` and ``horizon_hours``."""
    if not origins:
        raise ValueError("origins must not be empty.")
    if horizon_hours < 1:
        raise ValueError("horizon_hours must be >= 1.")

    normalized_origins = tuple(_normalize_origin(origin) for origin in origins)
    effective_min_history = (
        task.policies.min_training_hours if min_history_hours is None else min_history_hours
    )
    min_history_overridden = min_history_hours is not None

    load = data.load[[DATETIME_COL, SUBJECT_COL, LOAD_MW_COL]].copy()
    load[DATETIME_COL] = standardize_taiwan_datetime(load[DATETIME_COL])
    load = (
        load.dropna(subset=[LOAD_MW_COL])
        .drop_duplicates(subset=[DATETIME_COL], keep="last")
        .sort_values(DATETIME_COL, ignore_index=True)
    )

    weather_fields = list(task.weather.fields)
    weather = data.weather[[DATETIME_COL, *weather_fields]].copy()
    weather[DATETIME_COL] = standardize_taiwan_datetime(weather[DATETIME_COL])
    weather = weather.sort_values(DATETIME_COL, ignore_index=True)

    lookback_hours = get_task_type(task.task_type).requirements(task.params).lookback_hours

    y_true_by_step: dict[int, list[float]] = {step: [] for step in range(1, horizon_hours + 1)}
    y_pred_by_step: dict[int, list[float]] = {step: [] for step in range(1, horizon_hours + 1)}

    for origin in normalized_origins:
        train_load = load[load[DATETIME_COL] <= origin].reset_index(drop=True)
        accumulated_hours = int(train_load[DATETIME_COL].nunique())
        if accumulated_hours < effective_min_history:
            raise ValueError(
                f"Origin {origin.isoformat()} failed minimum history check: "
                f"{accumulated_hours} valid load hours <= origin, "
                f"requires min_history_hours={effective_min_history}."
            )

        expected_lookback = pd.date_range(end=origin, periods=lookback_hours, freq="h")
        missing_lookback = expected_lookback.difference(pd.DatetimeIndex(train_load[DATETIME_COL]))
        if len(missing_lookback) > 0:
            raise ValueError(
                f"Origin {origin.isoformat()} failed lookback load completeness check: "
                f"missing {len(missing_lookback)} hour(s) in {lookback_hours}h lookback window "
                f"(first missing: {missing_lookback[0].isoformat()})."
            )

        horizon_times = pd.date_range(
            start=origin + pd.Timedelta(hours=1), periods=horizon_hours, freq="h"
        )
        horizon_load = load[load[DATETIME_COL].isin(horizon_times)].sort_values(
            DATETIME_COL, ignore_index=True
        )
        missing_horizon_load = horizon_times.difference(
            pd.DatetimeIndex(horizon_load[DATETIME_COL])
        )
        if len(missing_horizon_load) > 0:
            raise ValueError(
                f"Origin {origin.isoformat()} failed horizon load completeness check: "
                f"missing {len(missing_horizon_load)} hour(s) in target horizon "
                f"(first missing: {missing_horizon_load[0].isoformat()})."
            )

        horizon_grid = pd.DataFrame({DATETIME_COL: horizon_times})
        weather_for_horizon = weather[weather[DATETIME_COL] <= horizon_times[-1]]
        aligned_weather = merge_weather_features(horizon_grid, weather_for_horizon)
        aligned_weather = aligned_weather[[DATETIME_COL, *weather_fields]].sort_values(
            DATETIME_COL, ignore_index=True
        )
        missing_weather_mask = aligned_weather[weather_fields].isna().any(axis=1)
        if missing_weather_mask.any():
            first_missing_wx = pd.Timestamp(
                aligned_weather.loc[missing_weather_mask, DATETIME_COL].iloc[0]
            )
            raise ValueError(
                f"Origin {origin.isoformat()} failed horizon weather completeness check: "
                f"missing aligned weather in target horizon "
                f"(first missing: {first_missing_wx.isoformat()})."
            )

        train_weather = weather[weather[DATETIME_COL] <= origin].reset_index(drop=True)
        truncated_data = TrainingData(
            load=train_load,
            weather=train_weather,
            validation_start=origin + pd.Timedelta(hours=1),
        )
        trained = fit_task(task, truncated_data)

        prediction_data = PredictionData(
            anchor=origin,
            load_history=train_load,
            weather=aligned_weather,
            horizon_hours=horizon_hours,
        )
        predictions = trained.model.predict(prediction_data).sort_values(
            DATETIME_COL, ignore_index=True
        )

        for step_idx in range(horizon_hours):
            step = step_idx + 1
            y_true_by_step[step].append(float(horizon_load[LOAD_MW_COL].iloc[step_idx]))
            y_pred_by_step[step].append(float(predictions[PREDICTION_COL].iloc[step_idx]))

    all_y_true = np.array(
        [val for step in range(1, horizon_hours + 1) for val in y_true_by_step[step]],
        dtype=float,
    )
    all_y_pred = np.array(
        [val for step in range(1, horizon_hours + 1) for val in y_pred_by_step[step]],
        dtype=float,
    )
    overall_mape = float(evaluate_forecast(all_y_true, all_y_pred)["mape"])
    mape_by_horizon = {
        step: float(
            evaluate_forecast(
                np.array(y_true_by_step[step], dtype=float),
                np.array(y_pred_by_step[step], dtype=float),
            )["mape"]
        )
        for step in range(1, horizon_hours + 1)
    }

    return BacktestReport(
        overall_mape=overall_mape,
        mape_by_horizon=mape_by_horizon,
        origins=normalized_origins,
        horizon_hours=horizon_hours,
        min_history_hours=effective_min_history,
        min_history_overridden=min_history_overridden,
        params=task.params,
    )
