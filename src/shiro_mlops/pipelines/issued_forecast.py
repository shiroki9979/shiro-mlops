"""Issued forecasts: one scheduled dynamic horizon forecast per hour, kept as issued (ADR-0013).

The issue time is the schedule tick in Taiwan-local time and is the forecast's
``as_of``. It is never floored to the hour: load is filtered by its hourly
timestamp rather than by when it was stored, so an issue time earlier than the
data actually landed would break point-in-time. Only the run a tick launched
issues; the asset refuses any run without a scheduled tick, so a manual run or a
re-execution fails and writes nothing.

This asset sits outside the task factory and depends only on the ingested
inputs, never on ``{task}__model``: otherwise the tickless 00:00 training job
would select it downstream and issue a forecast.
"""

from datetime import datetime

from dagster import (
    AssetExecutionContext,
    AssetKey,
    AssetSelection,
    DagsterInstance,
    Failure,
    MaterializeResult,
    MetadataValue,
    RunRequest,
    ScheduleEvaluationContext,
    SkipReason,
    asset,
    define_asset_job,
    schedule,
)

from shiro_mlops.core.config import settings
from shiro_mlops.core.constants import DATETIME_COL, MAX_HORIZON_HOURS
from shiro_mlops.core.datetime_utils import TAIWAN_TZ
from shiro_mlops.data.issued_forecast import IssuedForecast, IssuedForecastStep
from shiro_mlops.pipelines.cold_start import ScheduleDecision, read_model_presence
from shiro_mlops.pipelines.execution_origin import (
    WithoutTick,
    run_as_of,
    scheduled_tick,
    tick_run_request,
)
from shiro_mlops.pipelines.schedules import (
    CWA_FORECAST_ASSET,
    CWA_OBSERVATION_ASSET,
    HOURLY_ACTUAL_LOAD_ASSET,
)
from shiro_mlops.pipelines.task_pipelines import (
    MODEL_SHA256_METADATA,
    TIME_SERIES_REPO,
    latest_recorded_model,
)
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task
from shiro_mlops.tasks.model_store import LoadedModel, load_model_with_sha256
from shiro_mlops.tasks.runner import (
    PredictionOutcome,
    TaskRuntime,
    TaskUnavailableError,
    predict_task,
)
from shiro_mlops.tasks.types.recursive_regression import PREDICTION_COL

ISSUED_FORECAST_ASSET = "issued_forecast"
# job、排程名稱與 cron 由 smoke_check.ISSUED_FORECAST_SCHEDULES 重述為部署契約；
# 變更時須同步該處與 docs/reference/dagster-schedules.md 第 6 項。
ISSUED_FORECAST_JOB = "issued_forecast_job"
ISSUED_FORECAST_SCHEDULE = "issued_forecast_schedule"
ISSUED_FORECAST_TASK = DYNAMIC_HORIZON_FORECAST


@asset(
    name=ISSUED_FORECAST_ASSET,
    group_name=ISSUED_FORECAST_ASSET,
    description="Issue the scheduled dynamic horizon forecast and keep it as issued",
    required_resource_keys={TIME_SERIES_REPO},
    deps=[
        AssetKey(HOURLY_ACTUAL_LOAD_ASSET),
        AssetKey(CWA_OBSERVATION_ASSET),
        AssetKey(CWA_FORECAST_ASSET),
    ],
)
def issued_forecast(context: AssetExecutionContext) -> MaterializeResult:
    """Issue once per tick; fail without writing when no forecast can be produced.

    An issue time already on record succeeds without writing, so a run retried
    after its commit never overwrites what was issued.
    """
    issued_at = run_as_of(context, without_tick=WithoutTick.REFUSE)
    repository = getattr(context.resources, TIME_SERIES_REPO)
    store = repository.issued_forecast_store
    if store.fetch(issued_at) is not None:
        return _issued_result(issued_at, already_issued=True)
    runtime = TaskRuntime.from_composition_root(repository)
    loaded = _load_model(context, issued_at)
    try:
        outcome = predict_task(
            deployed_task(ISSUED_FORECAST_TASK),
            loaded.model,
            runtime,
            as_of=issued_at,
            horizon_hours=MAX_HORIZON_HOURS,
        )
    except TaskUnavailableError as error:
        raise Failure(description=str(error), metadata=_issued_at_metadata(issued_at)) from error
    forecast = _issued_forecast(
        issued_at,
        outcome,
        loaded,
        mlflow_model_version=_mlflow_model_version_note(context, loaded.sha256),
    )
    written = store.insert(forecast)
    return _issued_result(issued_at, already_issued=not written, forecast=forecast)


def _load_model(context: AssetExecutionContext, issued_at: datetime) -> LoadedModel:
    """Load only when issuing may run; otherwise fail with the issuing schedule's skip reason.

    The decision is read again when loading finds nothing: the directory can vanish
    between the decision and the load, and the second read names what is missing now.
    """
    decision = _issuing_decision(context.instance)
    if decision.runs:
        loaded = load_model_with_sha256(settings.models_dir, deployed_task(ISSUED_FORECAST_TASK))
        if loaded is not None:
            return loaded
        decision = _issuing_decision(context.instance)
    raise Failure(
        description=decision.skip_reason
        or f"{ISSUED_FORECAST_TASK} model changed while loading; the next tick loads it again.",
        metadata=_issued_at_metadata(issued_at),
    )


def _issuing_decision(instance: DagsterInstance) -> ScheduleDecision:
    """Model presence only: issuing never queries the accumulation gate or the load store for it."""
    return read_model_presence(
        ISSUED_FORECAST_TASK, instance=instance, models_root=settings.models_dir
    ).issuing(ISSUED_FORECAST_SCHEDULE)


def _mlflow_model_version_note(context: AssetExecutionContext, loaded_sha256: str) -> str | None:
    """The latest model materialization's MLflow version, only if it recorded the loaded model.

    Read from the Dagster instance, never from MLflow. Training may finish between
    loading the model and this read, so a hash mismatch, missing metadata or an
    empty version leaves the note empty rather than naming the wrong model.
    """
    recorded = latest_recorded_model(context.instance, ISSUED_FORECAST_TASK)
    if recorded is None or recorded.sha256 != loaded_sha256:
        return None
    return recorded.mlflow_model_version


def _issued_forecast(
    issued_at: datetime,
    outcome: PredictionOutcome,
    loaded: LoadedModel,
    *,
    mlflow_model_version: str | None,
) -> IssuedForecast:
    """Keep every step the model produced, unfiltered and without weather."""
    return IssuedForecast(
        issued_at=issued_at,
        load_anchor=outcome.load_anchor.to_pydatetime(),
        status=outcome.mode,
        model_sha256=loaded.sha256,
        mlflow_model_version=mlflow_model_version,
        steps=tuple(
            IssuedForecastStep(
                target_hour=target_hour.to_pydatetime(), predicted_load_mw=float(load_mw)
            )
            for target_hour, load_mw in zip(
                outcome.predictions[DATETIME_COL],
                outcome.predictions[PREDICTION_COL],
                strict=True,
            )
        ),
    )


def _issued_at_metadata(issued_at: datetime) -> dict[str, MetadataValue]:
    """Every outcome of an issue, success or Failure, names the issue time it was for."""
    return {"issued_at": MetadataValue.text(issued_at.isoformat())}


def _issued_result(
    issued_at: datetime, *, already_issued: bool, forecast: IssuedForecast | None = None
) -> MaterializeResult:
    metadata = {
        **_issued_at_metadata(issued_at),
        "already_issued": MetadataValue.bool(already_issued),
    }
    if forecast is not None and not already_issued:
        metadata |= {
            "load_anchor": MetadataValue.text(forecast.load_anchor.isoformat()),
            "status": MetadataValue.text(forecast.status.value),
            MODEL_SHA256_METADATA: MetadataValue.text(forecast.model_sha256),
            "steps": MetadataValue.int(len(forecast.steps)),
        }
    return MaterializeResult(metadata=metadata)


issued_forecast_job = define_asset_job(
    name=ISSUED_FORECAST_JOB,
    selection=AssetSelection.assets(ISSUED_FORECAST_ASSET),
    description="Issue the hourly dynamic horizon forecast; no retries keep as_of honest",
)


@schedule(
    name=ISSUED_FORECAST_SCHEDULE,
    job=issued_forecast_job,
    # 排在逐時負載推算（:05）與觀測擷取（:10）之後。
    cron_schedule="15 * * * *",
    execution_timezone=TAIWAN_TZ,
    description="Issue the dynamic horizon forecast at fifteen minutes past each hour",
)
def issued_forecast_schedule(context: ScheduleEvaluationContext) -> RunRequest | SkipReason:
    """Each tick is its own issue time; only an installed model in the model directory issues."""
    return _issuing_decision(context.instance).run_or_skip(_issue_request(context))


def _issue_request(context: ScheduleEvaluationContext) -> RunRequest | SkipReason:
    if scheduled_tick(context) is None:
        return SkipReason("No scheduled tick to issue at; only scheduled ticks issue forecasts.")
    return tick_run_request(context)
