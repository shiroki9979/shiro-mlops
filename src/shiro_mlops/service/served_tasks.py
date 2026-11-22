"""The deployed tasks as this API process serves them: model state, readiness and prediction.

Each task's model is loaded once, keeping the sha256 of the directory version it
was read from, so the process can report what it serves. Failures come back
as two kinds: ``ServingUnavailableError`` (no model, or inputs that cannot support a
prediction right now) and ``ServingFailedError`` (anything unexpected).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import pandas as pd
from sqlalchemy.exc import SQLAlchemyError

from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.deployed import UnknownTaskError
from shiro_mlops.tasks.model_store import load_model_with_sha256
from shiro_mlops.tasks.runner import (
    PredictionOutcome,
    TaskRuntime,
    TaskUnavailableError,
    check_task_ready,
    predict_task,
)
from shiro_mlops.tasks.types.base import TaskModel

MODEL_NOT_LOADED_REASON = "Model is not loaded or trained yet."
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Loaded:
    model: TaskModel
    sha256: str


@dataclass(frozen=True)
class Untrained:
    pass


@dataclass(frozen=True)
class LoadFailed:
    reason: str


ModelState = Loaded | Untrained | LoadFailed


@dataclass(frozen=True)
class TaskModelStatus:
    """What one task's model state tells a caller; ``reason`` is set whenever no model serves."""

    task_type: str
    model_loaded: bool
    model_sha256: str | None
    reason: str | None


@dataclass(frozen=True)
class ServingReadiness:
    """Whether a task can serve a full-horizon prediction now, and in which weather mode."""

    ready: bool
    model_loaded: bool
    mode: str | None = None
    reason: str | None = None


class ServingUnavailableError(RuntimeError):
    """The task cannot predict right now: no model, or inputs that cannot support it."""


class ServingFailedError(RuntimeError):
    """The prediction failed unexpectedly; the traceback is already logged."""


class ServedTasks:
    """Model state, readiness and prediction of every deployed task, keyed by task id.

    A task missing from ``models`` is untrained.
    """

    def __init__(
        self,
        tasks: Mapping[str, TaskDefinition],
        models: Mapping[str, ModelState],
        *,
        repository: TimeSeriesRepository,
        clock: Callable[[], pd.Timestamp],
    ) -> None:
        self._tasks = dict(tasks)
        self._models = dict(models)
        self._runtime = TaskRuntime(repository=repository)
        self._clock = clock

    @classmethod
    def load(
        cls,
        tasks: Mapping[str, TaskDefinition],
        model_root: Path,
        *,
        repository: TimeSeriesRepository,
        clock: Callable[[], pd.Timestamp],
    ) -> Self:
        """Load each task's model with its sha256; a failed load leaves only that task unserved."""
        models = {task_id: _load_state(model_root, task) for task_id, task in tasks.items()}
        return cls(tasks, models, repository=repository, clock=clock)

    def task(self, task_id: str) -> TaskDefinition:
        """One served task definition; unknown ids fail loudly."""
        if task_id not in self._tasks:
            raise UnknownTaskError(
                f"Unknown task {task_id!r}; deployed tasks: {sorted(self._tasks)}"
            )
        return self._tasks[task_id]

    def model_status(self) -> dict[str, TaskModelStatus]:
        return {task_id: self._status(task) for task_id, task in self._tasks.items()}

    def readiness(self, task_id: str) -> ServingReadiness:
        state = self._state(task_id)
        if not isinstance(state, Loaded):
            return ServingReadiness(ready=False, model_loaded=False, reason=_missing_reason(state))
        try:
            readiness = check_task_ready(
                self.task(task_id), state.model, self._runtime, as_of=self._clock()
            )
        except Exception as error:
            logger.exception("Readiness check failed for task %s", task_id)
            return ServingReadiness(ready=False, model_loaded=True, reason=str(error))
        return ServingReadiness(
            ready=readiness.ready, model_loaded=True, mode=readiness.mode, reason=readiness.reason
        )

    def predict(self, task_id: str, *, horizon_hours: int) -> PredictionOutcome:
        state = self._state(task_id)
        if not isinstance(state, Loaded):
            raise ServingUnavailableError(_missing_reason(state))
        try:
            return predict_task(
                self.task(task_id),
                state.model,
                self._runtime,
                as_of=self._clock(),
                horizon_hours=horizon_hours,
            )
        except TaskUnavailableError as error:
            raise ServingUnavailableError(str(error)) from error
        except SQLAlchemyError as error:
            raise ServingUnavailableError(f"Persistence unavailable: {error}") from error
        except Exception as error:
            logger.exception("Prediction failed for task %s", task_id)
            raise ServingFailedError(f"Prediction error: {error}") from error

    def _state(self, task_id: str) -> ModelState:
        return self._models.get(self.task(task_id).task_id, Untrained())

    def _status(self, task: TaskDefinition) -> TaskModelStatus:
        state = self._state(task.task_id)
        if isinstance(state, Loaded):
            return TaskModelStatus(task.task_type, True, state.sha256, None)
        return TaskModelStatus(task.task_type, False, None, _missing_reason(state))


def _load_state(root: Path, task: TaskDefinition) -> ModelState:
    """A broken model leaves only its own task unserved; the other tasks still load."""
    try:
        loaded = load_model_with_sha256(root, task)
    except Exception as error:
        logger.exception("Could not load the %s model from %s.", task.task_id, root)
        return LoadFailed(f"Model failed to load: {type(error).__name__}: {error}")
    if loaded is None:
        return Untrained()
    return Loaded(loaded.model, loaded.sha256)


def _missing_reason(state: Untrained | LoadFailed) -> str:
    return state.reason if isinstance(state, LoadFailed) else MODEL_NOT_LOADED_REASON
