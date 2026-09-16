"""Unit tests for Taipower realtime snapshot job and schedule registration."""

from datetime import datetime
from zoneinfo import ZoneInfo

from dagster import build_schedule_context, load_assets_from_modules

from shiro_mlops.pipelines import assets as assets_module
from shiro_mlops.pipelines.schedules import (
    TAIPOWER_REALTIME_SNAPSHOT_ASSETS,
    daily_training_job,
    daily_training_schedule,
    hourly_drift_job,
    hourly_drift_schedule,
    taipower_supply_demand_snapshot_job,
    taipower_supply_demand_snapshot_schedule,
)


def _all_assets():
    return load_assets_from_modules([assets_module])


def test_realtime_job_selects_exactly_three_snapshot_assets() -> None:
    """10 分鐘工作應只選取全台、區域與機組三個即時資產。"""
    selected = {
        key.to_user_string()
        for key in taipower_supply_demand_snapshot_job.selection.resolve(_all_assets())
    }
    assert selected == set(TAIPOWER_REALTIME_SNAPSHOT_ASSETS)


def test_existing_jobs_exclude_realtime_snapshot_assets() -> None:
    """既有訓練與漂移工作不得包含三個即時快照資產。"""
    daily = {key.to_user_string() for key in daily_training_job.selection.resolve(_all_assets())}
    hourly = {key.to_user_string() for key in hourly_drift_job.selection.resolve(_all_assets())}
    assert daily.isdisjoint(TAIPOWER_REALTIME_SNAPSHOT_ASSETS)
    assert hourly.isdisjoint(TAIPOWER_REALTIME_SNAPSHOT_ASSETS)


def test_realtime_job_registers_limited_op_retry_policy() -> None:
    """暫時性來源失敗應在同一 run 內有限次重試。"""
    policy = taipower_supply_demand_snapshot_job.op_retry_policy
    assert policy is not None
    assert policy.max_retries == 2
    assert policy.delay == 10


def test_realtime_schedule_cron_and_shared_tick_config() -> None:
    """排程應每 10 分鐘觸發，並對三資產注入相同 observed_at。"""
    assert taipower_supply_demand_snapshot_schedule.cron_schedule == "*/10 * * * *"
    assert taipower_supply_demand_snapshot_schedule.execution_timezone == "Asia/Taipei"

    context = build_schedule_context(
        scheduled_execution_time=datetime(2026, 9, 5, 17, 30, tzinfo=ZoneInfo("Asia/Taipei"))
    )
    execution = taipower_supply_demand_snapshot_schedule.evaluate_tick(context)
    assert execution.run_requests is not None
    assert len(execution.run_requests) == 1

    request = execution.run_requests[0]
    assert request.run_key == "2026-09-05T17:30:00"
    ops_config = request.run_config["ops"]
    observed_values = {
        ops_config[asset_name]["config"]["observed_at"]
        for asset_name in TAIPOWER_REALTIME_SNAPSHOT_ASSETS
    }
    assert observed_values == {"2026-09-05T17:30:00"}


def test_load_dependent_schedules_are_deferred_without_a_historical_source() -> None:
    """訓練與 drift 不得重試無法取得的歷史逐時負載來源。"""
    context = build_schedule_context(
        scheduled_execution_time=datetime(2026, 9, 17, 8, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    )

    for deferred_schedule in (daily_training_schedule, hourly_drift_schedule):
        execution = deferred_schedule.evaluate_tick(context)

        assert execution.run_requests == []
        assert execution.skip_message == (
            "Historical hourly Taipower load source is unavailable; "
            "training and drift schedules are deferred."
        )
