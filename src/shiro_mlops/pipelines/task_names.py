"""Dagster names of the assets, jobs and schedules the asset factory generates per task."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskPipelineNames:
    """Dagster names derived from a task id; the ``__`` separator keeps them task-scoped."""

    task_id: str

    @property
    def features(self) -> str:
        return f"{self.task_id}__features"

    @property
    def model(self) -> str:
        return f"{self.task_id}__model"

    @property
    def monitoring(self) -> str:
        return f"{self.task_id}__monitoring"

    @property
    def training_job(self) -> str:
        return f"{self.task_id}__training_job"

    @property
    def monitoring_job(self) -> str:
        return f"{self.task_id}__monitoring_job"

    @property
    def training_schedule(self) -> str:
        return f"{self.task_id}__training_schedule"

    @property
    def monitoring_schedule(self) -> str:
        return f"{self.task_id}__monitoring_schedule"
