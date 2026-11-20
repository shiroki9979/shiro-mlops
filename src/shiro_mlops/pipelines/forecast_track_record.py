"""The forecast track record: issued forecasts against valid hourly observations (ADR-0013 §2.2–2.3).

The cutoff is the run's time floored to the hour: the schedule tick when the
schedule supplies one, otherwise the current Taiwan-local time. Every run
recompiles the whole window from the database and keeps no earlier result, so
manual runs, retries and re-executions are all safe; unlike issuing, the job
therefore has a retry policy.

This asset sits outside the task factory. It depends on ``issued_forecast`` and
the hourly actual load for lineage only and runs neither; its job is separate
from ``issued_forecast_job``, so compiling goes on when an issue fails or skips.
"""

from datetime import datetime

from dagster import (
    AssetExecutionContext,
    AssetKey,
    AssetSelection,
    Config,
    MetadataValue,
    Output,
    RetryPolicy,
    RunRequest,
    ScheduleEvaluationContext,
    asset,
    define_asset_job,
    schedule,
)

from shiro_mlops.core.datetime_utils import TAIWAN_TZ, taiwan_now
from shiro_mlops.data.forecast_track_record import (
    HEADLINE_LEAD_TIME_HOURS,
    ForecastTrackRecord,
    compile_forecast_track_record,
    track_record_cutoff,
    track_record_window,
)
from shiro_mlops.pipelines.issued_forecast import ISSUED_FORECAST_ASSET
from shiro_mlops.pipelines.schedules import HOURLY_ACTUAL_LOAD_ASSET, tick_run_key
from shiro_mlops.pipelines.task_pipelines import TIME_SERIES_REPO

FORECAST_TRACK_RECORD_ASSET = "forecast_track_record"
# job、排程名稱與 cron 由 smoke_check.FORECAST_TRACK_RECORD_SCHEDULES 重述為部署契約；
# 變更時須同步該處與 docs/reference/dagster-schedules.md 第 7 項。
FORECAST_TRACK_RECORD_JOB = "forecast_track_record_job"
FORECAST_TRACK_RECORD_SCHEDULE = "forecast_track_record_schedule"
# 彙整只讀資料庫並從頭重算，重試不會改變結果；短暫的資料庫中斷在數分鐘內重試，遠早於下一個 tick。
FORECAST_TRACK_RECORD_RETRY_POLICY = RetryPolicy(max_retries=2, delay=60)


class ForecastTrackRecordConfig(Config):
    """Set by the schedule: its tick as a Taiwan-local ISO time. Manual runs leave it empty."""

    scheduled_at: str | None = None


@asset(
    name=FORECAST_TRACK_RECORD_ASSET,
    group_name=FORECAST_TRACK_RECORD_ASSET,
    description="Compile the forecast track record over the 30 days before the cutoff",
    required_resource_keys={TIME_SERIES_REPO},
    deps=[AssetKey(ISSUED_FORECAST_ASSET), AssetKey(HOURLY_ACTUAL_LOAD_ASSET)],
)
def forecast_track_record(
    context: AssetExecutionContext, config: ForecastTrackRecordConfig
) -> Output[ForecastTrackRecord]:
    """Recompile from scratch; with no issued forecast yet, the record has 0 accumulated days."""
    cutoff = track_record_cutoff(_run_time(config))
    repository = getattr(context.resources, TIME_SERIES_REPO)
    pairs = repository.fetch_track_record_pairs(*track_record_window(cutoff))
    record = compile_forecast_track_record(cutoff, pairs)
    return Output(
        record,
        metadata={
            "cutoff": MetadataValue.text(record.cutoff.isoformat()),
            "accumulated_days": MetadataValue.int(record.accumulated_days),
            "window_pairs": MetadataValue.int(len(pairs)),
            "lead_24_pairs": MetadataValue.int(
                sum(pair.lead_time_hours == HEADLINE_LEAD_TIME_HOURS for pair in pairs)
            ),
        },
    )


def _run_time(config: ForecastTrackRecordConfig) -> datetime:
    if config.scheduled_at is not None:
        return datetime.fromisoformat(config.scheduled_at)
    return taiwan_now().to_pydatetime()


forecast_track_record_job = define_asset_job(
    name=FORECAST_TRACK_RECORD_JOB,
    selection=AssetSelection.assets(FORECAST_TRACK_RECORD_ASSET),
    description="Compile the forecast track record; retries are safe because it recomputes",
    op_retry_policy=FORECAST_TRACK_RECORD_RETRY_POLICY,
)


@schedule(
    name=FORECAST_TRACK_RECORD_SCHEDULE,
    job=forecast_track_record_job,
    # 排在逐時負載推算（:05）與發布（:15）之後，窗內最後一小時 E − 1h 已推算入庫；發布失敗或略過時照常彙整。
    cron_schedule="25 * * * *",
    execution_timezone=TAIWAN_TZ,
    description="Compile the forecast track record at twenty-five minutes past each hour",
)
def forecast_track_record_schedule(context: ScheduleEvaluationContext) -> RunRequest:
    """The tick, in Taiwan-local time, sets the cutoff; without one the run uses the current hour."""
    scheduled_at = tick_run_key(context)
    if scheduled_at is None:
        return RunRequest()
    return RunRequest(
        run_key=scheduled_at,
        run_config={
            "ops": {FORECAST_TRACK_RECORD_ASSET: {"config": {"scheduled_at": scheduled_at}}}
        },
    )
