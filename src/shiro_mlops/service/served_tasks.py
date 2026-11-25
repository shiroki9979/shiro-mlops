"""The deployed tasks as this API process serves them: model state, readiness and prediction.

Each task's model is loaded once into its state, keeping the sha256 of the directory
version it was read from. ``served_models`` hands callers that state itself, not flags derived from it.
Without a model, the state's ``reason`` is the only source of the text that model
state, readiness and prediction report. Readiness is the closed ``ReadinessState``
union, handed to callers as it is, never as flags. ``_classify`` decides what an error
that escapes the runner means. ``predict_task`` raises the runner's refusal, so a
refused prediction passes through it; ``check_task_ready`` returns its own refusal as
``InputsUnavailable``, so from readiness ``_classify`` sees only persistence and
unexpected errors. Readiness returns the verdict as a state; prediction raises it as
``ServingUnavailableError`` (also raised without a model) or ``ServingFailedError``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Self, assert_never

import pandas as pd
from sqlalchemy.exc import SQLAlchemyError

from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.deployed import UnknownTaskError
from shiro_mlops.tasks.model_store import load_model_with_sha256
from shiro_mlops.tasks.prediction_inputs import TaskUnavailableError
from shiro_mlops.tasks.runner import (
    InputsUnavailable,
    PredictionOutcome,
    Ready,
    TaskRuntime,
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
    reason: ClassVar[str] = MODEL_NOT_LOADED_REASON


@dataclass(frozen=True)
class LoadFailed:
    reason: str


ModelState = Loaded | Untrained | LoadFailed


@dataclass(frozen=True)
class ServedModel:
    """One deployed task's type and the state of its model."""

    task_type: str
    state: ModelState


@dataclass(frozen=True)
class Failed:
    """An unexpected error stopped the readiness check or prediction; its traceback is logged."""

    reason: str


ReadinessState = Untrained | LoadFailed | InputsUnavailable | Failed | Ready


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
        runtime: TaskRuntime,
        clock: Callable[[], pd.Timestamp],
    ) -> None:
        self._tasks = dict(tasks)
        self._models = dict(models)
        self._runtime = runtime
        self._clock = clock

    @classmethod
    def load(
        cls,
        tasks: Mapping[str, TaskDefinition],
        model_root: Path,
        *,
        runtime: TaskRuntime,
        clock: Callable[[], pd.Timestamp],
    ) -> Self:
        """Load each task's model with its sha256; a failed load leaves only that task unserved."""
        models = {task_id: _load_state(model_root, task) for task_id, task in tasks.items()}
        return cls(tasks, models, runtime=runtime, clock=clock)

    def task(self, task_id: str) -> TaskDefinition:
        """One served task definition; unknown ids fail loudly."""
        if task_id not in self._tasks:
            raise UnknownTaskError(
                f"Unknown task {task_id!r}; deployed tasks: {sorted(self._tasks)}"
            )
        return self._tasks[task_id]

    def served_models(self) -> dict[str, ServedModel]:
        return {
            task_id: ServedModel(task.task_type, self._state(task_id))
            for task_id, task in self._tasks.items()
        }

    def readiness(self, task_id: str) -> ReadinessState:
        state = self._state(task_id)
        if not isinstance(state, Loaded):
            return state
        try:
            return check_task_ready(
                self.task(task_id), state.model, self._runtime, as_of=self._clock()
            )
        except Exception as error:
            return _classify(error, activity="Readiness check", task_id=task_id)

    def predict(self, task_id: str, *, horizon_hours: int) -> PredictionOutcome:
        state = self._state(task_id)
        if not isinstance(state, Loaded):
            raise ServingUnavailableError(state.reason)
        try:
            return predict_task(
                self.task(task_id),
                state.model,
                self._runtime,
                as_of=self._clock(),
                horizon_hours=horizon_hours,
            )
        except Exception as error:
            match _classify(error, activity="Prediction", task_id=task_id):
                case InputsUnavailable(reason=reason):
                    raise ServingUnavailableError(reason) from error
                case Failed(reason=reason):
                    raise ServingFailedError(f"Prediction error: {reason}") from error
                case unraised:
                    assert_never(unraised)

    def _state(self, task_id: str) -> ModelState:
        return self._models.get(self.task(task_id).task_id, Untrained())


def _classify(error: Exception, *, activity: str, task_id: str) -> InputsUnavailable | Failed:
    """What an error that escaped the runner means.

    A runner refusal or unreachable persistence leaves the inputs unavailable; anything
    else failed, and only then is the traceback logged. Only ``predict_task`` lets a
    refusal escape: ``check_task_ready`` returns its own as ``InputsUnavailable``.
    """
    match error:
        case TaskUnavailableError():
            return InputsUnavailable(str(error))
        case SQLAlchemyError():
            return InputsUnavailable(f"Persistence unavailable: {error}")
        case _:
            logger.error("%s failed for task %s", activity, task_id, exc_info=error)
            return Failed(str(error))


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
