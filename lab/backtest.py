"""Rolling-origin backtest (滾動起點回測) for lab research."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd
from pydantic import BaseModel
from shiro_mlops.core.constants import DATETIME_COL, LOAD_MW_COL, SUBJECT_COL
from shiro_mlops.core.datetime_utils import standardize_taiwan_datetime
from shiro_mlops.features.transformers import merge_weather_features
from shiro_mlops.models.evaluator import evaluate_forecast
from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.runner import fit_task
from shiro_mlops.tasks.types import get_task_type
from shiro_mlops.tasks.types.base import PredictionData, TrainingData
from shiro_mlops.tasks.types.recursive_regression import TASK_TYPE_NAME as RECURSIVE_REGRESSION
from shiro_mlops.tasks.types.recursive_regression import training_features

from lab.timestamps import normalize_taiwan_timestamp

PREDICTION_COL = f"predicted_{LOAD_MW_COL}"


@dataclass(frozen=True)
class BacktestReport:
    """Summary of a rolling-origin backtest across a fixed origin set and horizon."""

    overall_mape: float
    mape_by_horizon: dict[int, float]
    predictions: dict[pd.Timestamp, tuple[float, ...]]
    origins: tuple[pd.Timestamp, ...]
    horizon_hours: int
    min_history_hours: int
    min_history_overridden: bool
    params: BaseModel

    def beats(self, baseline: BacktestReport) -> bool:
        """Return True when this report achieves strictly lower overall MAPE on the same origins and horizon."""
        self._require_comparable(baseline)
        return self.overall_mape < baseline.overall_mape

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


def rolling_origin_backtest(
    task: TaskDefinition,
    data: TrainingData,
    origins: Sequence[datetime | pd.Timestamp | str],
    horizon_hours: int,
    *,
    min_history_hours: int | None = None,
) -> BacktestReport:
    """Evaluate ``task`` with rolling-origin backtesting over ``origins`` and ``horizon_hours``."""
    normalized_origins = _validate_backtest_inputs(origins, horizon_hours)
    effective_min_history = (
        task.policies.min_training_hours if min_history_hours is None else min_history_hours
    )
    context = _build_context(task, data, horizon_hours, effective_min_history)
    predictions, y_true_by_step, y_pred_by_step = _collect_origin_forecasts(
        context, normalized_origins
    )
    overall_mape, mape_by_horizon = _compute_horizon_mape(
        y_true_by_step, y_pred_by_step, horizon_hours
    )

    return BacktestReport(
        overall_mape=overall_mape,
        mape_by_horizon=mape_by_horizon,
        predictions=predictions,
        origins=normalized_origins,
        horizon_hours=horizon_hours,
        min_history_hours=effective_min_history,
        min_history_overridden=min_history_hours is not None,
        params=task.params,
    )


@dataclass(frozen=True)
class OriginSplit:
    """Search origins and the later, target-disjoint evaluation origins (docs/reference/lab.md §3)."""

    search_origins: tuple[pd.Timestamp, ...]
    eval_origins: tuple[pd.Timestamp, ...]

    @property
    def eval_calendar_days(self) -> int:
        """Distinct calendar dates covered by the evaluation origins."""
        return len({origin.date() for origin in self.eval_origins})


def eligible_origins(
    task: TaskDefinition,
    data: TrainingData,
    horizon_hours: int,
    *,
    min_history_hours: int | None = None,
) -> tuple[pd.Timestamp, ...]:
    """Every hourly origin that ``rolling_origin_backtest`` would accept for ``data``.

    Runs the same three origin checks as the backtest without fitting a model, so a
    study can see how many origins its snapshot offers before choosing any.
    """
    if horizon_hours < 1:
        raise ValueError("horizon_hours must be >= 1.")
    effective_min_history = (
        task.policies.min_training_hours if min_history_hours is None else min_history_hours
    )
    context = _build_context(task, data, horizon_hours, effective_min_history)
    if context.load.empty:
        return ()
    candidates = pd.date_range(
        context.load[DATETIME_COL].iloc[0],
        context.load[DATETIME_COL].iloc[-1] - pd.Timedelta(hours=horizon_hours),
        freq="h",
    )
    accepted = []
    for origin in candidates:
        try:
            _check_origin(context, origin)
        except ValueError:
            continue
        accepted.append(origin)
    return tuple(accepted)


def origin_runs(
    origins: Sequence[pd.Timestamp],
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Group sorted hourly origins into ``(first, last)`` runs of consecutive hours."""
    runs: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for origin in origins:
        if runs and origin - runs[-1][1] == pd.Timedelta(hours=1):
            runs[-1] = (runs[-1][0], origin)
        else:
            runs.append((origin, origin))
    return runs


def split_search_and_eval_origins(
    eligible: Sequence[pd.Timestamp],
    *,
    horizon_hours: int,
    eval_calendar_days: int,
    hour_step: int,
) -> OriginSplit:
    """Split eligible origins into search origins and evaluation origins on the last calendar days.

    Only origins whose hour is a multiple of ``hour_step`` are used. Evaluation origins
    are those on the last ``eval_calendar_days`` dates; search origins are the earlier
    ones whose target window ends before the first evaluation target hour.
    """
    sampled = [origin for origin in eligible if origin.hour % hour_step == 0]
    dates = sorted({origin.date() for origin in sampled})
    eval_dates = set(dates[-eval_calendar_days:])
    eval_origins = tuple(origin for origin in sampled if origin.date() in eval_dates)
    if not eval_origins:
        raise ValueError(f"no eligible origins on hours that are multiples of {hour_step}")
    latest_search = eval_origins[0] - pd.Timedelta(hours=horizon_hours)
    search_origins = tuple(origin for origin in sampled if origin <= latest_search)
    if not search_origins:
        raise ValueError(
            f"no search origins at or before {latest_search.isoformat()}: the eligible origins "
            f"span {len(dates)} calendar day(s), all taken by {eval_calendar_days} evaluation day(s)"
        )
    split = OriginSplit(search_origins=search_origins, eval_origins=eval_origins)
    verify_non_overlapping_target_windows(split.search_origins, split.eval_origins, horizon_hours)
    return split


def training_row_count(
    task: TaskDefinition, data: TrainingData, origin: datetime | pd.Timestamp | str
) -> int:
    """Rows a recursive-regression backtest trains on at ``origin``.

    Weighted weather has no value in hours where any reference point is missing, and
    those rows are dropped, so this discloses each candidate's training-row loss.
    """
    if task.task_type != RECURSIVE_REGRESSION:
        raise ValueError(
            f"training_row_count supports {RECURSIVE_REGRESSION}, not {task.task_type}"
        )
    normalized = normalize_taiwan_timestamp(origin)
    load, weather = _prepare_backtest_frames(task, data)
    truncated = TrainingData(
        load=load[load[DATETIME_COL] <= normalized].reset_index(drop=True),
        weather=weather[weather[DATETIME_COL] <= normalized].reset_index(drop=True),
        validation_start=normalized + pd.Timedelta(hours=1),
    )
    return len(training_features(task.params, truncated))


def verify_non_overlapping_target_windows(
    search_origins: Sequence[pd.Timestamp],
    eval_origins: Sequence[pd.Timestamp],
    horizon_hours: int,
) -> None:
    """Reject eval origins that are not strictly later than, or share target hours with, search origins."""
    search_targets = {ts for origin in search_origins for ts in target_hours(origin, horizon_hours)}
    eval_targets = {ts for origin in eval_origins for ts in target_hours(origin, horizon_hours)}
    overlap = search_targets & eval_targets
    if overlap:
        raise ValueError(
            "Evaluation target window overlaps with search target window "
            f"(earliest shared hour: {min(overlap).isoformat()})."
        )
    if min(eval_origins) <= max(search_origins):
        raise ValueError("Evaluation origins must be strictly later than all search origins.")


def target_hours(origin: pd.Timestamp, horizon_hours: int) -> pd.DatetimeIndex:
    """Return the forecast target hours ``origin + 1h .. origin + horizon_hours``."""
    return pd.date_range(start=origin + pd.Timedelta(hours=1), periods=horizon_hours, freq="h")


def _validate_backtest_inputs(
    origins: Sequence[datetime | pd.Timestamp | str],
    horizon_hours: int,
) -> tuple[pd.Timestamp, ...]:
    if not origins:
        raise ValueError("origins must not be empty.")
    if horizon_hours < 1:
        raise ValueError("horizon_hours must be >= 1.")
    return tuple(normalize_taiwan_timestamp(origin) for origin in origins)


@dataclass(frozen=True)
class _BacktestContext:
    """Inputs shared by every origin within one backtest run."""

    task: TaskDefinition
    load: pd.DataFrame
    weather: pd.DataFrame
    horizon_hours: int
    min_history_hours: int
    lookback_hours: int

    @property
    def weather_fields(self) -> list[str]:
        return list(self.task.weather.fields)


def _build_context(
    task: TaskDefinition,
    data: TrainingData,
    horizon_hours: int,
    min_history_hours: int,
) -> _BacktestContext:
    load, weather = _prepare_backtest_frames(task, data)
    return _BacktestContext(
        task=task,
        load=load,
        weather=weather,
        horizon_hours=horizon_hours,
        min_history_hours=min_history_hours,
        lookback_hours=get_task_type(task.task_type).requirements(task.params).lookback_hours,
    )


def _prepare_backtest_frames(
    task: TaskDefinition,
    data: TrainingData,
) -> tuple[pd.DataFrame, pd.DataFrame]:
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
    return load, weather


def _collect_origin_forecasts(
    context: _BacktestContext,
    origins: tuple[pd.Timestamp, ...],
) -> tuple[dict[pd.Timestamp, tuple[float, ...]], dict[int, list[float]], dict[int, list[float]]]:
    steps = range(1, context.horizon_hours + 1)
    y_true_by_step: dict[int, list[float]] = {step: [] for step in steps}
    y_pred_by_step: dict[int, list[float]] = {step: [] for step in steps}
    predictions: dict[pd.Timestamp, tuple[float, ...]] = {}

    for origin in origins:
        horizon_load, forecast = _evaluate_single_origin(context, origin)
        predictions[origin] = tuple(float(value) for value in forecast[PREDICTION_COL])
        for step_idx, step in enumerate(steps):
            y_true_by_step[step].append(float(horizon_load[LOAD_MW_COL].iloc[step_idx]))
            y_pred_by_step[step].append(predictions[origin][step_idx])

    return predictions, y_true_by_step, y_pred_by_step


def _evaluate_single_origin(
    context: _BacktestContext,
    origin: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    train_load, horizon_load, aligned_weather = _check_origin(context, origin)
    forecast = _fit_and_predict_origin(context, origin, train_load, aligned_weather)
    return horizon_load, forecast


def _check_origin(
    context: _BacktestContext,
    origin: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Apply the three origin checks (docs/reference/lab.md §2); raise ``ValueError`` naming the first failure."""
    train_load = _slice_and_validate_origin_history(
        load=context.load,
        origin=origin,
        min_history_hours=context.min_history_hours,
        lookback_hours=context.lookback_hours,
    )
    horizon_times = target_hours(origin, context.horizon_hours)
    horizon_load = _slice_and_validate_horizon_load(
        load=context.load,
        origin=origin,
        horizon_times=horizon_times,
    )
    aligned_weather = _align_and_validate_horizon_weather(
        weather=context.weather,
        weather_fields=context.weather_fields,
        origin=origin,
        horizon_times=horizon_times,
    )
    return train_load, horizon_load, aligned_weather


def _slice_and_validate_origin_history(
    *,
    load: pd.DataFrame,
    origin: pd.Timestamp,
    min_history_hours: int,
    lookback_hours: int,
) -> pd.DataFrame:
    train_load = load[load[DATETIME_COL] <= origin].reset_index(drop=True)
    accumulated_hours = int(train_load[DATETIME_COL].nunique())
    if accumulated_hours < min_history_hours:
        raise ValueError(
            f"Origin {origin.isoformat()} failed minimum history check: "
            f"{accumulated_hours} valid load hours <= origin, "
            f"requires min_history_hours={min_history_hours}."
        )

    expected_lookback = pd.date_range(end=origin, periods=lookback_hours, freq="h")
    missing_lookback = expected_lookback.difference(pd.DatetimeIndex(train_load[DATETIME_COL]))
    if len(missing_lookback) > 0:
        raise ValueError(
            f"Origin {origin.isoformat()} failed lookback load completeness check: "
            f"missing {len(missing_lookback)} hour(s) in {lookback_hours}h lookback window "
            f"(first missing: {missing_lookback[0].isoformat()})."
        )
    return train_load


def _slice_and_validate_horizon_load(
    *,
    load: pd.DataFrame,
    origin: pd.Timestamp,
    horizon_times: pd.DatetimeIndex,
) -> pd.DataFrame:
    horizon_load = load[load[DATETIME_COL].isin(horizon_times)].sort_values(
        DATETIME_COL, ignore_index=True
    )
    missing_horizon_load = horizon_times.difference(pd.DatetimeIndex(horizon_load[DATETIME_COL]))
    if len(missing_horizon_load) > 0:
        raise ValueError(
            f"Origin {origin.isoformat()} failed horizon load completeness check: "
            f"missing {len(missing_horizon_load)} hour(s) in target horizon "
            f"(first missing: {missing_horizon_load[0].isoformat()})."
        )
    return horizon_load


def _align_and_validate_horizon_weather(
    *,
    weather: pd.DataFrame,
    weather_fields: list[str],
    origin: pd.Timestamp,
    horizon_times: pd.DatetimeIndex,
) -> pd.DataFrame:
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
    return aligned_weather


def _fit_and_predict_origin(
    context: _BacktestContext,
    origin: pd.Timestamp,
    train_load: pd.DataFrame,
    aligned_weather: pd.DataFrame,
) -> pd.DataFrame:
    train_weather = context.weather[context.weather[DATETIME_COL] <= origin].reset_index(drop=True)
    truncated_data = TrainingData(
        load=train_load,
        weather=train_weather,
        validation_start=origin + pd.Timedelta(hours=1),
    )
    trained = fit_task(context.task, truncated_data)

    prediction_data = PredictionData(
        anchor=origin,
        load_history=train_load,
        weather=aligned_weather,
        horizon_hours=context.horizon_hours,
    )
    return trained.model.predict(prediction_data).sort_values(DATETIME_COL, ignore_index=True)


def _compute_horizon_mape(
    y_true_by_step: dict[int, list[float]],
    y_pred_by_step: dict[int, list[float]],
    horizon_hours: int,
) -> tuple[float, dict[int, float]]:
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
    return overall_mape, mape_by_horizon
