"""Issued forecasts: one scheduled dynamic horizon forecast per hour, kept as issued (ADR-0013).

The issue time is the schedule tick in Taiwan-local time and is the forecast's
``as_of``. It is never floored to the hour: load is filtered by its hourly
timestamp rather than by when it was stored, so an issue time earlier than the
data actually landed would break point-in-time. Only scheduled ticks issue; a
manual run without a tick fails and writes nothing.

This asset sits outside the task factory and depends only on the ingested
inputs, never on ``{task}__model``: otherwise the tickless 00:00 training job
would select it downstream and issue a forecast.
"""

from datetime import datetime

from dagster import (
    AssetExecutionContext,
    AssetKey,
    AssetSelection,
    Config,
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
from shiro_mlops.pipelines.schedules import (
    CWA_FORECAST_ASSET,
    CWA_OBSERVATION_ASSET,
    HOURLY_ACTUAL_LOAD_ASSET,
    tick_run_key,
)
from shiro_mlops.pipelines.task_pipelines import TIME_SERIES_REPO, TaskPipelineNames
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
ISSUED_FORECAST_JOB = "issued_forecast_job"
ISSUED_FORECAST_SCHEDULE = "issued_forecast_schedule"
ISSUED_FORECAST_TASK = DYNAMIC_HORIZON_FORECAST
_MODEL_ASSET = TaskPipelineNames(ISSUED_FORECAST_TASK).model
# Dagster 對排程 tick 產生的每個 run 加上此標籤（`DagsterRun.tags_for_schedule`）。
SCHEDULE_NAME_TAG = "dagster/schedule_name"


class IssuedForecastConfig(Config):
    """Set only by the schedule: the tick as a Taiwan-local ISO issue time."""

    issued_at: str | None = None


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
def issued_forecast(
    context: AssetExecutionContext, config: IssuedForecastConfig
) -> MaterializeResult:
    """Issue once per tick; fail without writing when no forecast can be produced.

    An issue time already on record succeeds without writing, so a run retried
    after its commit never overwrites what was issued.
    """
    issued_at = _scheduled_issue_time(context, config)
    repository = getattr(context.resources, TIME_SERIES_REPO)
    if repository.fetch_issued_forecast(issued_at) is not None:
        return _issued_result(issued_at, already_issued=True)
    loaded = _load_model()
    try:
        outcome = predict_task(
            deployed_task(ISSUED_FORECAST_TASK),
            loaded.model,
            TaskRuntime(repository=repository),
            as_of=issued_at,
            horizon_hours=MAX_HORIZON_HOURS,
        )
    except TaskUnavailableError as error:
        raise Failure(
            description=str(error),
            metadata={"issued_at": MetadataValue.text(issued_at.isoformat())},
        ) from error
    # MLflow 版本附註由 #153 依 `{task}__model` materialization 比對雜湊後填入。
    forecast = _issued_forecast(issued_at, outcome, loaded, mlflow_model_version=None)
    written = repository.insert_issued_forecast(forecast)
    return _issued_result(issued_at, already_issued=not written, forecast=forecast)


def _scheduled_issue_time(context: AssetExecutionContext, config: IssuedForecastConfig) -> datetime:
    """Only a run launched by the schedule's tick carries an issue time that counts."""
    scheduled = context.run.tags.get(SCHEDULE_NAME_TAG) == ISSUED_FORECAST_SCHEDULE
    if config.issued_at is None or not scheduled:
        raise Failure(
            description=(
                f"{ISSUED_FORECAST_ASSET} issues only from {ISSUED_FORECAST_SCHEDULE} "
                "scheduled ticks; a run without a scheduled tick writes nothing."
            )
        )
    return datetime.fromisoformat(config.issued_at)


def _load_model() -> LoadedModel:
    loaded = load_model_with_sha256(settings.models_dir, deployed_task(ISSUED_FORECAST_TASK))
    if loaded is None:
        raise Failure(
            description=f"No trained {ISSUED_FORECAST_TASK} model under {settings.models_dir}."
        )
    return loaded


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
        load_anchor=outcome.anchor.to_pydatetime(),
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


def _issued_result(
    issued_at: datetime, *, already_issued: bool, forecast: IssuedForecast | None = None
) -> MaterializeResult:
    metadata = {
        "issued_at": MetadataValue.text(issued_at.isoformat()),
        "already_issued": MetadataValue.bool(already_issued),
    }
    if forecast is not None and not already_issued:
        metadata |= {
            "load_anchor": MetadataValue.text(forecast.load_anchor.isoformat()),
            "status": MetadataValue.text(forecast.status),
            "model_sha256": MetadataValue.text(forecast.model_sha256),
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
    """Each tick is its own issue time; nothing is issued before the first trained model."""
    if context.instance.get_latest_materialization_event(AssetKey(_MODEL_ASSET)) is None:
        return SkipReason(
            f"No {_MODEL_ASSET} materialization yet; {ISSUED_FORECAST_SCHEDULE} waits for "
            "the first successful training run."
        )
    issued_at = tick_run_key(context)
    if issued_at is None:
        return SkipReason("No scheduled tick to issue at; only scheduled ticks issue forecasts.")
    return RunRequest(
        run_key=issued_at,
        run_config={"ops": {ISSUED_FORECAST_ASSET: {"config": {"issued_at": issued_at}}}},
    )
