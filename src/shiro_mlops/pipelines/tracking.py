"""MLflow tracking per ML task: each task owns one experiment and one registered model.

Both names derive from the task id, so adding a task definition adds its own
experiment and registry entry without configuration (ADR-0009).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import mlflow
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

from shiro_mlops.core.config import settings
from shiro_mlops.tasks.definition import TaskDefinition

MODEL_ARTIFACT_PATH = "model"
RESOURCE_ALREADY_EXISTS = "RESOURCE_ALREADY_EXISTS"


@dataclass(frozen=True)
class TrackedRun:
    """Where one training run was recorded."""

    run_id: str
    model_version: str


def log_training_run(
    task: TaskDefinition, metrics: Mapping[str, float], model_dir: Path
) -> TrackedRun:
    """Log metrics, flattened params and the native model files, then register a new version."""
    mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)
    mlflow.set_experiment(task.task_id)
    with mlflow.start_run(run_name=f"{task.task_id}_training") as run:
        mlflow.log_metrics(dict(metrics))
        mlflow.log_params(flatten_params(task))
        mlflow.log_artifacts(str(model_dir), artifact_path=MODEL_ARTIFACT_PATH)
        source = mlflow.get_artifact_uri(MODEL_ARTIFACT_PATH)
    version = _register_version(task.task_id, source, run.info.run_id)
    return TrackedRun(run_id=run.info.run_id, model_version=version)


def flatten_params(task: TaskDefinition) -> dict[str, object]:
    """MLflow params are flat key/value pairs; nested task params become dotted keys."""
    flat: dict[str, object] = {"task_id": task.task_id, "task_type": task.task_type}
    pending = [("", task.params.model_dump())]
    while pending:
        prefix, values = pending.pop()
        for key, value in values.items():
            if isinstance(value, dict):
                pending.append((f"{prefix}{key}.", value))
            else:
                flat[f"{prefix}{key}"] = value
    return flat


def _register_version(name: str, source: str, run_id: str) -> str:
    # 模型以原生檔案記錄（ADR-0010），不是 MLflow logged model；MLflow 3 的 register_model
    # 只接受 logged model，故直接以 artifact URI 建立 model version。
    client = MlflowClient()
    try:
        client.create_registered_model(name)
    except MlflowException as error:
        if error.error_code != RESOURCE_ALREADY_EXISTS:
            raise
    # 各 store 回傳的 version 型別不一（int 或 str），統一為字串。
    return str(client.create_model_version(name, source=source, run_id=run_id).version)
