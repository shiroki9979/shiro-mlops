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
from dagster import (
    DagsterInstance,
    Definitions,
    ExecuteInProcessResult,
    RetryPolicy,
    build_schedule_context,
    define_asset_job,
)

from shiro_mlops.core.datetime_utils import TAIWAN_TZ
from shiro_mlops.data.hourly_actual_load import HourWindow
from shiro_mlops.data.hourly_actual_load_store import HourlyActualLoadStore
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.pipelines.assets import raw_taipower_load
from shiro_mlops.pipelines.execution_origin import SCHEDULED_TICK_TAG
from shiro_mlops.pipelines.schedules import hourly_actual_load_job, hourly_actual_load_schedule
from tests.helpers import (
    derived_hourly_load,
    derived_load_series,
    regional_supply_demand_snapshots,
    scheduled_run_tags,
    write_derived_load,
)

TICK = datetime(2026, 9, 5, 18, 5, tzinfo=ZoneInfo(TAIWAN_TZ))
# 區域 fixture 四區用電加總 3254.0 萬瓩，即 32540 MW。
FIXTURE_TOTAL_MW = 32540.0
TAIPEI = ZoneInfo(TAIWAN_TZ)
REEXECUTION = {"dagster/parent_run_id": "tick-run", "dagster/root_run_id": "tick-run"}


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

    [request] = evaluation.run_requests
    with patch("httpx.Client", side_effect=AssertionError("external API must not be called")):
        result = job_def.execute_in_process(
            run_config=request.run_config, tags=request.tags, instance=instance
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


def _run(repo, instance: DagsterInstance, tags: dict[str, str]) -> ExecuteInProcessResult:
    """Run the hourly actual-load job in a run tagged ``tags``."""
    job_def = Definitions(
        assets=[raw_taipower_load],
        jobs=[hourly_actual_load_job],
        resources={"time_series_repo": repo},
    ).resolve_job_def("hourly_actual_load_job")
    result = job_def.execute_in_process(tags=tags, instance=instance)
    assert result.success
    return result


def _creation_hour(instance: DagsterInstance, run_id: str) -> datetime:
    """The hour, in Taiwan-local time, at which Dagster created the run."""
    created = instance.get_run_record_by_id(run_id).create_timestamp
    return created.astimezone(TAIPEI).replace(tzinfo=None, minute=0, second=0, microsecond=0)


def _derived_window_end(instance: DagsterInstance, result: ExecuteInProcessResult) -> datetime:
    [message] = _run_log(instance, result, logging.INFO)
    return datetime.fromisoformat(message.split(", ")[1].split(")")[0])


@pytest.mark.parametrize(
    "run_tags",
    [
        pytest.param({}, id="manual"),
        pytest.param({SCHEDULED_TICK_TAG: "2026-09-05T18:05:00"}, id="tick-tag-typed-by-hand"),
        pytest.param(
            {**scheduled_run_tags(hourly_actual_load_schedule, TICK), **REEXECUTION},
            id="re-execution-of-the-tick-run",
        ),
    ],
)
def test_a_run_without_a_scheduled_tick_derives_up_to_the_hour_it_was_created(
    test_repo: TimeSeriesRepository, dagster_instance: DagsterInstance, run_tags: dict[str, str]
) -> None:
    result = _run(test_repo, dagster_instance, run_tags)

    window_end = _derived_window_end(dagster_instance, result)
    assert window_end == _creation_hour(dagster_instance, result.run_id)
    assert window_end != datetime(2026, 9, 5, 18, 0)


def test_re_executing_a_failed_tick_run_derives_the_hours_that_tick_missed(
    test_repo: TimeSeriesRepository, dagster_instance: DagsterInstance
) -> None:
    """The window catches up after the latest derived hour, so the tick's hours stay in it."""
    now_hour = datetime.now(TAIPEI).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    missed_hour = now_hour - timedelta(hours=1)
    tick = (now_hour + timedelta(minutes=5)).replace(tzinfo=TAIPEI)
    write_derived_load(test_repo.engine, derived_hourly_load(1, missed_hour - timedelta(hours=5)))
    _store_samples(test_repo, missed_hour, 6)

    _run(
        test_repo,
        dagster_instance,
        {**scheduled_run_tags(hourly_actual_load_schedule, tick), **REEXECUTION},
    )

    assert _persisted_load(test_repo)[pd.Timestamp(missed_hour)] == pytest.approx(FIXTURE_TOTAL_MW)


class _FirstDerivationFails:
    """The store behind a brief database outage that drops the first derivation's reply."""

    def __init__(self, store: HourlyActualLoadStore) -> None:
        self._store = store
        self.windows: list[HourWindow] = []

    def derive_scheduled(self, evaluated_at, policy):
        derivation = self._store.derive_scheduled(evaluated_at, policy)
        self.windows.append(derivation.window)
        if len(self.windows) == 1:
            raise ConnectionError("database briefly unreachable")
        return derivation


class _Repository:
    def __init__(self, store: _FirstDerivationFails) -> None:
        self.hourly_actual_load_store = store


@pytest.mark.parametrize(
    "scheduled", [pytest.param(True, id="scheduled"), pytest.param(False, id="manual")]
)
def test_a_retry_in_the_same_run_derives_the_same_window(
    test_repo: TimeSeriesRepository, dagster_instance: DagsterInstance, scheduled: bool
) -> None:
    flaky = _FirstDerivationFails(test_repo.hourly_actual_load_store)
    # 正式 job 不設重試；此處只加上立即重試，資產與 run 標籤與排程 run 相同。
    job = Definitions(
        assets=[raw_taipower_load],
        jobs=[
            define_asset_job(
                "hourly_load_retrying_at_once",
                selection=["raw_taipower_load"],
                op_retry_policy=RetryPolicy(max_retries=1),
            )
        ],
        resources={"time_series_repo": _Repository(flaky)},
    ).resolve_job_def("hourly_load_retrying_at_once")
    tags = scheduled_run_tags(hourly_actual_load_schedule, TICK) if scheduled else {}

    result = job.execute_in_process(instance=dagster_instance, tags=tags)

    assert result.success
    first, retried = flaky.windows
    assert retried == first
