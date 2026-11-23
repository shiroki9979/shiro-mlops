"""Outcomes of issuing at a resolved issue time: real runner, SQLite store and a temporary model directory."""

import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from dagster import AssetMaterialization, MetadataValue
from sqlalchemy import create_engine

from shiro_mlops.core.config import settings
from shiro_mlops.data.issued_forecast import IssuedForecast, IssuedForecastStep
from shiro_mlops.data.issued_forecast_repository import IssuedForecastRepository
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.weather_resolution import ForecastMode
from shiro_mlops.pipelines.issuing import (
    AlreadyIssued,
    ForecastUnavailable,
    Issued,
    IssuingOutcome,
    ModelUnavailable,
    issue_forecast,
)
from shiro_mlops.pipelines.task_pipelines import (
    MLFLOW_MODEL_VERSION_METADATA,
    MODEL_SHA256_METADATA,
    TaskPipelineNames,
)
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST
from shiro_mlops.tasks.model_store import SavedModel, model_directory
from tests.helpers import (
    canonical_observation_batch,
    hourly_load_with_weather,
    task_runtime,
    train_and_install_forecast_model,
    write_derived_load,
)

LOAD_ANCHOR = datetime(2026, 11, 20, 9, 0)
HOURS = 24 * 21
ISSUED_AT = datetime(2026, 11, 20, 10, 15)
# 負載起點 09:00 落後 12:15 超過 3 小時。
STALE_ISSUED_AT = datetime(2026, 11, 20, 12, 15)
BEFORE_HISTORY_ISSUED_AT = datetime(2026, 10, 1, 10, 15)
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
def models_root(tmp_path: Path) -> Path:
    return tmp_path / "models"


@pytest.fixture
def trained(repo: TimeSeriesRepository, dagster_instance, models_root: Path) -> SavedModel:
    """A trained model in the model directory and the materialization that recorded it in MLflow."""
    saved = _train(repo, models_root, n_estimators=20)
    _record(
        dagster_instance,
        {MODEL_SHA256_METADATA: saved.sha256, MLFLOW_MODEL_VERSION_METADATA: MLFLOW_VERSION},
    )
    return saved


def _train(repo: TimeSeriesRepository, models_root: Path, *, n_estimators: int) -> SavedModel:
    return train_and_install_forecast_model(
        repo, models_root, as_of=ISSUED_AT, min_training_hours=HOURS, n_estimators=n_estimators
    )


def _record(instance, metadata: dict | None = None) -> None:
    instance.report_runless_asset_event(AssetMaterialization(NAMES.model, metadata=metadata))


def _issue(
    repo: TimeSeriesRepository,
    instance,
    models_root: Path,
    issued_at: datetime = ISSUED_AT,
    *,
    store: IssuedForecastRepository | None = None,
) -> IssuingOutcome:
    return issue_forecast(
        issued_at,
        store=store or repo.issued_forecast_store,
        runtime=task_runtime(repo),
        instance=instance,
        models_root=models_root,
    )


def _load_only_repo(tmp_path: Path) -> TimeSeriesRepository:
    """Load accumulated but CWA never ingested: no forecast and no observation to fall back on."""
    load_only = TimeSeriesRepository(engine=create_engine(f"sqlite:///{tmp_path / 'load.db'}"))
    load, _weather = hourly_load_with_weather(HOURS, LOAD_ANCHOR)
    write_derived_load(load_only.engine, load)
    return load_only


def _earlier_issue(issued_at: datetime = ISSUED_AT) -> IssuedForecast:
    """A record another issue left at the same issue time; told apart by its hash and load."""
    return IssuedForecast(
        issued_at=issued_at,
        load_anchor=LOAD_ANCHOR,
        status=ForecastMode.DEGRADED,
        model_sha256="e" * 64,
        mlflow_model_version=None,
        steps=(
            IssuedForecastStep(target_hour=LOAD_ANCHOR + timedelta(hours=1), predicted_load_mw=1.0),
        ),
    )


class _ReadsBeforeTheOtherIssueCommits(IssuedForecastRepository):
    """A store whose read misses a record that is committed by the time this issue writes."""

    def fetch(self, issued_at: datetime) -> IssuedForecast | None:
        return None


def test_issue_keeps_the_168_hour_forecast_of_the_loaded_model(
    repo: TimeSeriesRepository, dagster_instance, models_root: Path, trained: SavedModel
) -> None:
    outcome = _issue(repo, dagster_instance, models_root)

    assert isinstance(outcome, Issued)
    forecast = outcome.forecast
    assert forecast == repo.issued_forecast_store.fetch(ISSUED_AT)
    assert forecast.issued_at == ISSUED_AT
    assert forecast.load_anchor == LOAD_ANCHOR
    assert forecast.status is ForecastMode.DEGRADED  # 沒有 CWA 預報，天氣降級
    assert forecast.model_sha256 == trained.sha256
    assert forecast.mlflow_model_version == MLFLOW_VERSION
    assert len(forecast.steps) == 168
    assert forecast.steps[0].target_hour == LOAD_ANCHOR + timedelta(hours=1)
    assert forecast.steps[-1].target_hour == LOAD_ANCHOR + timedelta(hours=168)
    assert all(step.predicted_load_mw > 0 for step in forecast.steps)


def test_issue_time_on_record_is_not_forecast_again(
    repo: TimeSeriesRepository, dagster_instance, models_root: Path
) -> None:
    """No model is installed: the record answers before a model is looked for."""
    repo.issued_forecast_store.insert(_earlier_issue())

    outcome = _issue(repo, dagster_instance, models_root)

    assert outcome == AlreadyIssued()
    assert repo.issued_forecast_store.fetch(ISSUED_AT) == _earlier_issue()


def test_record_written_while_forecasting_is_kept_and_reported_as_already_issued(
    repo: TimeSeriesRepository, dagster_instance, models_root: Path, trained: SavedModel
) -> None:
    repo.issued_forecast_store.insert(_earlier_issue())
    racing_store = _ReadsBeforeTheOtherIssueCommits(engine=repo.engine, auto_init=False)

    outcome = _issue(repo, dagster_instance, models_root, store=racing_store)

    assert outcome == AlreadyIssued()
    assert repo.issued_forecast_store.fetch(ISSUED_AT) == _earlier_issue()


@pytest.mark.parametrize(
    ("issue_from", "issued_at", "reason"),
    [
        pytest.param(
            lambda repo, _tmp: repo, STALE_ISSUED_AT, "Stale load anchor", id="stale-anchor"
        ),
        pytest.param(
            lambda repo, _tmp: repo,
            BEFORE_HISTORY_ISSUED_AT,
            "No persisted nationwide load history",
            id="no-load-history",
        ),
        pytest.param(
            lambda _repo, tmp: _load_only_repo(tmp),
            ISSUED_AT,
            "No weather coverage",
            id="weather-unavailable",
        ),
    ],
)
def test_forecast_the_runner_cannot_produce_leaves_the_issue_time_unissued(
    repo: TimeSeriesRepository,
    dagster_instance,
    models_root: Path,
    trained: SavedModel,
    tmp_path: Path,
    issue_from,
    issued_at: datetime,
    reason: str,
) -> None:
    issuing_repo = issue_from(repo, tmp_path)

    outcome = _issue(issuing_repo, dagster_instance, models_root, issued_at)

    assert isinstance(outcome, ForecastUnavailable)
    assert reason in outcome.reason
    assert issuing_repo.issued_forecast_store.fetch(issued_at) is None


def test_no_model_on_either_side_says_there_is_no_model(
    repo: TimeSeriesRepository, dagster_instance, models_root: Path
) -> None:
    outcome = _issue(repo, dagster_instance, models_root)

    assert isinstance(outcome, ModelUnavailable)
    assert outcome.reason.startswith(f"No {NAMES.model} materialization yet")
    assert "valid hourly observations" not in outcome.reason
    assert repo.issued_forecast_store.fetch(ISSUED_AT) is None


def test_training_record_without_a_model_directory_names_the_mismatch(
    repo: TimeSeriesRepository, dagster_instance, models_root: Path, trained: SavedModel
) -> None:
    shutil.rmtree(model_directory(models_root, DYNAMIC_HORIZON_FORECAST))

    outcome = _issue(repo, dagster_instance, models_root)

    assert isinstance(outcome, ModelUnavailable)
    assert "Training record and model directory disagree" in outcome.reason
    assert f"Run {NAMES.training_job} once" in outcome.reason
    assert repo.issued_forecast_store.fetch(ISSUED_AT) is None


def test_model_that_cannot_be_loaded_while_the_directory_still_holds_one_waits_for_the_next_tick(
    repo: TimeSeriesRepository,
    dagster_instance,
    models_root: Path,
    trained: SavedModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Training replaced the directory between the two reads: there is no skip reason to borrow."""
    monkeypatch.setattr(
        "shiro_mlops.pipelines.issuing.load_model_with_sha256", lambda *_args, **_kwargs: None
    )

    outcome = _issue(repo, dagster_instance, models_root)

    assert isinstance(outcome, ModelUnavailable)
    assert "model changed while loading" in outcome.reason
    assert repo.issued_forecast_store.fetch(ISSUED_AT) is None


def test_model_directory_without_a_training_record_issues_with_an_empty_mlflow_note(
    repo: TimeSeriesRepository, dagster_instance, models_root: Path
) -> None:
    """A rebuilt Dagster instance lost the record, but data/models still holds the trained model."""
    saved = _train(repo, models_root, n_estimators=20)

    outcome = _issue(repo, dagster_instance, models_root)

    assert isinstance(outcome, Issued)
    assert outcome.forecast.model_sha256 == saved.sha256
    assert outcome.forecast.mlflow_model_version is None


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
    repo: TimeSeriesRepository,
    dagster_instance,
    models_root: Path,
    trained: SavedModel,
    latest_metadata,
) -> None:
    _record(dagster_instance, latest_metadata(trained.sha256))

    outcome = _issue(repo, dagster_instance, models_root)

    assert isinstance(outcome, Issued)
    assert outcome.forecast.model_sha256 == trained.sha256
    assert outcome.forecast.mlflow_model_version is None


def test_issuing_never_calls_mlflow_and_reads_the_note_from_the_materialization(
    repo: TimeSeriesRepository,
    dagster_instance,
    models_root: Path,
    trained: SavedModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unreachable(*_args, **_kwargs):
        raise ConnectionError("MLflow is down")

    monkeypatch.setattr(settings, "MLFLOW_TRACKING_URI", "http://127.0.0.1:9")
    monkeypatch.setattr("mlflow.set_tracking_uri", unreachable)
    monkeypatch.setattr("mlflow.MlflowClient", unreachable)

    outcome = _issue(repo, dagster_instance, models_root)

    assert isinstance(outcome, Issued)
    assert outcome.forecast.model_sha256 == trained.sha256
    assert outcome.forecast.mlflow_model_version == MLFLOW_VERSION


def _unreadable_load_store(*_args, **_kwargs):
    raise RuntimeError("load store unreachable")


def test_issuing_never_queries_the_accumulation_gate(
    repo: TimeSeriesRepository,
    dagster_instance,
    models_root: Path,
    trained: SavedModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issuing needs only the model directory, so a failing gate query cannot stop it."""
    monkeypatch.setattr(
        "shiro_mlops.pipelines.cold_start.check_training_readiness", _unreadable_load_store
    )

    outcome = _issue(repo, dagster_instance, models_root)

    assert isinstance(outcome, Issued)
    assert repo.issued_forecast_store.fetch(ISSUED_AT) is not None
