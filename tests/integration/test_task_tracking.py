"""MLflow tracking per task: one experiment and one registered model per task id."""

from dataclasses import replace
from pathlib import Path

import pytest
from mlflow import MlflowClient

from shiro_mlops.core.config import settings
from shiro_mlops.pipelines.tracking import log_training_run
from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task

OTHER_TASK = "evening_peak_forecast"


@pytest.fixture
def client() -> MlflowClient:
    return MlflowClient(settings.MLFLOW_TRACKING_URI)


@pytest.fixture
def model_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "model"
    directory.mkdir()
    (directory / "model.txt").write_text("tree", encoding="utf-8")
    return directory


def _with_local_artifacts(client: MlflowClient, task_id: str, tmp_path: Path) -> None:
    """Pre-create the experiment so artifacts land in tmp_path instead of ./mlruns."""
    client.create_experiment(task_id, artifact_location=(tmp_path / task_id).as_uri())


def _run(task: TaskDefinition, model_dir: Path, client: MlflowClient, tmp_path: Path):
    _with_local_artifacts(client, task.task_id, tmp_path)
    return log_training_run(task, {"mape": 4.2}, model_dir)


def test_training_run_is_logged_to_the_task_experiment_and_registered_under_its_id(
    client: MlflowClient, model_dir: Path, tmp_path: Path
) -> None:
    task = deployed_task(DYNAMIC_HORIZON_FORECAST)

    tracked = _run(task, model_dir, client, tmp_path)

    run = client.get_run(tracked.run_id)
    experiment = client.get_experiment_by_name(DYNAMIC_HORIZON_FORECAST)
    assert run.info.experiment_id == experiment.experiment_id
    assert run.data.metrics == {"mape": 4.2}
    assert run.data.params["task_id"] == DYNAMIC_HORIZON_FORECAST
    assert run.data.params["model.num_leaves"] == "31"
    versions = client.search_model_versions(f"name='{DYNAMIC_HORIZON_FORECAST}'")
    assert [(str(version.version), version.run_id) for version in versions] == [
        (tracked.model_version, tracked.run_id)
    ]


def test_each_task_owns_a_separate_experiment_and_registered_model(
    client: MlflowClient, model_dir: Path, tmp_path: Path
) -> None:
    task = deployed_task(DYNAMIC_HORIZON_FORECAST)
    other = replace(task, task_id=OTHER_TASK)

    first = _run(task, model_dir, client, tmp_path)
    second = _run(other, model_dir, client, tmp_path)

    first_experiment = client.get_run(first.run_id).info.experiment_id
    second_experiment = client.get_run(second.run_id).info.experiment_id
    assert first_experiment != second_experiment
    assert [v.run_id for v in client.search_model_versions(f"name='{OTHER_TASK}'")] == [
        second.run_id
    ]


def test_retraining_adds_a_new_version_to_the_existing_registered_model(
    client: MlflowClient, model_dir: Path, tmp_path: Path
) -> None:
    task = deployed_task(DYNAMIC_HORIZON_FORECAST)
    _with_local_artifacts(client, task.task_id, tmp_path)

    first = log_training_run(task, {"mape": 4.2}, model_dir)
    second = log_training_run(task, {"mape": 3.9}, model_dir)

    assert (first.model_version, second.model_version) == ("1", "2")
