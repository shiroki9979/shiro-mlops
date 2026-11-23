"""Contract tests for the issued forecast schedule and job (ADR-0013)."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from dagster import AssetKey, AssetMaterialization, build_schedule_context

from shiro_mlops.pipelines.definitions import defs
from shiro_mlops.pipelines.execution_origin import SCHEDULE_NAME_TAG, SCHEDULED_TICK_TAG
from shiro_mlops.pipelines.issued_forecast import (
    ISSUED_FORECAST_ASSET,
    issued_forecast,
    issued_forecast_job,
    issued_forecast_schedule,
)
from shiro_mlops.pipelines.schedules import (
    CWA_INGESTION_ASSETS,
    HOURLY_ACTUAL_LOAD_ASSET,
    TAIPOWER_REALTIME_SNAPSHOT_ASSETS,
)
from shiro_mlops.pipelines.task_pipelines import TaskPipelineNames
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST
from tests.helpers import install_model_double, selected_asset_names, task_jobs

NAMES = TaskPipelineNames(DYNAMIC_HORIZON_FORECAST)
# 2026-11-20 02:15 UTC 即台灣 10:15，發布時刻不取整點。
TICK = datetime(2026, 11, 20, 2, 15, tzinfo=ZoneInfo("UTC"))

pytestmark = pytest.mark.usefixtures("isolated_models_dir")


def _evaluate(instance, tick: datetime | None = TICK):
    if tick is None:
        context = build_schedule_context(instance=instance)
    else:
        context = build_schedule_context(instance=instance, scheduled_execution_time=tick)
    return issued_forecast_schedule.evaluate_tick(context)


def _record(instance) -> None:
    instance.report_runless_asset_event(AssetMaterialization(NAMES.model))


def _train(instance, models_root: Path) -> None:
    install_model_double(models_root)
    _record(instance)


def test_schedule_issues_at_a_quarter_past_every_taiwan_hour() -> None:
    schedule = defs.resolve_schedule_def("issued_forecast_schedule")

    assert schedule.cron_schedule == "15 * * * *"
    assert schedule.execution_timezone == "Asia/Taipei"
    assert schedule.job_name == "issued_forecast_job"


def test_schedule_skips_until_the_forecast_model_has_been_trained(dagster_instance) -> None:
    execution = _evaluate(dagster_instance)

    assert execution.run_requests == []
    assert NAMES.model in execution.skip_message


def test_schedule_tick_becomes_the_taiwan_local_issue_time(
    dagster_instance, isolated_models_dir: Path
) -> None:
    """The tick reaches the asset as a run tag, never as config an operator could type in."""
    _train(dagster_instance, isolated_models_dir)

    execution = _evaluate(dagster_instance)

    [request] = execution.run_requests
    assert request.run_key == "2026-11-20T10:15:00"
    assert request.tags == {
        SCHEDULE_NAME_TAG: "issued_forecast_schedule",
        SCHEDULED_TICK_TAG: "2026-11-20T10:15:00",
    }
    assert not request.run_config


def test_schedule_evaluated_without_a_tick_requests_nothing(
    dagster_instance, isolated_models_dir: Path
) -> None:
    """Only a scheduled tick has an issue time; a manual evaluation must not issue."""
    _train(dagster_instance, isolated_models_dir)

    execution = _evaluate(dagster_instance, tick=None)

    assert execution.run_requests == []
    assert execution.skip_message


def test_schedule_without_a_model_on_either_side_keeps_its_skip_message(dagster_instance) -> None:
    execution = _evaluate(dagster_instance)

    assert execution.skip_message == (
        f"No {NAMES.model} materialization yet; issued_forecast_schedule waits for "
        "the first successful training run."
    )


def test_schedule_issues_from_the_model_directory_after_the_dagster_instance_is_rebuilt(
    dagster_instance, isolated_models_dir: Path
) -> None:
    """`docker compose down -v` drops the instance but keeps data/models: every hour must still issue."""
    install_model_double(isolated_models_dir)

    execution = _evaluate(dagster_instance)

    [request] = execution.run_requests
    assert request.run_key == "2026-11-20T10:15:00"


def test_schedule_skips_a_training_record_whose_model_directory_was_removed(
    dagster_instance,
) -> None:
    """A run would only fail loading the model, so the tick names the mismatch instead."""
    _record(dagster_instance)

    execution = _evaluate(dagster_instance)

    assert execution.run_requests == []
    assert "Training record and model directory disagree" in execution.skip_message
    assert f"Run {NAMES.training_job} once" in execution.skip_message


def test_issued_forecast_job_selects_only_the_issued_forecast() -> None:
    selected = selected_asset_names(issued_forecast_job)

    assert selected == {ISSUED_FORECAST_ASSET}
    assert selected.isdisjoint(TAIPOWER_REALTIME_SNAPSHOT_ASSETS)
    assert selected.isdisjoint(CWA_INGESTION_ASSETS)
    assert HOURLY_ACTUAL_LOAD_ASSET not in selected


def test_task_jobs_never_select_the_issued_forecast() -> None:
    """Training at 00:00 has no tick; it must not drag an issue along downstream."""
    for job in task_jobs():
        assert ISSUED_FORECAST_ASSET not in selected_asset_names(job), job.name


def test_issued_forecast_lineage_depends_only_on_ingested_inputs() -> None:
    node = defs.resolve_asset_graph().get(AssetKey(ISSUED_FORECAST_ASSET))

    parents = {key.to_user_string() for key in node.parent_keys}

    assert parents == {HOURLY_ACTUAL_LOAD_ASSET, *CWA_INGESTION_ASSETS}


def test_issued_forecast_never_retries() -> None:
    """A retry keeps the original tick as as_of but would read load stored after it."""
    assert issued_forecast.op.retry_policy is None
    assert issued_forecast_job.op_retry_policy is None
    assert defs.resolve_job_def("issued_forecast_job").tags.get("dagster/max_retries") is None
