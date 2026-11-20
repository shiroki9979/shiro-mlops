"""Contract tests for the Forecast View export asset, job and schedule (ADR-0015 §2.3)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from dagster import AssetKey, DefaultScheduleStatus, build_schedule_context

from shiro_mlops.pipelines.definitions import defs
from shiro_mlops.pipelines.forecast_track_record import (
    FORECAST_TRACK_RECORD_ASSET,
    forecast_track_record_job,
)
from shiro_mlops.pipelines.forecast_view_export import (
    FORECAST_VIEW_EXPORT_ASSET,
    forecast_view_export_job,
    forecast_view_export_schedule,
)
from shiro_mlops.pipelines.issued_forecast import ISSUED_FORECAST_ASSET, issued_forecast_job
from shiro_mlops.pipelines.schedules import (
    CWA_INGESTION_ASSETS,
    HOURLY_ACTUAL_LOAD_ASSET,
    TAIPOWER_REALTIME_SNAPSHOT_ASSETS,
)
from tests.helpers import selected_asset_names, task_jobs

# 2026-11-20 02:35 UTC 即台灣 10:35，排在發布（:15）與預報實績彙整（:25）之後。
TICK = datetime(2026, 11, 20, 2, 35, tzinfo=ZoneInfo("UTC"))


def test_export_lineage_follows_issued_forecasts_and_the_track_record() -> None:
    node = defs.resolve_asset_graph().get(AssetKey(FORECAST_VIEW_EXPORT_ASSET))

    assert {key.to_user_string() for key in node.parent_keys} == {
        ISSUED_FORECAST_ASSET,
        FORECAST_TRACK_RECORD_ASSET,
    }


def test_schedule_exports_at_thirty_five_past_every_taiwan_hour() -> None:
    schedule = defs.resolve_schedule_def("forecast_view_export_schedule")

    assert schedule.cron_schedule == "35 * * * *"
    assert schedule.execution_timezone == "Asia/Taipei"
    assert schedule.job_name == "forecast_view_export_job"


def test_schedule_is_off_until_an_operator_turns_it_on() -> None:
    schedule = defs.resolve_schedule_def("forecast_view_export_schedule")

    assert schedule.default_status == DefaultScheduleStatus.STOPPED


def test_schedule_tick_deduplicates_on_the_taiwan_local_tick() -> None:
    context = build_schedule_context(scheduled_execution_time=TICK)

    [request] = forecast_view_export_schedule.evaluate_tick(context).run_requests

    assert request.run_key == "2026-11-20T10:35:00"
    assert not request.run_config


def test_schedule_evaluated_without_a_tick_still_requests_an_export() -> None:
    [request] = forecast_view_export_schedule.evaluate_tick(build_schedule_context()).run_requests

    assert request.run_key is None


def test_job_selects_only_the_export_never_ingestion_issuing_or_compiling() -> None:
    """A failed or skipped compilation must not keep the newest issued forecast off the page."""
    selected = selected_asset_names(forecast_view_export_job)

    assert selected == {FORECAST_VIEW_EXPORT_ASSET}
    assert selected.isdisjoint(TAIPOWER_REALTIME_SNAPSHOT_ASSETS)
    assert selected.isdisjoint(CWA_INGESTION_ASSETS)
    assert HOURLY_ACTUAL_LOAD_ASSET not in selected


def test_no_other_job_exports() -> None:
    for job in [issued_forecast_job, forecast_track_record_job, *task_jobs()]:
        assert FORECAST_VIEW_EXPORT_ASSET not in selected_asset_names(job), job.name


def test_job_retries_because_every_export_overwrites_the_same_files() -> None:
    job = defs.resolve_job_def("forecast_view_export_job")

    policy = job.op_retry_policy
    assert policy is not None
    assert policy.max_retries > 0


def test_deployment_provides_the_publisher_resource() -> None:
    assert "forecast_view_publisher" in defs.resources
