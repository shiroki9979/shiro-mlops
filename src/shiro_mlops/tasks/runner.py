"""Task runner: the single entry point Dagster and the API use to train, monitor, and serve tasks.

The runner owns I/O and the shared components (ADR-0009): the minimum
accumulation gate, bounded data retrieval, the stale load anchor rule, and
weather resolution with degradation. Task types only ever receive in-memory
frames. Every time-dependent decision takes an explicit ``as_of`` in
Taiwan-local naive time.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cached_property

import pandas as pd

from shiro_mlops.core.constants import (
    DATETIME_COL,
    LOAD_MW_COL,
    MAX_HORIZON_HOURS,
    SUBJECT_COL,
)
from shiro_mlops.core.datetime_utils import with_datetime_column
from shiro_mlops.data.hourly_actual_load import REGIONAL_SNAPSHOT_SUM_SOURCE, is_stale_load_anchor
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.weather_resolution import WeatherResolutionMode, resolve_weather
from shiro_mlops.tasks.accumulation import TrainingLoadReadiness, check_training_load_readiness
from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.types import get_task_type
from shiro_mlops.tasks.types.base import (
    HealthAssessment,
    InputRequirements,
    PredictionData,
    TaskModel,
    Trained,
    TrainingData,
    WeatherInput,
)
from shiro_mlops.tasks.weighted_weather import (
    PointResolution,
    PointSources,
    PointWeather,
    WeightedWeather,
    weighted_observations,
    weighted_resolution,
)

OBSERVED_WEATHER_SOURCE = "station_observation"
OBSERVED_AT_FIELD = "observed_at"
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


class InsufficientLoadHistoryError(TaskUnavailableError):
    """Too few actual load hours before the anchor for the task type's history window."""


class WeatherUnavailableError(TaskUnavailableError):
    """Neither forecasts nor degraded fallbacks cover the requested horizon.

    For observed-weather tasks: no station observation exists in the lookback.
    """


class ObservedInputsIncompleteError(TaskUnavailableError):
    """Gaps in observed load or weather leave no requested hour that can be scored."""


@dataclass(frozen=True)
class Readiness:
    """Whether a task can serve a full-horizon prediction now, and in which weather mode."""

    ready: bool
    mode: WeatherResolutionMode | None = None
    reason: str | None = None


@dataclass(frozen=True)
class PredictionOutcome:
    """A task prediction with its load anchor, the weather it used and that weather's provenance."""

    subject: str
    load_anchor: pd.Timestamp
    mode: WeatherResolutionMode
    predictions: pd.DataFrame
    weather: pd.DataFrame
    weather_sources: tuple[PointSources, ...]


@dataclass(frozen=True)
class MonitoringReport:
    """The task type's health verdict on training metrics beside the newest persisted target."""

    task_id: str
    health: HealthAssessment
    metrics: Mapping[str, float]
    target_hours: int
    latest_target_time: pd.Timestamp
    latest_target_value: float


# --- Training ------------------------------------------------------------------------------


def check_training_readiness(
    task: TaskDefinition, runtime: TaskRuntime, *, as_of: datetime | None = None
) -> TrainingLoadReadiness:
    """Summarize target history through ``as_of`` against the minimum accumulation."""
    return check_training_load_readiness(
        runtime.repository, task.policies.min_training_hours, subject=task.subject, as_of=as_of
    )


def load_training_data(
    task: TaskDefinition, runtime: TaskRuntime, *, as_of: datetime
) -> TrainingData:
    """Gate on accumulation, then read target history and observed weather up to ``as_of``.

    The training window is derived from the accumulated target rows themselves.
    """
    readiness = check_training_readiness(task, runtime, as_of=as_of)
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
    return fit_task(task, load_training_data(task, runtime, as_of=as_of))


def fit_task(task: TaskDefinition, data: TrainingData) -> Trained:
    """Train the task's type on training data that was already read and gated."""
    return get_task_type(task.task_type).train(task.params, data)


def training_table(data: TrainingData) -> pd.DataFrame:
    """Serialize target and observed weather across the union of their hourly timelines."""
    return data.load.merge(data.weather, on=DATETIME_COL, how="outer").sort_values(
        DATETIME_COL, ignore_index=True
    )


def training_data_from_table(task: TaskDefinition, table: pd.DataFrame) -> TrainingData:
    """Invert ``training_table``: restore target rows with load and weather rows with observations.

    ``validation_start`` is recomputed from the restored target hours with the same
    shared split, matching the value ``load_training_data`` derived.
    """
    fields = list(task.weather.fields)
    load = (
        table[TARGET_COLUMNS]
        .dropna(subset=[LOAD_MW_COL])
        .sort_values(DATETIME_COL, ignore_index=True)
    )
    weather = (
        table[[DATETIME_COL, *fields]]
        .dropna(subset=fields, how="all")
        .sort_values(DATETIME_COL, ignore_index=True)
    )
    return TrainingData(
        load=load,
        weather=weather,
        validation_start=_validation_start(load[DATETIME_COL], task.policies.validation_fraction),
    )


def load_observed_weather(
    task: TaskDefinition,
    runtime: TaskRuntime,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> pd.DataFrame:
    """Observed weighted weather over the task's reference points, limited to its weather fields.

    An hour that any reference point did not observe has no weighted value (ADR-0012).
    """
    points = []
    for point in task.weather.reference_points:
        observed = runtime.repository.fetch_weather_range(
            start_time=start, end_time=end, reference_point=point.location.alias
        )
        observed = with_datetime_column(observed)[[DATETIME_COL, *task.weather.fields]]
        points.append(PointWeather(point.location.alias, point.weight, observed))
    return weighted_observations(points, task.weather.fields)


# --- Monitoring ----------------------------------------------------------------------------


def monitor_task(
    task: TaskDefinition, runtime: TaskRuntime, metrics: Mapping[str, float], *, as_of: datetime
) -> MonitoringReport:
    """Judge training metrics with the task type's health rule and the task's thresholds.

    Reads only the accumulation summary and the newest target row, never the full
    history, because monitoring runs hourly. Raises ``TaskNotReady`` while the
    minimum accumulation is unmet.
    """
    readiness = check_training_readiness(task, runtime, as_of=as_of)
    if not readiness.ready:
        raise TaskNotReady(readiness)
    newest = _latest_target_row(task, runtime.repository, as_of)
    return MonitoringReport(
        task_id=task.task_id,
        health=get_task_type(task.task_type).assess_health(task.health, metrics),
        metrics=dict(metrics),
        target_hours=readiness.valid_hours,
        latest_target_time=pd.Timestamp(newest[DATETIME_COL]),
        latest_target_value=float(newest[LOAD_MW_COL]),
    )


# --- Serving -------------------------------------------------------------------------------


def check_task_ready(
    task: TaskDefinition, model: TaskModel, runtime: TaskRuntime, *, as_of: datetime
) -> Readiness:
    """Whether a fresh load anchor and full-horizon weather are available to the model."""
    request = _readiness_request(task, runtime, as_of)
    try:
        data, weather = _prepare_prediction(request)
        weather = request.weather_path.probe(model, data, weather)
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

    Forecast-weather tasks predict ``horizon_hours`` hours after the load anchor;
    observed-weather tasks score the latest ``horizon_hours`` hours up to the anchor.
    Either way each outcome weather row and source belongs to the prediction row
    at the same position. Raises ``MissingLoadHistoryError``,
    ``StaleLoadAnchorError``, ``InsufficientLoadHistoryError``, ``WeatherUnavailableError`` or
    ``ObservedInputsIncompleteError`` (all ``TaskUnavailableError``) instead of
    degrading where no substitute exists.
    """
    request = _ServingRequest(task, runtime, as_of, horizon_hours)
    data, weather = _prepare_prediction(request)
    predictions = model.predict(data)
    weather = request.weather_path.align(predictions, weather)
    return PredictionOutcome(
        subject=task.subject,
        load_anchor=data.anchor,
        mode=weather.mode,
        predictions=predictions,
        weather=weather.dataframe[[DATETIME_COL, *task.weather.fields]],
        weather_sources=weather.sources,
    )


@dataclass(frozen=True)
class _ServingRequest:
    """One point-in-time prediction: the task, its store, the request time, and the horizon."""

    task: TaskDefinition
    runtime: TaskRuntime
    as_of: datetime
    horizon_hours: int | None

    @cached_property
    def requirements(self) -> InputRequirements:
        return _requirements_of(self.task)

    @property
    def repository(self) -> TimeSeriesRepository:
        return self.runtime.repository

    @property
    def weather_path(self) -> _WeatherPath:
        return _weather_path(self.requirements)


@dataclass(frozen=True)
class _WeatherPath:
    """How one weather input is read before predicting and matched to prediction rows after.

    Readiness asks for ``readiness_horizon_hours`` and passes the prepared inputs
    through ``probe``, which raises ``TaskUnavailableError`` when they cannot serve.
    """

    read: Callable[[_ServingRequest, pd.Timestamp, pd.Timestamp], WeightedWeather]
    align: Callable[[pd.DataFrame, WeightedWeather], WeightedWeather]
    readiness_horizon_hours: int
    probe: Callable[[TaskModel, PredictionData, WeightedWeather], WeightedWeather]


def _requirements_of(task: TaskDefinition) -> InputRequirements:
    return get_task_type(task.task_type).requirements(task.params)


def _weather_path(requirements: InputRequirements) -> _WeatherPath:
    return _WEATHER_PATHS[requirements.weather]


def _readiness_request(
    task: TaskDefinition, runtime: TaskRuntime, as_of: datetime
) -> _ServingRequest:
    """Readiness proves the horizon its weather path requires, so that horizon sets the request."""
    horizon_hours = _weather_path(_requirements_of(task)).readiness_horizon_hours
    return _ServingRequest(task, runtime, as_of, horizon_hours)


def _prepare_prediction(request: _ServingRequest) -> tuple[PredictionData, WeightedWeather]:
    task, requirements = request.task, request.requirements
    anchor = _fresh_load_anchor(task, request.repository, request.as_of)
    history_start = anchor - timedelta(hours=requirements.lookback_hours)
    history = _fetch_target(task, request.repository, start=history_start, end=anchor)
    _require_history_coverage(request, history, anchor)
    weather = request.weather_path.read(request, history_start, anchor)
    data = PredictionData(
        anchor=anchor,
        load_history=history,
        weather=weather.dataframe[[DATETIME_COL, *task.weather.fields]],
        horizon_hours=request.horizon_hours,
    )
    return data, weather


def _fresh_load_anchor(
    task: TaskDefinition, repository: TimeSeriesRepository, as_of: datetime
) -> pd.Timestamp:
    """Refuse rather than degrade: actual load has no substitute as the recursion origin."""
    anchor = pd.Timestamp(_latest_target_row(task, repository, as_of)[DATETIME_COL])
    max_lag_hours = task.policies.stale_anchor_max_lag_hours
    if is_stale_load_anchor(anchor, pd.Timestamp(as_of), max_lag_hours):
        raise StaleLoadAnchorError(
            f"Stale load anchor: latest actual load at {anchor.isoformat()} lags request time "
            f"{pd.Timestamp(as_of).isoformat()} by more than {max_lag_hours} hours."
        )
    return anchor


def _require_history_coverage(
    request: _ServingRequest, history: pd.DataFrame, anchor: pd.Timestamp
) -> None:
    """Refuse rather than let the task type fail: missing past load has no substitute."""
    coverage = request.requirements.history_coverage
    if coverage is None:
        return
    window_start = anchor - timedelta(hours=coverage.window_hours)
    times = pd.to_datetime(history.loc[history[LOAD_MW_COL].notna(), DATETIME_COL])
    valid_hours = times[(times > window_start) & (times <= anchor)].nunique()
    if valid_hours < coverage.min_valid_hours:
        raise InsufficientLoadHistoryError(
            f"Only {valid_hours} {request.task.subject} load hours in the {coverage.window_hours}-hour "
            f"window ending at anchor {anchor.isoformat()}; {coverage.min_valid_hours} required."
        )


def _resolve_future_weather(
    request: _ServingRequest, _history_start: pd.Timestamp, anchor: pd.Timestamp
) -> WeightedWeather:
    """Forecasts (or degraded fallbacks) for the hours after the anchor at every reference point."""
    if request.horizon_hours is None:
        raise ValueError("Forecast-weather prediction needs an explicit horizon_hours")
    fields = request.task.weather.fields
    resolutions = [
        PointResolution(
            point.location.alias,
            point.weight,
            resolve_weather(
                request.repository,
                reference_point=point.location,
                start_time=anchor + timedelta(hours=1),
                horizon_hours=request.horizon_hours,
                as_of=request.as_of,
                fields=fields,
            ),
        )
        for point in request.task.weather.reference_points
    ]
    weather = weighted_resolution(resolutions, fields)
    if weather.mode == "unavailable" or weather.dataframe.empty:
        raise WeatherUnavailableError(weather.reason or "Weather coverage is unavailable.")
    return weather


def _observed_weather_until(
    request: _ServingRequest, start: pd.Timestamp, anchor: pd.Timestamp
) -> WeightedWeather:
    """Station observations over the load history; observed tasks never degrade (mode normal).

    Observations are already known at the anchor, so no forecast release or
    fallback applies; each row's source records when it was observed.
    """
    task = request.task
    observed = load_observed_weather(task, request.runtime, start=start, end=anchor)
    observed = observed.dropna(subset=list(task.weather.fields), how="all")
    if observed.empty:
        raise WeatherUnavailableError(
            f"No observed weather at {', '.join(task.weather.aliases)} between "
            f"{start.isoformat()} and {anchor.isoformat()}."
        )
    observed = observed.assign(
        **{DATETIME_COL: pd.to_datetime(observed[DATETIME_COL]).astype("datetime64[ns]")}
    ).sort_values(DATETIME_COL, ignore_index=True)
    sources = tuple(
        _observation_source(task, observed_at) for observed_at in observed[DATETIME_COL]
    )
    return WeightedWeather(dataframe=observed, sources=sources, mode="normal")


def _observed_weather_at(predictions: pd.DataFrame, observed: WeightedWeather) -> WeightedWeather:
    """Keep, for each scored hour, the latest observation at or before it.

    That is the observation the task type's window used for its end hour, and it
    gives the service one weather row and source per prediction row, in order.
    """
    if predictions.empty:
        raise ObservedInputsIncompleteError(
            "No complete observed window ends within the requested hours; "
            "observed load or weather has gaps."
        )
    scored = pd.DataFrame(
        {DATETIME_COL: pd.to_datetime(predictions[DATETIME_COL]).astype("datetime64[ns]")}
    )
    positions = observed.dataframe[[DATETIME_COL]].assign(_position=range(len(observed.dataframe)))
    matched = pd.merge_asof(scored, positions, on=DATETIME_COL, direction="backward")
    if matched["_position"].isna().any():
        raise ObservedInputsIncompleteError("A scored hour precedes every delivered observation.")
    rows = matched["_position"].astype(int).tolist()
    aligned = observed.dataframe.iloc[rows].assign(**{DATETIME_COL: scored[DATETIME_COL].values})
    return WeightedWeather(
        dataframe=aligned.reset_index(drop=True),
        sources=tuple(observed.sources[row] for row in rows),
        mode=observed.mode,
    )


def _forecast_weather_as_delivered(
    _predictions: pd.DataFrame, weather: WeightedWeather
) -> WeightedWeather:
    """Forecast-weather task types already return one row per delivered weather hour."""
    return weather


def _forecast_weather_covers_horizon(
    _model: TaskModel, _data: PredictionData, weather: WeightedWeather
) -> WeightedWeather:
    """Resolving the full horizon already proved forecast coverage; predicting adds nothing."""
    return weather


def _observed_window_scores(
    model: TaskModel, data: PredictionData, weather: WeightedWeather
) -> WeightedWeather:
    """Observed gaps only show once the task type builds its window, so score the latest hour."""
    return _observed_weather_at(model.predict(data), weather)


_WEATHER_PATHS = {
    WeatherInput.FORECAST: _WeatherPath(
        read=_resolve_future_weather,
        align=_forecast_weather_as_delivered,
        readiness_horizon_hours=MAX_HORIZON_HOURS,
        probe=_forecast_weather_covers_horizon,
    ),
    WeatherInput.OBSERVED: _WeatherPath(
        read=_observed_weather_until,
        align=_observed_weather_at,
        readiness_horizon_hours=1,
        probe=_observed_window_scores,
    ),
}


def _observation_source(task: TaskDefinition, observed_at: pd.Timestamp) -> PointSources:
    """Weighted observations exist only where every point observed that same hour."""
    source = {"source": OBSERVED_WEATHER_SOURCE, OBSERVED_AT_FIELD: observed_at.isoformat()}
    aliases = task.weather.aliases
    return {field: {alias: dict(source) for alias in aliases} for field in task.weather.fields}


# --- Shared I/O ----------------------------------------------------------------------------


def _latest_target_row(
    task: TaskDefinition, repository: TimeSeriesRepository, as_of: datetime
) -> pd.Series:
    """The newest derived target row known at ``as_of``; its absence has no substitute."""
    latest = with_datetime_column(
        repository.fetch_latest_load(
            subject=task.subject, source=REGIONAL_SNAPSHOT_SUM_SOURCE, at_or_before=as_of
        )
    )
    if latest.empty:
        raise MissingLoadHistoryError(
            f"No persisted {task.subject} load history at or before "
            f"{pd.Timestamp(as_of).isoformat()}."
        )
    return latest.sort_values(DATETIME_COL).iloc[-1]


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
    load = with_datetime_column(load)
    if SUBJECT_COL not in load.columns:
        load = load.assign(**{SUBJECT_COL: task.subject})
    return load[TARGET_COLUMNS].reset_index(drop=True)


def _validation_start(times: pd.Series, validation_fraction: float) -> pd.Timestamp:
    """The shared out-of-time split: the latest ``validation_fraction`` of target hours validate."""
    ordered = pd.Series(pd.to_datetime(times).sort_values().unique())
    split_index = min(int(len(ordered) * (1.0 - validation_fraction)), len(ordered) - 1)
    return pd.Timestamp(ordered.iloc[split_index])
