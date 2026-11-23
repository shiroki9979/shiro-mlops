"""Offline tests for the container smoke check of schedules and downstream readiness."""

import gc
from datetime import datetime
from pathlib import Path

import pytest
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
    FORECAST_TRACK_RECORD_SCHEDULES,
    FORECAST_VIEW_EXPORT_SCHEDULES,
    ISSUED_FORECAST_SCHEDULES,
    CheckStatus,
    Deployment,
    check_downstream_readiness,
    check_load_consumer_boundaries,
    check_schedule_configuration,
    exit_code,
    format_report,
    main,
    run_smoke_check,
    running_schedule_names,
)
from shiro_mlops.pipelines.task_pipelines import TaskPipelineNames, build_task_pipelines
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task, deployed_tasks
from tests.conftest import TEST_MIN_LOAD_HOURS
from tests.helpers import (
    derived_hourly_load,
    hand_copied_model_double,
    install_model_double,
    override_task_policies,
    write_derived_load,
)

# 監控與發布排程的 tick 讀 DATA_DIR 下的模型目錄；隔離後主機上的 data/models 不會影響判定。
pytestmark = pytest.mark.usefixtures("isolated_models_dir")

NOW = datetime(2026, 9, 27, 0, 30)
ISSUED_SCHEDULE = "issued_forecast_schedule"
# 全新部署上發布排程停用（WAIT）且 tick 因尚無模型略過（WAIT）。
ISSUED_WAITS = 2
TRACK_RECORD_SCHEDULE = "forecast_track_record_schedule"
EXPORT_SCHEDULE = "forecast_view_export_schedule"
# 擷取、預報實績與匯出排程停用時皆為 FAIL；冷啟動時一起開啟。
ALWAYS_ON_SCHEDULES = (
    len(EXPECTED_SCHEDULES)
    + len(FORECAST_TRACK_RECORD_SCHEDULES)
    + len(FORECAST_VIEW_EXPORT_SCHEDULES)
)
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
    write_derived_load(test_repo.engine, derived_hourly_load(10, datetime(2026, 9, 26, 23, 0)))

    results = check_downstream_readiness(Deployment(defs, test_repo, dagster_instance, NOW))

    statuses = _statuses(results)
    assert statuses == {
        name: status
        for task_id in deployed_tasks()
        for name, status in {
            f"{task_id} load accumulation": CheckStatus.WAIT,
            f"{task_id} load freshness": CheckStatus.PASS,
            f"{task_id} model": CheckStatus.WAIT,
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
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int, isolated_models_dir: Path
) -> None:
    write_derived_load(
        test_repo.engine, derived_hourly_load(min_hours, datetime(2026, 9, 26, 23, 0))
    )
    for task_id in deployed_tasks():
        install_model_double(isolated_models_dir, task_id)
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
    """A derived-load anchor older than the configured lag signals stalled ingestion or derivation."""
    write_derived_load(
        test_repo.engine, derived_hourly_load(min_hours, datetime(2026, 9, 26, 20, 0))
    )

    results = check_downstream_readiness(Deployment(defs, test_repo, dagster_instance, NOW))

    assert _statuses(results)["dynamic_horizon_forecast load freshness"] is CheckStatus.FAIL
    assert exit_code(results, require_ready=False) == 1


def test_unreachable_store_fails_instead_of_raising(dagster_instance) -> None:
    class UnreachableStore:
        def accumulation(self, at_or_before=None, *, subject: str):
            raise ConnectionError("TimescaleDB unreachable")

    class UnreachableRepository:
        hourly_actual_load_store = UnreachableStore()

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
    assert f"[WAIT] schedule {ISSUED_SCHEDULE}" in report
    assert f"[FAIL] schedule {TRACK_RECORD_SCHEDULE}" in report
    assert f"[FAIL] schedule {EXPORT_SCHEDULE}" in report
    # 每個任務：兩個 job 通過、累積／模型／兩個 tick 等待、新鮮度通過、兩個排程未啟動；
    # 發布排程停用與其 tick 各等待一項；擷取、預報實績與匯出排程未啟動。
    tasks = len(deployed_tasks())
    failed = ALWAYS_ON_SCHEDULES + 2 * tasks
    waiting = 5 * tasks + ISSUED_WAITS
    assert report.splitlines()[-1] == f"Summary: {2 * tasks} pass, {waiting} wait, {failed} fail"
    assert exit_code(results, require_ready=False) == 1


def _scoped_definitions() -> Definitions:
    pipelines = build_task_pipelines(deployed_tasks())
    return Definitions(
        assets=all_assets,
        jobs=[job for pipeline in pipelines for job in pipeline.jobs],
        schedules=[schedule for pipeline in pipelines for schedule in pipeline.schedules],
        resources=defs.resources,
    )


def test_task_scope_is_ready_while_another_task_still_accumulates(
    test_repo: TimeSeriesRepository,
    dagster_instance,
    monkeypatch: pytest.MonkeyPatch,
    isolated_models_dir: Path,
) -> None:
    """M6 acceptance: one task ready must not be blocked by another task's higher threshold."""
    override_task_policies(
        monkeypatch, DYNAMIC_HORIZON_FORECAST, min_training_hours=TEST_MIN_LOAD_HOURS
    )
    write_derived_load(
        test_repo.engine, derived_hourly_load(TEST_MIN_LOAD_HOURS, datetime(2026, 9, 26, 23, 0))
    )
    install_model_double(isolated_models_dir)
    dagster_instance.report_runless_asset_event(
        AssetMaterialization(TaskPipelineNames(DYNAMIC_HORIZON_FORECAST).model)
    )
    deployment = Deployment(_scoped_definitions(), test_repo, dagster_instance, NOW)
    scope = {DYNAMIC_HORIZON_FORECAST: deployed_task(DYNAMIC_HORIZON_FORECAST)}

    scoped = check_downstream_readiness(deployment, scope)
    everything = check_downstream_readiness(deployment)

    assert {result.status for result in scoped} == {CheckStatus.PASS}
    assert exit_code(scoped, require_ready=True) == 0
    assert exit_code(everything, require_ready=True) == 1


def test_task_scope_keeps_ingestion_schedules_and_drops_other_tasks() -> None:
    other_tasks = set(deployed_tasks()) - {DYNAMIC_HORIZON_FORECAST}
    scope = {DYNAMIC_HORIZON_FORECAST: deployed_task(DYNAMIC_HORIZON_FORECAST)}
    names = TaskPipelineNames(DYNAMIC_HORIZON_FORECAST)

    schedules = check_schedule_configuration(defs, running=ALL_SCHEDULES, tasks=scope)
    jobs = check_load_consumer_boundaries(defs, tasks=scope)

    assert [result.name for result in schedules] == [
        *(f"schedule {name}" for name in EXPECTED_SCHEDULES),
        *(f"schedule {name}" for name in ISSUED_FORECAST_SCHEDULES),
        *(f"schedule {name}" for name in FORECAST_TRACK_RECORD_SCHEDULES),
        *(f"schedule {name}" for name in FORECAST_VIEW_EXPORT_SCHEDULES),
        f"schedule {names.training_schedule}",
        f"schedule {names.monitoring_schedule}",
    ]
    assert [result.name for result in jobs] == [
        f"job {names.training_job}",
        f"job {names.monitoring_job}",
    ]
    assert other_tasks, "scope test needs more than one deployed task"


def test_full_run_scoped_to_one_task_reports_only_that_task(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int
) -> None:
    results = run_smoke_check(
        Deployment(defs, test_repo, dagster_instance, NOW), task_id=DYNAMIC_HORIZON_FORECAST
    )

    report = format_report(results)
    for task_id in set(deployed_tasks()) - {DYNAMIC_HORIZON_FORECAST}:
        assert task_id not in report
    assert f"schedule {ISSUED_SCHEDULE}" in report
    assert f"[FAIL] schedule {TRACK_RECORD_SCHEDULE}" in report
    assert f"[FAIL] schedule {EXPORT_SCHEDULE}" in report
    failed = ALWAYS_ON_SCHEDULES + 2
    assert report.splitlines()[-1] == f"Summary: 2 pass, {5 + ISSUED_WAITS} wait, {failed} fail"


def test_unknown_task_is_a_usage_error_listing_deployed_tasks(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exited:
        main(["--task", "no_such_task"])

    assert exited.value.code == 2
    error = capsys.readouterr().err
    for task_id in deployed_tasks():
        assert task_id in error


def test_stopped_issued_forecast_schedule_waits_until_turned_on_after_first_training() -> None:
    """冷啟動期間發布排程刻意停用：回報 WAIT 並說明何時開啟，只在 --require-ready 時擋下。"""
    results = check_schedule_configuration(defs, running=ALL_SCHEDULES - {ISSUED_SCHEDULE})

    not_passing = [result for result in results if result.status is not CheckStatus.PASS]
    assert [(result.name, result.status) for result in not_passing] == [
        (f"schedule {ISSUED_SCHEDULE}", CheckStatus.WAIT)
    ]
    assert "not running" in not_passing[0].detail
    assert "first successful training" in not_passing[0].detail
    assert exit_code(results, require_ready=False) == 0
    assert exit_code(results, require_ready=True) == 1


def test_unregistered_or_drifted_issued_forecast_schedule_fails() -> None:
    issued_job = defs.resolve_job_def("issued_forecast_job")
    drifted = Definitions(
        assets=all_assets,
        jobs=[issued_job],
        schedules=[
            ScheduleDefinition(
                name=ISSUED_SCHEDULE,
                job=issued_job,
                cron_schedule="0 * * * *",
                execution_timezone="Asia/Taipei",
            )
        ],
    )

    unregistered = check_schedule_configuration(_scoped_definitions(), running=ALL_SCHEDULES)
    drift = check_schedule_configuration(drifted, running=ALL_SCHEDULES)

    missing = next(r for r in unregistered if r.name == f"schedule {ISSUED_SCHEDULE}")
    assert missing.status is CheckStatus.FAIL
    assert missing.detail == "not registered in Definitions"
    cron = next(r for r in drift if r.name == f"schedule {ISSUED_SCHEDULE}")
    assert cron.status is CheckStatus.FAIL
    assert "'15 * * * *'" in cron.detail and "'0 * * * *'" in cron.detail


def _issued_tick(results):
    return next(result for result in results if result.name == f"tick {ISSUED_SCHEDULE}")


def test_issued_forecast_tick_waits_for_the_first_model_without_launching_a_run(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int
) -> None:
    results = run_smoke_check(Deployment(defs, test_repo, dagster_instance, NOW))

    tick = _issued_tick(results)
    assert tick.status is CheckStatus.WAIT
    assert "would skip" in tick.detail
    assert "dynamic_horizon_forecast__model" in tick.detail
    assert dagster_instance.get_runs() == []


def test_issued_forecast_tick_would_issue_once_a_model_exists_without_launching_a_run(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int, isolated_models_dir: Path
) -> None:
    install_model_double(isolated_models_dir)
    dagster_instance.report_runless_asset_event(
        AssetMaterialization(TaskPipelineNames(DYNAMIC_HORIZON_FORECAST).model)
    )

    results = run_smoke_check(
        Deployment(defs, test_repo, dagster_instance, NOW), task_id=DYNAMIC_HORIZON_FORECAST
    )

    tick = _issued_tick(results)
    assert (tick.status, tick.detail) == (CheckStatus.PASS, "would request a run")
    assert dagster_instance.get_runs() == []


def _track_record_schedule(results):
    return next(r for r in results if r.name == f"schedule {TRACK_RECORD_SCHEDULE}")


def test_stopped_track_record_schedule_fails_because_it_needs_no_model() -> None:
    """不比照發布排程的 WAIT：彙整不依賴模型，冷啟動時就與擷取排程一起開啟。"""
    results = check_schedule_configuration(defs, running=ALL_SCHEDULES - {TRACK_RECORD_SCHEDULE})

    stopped = _track_record_schedule(results)
    assert stopped.status is CheckStatus.FAIL
    assert "not running" in stopped.detail
    assert exit_code(results, require_ready=False) == 1


def test_unregistered_or_drifted_track_record_schedule_fails() -> None:
    track_record_job = defs.resolve_job_def("forecast_track_record_job")
    drifted = Definitions(
        assets=all_assets,
        jobs=[track_record_job],
        schedules=[
            ScheduleDefinition(
                name=TRACK_RECORD_SCHEDULE,
                job=track_record_job,
                cron_schedule="15 * * * *",
                execution_timezone="Asia/Taipei",
            )
        ],
    )

    missing = _track_record_schedule(
        check_schedule_configuration(_scoped_definitions(), running=ALL_SCHEDULES)
    )
    cron = _track_record_schedule(check_schedule_configuration(drifted, running=ALL_SCHEDULES))

    assert (missing.status, missing.detail) == (CheckStatus.FAIL, "not registered in Definitions")
    assert cron.status is CheckStatus.FAIL
    assert "'25 * * * *'" in cron.detail and "'15 * * * *'" in cron.detail


def test_track_record_schedule_check_survives_task_scope_without_launching_a_run(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int
) -> None:
    results = run_smoke_check(
        Deployment(defs, test_repo, dagster_instance, NOW), task_id=DYNAMIC_HORIZON_FORECAST
    )

    assert _track_record_schedule(results).status is CheckStatus.FAIL
    assert dagster_instance.get_runs() == []


def _export_schedule(results):
    return next(r for r in results if r.name == f"schedule {EXPORT_SCHEDULE}")


def test_stopped_export_schedule_fails_because_it_needs_no_model() -> None:
    """匯出不依賴模型，尚無已發布預報時照常輸出空狀態，因此比照預報實績排程。"""
    results = check_schedule_configuration(defs, running=ALL_SCHEDULES - {EXPORT_SCHEDULE})

    stopped = _export_schedule(results)
    assert stopped.status is CheckStatus.FAIL
    assert "not running" in stopped.detail


def test_unregistered_or_drifted_export_schedule_fails() -> None:
    export_job = defs.resolve_job_def("forecast_view_export_job")
    drifted = Definitions(
        assets=all_assets,
        jobs=[export_job],
        schedules=[
            ScheduleDefinition(
                name=EXPORT_SCHEDULE,
                job=export_job,
                cron_schedule="25 * * * *",
                execution_timezone="Asia/Taipei",
            )
        ],
    )

    missing = _export_schedule(
        check_schedule_configuration(_scoped_definitions(), running=ALL_SCHEDULES)
    )
    cron = _export_schedule(check_schedule_configuration(drifted, running=ALL_SCHEDULES))

    assert (missing.status, missing.detail) == (CheckStatus.FAIL, "not registered in Definitions")
    assert cron.status is CheckStatus.FAIL
    assert "'35 * * * *'" in cron.detail and "'25 * * * *'" in cron.detail


def _model_line(results, task_id: str = DYNAMIC_HORIZON_FORECAST):
    return next(result for result in results if result.name == f"{task_id} model")


def _ready_deployment(test_repo: TimeSeriesRepository, dagster_instance) -> Deployment:
    write_derived_load(
        test_repo.engine, derived_hourly_load(TEST_MIN_LOAD_HOURS, datetime(2026, 9, 26, 23, 0))
    )
    return Deployment(_scoped_definitions(), test_repo, dagster_instance, NOW)


def test_record_without_model_directory_fails_without_require_ready(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int
) -> None:
    """Instance kept but data/models removed: the model line names the missing directory."""
    deployment = _ready_deployment(test_repo, dagster_instance)
    dagster_instance.report_runless_asset_event(
        AssetMaterialization(TaskPipelineNames(DYNAMIC_HORIZON_FORECAST).model)
    )
    scope = {DYNAMIC_HORIZON_FORECAST: deployed_task(DYNAMIC_HORIZON_FORECAST)}

    results = check_downstream_readiness(deployment, scope)

    model = _model_line(results)
    assert model.status is CheckStatus.FAIL
    assert "model directory" in model.detail
    assert "holds no model" in model.detail
    assert "Run dynamic_horizon_forecast__training_job once" in model.detail
    assert exit_code(results, require_ready=False) == 1


def test_model_directory_without_record_fails_and_keeps_load_lines_unchanged(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int, isolated_models_dir: Path
) -> None:
    """dagster_home volume removed but data/models kept: the model line names the missing record."""
    deployment = _ready_deployment(test_repo, dagster_instance)
    scope = {DYNAMIC_HORIZON_FORECAST: deployed_task(DYNAMIC_HORIZON_FORECAST)}
    before = {result.name: result for result in check_downstream_readiness(deployment, scope)}
    install_model_double(isolated_models_dir)

    results = {result.name: result for result in check_downstream_readiness(deployment, scope)}

    model = results["dynamic_horizon_forecast model"]
    assert model.status is CheckStatus.FAIL
    assert "training record has no dynamic_horizon_forecast__model materialization" in model.detail
    assert "Run dynamic_horizon_forecast__training_job once" in model.detail
    for line in (
        "dynamic_horizon_forecast load accumulation",
        "dynamic_horizon_forecast load freshness",
    ):
        assert results[line] == before[line]
    assert exit_code(results.values(), require_ready=False) == 1


def test_hand_copied_model_directory_with_record_fails(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int, isolated_models_dir: Path
) -> None:
    """A directory the model store did not install counts as no model, as loading it would fail."""
    deployment = _ready_deployment(test_repo, dagster_instance)
    hand_copied_model_double(isolated_models_dir)
    dagster_instance.report_runless_asset_event(
        AssetMaterialization(TaskPipelineNames(DYNAMIC_HORIZON_FORECAST).model)
    )
    scope = {DYNAMIC_HORIZON_FORECAST: deployed_task(DYNAMIC_HORIZON_FORECAST)}

    model = _model_line(check_downstream_readiness(deployment, scope))

    assert model.status is CheckStatus.FAIL
    assert "holds no model installed by the model store" in model.detail


def test_trained_task_model_line_passes_and_waits_before_first_training(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int, isolated_models_dir: Path
) -> None:
    deployment = _ready_deployment(test_repo, dagster_instance)
    scope = {DYNAMIC_HORIZON_FORECAST: deployed_task(DYNAMIC_HORIZON_FORECAST)}

    untrained = _model_line(check_downstream_readiness(deployment, scope))
    install_model_double(isolated_models_dir)
    dagster_instance.report_runless_asset_event(
        AssetMaterialization(TaskPipelineNames(DYNAMIC_HORIZON_FORECAST).model)
    )
    trained = _model_line(check_downstream_readiness(deployment, scope))

    assert untrained.status is CheckStatus.WAIT
    assert untrained.detail.startswith("AWAITING_FIRST_TRAINING: ")
    assert "dynamic_horizon_forecast__training_job" in untrained.detail
    assert trained.status is CheckStatus.PASS
    assert trained.detail.startswith("TRAINED: ")


def test_task_scope_reports_only_the_scoped_task_model_line(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int, isolated_models_dir: Path
) -> None:
    other_tasks = set(deployed_tasks()) - {DYNAMIC_HORIZON_FORECAST}
    for task_id in other_tasks:
        install_model_double(isolated_models_dir, task_id)

    results = run_smoke_check(
        Deployment(defs, test_repo, dagster_instance, NOW), task_id=DYNAMIC_HORIZON_FORECAST
    )

    assert [result.name for result in results if result.name.endswith(" model")] == [
        "dynamic_horizon_forecast model"
    ]
    assert other_tasks


def test_unreadable_model_directory_fails_the_model_line_only(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int, isolated_models_dir: Path
) -> None:
    deployment = _ready_deployment(test_repo, dagster_instance)
    # 自我指向的 symlink 讓開啟模型鎖檔失敗（ELOOP），以 root 執行時權限位元擋不住讀取。
    lock = isolated_models_dir / f".{DYNAMIC_HORIZON_FORECAST}.lock"
    isolated_models_dir.mkdir(parents=True)
    lock.symlink_to(lock)
    scope = {DYNAMIC_HORIZON_FORECAST: deployed_task(DYNAMIC_HORIZON_FORECAST)}

    results = {result.name: result for result in check_downstream_readiness(deployment, scope)}

    model = results["dynamic_horizon_forecast model"]
    assert model.status is CheckStatus.FAIL
    assert "Cannot read the training record or model directory" in model.detail
    assert results["dynamic_horizon_forecast load accumulation"].status is CheckStatus.PASS
    assert results["dynamic_horizon_forecast load freshness"].status is CheckStatus.PASS
    assert len(results) == 5


def test_failing_tick_closes_the_instance_it_opened(
    test_repo: TimeSeriesRepository,
    min_hours: int,
    isolated_models_dir: Path,
    tmp_path: Path,
) -> None:
    """A tick that raises must not leave a closed instance current for later Definitions loads."""
    lock = isolated_models_dir / f".{DYNAMIC_HORIZON_FORECAST}.lock"
    isolated_models_dir.mkdir(parents=True)
    lock.symlink_to(lock)
    scope = {DYNAMIC_HORIZON_FORECAST: deployed_task(DYNAMIC_HORIZON_FORECAST)}
    (tmp_path / "instance").mkdir()
    with DagsterInstance.local_temp(tempdir=str(tmp_path / "instance")) as instance:
        deployment = _ready_deployment(test_repo, instance)
        ticks = [
            result
            for result in check_downstream_readiness(deployment, scope)
            if result.name.startswith("tick ")
        ]
        assert CheckStatus.FAIL in {result.status for result in ticks}
    # 釋放對已關閉 instance 的參照，殘留的 weakref 才會像下一個測試那樣失效。
    del instance, deployment
    gc.collect()

    assert _scoped_definitions().resolve_asset_graph() is not None
