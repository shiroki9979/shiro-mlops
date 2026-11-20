"""Export the latest issued forecast and the forecast track record as the Forecast View's JSON.

ADR-0015 §2.3–2.4: the export runs hourly after issuing and compiling, writes
the local directory that Nginx serves under ``/published/`` and, when a bucket
is set, uploads the same files to its ``published/`` prefix. Each run
overwrites the same two file names, so manual runs, retries and re-executions
are all safe.

The track record arrives as this asset's input, read from the latest
``forecast_track_record`` artifact; the latest issued forecast is read from the
database. Its job selects only this asset, so a failed or skipped compilation
still lets the newest issued forecast reach the page.
"""

from dagster import (
    AssetExecutionContext,
    AssetIn,
    AssetKey,
    AssetSelection,
    MaterializeResult,
    MetadataValue,
    RetryPolicy,
    RunRequest,
    ScheduleEvaluationContext,
    asset,
    define_asset_job,
    schedule,
)

from shiro_mlops.core.datetime_utils import TAIWAN_TZ
from shiro_mlops.core.forecast_view_publisher import ForecastViewPublisher
from shiro_mlops.data.forecast_view import (
    FORECAST_TRACK_RECORD_FILE,
    LATEST_ISSUED_FORECAST_FILE,
    encode_document,
    forecast_track_record_document,
    latest_issued_forecast_document,
)
from shiro_mlops.pipelines.forecast_track_record import FORECAST_TRACK_RECORD_ASSET
from shiro_mlops.pipelines.issued_forecast import ISSUED_FORECAST_ASSET
from shiro_mlops.pipelines.schedules import tick_run_key
from shiro_mlops.pipelines.task_pipelines import TIME_SERIES_REPO

FORECAST_VIEW_EXPORT_ASSET = "forecast_view_export"
FORECAST_VIEW_PUBLISHER = "forecast_view_publisher"
# job、排程名稱與 cron 由 smoke_check.FORECAST_VIEW_EXPORT_SCHEDULES 重述為部署契約；
# 變更時須同步該處與 docs/reference/dagster-schedules.md 第 8 項。
FORECAST_VIEW_EXPORT_JOB = "forecast_view_export_job"
FORECAST_VIEW_EXPORT_SCHEDULE = "forecast_view_export_schedule"
# 匯出覆寫固定檔名，重試不會留下不一致的版本；S3 或檔案系統的短暫錯誤在數分鐘內重試。
FORECAST_VIEW_EXPORT_RETRY_POLICY = RetryPolicy(max_retries=2, delay=60)


@asset(
    name=FORECAST_VIEW_EXPORT_ASSET,
    group_name=FORECAST_VIEW_EXPORT_ASSET,
    description="Export the latest issued forecast and the forecast track record as public JSON",
    required_resource_keys={TIME_SERIES_REPO, FORECAST_VIEW_PUBLISHER},
    ins={"track_record": AssetIn(key=FORECAST_TRACK_RECORD_ASSET)},
    deps=[AssetKey(ISSUED_FORECAST_ASSET)],
)
def forecast_view_export(context: AssetExecutionContext, track_record: dict) -> MaterializeResult:
    """Before the first issue, the forecast document is empty and the export still succeeds."""
    repository = getattr(context.resources, TIME_SERIES_REPO)
    publisher: ForecastViewPublisher = getattr(context.resources, FORECAST_VIEW_PUBLISHER)
    forecast = latest_issued_forecast_document(repository.fetch_latest_issued_forecast())
    record = forecast_track_record_document(track_record)
    publisher.publish(
        {
            LATEST_ISSUED_FORECAST_FILE: encode_document(forecast),
            FORECAST_TRACK_RECORD_FILE: encode_document(record),
        }
    )
    return MaterializeResult(
        metadata={
            "issued_at": MetadataValue.text(forecast["issued_at"] or ""),
            "published_steps": MetadataValue.int(len(forecast["steps"])),
            "cutoff": MetadataValue.text(record["cutoff"]),
            "accumulated_days": MetadataValue.int(record["accumulated_days"]),
            "local_dir": MetadataValue.path(str(publisher.local_dir)),
            "uploaded_to_s3": MetadataValue.bool(publisher.uploads_to_s3),
        }
    )


forecast_view_export_job = define_asset_job(
    name=FORECAST_VIEW_EXPORT_JOB,
    selection=AssetSelection.assets(FORECAST_VIEW_EXPORT_ASSET),
    description="Export the Forecast View's JSON; retries are safe because it overwrites",
    op_retry_policy=FORECAST_VIEW_EXPORT_RETRY_POLICY,
)


@schedule(
    name=FORECAST_VIEW_EXPORT_SCHEDULE,
    job=forecast_view_export_job,
    # 排在發布（:15）與預報實績彙整（:25，含重試約於 :28 前結束）之後。
    cron_schedule="35 * * * *",
    execution_timezone=TAIWAN_TZ,
    description="Export the Forecast View's JSON at thirty-five minutes past each hour",
)
def forecast_view_export_schedule(context: ScheduleEvaluationContext) -> RunRequest:
    """The tick only deduplicates runs; what is exported is whatever is latest at run time."""
    return RunRequest(run_key=tick_run_key(context))
