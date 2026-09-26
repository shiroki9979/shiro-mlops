"""Integration tests for the hourly actual-load derivation Dagster job."""

from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from dagster import Definitions, build_schedule_context

from shiro_mlops.core.datetime_utils import TAIWAN_TZ
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.pipelines.assets import raw_taipower_load
from shiro_mlops.pipelines.schedules import hourly_actual_load_job, hourly_actual_load_schedule
from tests.helpers import regional_supply_demand_snapshots

TICK = datetime(2026, 9, 5, 18, 5, tzinfo=ZoneInfo(TAIWAN_TZ))
# 區域 fixture 四區用電加總 3254.0 萬瓩，即 32540 MW。
FIXTURE_TOTAL_MW = 32540.0


def _store_samples(repo: TimeSeriesRepository, start: datetime, count: int) -> None:
    """以十分鐘間隔寫入四區快照；fixture 來源時間固定，故改寫為各 slot 以模擬來源逐筆更新。"""
    for index in range(count):
        slot = start + timedelta(minutes=10 * index)
        snapshots = [
            replace(snapshot, source_time=slot)
            for snapshot in regional_supply_demand_snapshots(slot)
        ]
        repo.upsert_regional_supply_demand_snapshots(snapshots)


def _run_scheduled_tick(repo: TimeSeriesRepository):
    evaluation = hourly_actual_load_schedule.evaluate_tick(
        build_schedule_context(scheduled_execution_time=TICK)
    )
    assert evaluation.run_requests is not None
    job_def = Definitions(
        assets=[raw_taipower_load],
        jobs=[hourly_actual_load_job],
        resources={"time_series_repo": repo},
    ).resolve_job_def("hourly_actual_load_job")

    # 推算只讀資料庫；任何台電 HTTP 呼叫都代表越過邊界。
    with patch("httpx.Client", side_effect=AssertionError("external API must not be called")):
        result = job_def.execute_in_process(run_config=evaluation.run_requests[0].run_config)
    assert result.success
    return result


def _persisted_load(repo: TimeSeriesRepository) -> dict[pd.Timestamp, float]:
    loads = repo.fetch_load_range(location="Taipei")
    return dict(zip(loads["time"], loads["load_mw"], strict=True))


def test_job_recomputes_recent_completed_hours_idempotently(
    test_repo: TimeSeriesRepository,
) -> None:
    _store_samples(test_repo, datetime(2026, 9, 5, 14, 0), 6)  # 超出三小時重算窗口
    _store_samples(test_repo, datetime(2026, 9, 5, 15, 0), 6)
    _store_samples(test_repo, datetime(2026, 9, 5, 16, 0), 4)
    _store_samples(test_repo, datetime(2026, 9, 5, 17, 0), 3)  # 低於門檻
    _store_samples(test_repo, datetime(2026, 9, 5, 18, 0), 1)  # 尚未結束

    _run_scheduled_tick(test_repo)
    first = _persisted_load(test_repo)
    _run_scheduled_tick(test_repo)

    assert first == {
        pd.Timestamp("2026-09-05 15:00:00"): pytest.approx(FIXTURE_TOTAL_MW),
        pd.Timestamp("2026-09-05 16:00:00"): pytest.approx(FIXTURE_TOTAL_MW),
    }
    assert _persisted_load(test_repo) == first


def test_late_sample_fills_previously_missing_hour(test_repo: TimeSeriesRepository) -> None:
    _store_samples(test_repo, datetime(2026, 9, 5, 17, 0), 3)
    _run_scheduled_tick(test_repo)
    assert _persisted_load(test_repo) == {}

    _store_samples(test_repo, datetime(2026, 9, 5, 17, 30), 1)
    _run_scheduled_tick(test_repo)

    assert _persisted_load(test_repo) == {
        pd.Timestamp("2026-09-05 17:00:00"): pytest.approx(FIXTURE_TOTAL_MW)
    }
