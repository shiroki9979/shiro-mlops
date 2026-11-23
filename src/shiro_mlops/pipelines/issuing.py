"""Issue one forecast at a resolved issue time and name how the issue ended (ADR-0013).

The issue time arrives already resolved: which runs carry one is decided in
src/shiro_mlops/pipelines/execution_origin.py, before anything here runs. From
that issue time an issue ends in exactly one ``IssuingOutcome``. An issue time
already on record is never forecast again or overwritten, whether the record is
found before forecasting or only when writing.

The schedule and the issue read the same decision on whether a model can issue
(``issuing_decision``): only the model directory counts, never the accumulation
gate.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dagster import DagsterInstance

from shiro_mlops.core.constants import DATETIME_COL, MAX_HORIZON_HOURS
from shiro_mlops.data.issued_forecast import IssuedForecast, IssuedForecastStep
from shiro_mlops.data.issued_forecast_repository import IssuedForecastRepository
from shiro_mlops.pipelines.cold_start import ScheduleDecision, read_model_presence
from shiro_mlops.pipelines.task_pipelines import latest_recorded_model
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task
from shiro_mlops.tasks.model_store import LoadedModel, load_model_with_sha256
from shiro_mlops.tasks.runner import (
    PredictionOutcome,
    TaskRuntime,
    TaskUnavailableError,
    predict_task,
)
from shiro_mlops.tasks.types.recursive_regression import PREDICTION_COL

# SYNC(src/shiro_mlops/pipelines/smoke_check.py, docs/reference/dagster-schedules.md): 排程名稱由
# smoke_check.ISSUED_FORECAST_SCHEDULES 重述為部署契約（文件第 6 項）
ISSUED_FORECAST_SCHEDULE = "issued_forecast_schedule"
ISSUED_FORECAST_TASK = DYNAMIC_HORIZON_FORECAST


@dataclass(frozen=True)
class Issued:
    """The forecast was written as the record of its issue time."""

    forecast: IssuedForecast


@dataclass(frozen=True)
class AlreadyIssued:
    """The issue time already had a record; nothing was written."""


@dataclass(frozen=True)
class ModelUnavailable:
    """The model directory held no model to issue with; ``reason`` is the schedule's skip reason."""

    reason: str


@dataclass(frozen=True)
class ForecastUnavailable:
    """The runner could not produce a forecast; the issue time stays unissued and is not backfilled."""

    reason: str


IssuingOutcome = Issued | AlreadyIssued | ModelUnavailable | ForecastUnavailable


def issue_forecast(
    issued_at: datetime,
    *,
    store: IssuedForecastRepository,
    runtime: TaskRuntime,
    instance: DagsterInstance,
    models_root: Path,
) -> IssuingOutcome:
    """Forecast as of ``issued_at`` and keep it, unless that issue time is already on record."""
    if store.fetch(issued_at) is not None:
        return AlreadyIssued()
    loaded = _load_model(instance, models_root)
    if isinstance(loaded, ModelUnavailable):
        return loaded
    try:
        prediction = predict_task(
            deployed_task(ISSUED_FORECAST_TASK),
            loaded.model,
            runtime,
            as_of=issued_at,
            horizon_hours=MAX_HORIZON_HOURS,
        )
    except TaskUnavailableError as error:
        return ForecastUnavailable(str(error))
    forecast = _issued_forecast(
        issued_at,
        prediction,
        loaded,
        mlflow_model_version=_mlflow_model_version_note(instance, loaded.sha256),
    )
    if not store.insert(forecast):
        return AlreadyIssued()
    return Issued(forecast)


def issuing_decision(instance: DagsterInstance, *, models_root: Path) -> ScheduleDecision:
    """Model presence only: issuing never queries the accumulation gate or the load store for it."""
    return read_model_presence(
        ISSUED_FORECAST_TASK, instance=instance, models_root=models_root
    ).issuing(ISSUED_FORECAST_SCHEDULE)


def _load_model(instance: DagsterInstance, models_root: Path) -> LoadedModel | ModelUnavailable:
    """Load only when issuing may run; otherwise answer with the issuing schedule's skip reason.

    The decision is read again when loading finds nothing: the directory can vanish
    between the decision and the load, and the second read names what is missing now.
    """
    decision = issuing_decision(instance, models_root=models_root)
    if decision.runs:
        loaded = load_model_with_sha256(models_root, deployed_task(ISSUED_FORECAST_TASK))
        if loaded is not None:
            return loaded
        decision = issuing_decision(instance, models_root=models_root)
    return ModelUnavailable(
        decision.skip_reason
        or f"{ISSUED_FORECAST_TASK} model changed while loading; the next tick loads it again."
    )


def _mlflow_model_version_note(instance: DagsterInstance, loaded_sha256: str) -> str | None:
    """The latest model materialization's MLflow version, only if it recorded the loaded model.

    Read from the Dagster instance, never from MLflow. Training may finish between
    loading the model and this read, so a hash mismatch, missing metadata or an
    empty version leaves the note empty rather than naming the wrong model.
    """
    recorded = latest_recorded_model(instance, ISSUED_FORECAST_TASK)
    if recorded is None or recorded.sha256 != loaded_sha256:
        return None
    return recorded.mlflow_model_version


def _issued_forecast(
    issued_at: datetime,
    prediction: PredictionOutcome,
    loaded: LoadedModel,
    *,
    mlflow_model_version: str | None,
) -> IssuedForecast:
    """Keep every step the model produced, unfiltered and without weather."""
    return IssuedForecast(
        issued_at=issued_at,
        load_anchor=prediction.load_anchor.to_pydatetime(),
        status=prediction.mode,
        model_sha256=loaded.sha256,
        mlflow_model_version=mlflow_model_version,
        steps=tuple(
            IssuedForecastStep(
                target_hour=target_hour.to_pydatetime(), predicted_load_mw=float(load_mw)
            )
            for target_hour, load_mw in zip(
                prediction.predictions[DATETIME_COL],
                prediction.predictions[PREDICTION_COL],
                strict=True,
            )
        ),
    )
