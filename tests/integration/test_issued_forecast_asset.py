"""Issuing a forecast end to end: schedule tick, Dagster job, runner and the issued-forecast store."""

import shutil
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from dagster import AssetMaterialization, Definitions, MetadataValue, build_schedule_context
from sqlalchemy import create_engine

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
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task
from shiro_mlops.tasks.model_store import SavedModel, model_directory, save_model
from shiro_mlops.tasks.runner import train_task
from tests.helpers import (
    canonical_observation_batch,
    hourly_load_with_weather,
    task_runtime,
    write_derived_load,
)

TAIPEI = ZoneInfo("Asia/Taipei")
LOAD_ANCHOR = datetime(2026, 11, 20, 9, 0)
HOURS = 24 * 21
TICK = datetime(2026, 11, 20, 10, 15, tzinfo=TAIPEI)
ISSUED_AT = datetime(2026, 11, 20, 10, 15)
# 負載起點 09:00 落後 12:15 超過 3 小時。
STALE_TICK = datetime(2026, 11, 20, 12, 15, tzinfo=TAIPEI)
# 早於第一筆逐時負載的 tick：尚無負載歷史可作起點。
BEFORE_HISTORY_TICK = datetime(2026, 10, 1, 10, 15, tzinfo=TAIPEI)
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
    shipped = deployed_task(DYNAMIC_HORIZON_FORECAST)
    task = replace(
        shipped,
        params=shipped.params.model_copy(
            update={"model": shipped.params.model.model_copy(update={"n_estimators": n_estimators})}
        ),
        policies=shipped.policies.model_copy(update={"min_training_hours": HOURS}),
    )
    model = train_task(task, task_runtime(repo), as_of=ISSUED_AT).model
    return save_model(settings.models_dir, DYNAMIC_HORIZON_FORECAST, model)


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
        tags={**request.tags, **(extra_tags or {})},
        raise_on_error=False,
    )


def _load_only_repo(tmp_path) -> TimeSeriesRepository:
    """Load accumulated but CWA never ingested: no forecast and no observation to fall back on."""
    load_only = TimeSeriesRepository(engine=create_engine(f"sqlite:///{tmp_path / 'load.db'}"))
    load, _weather = hourly_load_with_weather(HOURS, LOAD_ANCHOR)
    write_derived_load(load_only.engine, load)
    return load_only


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
    assert _materialization_metadata(result)["already_issued"] is False


def test_issuing_the_same_tick_again_keeps_the_first_record(
    repo: TimeSeriesRepository, dagster_instance, trained: SavedModel
) -> None:
    _issue(repo, dagster_instance)
    first = repo.issued_forecast_store.fetch(ISSUED_AT)
    # 同一 tick 重跑前模型已換新；保存內容仍須是第一次發布的那份。
    assert _train_and_save(repo, n_estimators=10).sha256 != trained.sha256

    result = _issue(repo, dagster_instance)

    assert result.success
    assert _materialization_metadata(result)["already_issued"] is True
    assert repo.issued_forecast_store.fetch(ISSUED_AT) == first


@pytest.mark.parametrize(
    ("issue_from", "tick", "reason"),
    [
        pytest.param(lambda repo, _tmp: repo, STALE_TICK, "Stale load anchor", id="stale-anchor"),
        pytest.param(
            lambda repo, _tmp: repo,
            BEFORE_HISTORY_TICK,
            "No persisted nationwide load history",
            id="no-load-history",
        ),
        pytest.param(
            lambda _repo, tmp: _load_only_repo(tmp),
            TICK,
            "No weather coverage",
            id="weather-unavailable",
        ),
    ],
)
def test_forecast_the_runner_cannot_produce_fails_the_issue_and_records_nothing(
    repo: TimeSeriesRepository,
    dagster_instance,
    trained: SavedModel,
    tmp_path,
    issue_from,
    tick: datetime,
    reason: str,
) -> None:
    issuing_repo = issue_from(repo, tmp_path)
    issued_at = tick.replace(tzinfo=None)

    result = _issue(issuing_repo, dagster_instance, tick=tick)

    assert not result.success
    failure = _failure(result)
    assert reason in failure.description
    assert failure.metadata["issued_at"] == MetadataValue.text(issued_at.isoformat())
    assert issuing_repo.issued_forecast_store.fetch(issued_at) is None


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


def test_issuing_never_calls_mlflow_and_reads_the_note_from_the_materialization(
    repo: TimeSeriesRepository,
    dagster_instance,
    trained: SavedModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unreachable(*_args, **_kwargs):
        raise ConnectionError("MLflow is down")

    monkeypatch.setattr(settings, "MLFLOW_TRACKING_URI", "http://127.0.0.1:9")
    monkeypatch.setattr("mlflow.set_tracking_uri", unreachable)
    monkeypatch.setattr("mlflow.MlflowClient", unreachable)

    result = _issue(repo, dagster_instance)

    assert result.success
    issued = repo.issued_forecast_store.fetch(ISSUED_AT)
    assert issued is not None
    assert issued.model_sha256 == trained.sha256
    assert issued.mlflow_model_version == MLFLOW_VERSION


@pytest.mark.parametrize(
    "latest_metadata",
    [
        pytest.param(
            lambda _loaded: {
                MODEL_SHA256_METADATA: "0" * 64,
                MLFLOW_MODEL_VERSION_METADATA: "8",
            },
            id="training-finished-after-the-model-was-loaded",
        ),
        pytest.param(lambda _loaded: {}, id="materialization-without-metadata"),
        pytest.param(
            lambda loaded: {
                MODEL_SHA256_METADATA: loaded,
                MLFLOW_MODEL_VERSION_METADATA: MetadataValue.null(),
            },
            id="mlflow-was-unavailable-at-training",
        ),
        pytest.param(
            lambda loaded: {MODEL_SHA256_METADATA: loaded, MLFLOW_MODEL_VERSION_METADATA: ""},
            id="empty-mlflow-version",
        ),
    ],
)
def test_mlflow_note_stays_empty_unless_the_latest_materialization_names_the_loaded_model(
    repo: TimeSeriesRepository, dagster_instance, trained: SavedModel, latest_metadata
) -> None:
    _report_model_materialization(dagster_instance, latest_metadata(trained.sha256))

    result = _issue(repo, dagster_instance)

    assert result.success
    issued = repo.issued_forecast_store.fetch(ISSUED_AT)
    assert issued is not None
    assert issued.model_sha256 == trained.sha256
    assert issued.mlflow_model_version is None


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


def test_model_directory_without_a_training_record_issues_with_an_empty_mlflow_note(
    repo: TimeSeriesRepository, dagster_instance, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rebuilt Dagster instance lost the record, but data/models still holds the trained model."""
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    saved = _train_and_save(repo, n_estimators=20)

    result = _issue(repo, dagster_instance)

    assert result.success
    issued = repo.issued_forecast_store.fetch(ISSUED_AT)
    assert issued is not None
    assert issued.model_sha256 == saved.sha256
    assert issued.mlflow_model_version is None


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
        tags=request.tags,
        raise_on_error=False,
    )

    assert not result.success
    failure = _failure(result)
    assert "Training record and model directory disagree" in failure.description
    assert f"Run {NAMES.training_job} once" in failure.description
    assert failure.metadata["issued_at"] == MetadataValue.text(ISSUED_AT.isoformat())
    assert repo.issued_forecast_store.fetch(ISSUED_AT) is None


def _unreadable_load_store(*_args, **_kwargs):
    raise RuntimeError("load store unreachable")


def test_issuing_never_queries_the_accumulation_gate(
    repo: TimeSeriesRepository,
    dagster_instance,
    trained: SavedModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issuing needs only the model directory, so a failing gate query cannot stop it."""
    monkeypatch.setattr(
        "shiro_mlops.pipelines.cold_start.check_training_readiness", _unreadable_load_store
    )

    result = _issue(repo, dagster_instance)

    assert result.success
    assert repo.issued_forecast_store.fetch(ISSUED_AT) is not None


def test_no_model_on_either_side_fails_saying_there_is_no_model(
    repo: TimeSeriesRepository, dagster_instance, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    _train_and_save(repo, n_estimators=20)
    execution = issued_forecast_schedule.evaluate_tick(
        build_schedule_context(instance=dagster_instance, scheduled_execution_time=TICK)
    )
    [request] = execution.run_requests
    shutil.rmtree(model_directory(settings.models_dir, DYNAMIC_HORIZON_FORECAST))

    result = _job(repo).execute_in_process(
        run_config=request.run_config,
        instance=dagster_instance,
        tags=request.tags,
        raise_on_error=False,
    )

    assert not result.success
    description = _failure_description(result)
    assert description.startswith(f"No {NAMES.model} materialization yet")
    assert "valid hourly observations" not in description
    assert repo.issued_forecast_store.fetch(ISSUED_AT) is None
