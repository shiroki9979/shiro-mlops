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

What an issue does once it has an issue time, and the outcome it ends in, is in
src/shiro_mlops/pipelines/issuing.py; the asset only turns that outcome into a
materialization or a ``Failure``.
"""

from datetime import datetime
from typing import assert_never

from dagster import (
    AssetExecutionContext,
    AssetKey,
    AssetSelection,
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
from shiro_mlops.core.datetime_utils import TAIWAN_TZ
from shiro_mlops.pipelines.execution_origin import (
    WithoutTick,
    run_as_of,
    scheduled_tick,
    tick_run_request,
)
from shiro_mlops.pipelines.issuing import (
    ISSUED_FORECAST_SCHEDULE,
    AlreadyIssued,
    ForecastUnavailable,
    Issued,
    ModelUnavailable,
    issue_forecast,
    issuing_decision,
)
from shiro_mlops.pipelines.schedules import (
    CWA_FORECAST_ASSET,
    CWA_OBSERVATION_ASSET,
    HOURLY_ACTUAL_LOAD_ASSET,
)
from shiro_mlops.pipelines.task_pipelines import MODEL_SHA256_METADATA, TIME_SERIES_REPO
from shiro_mlops.tasks.runner import TaskRuntime

ISSUED_FORECAST_ASSET = "issued_forecast"
# SYNC(src/shiro_mlops/pipelines/smoke_check.py, docs/reference/dagster-schedules.md): job 名稱與 cron
# 由 smoke_check.ISSUED_FORECAST_SCHEDULES 重述為部署契約（文件第 6 項）
ISSUED_FORECAST_JOB = "issued_forecast_job"


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
    outcome = issue_forecast(
        issued_at,
        store=repository.issued_forecast_store,
        runtime=TaskRuntime.from_composition_root(repository),
        instance=context.instance,
        models_root=settings.models_dir,
    )
    match outcome:
        case Issued(forecast=forecast):
            return MaterializeResult(
                metadata={
                    **_issued_at_metadata(issued_at),
                    "already_issued": MetadataValue.bool(False),
                    "load_anchor": MetadataValue.text(forecast.load_anchor.isoformat()),
                    "status": MetadataValue.text(forecast.status.value),
                    MODEL_SHA256_METADATA: MetadataValue.text(forecast.model_sha256),
                    "steps": MetadataValue.int(len(forecast.steps)),
                }
            )
        case AlreadyIssued():
            return MaterializeResult(
                metadata={
                    **_issued_at_metadata(issued_at),
                    "already_issued": MetadataValue.bool(True),
                }
            )
        case ModelUnavailable(reason=reason) | ForecastUnavailable(reason=reason):
            raise Failure(description=reason, metadata=_issued_at_metadata(issued_at))
        case _:
            assert_never(outcome)


def _issued_at_metadata(issued_at: datetime) -> dict[str, MetadataValue]:
    """Every outcome of an issue, success or Failure, names the issue time it was for."""
    return {"issued_at": MetadataValue.text(issued_at.isoformat())}


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
    return issuing_decision(context.instance, models_root=settings.models_dir).run_or_skip(
        _issue_request(context)
    )


def _issue_request(context: ScheduleEvaluationContext) -> RunRequest | SkipReason:
    if scheduled_tick(context) is None:
        return SkipReason("No scheduled tick to issue at; only scheduled ticks issue forecasts.")
    return tick_run_request(context)
