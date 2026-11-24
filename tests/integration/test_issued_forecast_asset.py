"""Issuing a forecast end to end: schedule tick, Dagster job, runner and the issued-forecast store.

Here: which runs issue, and how each issuing outcome becomes a materialization or a
``Failure``. What decides the outcome is tested in tests/integration/test_issuing.py.
"""

import shutil
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from dagster import AssetMaterialization, Definitions, MetadataValue, build_schedule_context

from shiro_mlops.core.config import settings
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.pipelines.execution_origin import SCHEDULED_TICK_TAG
from shiro_mlops.pipelines.issued_forecast import (
    ISSUED_FORECAST_ASSET,
    ISSUED_FORECAST_JOB,
    issued_forecast,
    issued_forecast_job,
    issued_forecast_schedule,
)
from shiro_mlops.pipelines.task_pipelines import (
    MLFLOW_MODEL_VERSION_METADATA,
    MODEL_SHA256_METADATA,
    TaskPipelineNames,
)
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_tasks
from shiro_mlops.tasks.model_store import SavedModel, model_directory
from tests.helpers import (
    canonical_observation_batch,
    hourly_load_with_weather,
    scheduler_launch_tags,
    tick_preview_launch_tags,
    train_and_install_forecast_model,
    write_derived_load,
)

TAIPEI = ZoneInfo("Asia/Taipei")
LOAD_ANCHOR = datetime(2026, 11, 20, 9, 0)
HOURS = 24 * 21
TICK = datetime(2026, 11, 20, 10, 15, tzinfo=TAIPEI)
ISSUED_AT = datetime(2026, 11, 20, 10, 15)
# 負載起點 09:00 落後 12:15 超過 3 小時。
STALE_TICK = datetime(2026, 11, 20, 12, 15, tzinfo=TAIPEI)
NAMES = TaskPipelineNames(DYNAMIC_HORIZON_FORECAST)
MLFLOW_VERSION = "7"


@pytest.fixture
def repo(test_repo: TimeSeriesRepository) -> TimeSeriesRepository:
    load, weather = hourly_load_with_weather(HOURS, LOAD_ANCHOR)
    write_derived_load(test_repo.engine, load)
    test_repo.cwa_weather_store.upsert_cwa_observation_batch(
        canonical_observation_batch(weather.assign(location="Taipei"))
    )
    return test_repo


@pytest.fixture
def trained(
    repo: TimeSeriesRepository, dagster_instance, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> SavedModel:
    """A trained model on disk and the materialization that recorded it in MLflow."""
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    saved = _train_and_save(repo, n_estimators=20)
    _report_model_materialization(
        dagster_instance,
        {MODEL_SHA256_METADATA: saved.sha256, MLFLOW_MODEL_VERSION_METADATA: MLFLOW_VERSION},
    )
    return saved


def _report_model_materialization(instance, metadata: dict) -> None:
    instance.report_runless_asset_event(AssetMaterialization(NAMES.model, metadata=metadata))


def _train_and_save(repo: TimeSeriesRepository, *, n_estimators: int) -> SavedModel:
    return train_and_install_forecast_model(
        repo,
        settings.models_dir,
        as_of=ISSUED_AT,
        min_training_hours=HOURS,
        n_estimators=n_estimators,
    )


def _job(repo: TimeSeriesRepository):
    return Definitions(
        assets=[issued_forecast],
        jobs=[issued_forecast_job],
        resources={"time_series_repo": repo},
    ).resolve_job_def(ISSUED_FORECAST_JOB)


def _issue(
    repo: TimeSeriesRepository, instance, tick: datetime = TICK, extra_tags: dict | None = None
):
    """Evaluate the schedule at ``tick`` and run the job exactly as the daemon would."""
    execution = issued_forecast_schedule.evaluate_tick(
        build_schedule_context(instance=instance, scheduled_execution_time=tick)
    )
    [request] = execution.run_requests
    return _job(repo).execute_in_process(
        run_config=request.run_config,
        instance=instance,
        tags={**scheduler_launch_tags(request), **(extra_tags or {})},
        raise_on_error=False,
    )


def _materialization_metadata(result) -> dict:
    [materialization] = result.asset_materializations_for_node(ISSUED_FORECAST_ASSET)
    return {key: value.value for key, value in materialization.metadata.items()}


def _failure(result):
    [failure] = [event for event in result.all_events if event.is_step_failure]
    return failure.step_failure_data.user_failure_data


def _failure_description(result) -> str:
    return _failure(result).description


def test_scheduled_tick_issues_the_168_hour_forecast_from_the_loaded_model(
    repo: TimeSeriesRepository, dagster_instance, trained: SavedModel
) -> None:
    result = _issue(repo, dagster_instance)

    assert result.success
    issued = repo.issued_forecast_store.fetch(ISSUED_AT)
    assert issued is not None
    assert issued.issued_at == ISSUED_AT
    assert issued.load_anchor == LOAD_ANCHOR
    assert issued.status == "degraded"  # 沒有 CWA 預報，天氣降級
    assert issued.model_sha256 == trained.sha256
    assert issued.mlflow_model_version == MLFLOW_VERSION
    assert len(issued.steps) == 168
    assert issued.steps[0].target_hour == LOAD_ANCHOR + timedelta(hours=1)
    assert issued.steps[-1].target_hour == LOAD_ANCHOR + timedelta(hours=168)
    assert all(step.predicted_load_mw > 0 for step in issued.steps)
    assert _materialization_metadata(result) == {
        "issued_at": ISSUED_AT.isoformat(),
        "already_issued": False,
        "load_anchor": LOAD_ANCHOR.isoformat(),
        "status": "degraded",
        MODEL_SHA256_METADATA: trained.sha256,
        "steps": 168,
    }


def test_issuing_the_same_tick_again_keeps_the_first_record(
    repo: TimeSeriesRepository, dagster_instance, trained: SavedModel
) -> None:
    _issue(repo, dagster_instance)
    first = repo.issued_forecast_store.fetch(ISSUED_AT)
    # 同一 tick 重跑前模型已換新；保存內容仍須是第一次發布的那份。
    assert _train_and_save(repo, n_estimators=10).sha256 != trained.sha256

    result = _issue(repo, dagster_instance)

    assert result.success
    assert _materialization_metadata(result) == {
        "issued_at": ISSUED_AT.isoformat(),
        "already_issued": True,
    }
    assert repo.issued_forecast_store.fetch(ISSUED_AT) == first


def test_forecast_the_runner_cannot_produce_fails_the_run_naming_the_issue_time(
    repo: TimeSeriesRepository, dagster_instance, trained: SavedModel
) -> None:
    issued_at = STALE_TICK.replace(tzinfo=None)

    result = _issue(repo, dagster_instance, tick=STALE_TICK)

    assert not result.success
    failure = _failure(result)
    assert "Stale load anchor" in failure.description
    assert failure.metadata["issued_at"] == MetadataValue.text(issued_at.isoformat())
    assert repo.issued_forecast_store.fetch(issued_at) is None


@pytest.mark.parametrize(
    "lineage_tags",
    [
        pytest.param(
            {"dagster/parent_run_id": "failed-run", "dagster/root_run_id": "failed-run"},
            id="ui-re-execution",
        ),
        pytest.param({"dagster/parent_run_id": "failed-run"}, id="parent-only"),
        pytest.param({"dagster/root_run_id": "failed-run"}, id="root-only"),
    ],
)
def test_re_executed_scheduled_run_fails_and_issues_nothing(
    repo: TimeSeriesRepository, dagster_instance, trained: SavedModel, lineage_tags: dict
) -> None:
    """Re-execution copies the tick's tags and issue time, yet would read load stored after it."""
    result = _issue(repo, dagster_instance, extra_tags=lineage_tags)

    assert not result.success
    assert "re-execut" in _failure_description(result)
    assert repo.issued_forecast_store.fetch(ISSUED_AT) is None


def test_manual_run_without_a_tick_fails_and_issues_nothing(
    repo: TimeSeriesRepository, dagster_instance, trained: SavedModel
) -> None:
    result = _job(repo).execute_in_process(instance=dagster_instance, raise_on_error=False)

    assert not result.success
    assert "scheduled tick" in _failure_description(result)
    assert repo.issued_forecast_store.fetch(ISSUED_AT) is None


def test_hand_launched_run_with_an_issue_time_but_no_tick_issues_nothing(
    repo: TimeSeriesRepository, dagster_instance, trained: SavedModel
) -> None:
    """Typing an issue time into the launchpad is not a scheduled issue; nothing is backfilled."""
    result = _job(repo).execute_in_process(
        instance=dagster_instance,
        tags={SCHEDULED_TICK_TAG: ISSUED_AT.isoformat()},
        raise_on_error=False,
    )

    assert not result.success
    assert "scheduled tick" in _failure_description(result)
    assert repo.issued_forecast_store.fetch(ISSUED_AT) is None


@pytest.mark.parametrize(
    "preview_tick",
    [
        pytest.param(TICK - timedelta(hours=10), id="oldest-past-tick"),
        pytest.param(TICK, id="tick-that-has-not-issued"),
        pytest.param(TICK + timedelta(hours=1), id="next-future-tick"),
    ],
)
def test_run_launched_from_the_schedule_tick_preview_issues_nothing(
    repo: TimeSeriesRepository, dagster_instance, trained: SavedModel, preview_tick: datetime
) -> None:
    """The preview offers past and future ticks; launching one would backfill or pre-issue."""
    result = _job(repo).execute_in_process(
        instance=dagster_instance,
        tags=tick_preview_launch_tags(
            issued_forecast_schedule, preview_tick, instance=dagster_instance
        ),
        raise_on_error=False,
    )

    assert not result.success
    assert "scheduled tick" in _failure_description(result)
    assert repo.issued_forecast_store.fetch(preview_tick.replace(tzinfo=None)) is None


def test_model_directory_removed_after_the_tick_fails_with_the_stage_reason(
    repo: TimeSeriesRepository, dagster_instance, trained: SavedModel
) -> None:
    execution = issued_forecast_schedule.evaluate_tick(
        build_schedule_context(instance=dagster_instance, scheduled_execution_time=TICK)
    )
    [request] = execution.run_requests
    shutil.rmtree(model_directory(settings.models_dir, DYNAMIC_HORIZON_FORECAST))

    result = _job(repo).execute_in_process(
        run_config=request.run_config,
        instance=dagster_instance,
        tags=scheduler_launch_tags(request),
        raise_on_error=False,
    )

    assert not result.success
    failure = _failure(result)
    assert "Training record and model directory disagree" in failure.description
    assert f"Run {NAMES.training_job} once" in failure.description
    assert failure.metadata["issued_at"] == MetadataValue.text(ISSUED_AT.isoformat())
    assert repo.issued_forecast_store.fetch(ISSUED_AT) is None


def test_a_model_trained_with_another_feature_recipe_issues_nothing(
    repo: TimeSeriesRepository,
    dagster_instance,
    trained: SavedModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An issued forecast is kept for good; one made with mismatched inputs could never be fixed."""
    tasks = deployed_tasks()
    shipped = tasks[DYNAMIC_HORIZON_FORECAST]
    monkeypatch.setitem(
        tasks,
        DYNAMIC_HORIZON_FORECAST,
        replace(shipped, params=shipped.params.model_copy(update={"lags": [1, 2, 24, 48]})),
    )

    result = _issue(repo, dagster_instance)

    assert not result.success
    description = _failure_description(result)
    assert "lags" in description
    assert "retrain" in description
    assert repo.issued_forecast_store.fetch(ISSUED_AT) is None
