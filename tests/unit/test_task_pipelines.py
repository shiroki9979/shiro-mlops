"""Asset factory: every task definition yields its own assets, jobs, and schedules (ADR-0009)."""

from pathlib import Path

import pytest
from dagster import AssetKey, Definitions, load_assets_from_modules

from shiro_mlops.core.datetime_utils import TAIWAN_TZ
from shiro_mlops.data.cwa_client import DEFAULT_CWA_LOCATIONS
from shiro_mlops.pipelines import assets as assets_module
from shiro_mlops.pipelines.definitions import defs
from shiro_mlops.pipelines.task_pipelines import TaskPipelineNames, build_task_pipelines
from shiro_mlops.tasks.definition import TaskDefinition, load_task_definitions
from shiro_mlops.tasks.deployed import (
    DYNAMIC_HORIZON_FORECAST,
    TASK_DEFINITIONS_DIR,
    deployed_tasks,
)

FEAST_ASSETS = {"taipower_features", "weather_features"}
EXTRA_TASK = "evening_peak_forecast"


@pytest.fixture
def tasks_with_extra(tmp_path: Path) -> dict[str, TaskDefinition]:
    """The shipped definitions plus one more, differing only in id and schedule."""
    shipped = (TASK_DEFINITIONS_DIR / f"{DYNAMIC_HORIZON_FORECAST}.toml").read_text("utf-8")
    (tmp_path / f"{DYNAMIC_HORIZON_FORECAST}.toml").write_text(shipped, encoding="utf-8")
    extra = shipped.replace(
        f'task_id = "{DYNAMIC_HORIZON_FORECAST}"', f'task_id = "{EXTRA_TASK}"'
    ).replace('training = "0 0 * * *"', 'training = "30 18 * * *"')
    (tmp_path / f"{EXTRA_TASK}.toml").write_text(extra, encoding="utf-8")
    return load_task_definitions(tmp_path, DEFAULT_CWA_LOCATIONS)


def _asset_names(asset_defs) -> set[str]:
    return {key.to_user_string() for asset_def in asset_defs for key in asset_def.keys}


def _definitions(tasks: dict[str, TaskDefinition]) -> Definitions:
    pipelines = build_task_pipelines(tasks)
    return Definitions(
        assets=[
            *load_assets_from_modules([assets_module]),
            *(asset for pipeline in pipelines for asset in pipeline.assets),
        ],
        jobs=[job for pipeline in pipelines for job in pipeline.jobs],
        schedules=[schedule for pipeline in pipelines for schedule in pipeline.schedules],
        resources=defs.resources,
    )


def _selected(definitions: Definitions, job_name: str) -> set[str]:
    job = definitions.resolve_job_def(job_name)
    return {key.to_user_string() for key in job.asset_layer.executable_asset_keys}


def test_every_deployed_task_gets_features_model_and_monitoring_assets() -> None:
    graph = defs.resolve_asset_graph()

    assert {
        "dynamic_horizon_forecast__features",
        "dynamic_horizon_forecast__model",
        "dynamic_horizon_forecast__monitoring",
        "high_load_alert__features",
        "high_load_alert__model",
        "high_load_alert__monitoring",
        "load_pattern_anomaly__features",
        "load_pattern_anomaly__model",
        "load_pattern_anomaly__monitoring",
    } <= {key.to_user_string() for key in graph.get_all_asset_keys()}


@pytest.mark.parametrize("task_id", sorted(deployed_tasks()))
def test_every_deployed_task_schedules_follow_its_definition(task_id: str) -> None:
    names = TaskPipelineNames(task_id)
    task = deployed_tasks()[task_id]

    training = defs.resolve_schedule_def(names.training_schedule)
    monitoring = defs.resolve_schedule_def(names.monitoring_schedule)

    assert (training.job_name, training.cron_schedule, training.execution_timezone) == (
        names.training_job,
        task.schedule.training,
        TAIWAN_TZ,
    )
    assert (monitoring.job_name, monitoring.cron_schedule, monitoring.execution_timezone) == (
        names.monitoring_job,
        task.schedule.monitoring,
        TAIWAN_TZ,
    )


def test_adding_a_task_definition_generates_its_assets_and_schedules(
    tasks_with_extra: dict[str, TaskDefinition],
) -> None:
    pipelines = {
        pipeline.names.task_id: pipeline for pipeline in build_task_pipelines(tasks_with_extra)
    }
    extra = pipelines[EXTRA_TASK]

    assert _asset_names(extra.assets) == {
        "evening_peak_forecast__features",
        "evening_peak_forecast__model",
        "evening_peak_forecast__monitoring",
    }
    assert {schedule.name: schedule.cron_schedule for schedule in extra.schedules} == {
        "evening_peak_forecast__training_schedule": "30 18 * * *",
        "evening_peak_forecast__monitoring_schedule": "0 * * * *",
    }
    assert {job.name for job in extra.jobs} == {
        "evening_peak_forecast__training_job",
        "evening_peak_forecast__monitoring_job",
    }


def test_ingestion_assets_are_shared_not_generated_per_task(
    tasks_with_extra: dict[str, TaskDefinition],
) -> None:
    ingestion = _asset_names(load_assets_from_modules([assets_module])) - FEAST_ASSETS

    for pipeline in build_task_pipelines(tasks_with_extra):
        assert _asset_names(pipeline.assets).isdisjoint(ingestion)
        assert all(
            name.startswith(f"{pipeline.names.task_id}__") for name in _asset_names(pipeline.assets)
        )


def test_feast_export_hangs_only_off_the_dynamic_horizon_forecast(
    tasks_with_extra: dict[str, TaskDefinition],
) -> None:
    definitions = _definitions(tasks_with_extra)
    graph = definitions.resolve_asset_graph()

    for feast_asset in FEAST_ASSETS:
        assert graph.get(AssetKey(feast_asset)).parent_keys == {
            AssetKey(TaskPipelineNames(DYNAMIC_HORIZON_FORECAST).features)
        }
    assert FEAST_ASSETS <= _selected(
        definitions, TaskPipelineNames(DYNAMIC_HORIZON_FORECAST).training_job
    )
    assert _selected(definitions, TaskPipelineNames(EXTRA_TASK).training_job) == {
        "evening_peak_forecast__features",
        "evening_peak_forecast__model",
        "evening_peak_forecast__monitoring",
    }


def test_monitoring_job_reruns_only_the_monitoring_asset() -> None:
    """Hourly monitoring reads the latest row and valid-hour count without rerunning full-history feature assets."""
    names = TaskPipelineNames(DYNAMIC_HORIZON_FORECAST)

    assert _selected(defs, names.monitoring_job) == {names.monitoring}
