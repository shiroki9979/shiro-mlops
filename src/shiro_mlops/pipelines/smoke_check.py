"""Container smoke check: schedule configuration and training/drift readiness.

Run inside the Dagster container so the loaded code, DAGSTER_HOME instance, and
TimescaleDB connection are the deployed ones::

    python -m shiro_mlops.pipelines.smoke_check [--require-ready]

Exit status is 1 when any check fails, or when ``--require-ready`` is given and a
check is still waiting (for example during the cold-start accumulation).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from dagster import DagsterInstance, Definitions, ScheduleDefinition, build_schedule_context

# Dagster 未公開排程狀態型別；僅此處依賴內部路徑，升級時由離線測試揭露破壞。
from dagster._core.scheduler.instigation import InstigatorType

from shiro_mlops.core.config import settings
from shiro_mlops.core.datetime_utils import TAIWAN_TZ
from shiro_mlops.data.hourly_actual_load import is_stale_load_anchor
from shiro_mlops.pipelines.readiness import LoadAccumulationSource, check_training_load_readiness
from shiro_mlops.pipelines.schedules import (
    CWA_INGESTION_ASSETS,
    DRIFT_REPORT_ASSET,
    HOURLY_ACTUAL_LOAD_ASSET,
    LOAD_FEATURE_SOURCE_ASSET,
    TAIPOWER_REALTIME_SNAPSHOT_ASSETS,
)

# 各 job 經由哪個資產讀取 raw_taipower_load 資料表。
LOAD_CONSUMER_JOBS = {
    "daily_training_job": LOAD_FEATURE_SOURCE_ASSET,
    "hourly_drift_job": DRIFT_REPORT_ASSET,
}
READINESS_SCHEDULES = ("daily_training_schedule", "hourly_drift_schedule")
# 訓練與 drift 只能讀 raw_taipower_load 資料表；執行下列資產即代表會讀快照表或呼叫外部 API。
FORBIDDEN_IN_LOAD_CONSUMERS = frozenset(
    (*TAIPOWER_REALTIME_SNAPSHOT_ASSETS, *CWA_INGESTION_ASSETS, HOURLY_ACTUAL_LOAD_ASSET)
)


@dataclass(frozen=True)
class ExpectedSchedule:
    """Deployed schedule contract from docs/SPEC.md §3."""

    job_name: str
    cron_schedule: str
    execution_timezone: str | None


EXPECTED_SCHEDULES: dict[str, ExpectedSchedule] = {
    "taipower_supply_demand_snapshot_schedule": ExpectedSchedule(
        "taipower_supply_demand_snapshot_job", "*/10 * * * *", TAIWAN_TZ
    ),
    "hourly_actual_load_schedule": ExpectedSchedule(
        "hourly_actual_load_job", "5 * * * *", TAIWAN_TZ
    ),
    "cwa_observation_ingestion_job_schedule": ExpectedSchedule(
        "cwa_observation_ingestion_job", "10 * * * *", TAIWAN_TZ
    ),
    "cwa_forecast_ingestion_job_schedule": ExpectedSchedule(
        "cwa_forecast_ingestion_job", "40 * * * *", TAIWAN_TZ
    ),
    # 16:00 UTC 即台灣時間 00:00。
    "daily_training_schedule": ExpectedSchedule("daily_training_job", "0 16 * * *", None),
    "hourly_drift_schedule": ExpectedSchedule("hourly_drift_job", "0 * * * *", None),
}


class CheckStatus(StrEnum):
    PASS = "PASS"
    WAIT = "WAIT"
    FAIL = "FAIL"


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    detail: str


@dataclass(frozen=True)
class Deployment:
    """One deployment under check: its code, Dagster instance, and load store at ``now``."""

    defs: Definitions
    repository: LoadAccumulationSource
    instance: DagsterInstance
    now: datetime


def run_smoke_check(deployment: Deployment) -> list[CheckResult]:
    """Run every check against one deployment: code, Dagster instance, and store."""
    return [
        *check_schedule_configuration(deployment.defs, running_schedule_names(deployment.instance)),
        *check_load_consumer_boundaries(deployment.defs),
        *check_downstream_readiness(deployment),
    ]


def check_schedule_configuration(defs: Definitions, running: frozenset[str]) -> list[CheckResult]:
    """Each SPEC schedule is registered with its job, cron, and timezone, and is running."""
    registered = {schedule.name: schedule for schedule in defs.schedules or ()}
    return [
        _check_schedule(name, expected, registered.get(name), running)
        for name, expected in EXPECTED_SCHEDULES.items()
    ]


def check_load_consumer_boundaries(defs: Definitions) -> list[CheckResult]:
    """Training and drift jobs read persisted load only, never snapshots or external APIs."""
    return [
        _check_load_consumer(defs, job_name, load_reader)
        for job_name, load_reader in LOAD_CONSUMER_JOBS.items()
    ]


def check_downstream_readiness(deployment: Deployment) -> list[CheckResult]:
    """Report load accumulation, its freshness, and what the next training/drift ticks do."""
    try:
        readiness = check_training_load_readiness(
            deployment.repository, settings.TRAINING_MIN_LOAD_HOURS
        )
    except Exception as error:  # 以失敗檢查回報原因，不中斷其餘檢查
        detail = f"Cannot read raw_taipower_load: {_summarize(error)}"
        return [
            CheckResult(name, CheckStatus.FAIL, detail)
            for name in ("load accumulation", "load freshness", *_tick_check_names())
        ]
    return [
        CheckResult(
            "load accumulation",
            CheckStatus.PASS if readiness.ready else CheckStatus.WAIT,
            readiness.reason,
        ),
        _check_load_freshness(readiness.latest_hour, deployment.now),
        *(_check_tick(deployment, name) for name in READINESS_SCHEDULES),
    ]


def running_schedule_names(instance: DagsterInstance) -> frozenset[str]:
    """Names of schedules the instance's daemon will tick."""
    states = instance.all_instigator_state(instigator_type=InstigatorType.SCHEDULE)
    return frozenset(state.name for state in states if state.is_running)


def exit_code(results: Iterable[CheckResult], require_ready: bool) -> int:
    statuses = {result.status for result in results}
    if CheckStatus.FAIL in statuses:
        return 1
    if require_ready and CheckStatus.WAIT in statuses:
        return 1
    return 0


def format_report(results: Iterable[CheckResult]) -> str:
    results = list(results)
    lines = [f"[{result.status}] {result.name}: {result.detail}" for result in results]
    counts = {status: sum(r.status is status for r in results) for status in CheckStatus}
    lines.append(
        f"Summary: {counts[CheckStatus.PASS]} pass, {counts[CheckStatus.WAIT]} wait, "
        f"{counts[CheckStatus.FAIL]} fail"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Also fail while training or drift readiness is still waiting.",
    )
    args = parser.parse_args(argv)

    from shiro_mlops.data.repository import TimeSeriesRepository
    from shiro_mlops.pipelines.definitions import defs

    now = datetime.now(tz=ZoneInfo(TAIWAN_TZ)).replace(tzinfo=None)
    with DagsterInstance.get() as instance:
        deployment = Deployment(defs, TimeSeriesRepository(auto_init=False), instance, now)
        results = run_smoke_check(deployment)
    print(format_report(results))
    return exit_code(results, require_ready=args.require_ready)


def _check_schedule(
    name: str,
    expected: ExpectedSchedule,
    schedule: ScheduleDefinition | None,
    running: frozenset[str],
) -> CheckResult:
    check_name = f"schedule {name}"
    if schedule is None:
        return CheckResult(check_name, CheckStatus.FAIL, "not registered in Definitions")
    actual = ExpectedSchedule(
        schedule.job_name, schedule.cron_schedule, schedule.execution_timezone
    )
    if actual != expected:
        return CheckResult(check_name, CheckStatus.FAIL, f"expected {expected}, found {actual}")
    timezone = expected.execution_timezone or "UTC"
    summary = f"{expected.job_name} at '{expected.cron_schedule}' ({timezone})"
    if name not in running:
        return CheckResult(
            check_name,
            CheckStatus.FAIL,
            f"{summary} is registered but not running; turn it on in the Dagster UI",
        )
    return CheckResult(check_name, CheckStatus.PASS, f"{summary}, running")


def _check_load_consumer(defs: Definitions, job_name: str, load_reader: str) -> CheckResult:
    check_name = f"job {job_name}"
    try:
        job = defs.resolve_job_def(job_name)
    except Exception as error:  # 以失敗檢查回報原因，不中斷其餘檢查
        return CheckResult(check_name, CheckStatus.FAIL, f"cannot resolve job: {_summarize(error)}")
    selected = {key.to_user_string() for key in job.asset_layer.executable_asset_keys}
    problems = []
    if load_reader not in selected:
        problems.append(f"missing {load_reader}")
    leaked = sorted(selected & FORBIDDEN_IN_LOAD_CONSUMERS)
    if leaked:
        problems.append(f"must not execute {', '.join(leaked)}")
    if problems:
        return CheckResult(check_name, CheckStatus.FAIL, "; ".join(problems))
    return CheckResult(check_name, CheckStatus.PASS, f"reads raw_taipower_load via {load_reader}")


def _check_load_freshness(latest_hour: datetime | None, now: datetime) -> CheckResult:
    """A stale newest hour means snapshot capture or hourly derivation stopped accumulating."""
    if latest_hour is None:
        return CheckResult(
            "load freshness", CheckStatus.WAIT, "no derived hourly actual load persisted yet"
        )
    max_lag = timedelta(hours=settings.LOAD_ANCHOR_MAX_LAG_HOURS)
    lag = now - latest_hour
    detail = f"latest derived hour {latest_hour.isoformat()} lags {now.isoformat()} by {lag}"
    if is_stale_load_anchor(latest_hour, now, settings.LOAD_ANCHOR_MAX_LAG_HOURS):
        return CheckResult(
            "load freshness",
            CheckStatus.FAIL,
            f"{detail} (> {max_lag}); accumulation has stalled",
        )
    return CheckResult("load freshness", CheckStatus.PASS, detail)


def _check_tick(deployment: Deployment, schedule_name: str) -> CheckResult:
    """Evaluate the deployed schedule function exactly as the daemon would at ``now``."""
    check_name = f"tick {schedule_name}"
    context = build_schedule_context(
        instance=deployment.instance,
        scheduled_execution_time=deployment.now.replace(tzinfo=ZoneInfo(TAIWAN_TZ)),
        resources={"time_series_repo": deployment.repository},
    )
    try:
        execution = deployment.defs.resolve_schedule_def(schedule_name).evaluate_tick(context)
    except Exception as error:  # 以失敗檢查回報原因，不中斷其餘檢查
        return CheckResult(
            check_name, CheckStatus.FAIL, f"tick evaluation failed: {_summarize(error)}"
        )
    if execution.run_requests:
        return CheckResult(check_name, CheckStatus.PASS, "would request a run")
    return CheckResult(check_name, CheckStatus.WAIT, f"would skip: {execution.skip_message}")


def _summarize(error: Exception) -> str:
    """Keep one report line per check; driver errors append multi-line hints."""
    lines = str(error).strip().splitlines()
    return f"{type(error).__name__}: {lines[0] if lines else ''}"


def _tick_check_names() -> tuple[str, ...]:
    return tuple(f"tick {name}" for name in READINESS_SCHEDULES)


if __name__ == "__main__":
    sys.exit(main())
