"""Wiring of the hourly actual-load job: schedule tick, asset config, then the store.

Which hours a tick derives is specified on the store itself in
tests/unit/test_hourly_actual_load_store.py.
"""

import logging
from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from dagster import DagsterInstance, Definitions, ExecuteInProcessResult, build_schedule_context

from shiro_mlops.core.datetime_utils import TAIWAN_TZ
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.pipelines.assets import raw_taipower_load
from shiro_mlops.pipelines.schedules import hourly_actual_load_job, hourly_actual_load_schedule
from tests.helpers import (
    derived_hourly_load,
    derived_load_series,
    regional_supply_demand_snapshots,
    write_derived_load,
)

TICK = datetime(2026, 9, 5, 18, 5, tzinfo=ZoneInfo(TAIWAN_TZ))
# 區域 fixture 四區用電加總 3254.0 萬瓩，即 32540 MW。
FIXTURE_TOTAL_MW = 32540.0


def _store_samples(repo: TimeSeriesRepository, start: datetime, count: int) -> None:
    """Write four-region snapshots every ten minutes, varying fixture source times to model updates."""
    for index in range(count):
        slot = start + timedelta(minutes=10 * index)
        snapshots = [
            replace(snapshot, source_time=slot)
            for snapshot in regional_supply_demand_snapshots(slot)
        ]
        repo.upsert_regional_supply_demand_snapshots(snapshots)


def _run_scheduled_tick(
    repo: TimeSeriesRepository, instance: DagsterInstance
) -> ExecuteInProcessResult:
    evaluation = hourly_actual_load_schedule.evaluate_tick(
        build_schedule_context(scheduled_execution_time=TICK)
    )
    assert evaluation.run_requests is not None
    # 推算只讀資料庫：只綁定 repository，若 asset 需要任何來源 port，job 便無法解析；
    # 另擋下 httpx，以防 asset 繞過 port 自行建立 HTTP client。
    job_def = Definitions(
        assets=[raw_taipower_load],
        jobs=[hourly_actual_load_job],
        resources={"time_series_repo": repo},
    ).resolve_job_def("hourly_actual_load_job")

    with patch("httpx.Client", side_effect=AssertionError("external API must not be called")):
        result = job_def.execute_in_process(
            run_config=evaluation.run_requests[0].run_config, instance=instance
        )
    assert result.success
    return result


def _run_log(instance: DagsterInstance, result: ExecuteInProcessResult, level: int) -> list[str]:
    return [
        entry.user_message
        for entry in instance.all_logs(result.run_id)
        if entry.dagster_event is None and entry.level == level
    ]


def _persisted_load(repo: TimeSeriesRepository) -> dict[pd.Timestamp, float]:
    loads = derived_load_series(repo.engine)
    return dict(zip(loads["datetime"], loads["load_mw"], strict=True))


def test_scheduled_tick_derives_the_completed_hours_its_window_covers(
    test_repo: TimeSeriesRepository, dagster_instance: DagsterInstance
) -> None:
    _store_samples(test_repo, datetime(2026, 9, 5, 16, 0), 6)
    _store_samples(test_repo, datetime(2026, 9, 5, 17, 0), 3)  # 低於門檻

    result = _run_scheduled_tick(test_repo, dagster_instance)

    output = result.output_for_node("raw_taipower_load")
    assert output.to_dict("list") == {
        "datetime": [pd.Timestamp("2026-09-05 16:00:00")],
        "load_mw": [pytest.approx(FIXTURE_TOTAL_MW)],
        "sample_count": [6],
    }
    assert _persisted_load(test_repo) == {
        pd.Timestamp("2026-09-05 16:00:00"): pytest.approx(FIXTURE_TOTAL_MW)
    }
    assert _run_log(dagster_instance, result, logging.INFO) == [
        "Derived 1 of 168 hours in [2026-08-29T18:00:00, 2026-09-05T18:00:00) "
        "from 36 regional snapshots"
    ]
    assert _run_log(dagster_instance, result, logging.WARNING) == []


def test_scheduled_tick_warns_to_rederive_hours_beyond_the_catchup_limit(
    test_repo: TimeSeriesRepository, dagster_instance: DagsterInstance
) -> None:
    write_derived_load(test_repo.engine, derived_hourly_load(1, datetime(2026, 8, 1, 0, 0)))

    result = _run_scheduled_tick(test_repo, dagster_instance)

    assert _run_log(dagster_instance, result, logging.WARNING) == [
        "Hours in [2026-08-01T01:00:00, 2026-08-29T18:00:00) exceed "
        "HOURLY_LOAD_CATCHUP_MAX_HOURS=168 and are not derived; "
        "run scripts/rederive_hourly_actual_load.py for that range"
    ]
