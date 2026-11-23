"""Unit tests for Taipower realtime snapshot job and schedule registration."""

from datetime import datetime
from zoneinfo import ZoneInfo

from dagster import build_schedule_context

from shiro_mlops.pipelines.execution_origin import SCHEDULE_NAME_TAG, SCHEDULED_TICK_TAG
from shiro_mlops.pipelines.schedules import (
    TAIPOWER_REALTIME_SNAPSHOT_ASSETS,
    taipower_supply_demand_snapshot_job,
    taipower_supply_demand_snapshot_schedule,
)
from tests.helpers import selected_asset_names, task_jobs


def test_realtime_job_selects_exactly_three_snapshot_assets() -> None:
    """10 分鐘工作應只選取全台、區域與機組三個即時資產。"""
    selected = selected_asset_names(taipower_supply_demand_snapshot_job)
    assert selected == set(TAIPOWER_REALTIME_SNAPSHOT_ASSETS)


def test_task_jobs_exclude_realtime_snapshot_assets() -> None:
    """Training and monitoring jobs exclude all three realtime snapshot assets."""
    for job in task_jobs():
        assert selected_asset_names(job).isdisjoint(TAIPOWER_REALTIME_SNAPSHOT_ASSETS), job.name


def test_realtime_job_registers_limited_op_retry_policy() -> None:
    """暫時性來源失敗應在同一 run 內有限次重試。"""
    policy = taipower_supply_demand_snapshot_job.op_retry_policy
    assert policy is not None
    assert policy.max_retries == 2
    assert policy.delay == 10


def test_realtime_schedule_runs_every_ten_minutes_in_taiwan_time() -> None:
    assert taipower_supply_demand_snapshot_schedule.cron_schedule == "*/10 * * * *"
    assert taipower_supply_demand_snapshot_schedule.execution_timezone == "Asia/Taipei"


def test_realtime_schedule_tags_the_run_with_its_taiwan_local_tick() -> None:
    """三個快照從同一個 run 標籤取得 tick，不再各自帶 observed_at 設定。"""
    context = build_schedule_context(
        scheduled_execution_time=datetime(2026, 9, 5, 9, 30, tzinfo=ZoneInfo("UTC"))
    )
    [request] = taipower_supply_demand_snapshot_schedule.evaluate_tick(context).run_requests

    assert request.run_key == "2026-09-05T17:30:00"
    assert request.tags == {
        SCHEDULE_NAME_TAG: "taipower_supply_demand_snapshot_schedule",
        SCHEDULED_TICK_TAG: "2026-09-05T17:30:00",
    }
    assert not request.run_config


def test_realtime_schedule_without_tick_time_requests_an_unkeyed_untagged_run() -> None:
    """無 tick 的評估不帶 run key 與 tick 標籤；三個快照退回 run 建立時刻的 slot。"""
    execution = taipower_supply_demand_snapshot_schedule.evaluate_tick(build_schedule_context())

    [request] = execution.run_requests
    assert request.run_key is None
    assert SCHEDULED_TICK_TAG not in request.tags
    assert not request.run_config
