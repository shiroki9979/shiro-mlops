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
    """Write four-region snapshots every ten minutes, varying fixture source times to model updates."""
    for index in range(count):
        slot = start + timedelta(minutes=10 * index)
        snapshots = [
            replace(snapshot, source_time=slot)
            for snapshot in regional_supply_demand_snapshots(slot)
        ]
        repo.upsert_regional_supply_demand_snapshots(snapshots)


def _run_scheduled_tick(repo: TimeSeriesRepository, tick: datetime = TICK):
    evaluation = hourly_actual_load_schedule.evaluate_tick(
        build_schedule_context(scheduled_execution_time=tick)
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
    loads = repo.fetch_load_range(subject="nationwide")
    return dict(zip(loads["time"], loads["load_mw"], strict=True))


def test_job_derives_completed_hours_idempotently(
    test_repo: TimeSeriesRepository,
) -> None:
    _store_samples(test_repo, datetime(2026, 9, 5, 14, 0), 6)  # 尚無推算紀錄，由補算窗口涵蓋
    _store_samples(test_repo, datetime(2026, 9, 5, 15, 0), 6)
    _store_samples(test_repo, datetime(2026, 9, 5, 16, 0), 4)
    _store_samples(test_repo, datetime(2026, 9, 5, 17, 0), 3)  # 低於門檻
    _store_samples(test_repo, datetime(2026, 9, 5, 18, 0), 1)  # 尚未結束

    _run_scheduled_tick(test_repo)
    first = _persisted_load(test_repo)
    _run_scheduled_tick(test_repo)

    assert first == {
        pd.Timestamp("2026-09-05 14:00:00"): pytest.approx(FIXTURE_TOTAL_MW),
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


def test_resumed_job_derives_boundary_hour_left_by_an_outage(
    test_repo: TimeSeriesRepository,
) -> None:
    """An hour stored just before an outage is derived once the schedule resumes (#113)."""
    _store_samples(test_repo, datetime(2026, 9, 5, 10, 0), 6)
    _run_scheduled_tick(test_repo, tick=TICK.replace(hour=11))
    _store_samples(test_repo, datetime(2026, 9, 5, 11, 0), 6)  # 中斷前最後一個完整小時
    _store_samples(test_repo, datetime(2026, 9, 5, 17, 0), 6)  # 排程恢復後的小時

    _run_scheduled_tick(test_repo)

    assert _persisted_load(test_repo) == {
        pd.Timestamp("2026-09-05 10:00:00"): pytest.approx(FIXTURE_TOTAL_MW),
        pd.Timestamp("2026-09-05 11:00:00"): pytest.approx(FIXTURE_TOTAL_MW),
        pd.Timestamp("2026-09-05 17:00:00"): pytest.approx(FIXTURE_TOTAL_MW),
    }


def test_job_ignores_derived_hours_newer_than_its_tick(test_repo: TimeSeriesRepository) -> None:
    """A re-run of an old tick anchors on what was derived by then, not on later rows."""
    _store_samples(test_repo, datetime(2026, 9, 5, 11, 0), 6)
    _store_samples(test_repo, datetime(2026, 9, 5, 17, 0), 6)
    _run_scheduled_tick(test_repo)

    _store_samples(test_repo, datetime(2026, 9, 5, 12, 0), 6)
    _run_scheduled_tick(test_repo, tick=TICK.replace(hour=16))

    assert pd.Timestamp("2026-09-05 12:00:00") in _persisted_load(test_repo)
