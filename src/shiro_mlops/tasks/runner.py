"""Task runner: the single entry point Dagster and the API use to train, monitor, and serve tasks.

The runner owns I/O and the shared components (ADR-0009): the minimum
accumulation gate, bounded data retrieval, the stale load anchor rule, and
weather resolution with degradation; the forecast mode is never set here but
derived from the weather sources (``src/shiro_mlops/data/weather_resolution.py``).
The prediction input gate (``src/shiro_mlops/tasks/prediction_inputs.py``) judges
the frames it reads before any task type sees them; task types only ever receive
in-memory frames. Every time-dependent decision takes an explicit ``as_of`` in
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
from shiro_mlops.data.cwa_weather_store import CWAWeatherStore
from shiro_mlops.data.hourly_actual_load import ONE_HOUR, floor_to_hour, is_stale_load_anchor
from shiro_mlops.data.hourly_actual_load_store import HourlyActualLoadStore, HourlyLoadObservation
from shiro_mlops.data.weather_resolution import (
    ForecastMode,
    WeatherCoverageError,
    WeatherValueSource,
    resolve_weather,
)
from shiro_mlops.tasks.accumulation import TrainingLoadReadiness, check_training_load_readiness
from shiro_mlops.tasks.definition import TaskDefinition

# WHY-NOT(InsufficientLoadHistoryError): 看似未用的匯入是重新匯出；例外定義於預測輸入關卡，
# runner 本身不引用它；只有 runner 的兩支整合測試由此匯入，保留這條既有匯入路徑。
from shiro_mlops.tasks.prediction_inputs import (
    InsufficientLoadHistoryError as InsufficientLoadHistoryError,
)
from shiro_mlops.tasks.prediction_inputs import (
    TaskUnavailableError,
    WeatherUnavailableError,
    admit_prediction_inputs,
    require_load_coverage,
)
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
    SerializedPointSources,
    WeightedWeather,
    serialize_point_sources,
    weighted_observations,
    weighted_resolution,
)

TARGET_COLUMNS = [DATETIME_COL, SUBJECT_COL, LOAD_MW_COL]


@dataclass(frozen=True)
class TaskRuntime:
    """The only stores the runner reads task data through.

    ``hourly_actual_load`` holds the hourly actual load every task targets;
    ``cwa_weather`` holds the CWA observations and forecasts every task reads weather from.
    """

    hourly_actual_load: HourlyActualLoadStore
    cwa_weather: CWAWeatherStore


class TaskNotReady(RuntimeError):  # noqa: N818 - name fixed by the #66 interface design
    """Persisted target history does not yet allow training (minimum accumulation unmet)."""

    def __init__(self, readiness: TrainingLoadReadiness):
        super().__init__(readiness.reason)
        self.readiness = readiness


class MissingLoadHistoryError(TaskUnavailableError):
    """No persisted target history exists to anchor a prediction."""


class StaleLoadAnchorError(TaskUnavailableError):
    """The latest actual load is too old to anchor a recursive forecast."""


class ObservedInputsIncompleteError(TaskUnavailableError):
    """Gaps in observed load or weather leave no requested hour that can be scored."""


@dataclass(frozen=True)
class Readiness:
    """Whether a task can serve a full-horizon prediction now, and in which forecast mode."""

    ready: bool
    mode: ForecastMode | None = None
    reason: str | None = None


@dataclass(frozen=True)
class PredictionOutcome:
    """A task prediction with its load anchor, the weather it used and that weather's provenance."""

    subject: str
    load_anchor: pd.Timestamp
    mode: ForecastMode
    predictions: pd.DataFrame
    weather: pd.DataFrame
    weather_sources: tuple[SerializedPointSources, ...]


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
        runtime.hourly_actual_load,
        task.policies.min_training_hours,
        subject=task.subject,
        as_of=as_of,
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
    load = _fetch_target(task, runtime.hourly_actual_load, start=None, through=as_of)
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
        observed = runtime.cwa_weather.fetch_weather_range(
            reference_point=point.location, start_time=start, end_time=end
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
    newest = _latest_target(task, runtime.hourly_actual_load, as_of)
    return MonitoringReport(
        task_id=task.task_id,
        health=get_task_type(task.task_type).assess_health(task.health, metrics),
        metrics=dict(metrics),
        target_hours=readiness.valid_hours,
        latest_target_time=pd.Timestamp(newest.hour),
        latest_target_value=newest.load_mw,
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
        weather_sources=tuple(serialize_point_sources(sources) for sources in weather.sources),
    )


@dataclass(frozen=True)
class _ServingRequest:
    """One point-in-time prediction: the task, its stores, the request time, and the horizon."""

    task: TaskDefinition
    runtime: TaskRuntime
    as_of: datetime
    horizon_hours: int | None

    @cached_property
    def requirements(self) -> InputRequirements:
        return _requirements_of(self.task)

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
    hourly_actual_load = request.runtime.hourly_actual_load
    anchor = _fresh_load_anchor(task, hourly_actual_load, request.as_of)
    history_start = anchor - timedelta(hours=requirements.lookback_hours)
    history = _fetch_target(task, hourly_actual_load, start=history_start, through=anchor)
    require_load_coverage(requirements, anchor=anchor, load=history, subject=task.subject)
    weather = request.weather_path.read(request, history_start, anchor)
    data = admit_prediction_inputs(
        requirements,
        anchor=anchor,
        load=history,
        weather=weather.dataframe,
        weather_fields=task.weather.fields,
        horizon_hours=request.horizon_hours,
        subject=task.subject,
    )
    return data, weather


def _fresh_load_anchor(
    task: TaskDefinition, hourly_actual_load: HourlyActualLoadStore, as_of: datetime
) -> pd.Timestamp:
    """Refuse rather than degrade: actual load has no substitute as the recursion origin."""
    anchor = pd.Timestamp(_latest_target(task, hourly_actual_load, as_of).hour)
    max_lag_hours = task.policies.stale_anchor_max_lag_hours
    if is_stale_load_anchor(anchor, pd.Timestamp(as_of), max_lag_hours):
        raise StaleLoadAnchorError(
            f"Stale load anchor: latest actual load at {anchor.isoformat()} lags request time "
            f"{pd.Timestamp(as_of).isoformat()} by more than {max_lag_hours} hours."
        )
    return anchor


def _resolve_future_weather(
    request: _ServingRequest, _history_start: pd.Timestamp, anchor: pd.Timestamp
) -> WeightedWeather:
    """Forecasts (or degraded fallbacks) for the hours after the anchor at every reference point.

    The one place a reference point's lack of weather coverage becomes the task's
    ``WeatherUnavailableError``, so ``data/`` never depends on the task layer.
    """
    if request.horizon_hours is None:
        raise ValueError("Forecast-weather prediction needs an explicit horizon_hours")
    fields = request.task.weather.fields
    try:
        resolutions = [
            PointResolution(
                point.location.alias,
                point.weight,
                resolve_weather(
                    request.runtime.cwa_weather,
                    reference_point=point.location,
                    start_time=anchor + timedelta(hours=1),
                    horizon_hours=request.horizon_hours,
                    as_of=request.as_of,
                    fields=fields,
                ),
            )
            for point in request.task.weather.reference_points
        ]
    except WeatherCoverageError as error:
        raise WeatherUnavailableError(str(error)) from error
    return weighted_resolution(resolutions, fields)


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
    return WeightedWeather(dataframe=observed, sources=sources)


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
    )


def _forecast_weather_as_delivered(
    _predictions: pd.DataFrame, weather: WeightedWeather
) -> WeightedWeather:
    """Forecast-weather task types already return one row per delivered weather hour."""
    return weather


def _forecast_weather_covers_horizon(
    _model: TaskModel, _data: PredictionData, weather: WeightedWeather
) -> WeightedWeather:
    """The gate already proved every target hour has weather; predicting adds nothing."""
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
    source = WeatherValueSource.observed(observed_at)
    return {field: dict.fromkeys(task.weather.aliases, source) for field in task.weather.fields}


# --- Shared I/O ----------------------------------------------------------------------------


def _latest_target(
    task: TaskDefinition, hourly_actual_load: HourlyActualLoadStore, as_of: datetime
) -> HourlyLoadObservation:
    """The newest derived target hour known at ``as_of``; its absence has no substitute."""
    latest = hourly_actual_load.latest_observation(as_of, subject=task.subject)
    if latest is None:
        raise MissingLoadHistoryError(
            f"No persisted {task.subject} load history at or before "
            f"{pd.Timestamp(as_of).isoformat()}."
        )
    return latest


def _fetch_target(
    task: TaskDefinition,
    hourly_actual_load: HourlyActualLoadStore,
    *,
    start: datetime | None,
    through: datetime,
) -> pd.DataFrame:
    """Read the task's target series from ``start`` through the hour holding ``through``.

    Training (through ``as_of``) and serving (through the anchor) both include their
    end hour; this is the one place that turns that into the store's half-open window,
    ending at the next hour. Flooring first keeps out the hour after a mid-hour ``as_of``.
    """
    end = floor_to_hour(through) + ONE_HOUR
    load = hourly_actual_load.series(start=start, end=end, subject=task.subject)
    return load.assign(**{SUBJECT_COL: task.subject})[TARGET_COLUMNS]


def _validation_start(times: pd.Series, validation_fraction: float) -> pd.Timestamp:
    """The shared out-of-time split: the latest ``validation_fraction`` of target hours validate."""
    ordered = pd.Series(pd.to_datetime(times).sort_values().unique())
    split_index = min(int(len(ordered) * (1.0 - validation_fraction)), len(ordered) - 1)
    return pd.Timestamp(ordered.iloc[split_index])
