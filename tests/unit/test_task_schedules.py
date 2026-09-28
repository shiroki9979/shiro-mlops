"""Contract tests for generated task schedules: readiness from the task definition's policies."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from dagster import AssetMaterialization, Definitions, build_schedule_context

from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.pipelines.definitions import defs
from shiro_mlops.pipelines.schedules import CWA_INGESTION_ASSETS, TAIPOWER_REALTIME_SNAPSHOT_ASSETS
from shiro_mlops.pipelines.task_pipelines import TaskPipelineNames, build_task_pipeline
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_tasks
from tests.helpers import derived_hourly_load, selected_asset_names, task_jobs

TICK = datetime(2026, 9, 27, 0, 0, tzinfo=ZoneInfo("Asia/Taipei"))
LAST_HOUR = datetime(2026, 9, 26, 23, 0)
# 由區域快照推算的資產；訓練與監控只能讀它寫入的資料表，不能執行它。
DERIVATION_ASSET = "raw_taipower_load"
NAMES = TaskPipelineNames(DYNAMIC_HORIZON_FORECAST)


def _tick(schedule_name: str, repository: TimeSeriesRepository, instance):
    context = build_schedule_context(
        instance=instance,
        scheduled_execution_time=TICK,
        resources={"time_series_repo": repository},
    )
    return _schedule(schedule_name).evaluate_tick(context)


def _schedule(name: str):
    pipeline = build_task_pipeline(deployed_tasks(), DYNAMIC_HORIZON_FORECAST)
    return next(schedule for schedule in pipeline.schedules if schedule.name == name)


@pytest.mark.parametrize("job", task_jobs(), ids=lambda job: job.name)
def test_task_jobs_read_persisted_load_without_snapshots_or_external_apis(job) -> None:
    selected = selected_asset_names(job)

    assert selected.isdisjoint(TAIPOWER_REALTIME_SNAPSHOT_ASSETS)
    assert selected.isdisjoint(CWA_INGESTION_ASSETS)
    assert DERIVATION_ASSET not in selected


def test_training_job_runs_features_model_monitoring_and_feast_export() -> None:
    training_job = next(job for job in task_jobs() if job.name == NAMES.training_job)

    assert selected_asset_names(training_job) == {
        NAMES.features,
        NAMES.model,
        NAMES.monitoring,
        "taipower_features",
        "weather_features",
    }


def test_deployed_definitions_provide_the_store_that_readiness_schedules_query() -> None:
    Definitions.validate_loadable(defs)

    for name in (NAMES.training_schedule, NAMES.monitoring_schedule):
        assert defs.resolve_schedule_def(name).required_resource_keys == {"time_series_repo"}


def test_training_skips_with_accumulation_reason_during_cold_start(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int
) -> None:
    test_repo.upsert_taipower_load(derived_hourly_load(min_hours - 1, LAST_HOUR))

    execution = _tick(NAMES.training_schedule, test_repo, dagster_instance)

    assert execution.run_requests == []
    assert "23 valid hourly observations" in execution.skip_message
    assert "24 required" in execution.skip_message


def test_training_triggers_once_accumulation_is_sufficient(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int
) -> None:
    test_repo.upsert_taipower_load(derived_hourly_load(min_hours, LAST_HOUR))

    execution = _tick(NAMES.training_schedule, test_repo, dagster_instance)

    assert execution.skip_message is None
    assert [request.run_key for request in execution.run_requests] == ["2026-09-27T00:00:00"]


def test_training_without_tick_time_requests_an_undeduplicated_run(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int
) -> None:
    """Manual schedule evaluation has no tick for run-key deduplication and must still succeed."""
    test_repo.upsert_taipower_load(derived_hourly_load(min_hours, LAST_HOUR))
    context = build_schedule_context(
        instance=dagster_instance, resources={"time_series_repo": test_repo}
    )

    execution = _schedule(NAMES.training_schedule).evaluate_tick(context)

    assert [request.run_key for request in execution.run_requests] == [None]


def test_monitoring_skips_until_a_model_has_been_trained(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int
) -> None:
    test_repo.upsert_taipower_load(derived_hourly_load(min_hours, LAST_HOUR))

    execution = _tick(NAMES.monitoring_schedule, test_repo, dagster_instance)

    assert execution.run_requests == []
    assert NAMES.model in execution.skip_message


def test_monitoring_skips_with_accumulation_reason_during_cold_start(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int
) -> None:
    execution = _tick(NAMES.monitoring_schedule, test_repo, dagster_instance)

    assert execution.run_requests == []
    assert "0 valid hourly observations" in execution.skip_message


def test_monitoring_triggers_after_training_materialized_a_model(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int
) -> None:
    test_repo.upsert_taipower_load(derived_hourly_load(min_hours, LAST_HOUR))
    dagster_instance.report_runless_asset_event(AssetMaterialization(NAMES.model))

    execution = _tick(NAMES.monitoring_schedule, test_repo, dagster_instance)

    assert execution.skip_message is None
    assert len(execution.run_requests) == 1


def test_a_materialization_under_the_pre_factory_key_does_not_count(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int
) -> None:
    """Materialization under the old asset key cannot unblock monitoring before the renamed model is trained."""
    test_repo.upsert_taipower_load(derived_hourly_load(min_hours, LAST_HOUR))
    dagster_instance.report_runless_asset_event(AssetMaterialization("trained_forecaster_model"))

    execution = _tick(NAMES.monitoring_schedule, test_repo, dagster_instance)

    assert execution.run_requests == []
