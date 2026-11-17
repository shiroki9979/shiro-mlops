"""Contract tests for the hourly actual-load job, schedule, and snapshot retry policies."""

from datetime import datetime
from zoneinfo import ZoneInfo

from dagster import Backoff, RetryPolicy, build_schedule_context

from shiro_mlops.core.config import Settings
from shiro_mlops.pipelines import assets as assets_module
from shiro_mlops.pipelines.schedules import (
    hourly_actual_load_job,
    hourly_actual_load_schedule,
    taipower_supply_demand_snapshot_job,
)
from tests.helpers import selected_asset_names, task_jobs

HOURLY_ACTUAL_LOAD_ASSET = "raw_taipower_load"


def test_hourly_load_settings_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.HOURLY_LOAD_MIN_SAMPLES == 4
    assert settings.HOURLY_LOAD_RECOMPUTE_HOURS == 3
    assert settings.HOURLY_LOAD_CATCHUP_MAX_HOURS == 168


def test_hourly_actual_load_job_selects_only_derivation_asset() -> None:
    assert hourly_actual_load_job.name == "hourly_actual_load_job"
    assert selected_asset_names(hourly_actual_load_job) == {HOURLY_ACTUAL_LOAD_ASSET}


def test_task_jobs_do_not_run_the_snapshot_derivation() -> None:
    """Task training and monitoring cannot include snapshot-derived assets or read snapshot tables."""
    for job in task_jobs():
        assert HOURLY_ACTUAL_LOAD_ASSET not in selected_asset_names(job), job.name


def test_hourly_actual_load_schedule_passes_taiwan_tick_as_evaluation_time() -> None:
    assert hourly_actual_load_schedule.cron_schedule == "5 * * * *"
    assert hourly_actual_load_schedule.execution_timezone == "Asia/Taipei"

    context = build_schedule_context(
        scheduled_execution_time=datetime(2026, 9, 26, 14, 5, tzinfo=ZoneInfo("Asia/Taipei"))
    )
    execution = hourly_actual_load_schedule.evaluate_tick(context)

    assert execution.run_requests is not None
    request = execution.run_requests[0]
    assert request.run_key == "2026-09-26T14:05:00"
    assert request.run_config == {
        "ops": {HOURLY_ACTUAL_LOAD_ASSET: {"config": {"evaluated_at": "2026-09-26T14:05:00"}}}
    }


def test_hourly_actual_load_schedule_without_tick_time_lets_the_run_use_current_time() -> None:
    """Manual evaluation without a tick uses current time for its window and does not deduplicate runs."""
    execution = hourly_actual_load_schedule.evaluate_tick(build_schedule_context())

    assert execution.run_requests is not None
    request = execution.run_requests[0]
    assert request.run_key is None
    assert request.run_config == {}


def test_regional_snapshot_retries_with_exponential_backoff_while_others_keep_job_policy() -> None:
    """Regional snapshots alone feed hourly load and use longer retries; other snapshots retain their job policy."""
    regional = assets_module.raw_taipower_regional_supply_demand_snapshot.op.retry_policy

    assert regional is not None
    assert (regional.max_retries, regional.delay, regional.backoff) == (
        3,
        10,
        Backoff.EXPONENTIAL,
    )
    for asset_def in (
        assets_module.raw_taipower_supply_demand_snapshot,
        assets_module.raw_taipower_unit_generation_snapshot,
    ):
        assert asset_def.op.retry_policy is None
    assert taipower_supply_demand_snapshot_job.op_retry_policy == RetryPolicy(
        max_retries=2, delay=10
    )
