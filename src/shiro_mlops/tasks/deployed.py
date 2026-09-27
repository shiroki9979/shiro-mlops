"""Task definitions shipped with this package, loaded once per process.

Definitions live beside the code so the image carries them; a bad definition
fails the first call, which Dagster and the API make at startup.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from shiro_mlops.core.config import settings
from shiro_mlops.tasks.definition import TaskDefinition, load_task_definitions

TASK_DEFINITIONS_DIR = Path(__file__).parent
# /predict 為此任務的別名（ADR-0009），故服務層需以 id 指名。
DYNAMIC_HORIZON_FORECAST = "dynamic_horizon_forecast"


@cache
def deployed_tasks() -> dict[str, TaskDefinition]:
    """All shipped task definitions keyed by task id, validated against the CWA catalog."""
    return load_task_definitions(TASK_DEFINITIONS_DIR, settings.cwa_locations)


def deployed_task(task_id: str) -> TaskDefinition:
    """One shipped task definition; unknown ids fail loudly."""
    tasks = deployed_tasks()
    if task_id not in tasks:
        raise KeyError(f"Unknown task {task_id!r}; deployed tasks: {sorted(tasks)}")
    return tasks[task_id]
