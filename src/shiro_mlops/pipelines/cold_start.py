"""Cold-start stage of one ML task and what each of its schedules does about it (#288).

Three facts decide it: the minimum-accumulation gate, whether the model directory
holds a model the model store installed, and whether the training record (the
``{task_id}__model`` materialization) exists. Schedules take their decision and
skip reason from here instead of probing those facts themselves, so the stage
names in docs/reference/dagster-schedules.md hold for every schedule.

Only presence counts: no model is loaded and no hash compared. Training installs
the directory before it records the materialization, so comparing hashes would
call every training run's gap between the two a mismatch.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from dagster import AssetKey, DagsterInstance

from shiro_mlops.pipelines.task_names import TaskPipelineNames
from shiro_mlops.tasks.accumulation import AccumulationOutcome, TrainingLoadReadiness
from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.model_store import has_installed_model, model_directory
from shiro_mlops.tasks.runner import TaskRuntime, check_training_readiness


class ColdStartStage(Enum):
    """Where one task stands; exactly one applies.

    The three accumulation stages apply only while neither side holds a model.
    Once a model exists, the stage stays ``TRAINED`` or ``RECORD_DIRECTORY_MISMATCH``
    even if the gate closes again, so the stages are not one linear chain.
    """

    BLOCKED_BY_LEGACY_ROWS = auto()
    ACCUMULATING = auto()
    AWAITING_FIRST_TRAINING = auto()
    TRAINED = auto()
    RECORD_DIRECTORY_MISMATCH = auto()


@dataclass(frozen=True)
class ScheduleDecision:
    """One schedule tick's decision: request a run, or skip for ``skip_reason``."""

    skip_reason: str | None = None

    @property
    def runs(self) -> bool:
        return self.skip_reason is None


@dataclass(frozen=True)
class ModelPresence:
    """Whether the training record and the model directory each hold a model of one task.

    Read without the accumulation gate, so a decision that only needs one side's
    model never queries the load store.
    """

    names: TaskPipelineNames
    directory: Path
    recorded: bool
    installed: bool

    def issuing(self, schedule: str) -> ScheduleDecision:
        """Only the directory counts: issuing loads the model from it and never reads the record."""
        if self.installed:
            return ScheduleDecision()
        if self.recorded:
            return ScheduleDecision(_describe_mismatch(self))
        return ScheduleDecision(
            f"No {self.names.model} materialization yet; {schedule} waits for "
            "the first successful training run."
        )


@dataclass(frozen=True)
class ColdStart:
    """A task's cold-start stage, its reason, and each schedule's decision."""

    models: ModelPresence
    readiness: TrainingLoadReadiness

    @property
    def stage(self) -> ColdStartStage:
        if self.models.recorded and self.models.installed:
            return ColdStartStage.TRAINED
        if self.models.recorded or self.models.installed:
            return ColdStartStage.RECORD_DIRECTORY_MISMATCH
        match self.readiness.outcome:
            case AccumulationOutcome.BLOCKED_BY_LEGACY_ROWS:
                return ColdStartStage.BLOCKED_BY_LEGACY_ROWS
            case AccumulationOutcome.BELOW_MINIMUM_ACCUMULATION:
                return ColdStartStage.ACCUMULATING
            case AccumulationOutcome.MINIMUM_ACCUMULATION_REACHED:
                return ColdStartStage.AWAITING_FIRST_TRAINING

    @property
    def reason(self) -> str:
        names = self.models.names
        match self.stage:
            case ColdStartStage.BLOCKED_BY_LEGACY_ROWS | ColdStartStage.ACCUMULATING:
                return self.readiness.reason
            case ColdStartStage.AWAITING_FIRST_TRAINING:
                return (
                    f"{self.readiness.reason} No model trained yet; the next "
                    f"{names.training_job} run trains the first one."
                )
            case ColdStartStage.TRAINED:
                return (
                    f"Trained: {names.model} has a materialization and "
                    f"{self.models.directory} holds the installed model."
                )
            case ColdStartStage.RECORD_DIRECTORY_MISMATCH:
                return _describe_mismatch(self.models)

    @property
    def training(self) -> ScheduleDecision:
        """Only the gate counts: retraining is itself the remedy for a mismatch."""
        if not self.readiness.ready:
            return ScheduleDecision(self.readiness.reason)
        return ScheduleDecision()

    @property
    def monitoring(self) -> ScheduleDecision:
        """The gate and the training record count; monitoring reads the record's metrics, never the directory."""
        if not self.readiness.ready:
            return ScheduleDecision(self.readiness.reason)
        if self.models.recorded:
            return ScheduleDecision()
        if self.models.installed:
            return ScheduleDecision(_describe_mismatch(self.models))
        names = self.models.names
        return ScheduleDecision(
            f"No {names.model} materialization yet; {names.monitoring_schedule} waits for "
            f"the first successful {names.training_job} run."
        )

    def issuing(self, schedule: str) -> ScheduleDecision:
        """The gate never counts: a model already issued from keeps issuing while the gate is closed."""
        return self.models.issuing(schedule)


def read_model_presence(
    task_id: str, *, instance: DagsterInstance, models_root: Path
) -> ModelPresence:
    """Probe the training record and the model directory; loads no model."""
    names = TaskPipelineNames(task_id)
    return ModelPresence(
        names=names,
        directory=model_directory(models_root, task_id),
        recorded=instance.get_latest_materialization_event(AssetKey(names.model)) is not None,
        installed=has_installed_model(models_root, task_id),
    )


def read_cold_start(
    task: TaskDefinition,
    *,
    runtime: TaskRuntime,
    instance: DagsterInstance,
    models_root: Path,
) -> ColdStart:
    """Read all three facts for one task; the gate is summarized, never the full load history."""
    return ColdStart(
        models=read_model_presence(task.task_id, instance=instance, models_root=models_root),
        readiness=check_training_readiness(task, runtime),
    )


def _describe_mismatch(models: ModelPresence) -> str:
    if models.recorded:
        missing = (
            f"the model directory {models.directory} holds no model installed by the model "
            f"store, while {models.names.model} has a materialization"
        )
    else:
        missing = (
            f"the training record has no {models.names.model} materialization, while "
            f"{models.directory} holds a model"
        )
    return (
        f"Training record and model directory disagree: {missing}. "
        f"Run {models.names.training_job} once to train, install and record a model again."
    )
