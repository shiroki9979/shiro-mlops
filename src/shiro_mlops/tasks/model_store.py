"""Per-task model directories: the platform assigns ``<root>/<task_id>``; task types own the files.

Only native, non-executable formats are written or read (ADR-0010). A legacy
``model.joblib`` is never loaded; a task without a model directory is simply
untrained until its next training run.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.types import get_task_type
from shiro_mlops.tasks.types.base import TaskModel


def model_directory(root: Path, task_id: str) -> Path:
    """The directory holding the current model of one task."""
    return root / task_id


def save_model(root: Path, task_id: str, model: TaskModel) -> Path:
    """Write the model into a staging directory, then rename it into place.

    Readers therefore never observe a half-written model. POSIX cannot rename a
    directory over a non-empty one, so the previous model is first moved aside;
    only between those two renames is the task briefly without a model.
    """
    root.mkdir(parents=True, exist_ok=True)
    target = model_directory(root, task_id)
    token = uuid.uuid4().hex
    staging = root / f".{task_id}.staging-{token}"
    retired = root / f".{task_id}.retired-{token}"
    try:
        model.save(staging)
        if target.exists():
            target.rename(retired)
        staging.rename(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(retired, ignore_errors=True)
    return target


def load_model(root: Path, task: TaskDefinition) -> TaskModel | None:
    """Load the task's current model, or ``None`` when it has never been trained."""
    directory = model_directory(root, task.task_id)
    if not directory.is_dir():
        return None
    return get_task_type(task.task_type).load(directory)
