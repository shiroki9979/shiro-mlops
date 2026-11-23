"""Cold-start stage of an ML task from the accumulation gate, model directory and training record."""

from datetime import datetime
from pathlib import Path

import pytest
from dagster import AssetMaterialization

from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.pipelines.cold_start import ColdStartStage, read_cold_start, read_model_presence
from shiro_mlops.pipelines.task_names import TaskPipelineNames
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task
from shiro_mlops.tasks.runner import TaskRuntime
from shiro_mlops.tasks.types import get_task_type
from tests.helpers import (
    derived_hourly_load,
    hand_copied_model_double,
    install_model_double,
    write_derived_load,
)

LAST_HOUR = datetime(2026, 9, 26, 23, 0)
NAMES = TaskPipelineNames(DYNAMIC_HORIZON_FORECAST)


@pytest.fixture
def models_root(tmp_path: Path) -> Path:
    return tmp_path / "models"


def _cold_start(repository: TimeSeriesRepository, instance, models_root: Path):
    return read_cold_start(
        deployed_task(DYNAMIC_HORIZON_FORECAST),
        runtime=TaskRuntime(repository=repository),
        instance=instance,
        models_root=models_root,
    )


def test_below_minimum_accumulation_without_a_model_is_accumulating(
    test_repo: TimeSeriesRepository, dagster_instance, models_root: Path, min_hours: int
) -> None:
    write_derived_load(test_repo.engine, derived_hourly_load(min_hours - 1, LAST_HOUR))

    cold_start = _cold_start(test_repo, dagster_instance, models_root)

    assert cold_start.stage is ColdStartStage.ACCUMULATING
    assert "23 valid hourly observations" in cold_start.reason


def _record(instance) -> None:
    instance.report_runless_asset_event(AssetMaterialization(NAMES.model))


def test_legacy_rows_without_a_model_block_the_cold_start(
    legacy_upgraded_engine, dagster_instance, models_root: Path, min_hours: int
) -> None:
    repository = TimeSeriesRepository(engine=legacy_upgraded_engine)
    write_derived_load(repository.engine, derived_hourly_load(min_hours, LAST_HOUR))

    cold_start = _cold_start(repository, dagster_instance, models_root)

    assert cold_start.stage is ColdStartStage.BLOCKED_BY_LEGACY_ROWS
    assert "legacy rows" in cold_start.reason
    assert not cold_start.training.runs
    assert cold_start.training.skip_reason == cold_start.reason


def test_minimum_accumulation_without_a_model_awaits_the_first_training(
    test_repo: TimeSeriesRepository, dagster_instance, models_root: Path, min_hours: int
) -> None:
    write_derived_load(test_repo.engine, derived_hourly_load(min_hours, LAST_HOUR))

    cold_start = _cold_start(test_repo, dagster_instance, models_root)

    assert cold_start.stage is ColdStartStage.AWAITING_FIRST_TRAINING
    assert NAMES.training_job in cold_start.reason
    assert cold_start.training.runs
    assert cold_start.monitoring.skip_reason == (
        f"No {NAMES.model} materialization yet; {NAMES.monitoring_schedule} waits for "
        f"the first successful {NAMES.training_job} run."
    )


def test_a_model_on_both_sides_is_trained_and_monitored(
    test_repo: TimeSeriesRepository, dagster_instance, models_root: Path, min_hours: int
) -> None:
    write_derived_load(test_repo.engine, derived_hourly_load(min_hours, LAST_HOUR))
    install_model_double(models_root)
    _record(dagster_instance)

    cold_start = _cold_start(test_repo, dagster_instance, models_root)

    assert cold_start.stage is ColdStartStage.TRAINED
    assert cold_start.training.runs
    assert cold_start.monitoring.runs


def test_a_record_without_an_installed_model_is_a_mismatch_that_still_monitors(
    test_repo: TimeSeriesRepository, dagster_instance, models_root: Path, min_hours: int
) -> None:
    write_derived_load(test_repo.engine, derived_hourly_load(min_hours, LAST_HOUR))
    _record(dagster_instance)

    cold_start = _cold_start(test_repo, dagster_instance, models_root)

    assert cold_start.stage is ColdStartStage.RECORD_DIRECTORY_MISMATCH
    assert f"the model directory {models_root / DYNAMIC_HORIZON_FORECAST}" in cold_start.reason
    assert f"Run {NAMES.training_job} once" in cold_start.reason
    assert cold_start.training.runs
    assert cold_start.monitoring.runs


def test_an_installed_model_without_a_record_is_a_mismatch_that_skips_monitoring(
    test_repo: TimeSeriesRepository, dagster_instance, models_root: Path, min_hours: int
) -> None:
    write_derived_load(test_repo.engine, derived_hourly_load(min_hours, LAST_HOUR))
    install_model_double(models_root)

    cold_start = _cold_start(test_repo, dagster_instance, models_root)

    assert cold_start.stage is ColdStartStage.RECORD_DIRECTORY_MISMATCH
    assert f"the training record has no {NAMES.model} materialization" in cold_start.reason
    assert f"Run {NAMES.training_job} once" in cold_start.reason
    assert cold_start.training.runs
    assert cold_start.monitoring.skip_reason == cold_start.reason


def test_a_hand_copied_model_directory_does_not_count_as_a_model(
    test_repo: TimeSeriesRepository, dagster_instance, models_root: Path, min_hours: int
) -> None:
    """The store refuses to load a directory it did not install, so presence must agree."""
    write_derived_load(test_repo.engine, derived_hourly_load(min_hours, LAST_HOUR))
    hand_copied_model_double(models_root)
    _record(dagster_instance)

    cold_start = _cold_start(test_repo, dagster_instance, models_root)

    assert cold_start.stage is ColdStartStage.RECORD_DIRECTORY_MISMATCH
    assert "holds no model installed by the model store" in cold_start.reason


def test_a_trained_task_whose_gate_closes_again_stays_trained_but_skips_training_and_monitoring(
    test_repo: TimeSeriesRepository, dagster_instance, models_root: Path, min_hours: int
) -> None:
    """Raising min_training_hours after training: both schedules skip for the accumulation reason."""
    write_derived_load(test_repo.engine, derived_hourly_load(min_hours - 1, LAST_HOUR))
    install_model_double(models_root)
    _record(dagster_instance)

    cold_start = _cold_start(test_repo, dagster_instance, models_root)

    assert cold_start.stage is ColdStartStage.TRAINED
    assert "23 valid hourly observations" in cold_start.training.skip_reason
    assert cold_start.monitoring.skip_reason == cold_start.training.skip_reason


def test_stage_is_read_without_loading_the_model(
    test_repo: TimeSeriesRepository,
    dagster_instance,
    models_root: Path,
    min_hours: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_derived_load(test_repo.engine, derived_hourly_load(min_hours, LAST_HOUR))
    install_model_double(models_root)
    _record(dagster_instance)
    task_type = get_task_type(deployed_task(DYNAMIC_HORIZON_FORECAST).task_type)

    def refuse_to_load(directory: Path):
        raise AssertionError(f"loaded {directory}")

    monkeypatch.setattr(task_type, "load", refuse_to_load)

    assert _cold_start(test_repo, dagster_instance, models_root).stage is ColdStartStage.TRAINED


ISSUING_SCHEDULE = "issued_forecast_schedule"


def _presence(instance, models_root: Path):
    return read_model_presence(DYNAMIC_HORIZON_FORECAST, instance=instance, models_root=models_root)


def test_issuing_without_a_model_on_either_side_waits_for_the_first_training(
    dagster_instance, models_root: Path
) -> None:
    decision = _presence(dagster_instance, models_root).issuing(ISSUING_SCHEDULE)

    assert decision.skip_reason == (
        f"No {NAMES.model} materialization yet; {ISSUING_SCHEDULE} waits for "
        "the first successful training run."
    )


def test_issuing_runs_from_an_installed_model_even_without_a_training_record(
    dagster_instance, models_root: Path
) -> None:
    """The issued forecast loads from the directory, so a rebuilt Dagster instance must not stop it."""
    install_model_double(models_root)

    assert _presence(dagster_instance, models_root).issuing(ISSUING_SCHEDULE).runs


def test_issuing_skips_a_training_record_whose_model_directory_is_gone(
    dagster_instance, models_root: Path
) -> None:
    _record(dagster_instance)

    decision = _presence(dagster_instance, models_root).issuing(ISSUING_SCHEDULE)

    assert "Training record and model directory disagree" in decision.skip_reason
    assert f"Run {NAMES.training_job} once" in decision.skip_reason


def test_issuing_ignores_a_closed_accumulation_gate(
    test_repo: TimeSeriesRepository, dagster_instance, models_root: Path, min_hours: int
) -> None:
    write_derived_load(test_repo.engine, derived_hourly_load(min_hours - 1, LAST_HOUR))
    install_model_double(models_root)
    _record(dagster_instance)

    cold_start = _cold_start(test_repo, dagster_instance, models_root)

    assert not cold_start.training.runs
    assert cold_start.models.issuing(ISSUING_SCHEDULE).runs


def test_issuing_skips_with_the_stage_reason_of_a_mismatch(
    test_repo: TimeSeriesRepository, dagster_instance, models_root: Path, min_hours: int
) -> None:
    write_derived_load(test_repo.engine, derived_hourly_load(min_hours, LAST_HOUR))
    _record(dagster_instance)

    cold_start = _cold_start(test_repo, dagster_instance, models_root)

    assert cold_start.models.issuing(ISSUING_SCHEDULE).skip_reason == cold_start.reason
