"""Contract tests for the forecast track record schedule and job (ADR-0013 §2.3)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from dagster import build_schedule_context, materialize

from shiro_mlops.core.io_managers import get_parquet_io_manager
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.pipelines.definitions import defs
from shiro_mlops.pipelines.forecast_track_record import (
    FORECAST_TRACK_RECORD_ASSET,
    forecast_track_record,
    forecast_track_record_job,
    forecast_track_record_schedule,
)
from shiro_mlops.pipelines.issued_forecast import ISSUED_FORECAST_ASSET
from shiro_mlops.pipelines.schedules import (
    CWA_INGESTION_ASSETS,
    HOURLY_ACTUAL_LOAD_ASSET,
    TAIPOWER_REALTIME_SNAPSHOT_ASSETS,
)
from tests.helpers import selected_asset_names

# 2026-11-20 02:25 UTC 即台灣 10:25，排在發布（:15）之後。
TICK = datetime(2026, 11, 20, 2, 25, tzinfo=ZoneInfo("UTC"))


def _evaluate(tick: datetime | None = TICK):
    if tick is None:
        return forecast_track_record_schedule.evaluate_tick(build_schedule_context())
    context = build_schedule_context(scheduled_execution_time=tick)
    return forecast_track_record_schedule.evaluate_tick(context)


def test_schedule_compiles_at_twenty_five_past_every_taiwan_hour() -> None:
    schedule = defs.resolve_schedule_def("forecast_track_record_schedule")

    assert schedule.cron_schedule == "25 * * * *"
    assert schedule.execution_timezone == "Asia/Taipei"
    assert schedule.job_name == "forecast_track_record_job"


def test_schedule_tick_becomes_the_taiwan_local_run_time() -> None:
    [request] = _evaluate().run_requests

    assert request.run_key == "2026-11-20T10:25:00"
    assert request.run_config == {
        "ops": {FORECAST_TRACK_RECORD_ASSET: {"config": {"scheduled_at": "2026-11-20T10:25:00"}}}
    }


def test_scheduled_run_cuts_off_at_the_taiwan_local_tick_hour(
    test_repo: TimeSeriesRepository, dagster_instance, tmp_path
) -> None:
    [request] = _evaluate().run_requests

    result = materialize(
        [forecast_track_record],
        resources={
            "time_series_repo": test_repo,
            "io_manager": get_parquet_io_manager("local", "unused", tmp_path),
        },
        run_config=request.run_config,
        instance=dagster_instance,
    )

    record = result.output_for_node(FORECAST_TRACK_RECORD_ASSET)
    assert record.cutoff == datetime(2026, 11, 20, 10, 0)
    assert record.accumulated_days == 0


def test_schedule_evaluated_without_a_tick_lets_the_run_use_the_current_hour() -> None:
    """A manual evaluation has no tick to deduplicate on; the asset falls back to now."""
    [request] = _evaluate(tick=None).run_requests

    assert request.run_key is None
    assert not request.run_config


def test_job_selects_only_the_track_record_never_ingestion_or_issuing() -> None:
    selected = selected_asset_names(forecast_track_record_job)

    assert selected == {FORECAST_TRACK_RECORD_ASSET}
    assert selected.isdisjoint(TAIPOWER_REALTIME_SNAPSHOT_ASSETS)
    assert selected.isdisjoint(CWA_INGESTION_ASSETS)
    assert HOURLY_ACTUAL_LOAD_ASSET not in selected
    assert ISSUED_FORECAST_ASSET not in selected


def test_job_retries_because_every_compilation_recomputes_from_scratch() -> None:
    """Unlike issuing, a retried compilation reads the same window and overwrites nothing kept."""
    job = defs.resolve_job_def("forecast_track_record_job")

    policy = job.op_retry_policy
    assert policy is not None
    assert policy.max_retries > 0
