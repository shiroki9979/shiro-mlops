"""The forecast track record: issued forecasts against valid hourly observations (ADR-0013 §2.2–2.3).

The cutoff is the run's time floored to the hour: the schedule tick when the
schedule supplies one, otherwise the current Taiwan-local time. Every run
recompiles the whole window from the database and keeps no earlier result, so
manual runs, retries and re-executions are all safe.

This asset sits outside the task factory. It depends on ``issued_forecast`` and
the hourly actual load for lineage only and runs neither.
"""

from datetime import datetime

from dagster import (
    AssetExecutionContext,
    AssetKey,
    Config,
    MetadataValue,
    Output,
    asset,
)

from shiro_mlops.core.datetime_utils import taiwan_now
from shiro_mlops.data.forecast_track_record import (
    ForecastTrackRecord,
    compile_forecast_track_record,
    track_record_cutoff,
    track_record_window,
)
from shiro_mlops.pipelines.issued_forecast import ISSUED_FORECAST_ASSET
from shiro_mlops.pipelines.schedules import HOURLY_ACTUAL_LOAD_ASSET
from shiro_mlops.pipelines.task_pipelines import TIME_SERIES_REPO

FORECAST_TRACK_RECORD_ASSET = "forecast_track_record"


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
        },
    )


def _run_time(config: ForecastTrackRecordConfig) -> datetime:
    if config.scheduled_at is not None:
        return datetime.fromisoformat(config.scheduled_at)
    return taiwan_now().to_pydatetime()
