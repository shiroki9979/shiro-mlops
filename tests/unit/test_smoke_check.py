"""Offline tests for the container smoke check of schedules and downstream readiness."""

from datetime import datetime

from dagster import (
    AssetMaterialization,
    AssetSelection,
    DagsterInstance,
    Definitions,
    ScheduleDefinition,
    define_asset_job,
)

from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.pipelines.definitions import all_assets, defs
from shiro_mlops.pipelines.smoke_check import (
    EXPECTED_SCHEDULES,
    CheckStatus,
    Deployment,
    check_downstream_readiness,
    check_load_consumer_boundaries,
    check_schedule_configuration,
    exit_code,
    format_report,
    run_smoke_check,
    running_schedule_names,
)
from shiro_mlops.pipelines.task_pipelines import TaskPipelineNames, build_task_pipelines
from shiro_mlops.tasks.deployed import deployed_tasks
from tests.helpers import derived_hourly_load

NOW = datetime(2026, 9, 27, 0, 30)
ALL_SCHEDULES = frozenset(schedule.name for schedule in defs.schedules)


def _statuses(results) -> dict[str, CheckStatus]:
    return {result.name: result.status for result in results}


def test_registered_and_running_schedules_pass() -> None:
    results = check_schedule_configuration(defs, running=ALL_SCHEDULES)

    assert results
    assert {result.status for result in results} == {CheckStatus.PASS}


def test_stopped_schedule_fails_with_instruction() -> None:
    running = ALL_SCHEDULES - {"hourly_actual_load_schedule"}

    results = check_schedule_configuration(defs, running=running)

    failed = [result for result in results if result.status is CheckStatus.FAIL]
    assert [result.name for result in failed] == ["schedule hourly_actual_load_schedule"]
    assert "not running" in failed[0].detail


def test_schedule_cron_drift_and_missing_registration_fail() -> None:
    job = define_asset_job("dynamic_horizon_forecast__training_job", selection=AssetSelection.all())
    drifted = Definitions(
        assets=all_assets,
        jobs=[job],
        schedules=[
            ScheduleDefinition(
                name="dynamic_horizon_forecast__training_schedule",
                job=job,
                cron_schedule="0 16 * * *",
            )
        ],
    )

    statuses = _statuses(check_schedule_configuration(drifted, running=ALL_SCHEDULES))

    assert statuses["schedule dynamic_horizon_forecast__training_schedule"] is CheckStatus.FAIL
    assert statuses["schedule hourly_actual_load_schedule"] is CheckStatus.FAIL


def test_load_consumer_boundaries_pass_for_registered_jobs() -> None:
    results = check_load_consumer_boundaries(defs)

    assert _statuses(results) == {
        f"job {job}": CheckStatus.PASS
        for task_id in deployed_tasks()
        for job in (
            TaskPipelineNames(task_id).training_job,
            TaskPipelineNames(task_id).monitoring_job,
        )
    }


def test_training_job_selecting_snapshot_or_derivation_assets_fails() -> None:
    leaky = Definitions(
        assets=all_assets,
        resources=defs.resources,
        jobs=[
            define_asset_job(
                "dynamic_horizon_forecast__training_job", selection=AssetSelection.all()
            ),
            define_asset_job(
                "dynamic_horizon_forecast__monitoring_job",
                selection=AssetSelection.assets("dynamic_horizon_forecast__features"),
            ),
        ],
    )

    results = {result.name: result for result in check_load_consumer_boundaries(leaky)}

    assert results["job dynamic_horizon_forecast__training_job"].status is CheckStatus.FAIL
    assert (
        "raw_taipower_regional_supply_demand_snapshot"
        in results["job dynamic_horizon_forecast__training_job"].detail
    )
    assert results["job dynamic_horizon_forecast__monitoring_job"].status is CheckStatus.FAIL
    assert (
        "missing dynamic_horizon_forecast__monitoring"
        in results["job dynamic_horizon_forecast__monitoring_job"].detail
    )


def test_cold_start_reports_waiting_readiness_without_failing(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int
) -> None:
    test_repo.upsert_taipower_load(derived_hourly_load(10, datetime(2026, 9, 26, 23, 0)))

    results = check_downstream_readiness(Deployment(defs, test_repo, dagster_instance, NOW))

    statuses = _statuses(results)
    assert statuses == {
        name: status
        for task_id in deployed_tasks()
        for name, status in {
            f"{task_id} load accumulation": CheckStatus.WAIT,
            f"{task_id} load freshness": CheckStatus.PASS,
            f"tick {TaskPipelineNames(task_id).training_schedule}": CheckStatus.WAIT,
            f"tick {TaskPipelineNames(task_id).monitoring_schedule}": CheckStatus.WAIT,
        }.items()
    }
    accumulation = next(
        result for result in results if result.name == "dynamic_horizon_forecast load accumulation"
    )
    assert "10 valid hourly observations; 24 required" in accumulation.detail
    assert exit_code(results, require_ready=False) == 0
    assert exit_code(results, require_ready=True) == 1


def test_recovered_stack_reports_both_ticks_triggering(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int
) -> None:
    test_repo.upsert_taipower_load(derived_hourly_load(min_hours, datetime(2026, 9, 26, 23, 0)))
    for task_id in deployed_tasks():
        dagster_instance.report_runless_asset_event(
            AssetMaterialization(TaskPipelineNames(task_id).model)
        )

    pipelines = build_task_pipelines(deployed_tasks())
    refreshed = Definitions(
        assets=all_assets,
        jobs=[job for pipeline in pipelines for job in pipeline.jobs],
        schedules=[schedule for pipeline in pipelines for schedule in pipeline.schedules],
        resources=defs.resources,
    )
    results = check_downstream_readiness(Deployment(refreshed, test_repo, dagster_instance, NOW))

    assert {result.status for result in results} == {CheckStatus.PASS}, [
        (result.name, result.detail) for result in results if result.status is not CheckStatus.PASS
    ]
    assert exit_code(results, require_ready=True) == 0


def test_stalled_accumulation_fails(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int
) -> None:
    """最新推算小時落後超過任務設定 policies.stale_anchor_max_lag_hours 表示擷取或推算排程停擺。"""
    test_repo.upsert_taipower_load(derived_hourly_load(min_hours, datetime(2026, 9, 26, 20, 0)))

    results = check_downstream_readiness(Deployment(defs, test_repo, dagster_instance, NOW))

    assert _statuses(results)["dynamic_horizon_forecast load freshness"] is CheckStatus.FAIL
    assert exit_code(results, require_ready=False) == 1


def test_unreachable_store_fails_instead_of_raising(dagster_instance) -> None:
    class UnreachableRepository:
        def summarize_hourly_load_accumulation(self, subject: str):
            raise ConnectionError("TimescaleDB unreachable")

    results = check_downstream_readiness(
        Deployment(defs, UnreachableRepository(), dagster_instance, NOW)
    )

    assert {result.status for result in results} == {CheckStatus.FAIL}
    assert "TimescaleDB unreachable" in results[0].detail


def test_fresh_instance_has_no_running_schedules(dagster_instance: DagsterInstance) -> None:
    assert running_schedule_names(dagster_instance) == frozenset()


def test_full_run_on_fresh_deployment_flags_stopped_schedules_and_waiting_readiness(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int
) -> None:
    results = run_smoke_check(Deployment(defs, test_repo, dagster_instance, NOW))

    report = format_report(results)

    assert "[FAIL] schedule dynamic_horizon_forecast__training_schedule" in report
    assert "[PASS] job dynamic_horizon_forecast__training_job" in report
    assert "[WAIT] dynamic_horizon_forecast load accumulation" in report
    # 每個任務：兩個 job 通過、累積／新鮮度／兩個 tick 等待、兩個排程未啟動。
    tasks = len(deployed_tasks())
    failed = len(EXPECTED_SCHEDULES) + 2 * tasks
    assert report.splitlines()[-1] == f"Summary: {2 * tasks} pass, {4 * tasks} wait, {failed} fail"
    assert exit_code(results, require_ready=False) == 1
