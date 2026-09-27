"""Task runner: the single entry point Dagster and the API use to train and serve ML tasks.

The runner owns I/O and the shared components (ADR-0009): the minimum
accumulation gate, bounded data retrieval, the stale load anchor rule, and
weather resolution with degradation. Task types only ever receive in-memory
frames. Every time-dependent decision takes an explicit ``as_of`` in
Taiwan-local naive time.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from shiro_mlops.core.constants import (
    DATETIME_COL,
    LOAD_MW_COL,
    MAX_HORIZON_HOURS,
    STORAGE_TIME_COL,
    SUBJECT_COL,
)
from shiro_mlops.data.hourly_actual_load import REGIONAL_SNAPSHOT_SUM_SOURCE, is_stale_load_anchor
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.weather_resolution import (
    WeatherResolution,
    WeatherResolutionMode,
    resolve_weather,
)
from shiro_mlops.tasks.accumulation import TrainingLoadReadiness, check_training_load_readiness
from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.types import get_task_type
from shiro_mlops.tasks.types.base import (
    InputRequirements,
    PredictionData,
    TaskModel,
    Trained,
    TrainingData,
    WeatherInput,
)

MODEL_NOT_LOADED_REASON = "Model is not loaded or trained yet."
TARGET_COLUMNS = [DATETIME_COL, SUBJECT_COL, LOAD_MW_COL]


@dataclass(frozen=True)
class TaskRuntime:
    """Process resources the runner reads task data through."""

    repository: TimeSeriesRepository


class TaskNotReady(RuntimeError):  # noqa: N818 - name fixed by the #66 interface design
    """Persisted target history does not yet allow training (minimum accumulation unmet)."""

    def __init__(self, readiness: TrainingLoadReadiness):
        super().__init__(readiness.reason)
        self.readiness = readiness


class TaskUnavailableError(RuntimeError):
    """Serving inputs cannot support a prediction right now; the caller should answer 503."""


class MissingLoadHistoryError(TaskUnavailableError):
    """No persisted target history exists to anchor a prediction."""


class StaleLoadAnchorError(TaskUnavailableError):
    """The latest actual load is too old to anchor a recursive forecast."""


class WeatherUnavailableError(TaskUnavailableError):
    """Neither forecasts nor degraded fallbacks cover the requested horizon."""


@dataclass(frozen=True)
class Readiness:
    """Whether a task can serve a full-horizon prediction now, and in which weather mode."""

    ready: bool
    mode: WeatherResolutionMode | None = None
    reason: str | None = None


@dataclass(frozen=True)
class PredictionOutcome:
    """A task prediction with the weather it used and that weather's provenance."""

    subject: str
    mode: WeatherResolutionMode
    predictions: pd.DataFrame
    weather: pd.DataFrame
    weather_sources: tuple[Mapping[str, Mapping[str, str]], ...]


# --- Training ------------------------------------------------------------------------------


def check_training_readiness(task: TaskDefinition, runtime: TaskRuntime) -> TrainingLoadReadiness:
    """Summarize persisted target history against the task's minimum accumulation."""
    return check_training_load_readiness(
        runtime.repository, task.policies.min_training_hours, subject=task.subject
    )


def load_training_data(
    task: TaskDefinition, runtime: TaskRuntime, *, as_of: datetime
) -> TrainingData:
    """Gate on accumulation, then read target history and observed weather up to ``as_of``.

    The training window is derived from the accumulated target rows themselves.
    """
    readiness = check_training_readiness(task, runtime)
    if not readiness.ready:
        raise TaskNotReady(readiness)
    load = _fetch_target(task, runtime.repository, start=None, end=as_of)
    if load.empty:
        raise ValueError(f"No {task.subject} target rows at or before {as_of.isoformat()}")
    first, last = load[DATETIME_COL].min(), load[DATETIME_COL].max()
    return TrainingData(
        load=load,
        weather=load_observed_weather(task, runtime, start=first, end=last),
        validation_start=_validation_start(load[DATETIME_COL], task.policies.validation_fraction),
    )


def train_task(task: TaskDefinition, runtime: TaskRuntime, *, as_of: datetime) -> Trained:
    """Train the task's type on data known at ``as_of``; raises ``TaskNotReady`` first."""
    data = load_training_data(task, runtime, as_of=as_of)
    return get_task_type(task.task_type).train(task.params, data)


def load_observed_weather(
    task: TaskDefinition,
    runtime: TaskRuntime,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> pd.DataFrame:
    """Observed weather at the task's weather reference point, limited to its weather fields."""
    observed = runtime.repository.fetch_weather_range(
        start_time=start, end_time=end, reference_point=task.weather.reference_point.alias
    )
    observed = _with_datetime_column(observed)
    return observed[[DATETIME_COL, *task.weather.fields]].reset_index(drop=True)


# --- Serving -------------------------------------------------------------------------------


def check_task_ready(
    task: TaskDefinition, model: TaskModel | None, runtime: TaskRuntime, *, as_of: datetime
) -> Readiness:
    """Whether a loaded model, a fresh load anchor, and full-horizon weather are all available."""
    if model is None:
        return Readiness(ready=False, reason=MODEL_NOT_LOADED_REASON)
    try:
        _, weather = _prepare_prediction(
            task, runtime, as_of=as_of, horizon_hours=MAX_HORIZON_HOURS
        )
    except TaskUnavailableError as error:
        return Readiness(ready=False, reason=str(error))
    return Readiness(ready=True, mode=weather.mode)


def predict_task(
    task: TaskDefinition,
    model: TaskModel,
    runtime: TaskRuntime,
    *,
    as_of: datetime,
    horizon_hours: int | None,
) -> PredictionOutcome:
    """Predict from persisted data as known at ``as_of``.

    Raises ``MissingLoadHistoryError``, ``StaleLoadAnchorError`` or
    ``WeatherUnavailableError`` (all ``TaskUnavailableError``) instead of degrading
    where no substitute exists.
    """
    data, weather = _prepare_prediction(task, runtime, as_of=as_of, horizon_hours=horizon_hours)
    return PredictionOutcome(
        subject=task.subject,
        mode=weather.mode,
        predictions=model.predict(data),
        weather=data.weather,
        weather_sources=weather.sources,
    )


def _prepare_prediction(
    task: TaskDefinition, runtime: TaskRuntime, *, as_of: datetime, horizon_hours: int | None
) -> tuple[PredictionData, WeatherResolution]:
    requirements = get_task_type(task.task_type).requirements(task.params)
    anchor = _fresh_load_anchor(task, runtime.repository, as_of)
    history = _fetch_target(
        task,
        runtime.repository,
        start=anchor - timedelta(hours=requirements.lookback_hours),
        end=anchor,
    )
    weather = _resolve_future_weather(task, runtime, requirements, anchor, as_of, horizon_hours)
    data = PredictionData(
        anchor=anchor,
        load_history=history,
        weather=weather.dataframe[[DATETIME_COL, *task.weather.fields]],
        horizon_hours=horizon_hours,
    )
    return data, weather


def _fresh_load_anchor(
    task: TaskDefinition, repository: TimeSeriesRepository, as_of: datetime
) -> pd.Timestamp:
    """Refuse rather than degrade: actual load has no substitute as the recursion origin."""
    latest = _with_datetime_column(
        repository.fetch_latest_load(
            subject=task.subject, source=REGIONAL_SNAPSHOT_SUM_SOURCE, at_or_before=as_of
        )
    )
    if latest.empty:
        raise MissingLoadHistoryError(f"No persisted {task.subject} load history is available.")
    anchor = pd.Timestamp(latest[DATETIME_COL].max())
    max_lag_hours = task.policies.stale_anchor_max_lag_hours
    if is_stale_load_anchor(anchor, pd.Timestamp(as_of), max_lag_hours):
        raise StaleLoadAnchorError(
            f"Stale load anchor: latest actual load at {anchor.isoformat()} lags request time "
            f"{pd.Timestamp(as_of).isoformat()} by more than {max_lag_hours} hours."
        )
    return anchor


def _resolve_future_weather(
    task: TaskDefinition,
    runtime: TaskRuntime,
    requirements: InputRequirements,
    anchor: pd.Timestamp,
    as_of: datetime,
    horizon_hours: int | None,
) -> WeatherResolution:
    if requirements.weather is not WeatherInput.FORECAST or horizon_hours is None:
        raise NotImplementedError(
            "Only forecast weather over an explicit horizon is served; observed-weather "
            "prediction arrives with the first task type that needs it."
        )
    weather = resolve_weather(
        runtime.repository,
        reference_point=task.weather.reference_point,
        start_time=anchor + timedelta(hours=1),
        horizon_hours=horizon_hours,
        as_of=as_of,
        fields=task.weather.fields,
    )
    if weather.mode == "unavailable" or weather.dataframe.empty:
        raise WeatherUnavailableError(weather.reason or "Weather coverage is unavailable.")
    return weather


# --- Shared I/O ----------------------------------------------------------------------------


def _fetch_target(
    task: TaskDefinition,
    repository: TimeSeriesRepository,
    *,
    start: datetime | None,
    end: datetime | None,
) -> pd.DataFrame:
    """Read the task's target series.

    Only derived rows are read: d015046-era rows (NULL source) use a different
    measurement basis and must never train, anchor, or feed a forecast (ADR-0008).
    """
    load = repository.fetch_load_range(
        start_time=start, end_time=end, subject=task.subject, source=REGIONAL_SNAPSHOT_SUM_SOURCE
    )
    load = _with_datetime_column(load)
    if SUBJECT_COL not in load.columns:
        load = load.assign(**{SUBJECT_COL: task.subject})
    return load[TARGET_COLUMNS].reset_index(drop=True)


def _with_datetime_column(frame: pd.DataFrame) -> pd.DataFrame:
    """Persisted tables name their instant column ``time``; task frames use ``datetime``."""
    if DATETIME_COL not in frame.columns and STORAGE_TIME_COL in frame.columns:
        return frame.rename(columns={STORAGE_TIME_COL: DATETIME_COL})
    return frame


def _validation_start(times: pd.Series, validation_fraction: float) -> pd.Timestamp:
    """The shared out-of-time split: the latest ``validation_fraction`` of target hours validate."""
    ordered = pd.Series(pd.to_datetime(times).sort_values().unique())
    split_index = min(int(len(ordered) * (1.0 - validation_fraction)), len(ordered) - 1)
    return pd.Timestamp(ordered.iloc[split_index])
