"""Asset factory: Dagster assets, jobs, and schedules generated per ML task (ADR-0009).

Each task definition yields ``{task_id}__features`` -> ``{task_id}__model`` ->
``{task_id}__monitoring``, a training job and a monitoring job, and their
schedules in Asia/Taipei time. Ingestion assets stay source-centric and shared,
so no task ever triggers an external API or reads snapshot tables. Assets only
talk to the runner; task types never see Dagster
(tests/unit/test_task_type_import_boundary.py).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

import pandas as pd
from dagster import (
    AssetExecutionContext,
    AssetIn,
    AssetKey,
    AssetsDefinition,
    AssetSelection,
    DagsterInstance,
    Failure,
    MetadataValue,
    Output,
    RunRequest,
    ScheduleDefinition,
    ScheduleEvaluationContext,
    SkipReason,
    asset,
    define_asset_job,
    schedule,
)

from shiro_mlops.core.config import settings
from shiro_mlops.core.datetime_utils import TAIWAN_TZ, taiwan_now
from shiro_mlops.pipelines.execution_origin import tick_run_key
from shiro_mlops.pipelines.schedules import CWA_OBSERVATION_ASSET, HOURLY_ACTUAL_LOAD_ASSET
from shiro_mlops.pipelines.tracking import log_training_run
from shiro_mlops.tasks.accumulation import TrainingLoadReadiness
from shiro_mlops.tasks.definition import HOURLY_ACTUAL_LOAD_TARGET, TaskDefinition
from shiro_mlops.tasks.model_store import save_model
from shiro_mlops.tasks.runner import (
    MonitoringReport,
    TaskNotReady,
    TaskRuntime,
    check_training_readiness,
    fit_task,
    load_training_data,
    monitor_task,
    training_data_from_table,
    training_table,
)

TIME_SERIES_REPO = "time_series_repo"
# 目標序列來源對應其推算資產，僅供 lineage；訓練只讀該資產寫入的資料表。
TARGET_SOURCE_ASSETS = {HOURLY_ACTUAL_LOAD_TARGET: HOURLY_ACTUAL_LOAD_ASSET}
# MLflow 不可用時訓練仍保存模型，run 以此標示未被追蹤。
UNTRACKED_RUN_ID = "local_run"
# `{task}__model` materialization metadata：模型版本識別與 MLflow 版本附註（後者可為空）。
MODEL_SHA256_METADATA = "model_sha256"
MLFLOW_MODEL_VERSION_METADATA = "mlflow_model_version"


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


@dataclass(frozen=True)
class TaskPipeline:
    """Everything the factory generates for one task."""

    names: TaskPipelineNames
    assets: tuple[AssetsDefinition, ...]
    # define_asset_job 的回傳型別未由 dagster 公開匯出。
    jobs: tuple[Any, ...]
    schedules: tuple[ScheduleDefinition, ...]


def build_task_pipelines(tasks: Mapping[str, TaskDefinition]) -> tuple[TaskPipeline, ...]:
    """One pipeline per task definition, in task id order."""
    return tuple(build_task_pipeline(tasks, task_id) for task_id in sorted(tasks))


def build_task_pipeline(tasks: Mapping[str, TaskDefinition], task_id: str) -> TaskPipeline:
    """Generate one task's assets, jobs, and schedules from its validated definition."""
    names = TaskPipelineNames(task_id)
    task = tasks[task_id]

    # downstream() 讓只掛在特定任務的資產（如 Feast 匯出）隨該任務訓練，不需另列。
    training_job = define_asset_job(
        name=names.training_job,
        selection=AssetSelection.assets(names.features).downstream(),
        description=f"Read {task_id} training data, train, and report its health",
    )
    monitoring_job = define_asset_job(
        name=names.monitoring_job,
        selection=AssetSelection.assets(names.monitoring),
        description=f"Judge the latest {task_id} model against the newest persisted target",
    )
    return TaskPipeline(
        names=names,
        assets=(
            _features_asset(names, task),
            _model_asset(names, task),
            _monitoring_asset(names, task),
        ),
        jobs=(training_job, monitoring_job),
        schedules=(
            _training_schedule(names, training_job, task),
            _monitoring_schedule(names, monitoring_job, task),
        ),
    )


# --- Assets --------------------------------------------------------------------------------


def _features_asset(names: TaskPipelineNames, task: TaskDefinition) -> AssetsDefinition:
    @asset(
        name=names.features,
        group_name=names.task_id,
        description="Target history with observed weather, read once the minimum accumulation is met",
        required_resource_keys={TIME_SERIES_REPO},
        deps=[AssetKey(TARGET_SOURCE_ASSETS[task.target]), AssetKey(CWA_OBSERVATION_ASSET)],
    )
    def features(context: AssetExecutionContext) -> Output[pd.DataFrame]:
        """Read and gate training data once; the model asset trains from this table."""
        try:
            data = load_training_data(task, _runtime(context), as_of=taiwan_now())
        except TaskNotReady as error:
            raise _not_ready_failure(error.readiness) from error
        table = training_table(data)
        return Output(
            table,
            metadata={
                "rows": MetadataValue.int(len(table)),
                "validation_start": MetadataValue.text(data.validation_start.isoformat()),
            },
        )

    return features


class TrainedModelRecord(TypedDict):
    """Model asset value; the IO manager stores it as JSON, so it loads back as a plain dict.

    Asset signatures keep ``dict``: Dagster type-checks annotations with ``isinstance``,
    which ``TypedDict`` does not support.
    """

    task_id: str
    metrics: dict[str, float]
    run_id: str | None
    model_version: str | None
    model_path: str
    training_rows: int


def _model_asset(names: TaskPipelineNames, task: TaskDefinition) -> AssetsDefinition:
    @asset(
        name=names.model,
        group_name=names.task_id,
        description="Train through the runner, save the native model, and track it in MLflow",
        ins={"features": AssetIn(key=AssetKey(names.features))},
    )
    def model(context: AssetExecutionContext, features: pd.DataFrame) -> Output[dict]:
        trained = fit_task(task, training_data_from_table(task, features))
        metrics = {name: float(value) for name, value in trained.metrics.items()}
        saved = save_model(settings.models_dir, task.task_id, trained.model)
        run_id, model_version = _track(context, task, metrics, saved.directory)
        return Output(
            value=TrainedModelRecord(
                task_id=task.task_id,
                metrics=metrics,
                run_id=run_id,
                model_version=model_version,
                model_path=str(saved.directory),
                training_rows=len(features),
            ),
            metadata={
                **{name: MetadataValue.float(value) for name, value in metrics.items()},
                MODEL_SHA256_METADATA: MetadataValue.text(saved.sha256),
                MLFLOW_MODEL_VERSION_METADATA: (
                    MetadataValue.null()
                    if model_version is None
                    else MetadataValue.text(model_version)
                ),
            },
        )

    return model


@dataclass(frozen=True)
class RecordedModel:
    """What the latest ``{task_id}__model`` materialization recorded about the model it saved."""

    sha256: str | None
    mlflow_model_version: str | None


def latest_recorded_model(instance: DagsterInstance, task_id: str) -> RecordedModel | None:
    """Read the metadata the model asset wrote; ``None`` until the task has trained once.

    Missing, null or empty entries read as ``None``.
    """
    event = instance.get_latest_materialization_event(AssetKey(TaskPipelineNames(task_id).model))
    materialization = event.asset_materialization if event is not None else None
    if materialization is None:
        return None
    metadata = materialization.metadata
    return RecordedModel(
        sha256=_text_metadata(metadata.get(MODEL_SHA256_METADATA)),
        mlflow_model_version=_text_metadata(metadata.get(MLFLOW_MODEL_VERSION_METADATA)),
    )


def _text_metadata(entry: MetadataValue | None) -> str | None:
    if entry is None or not isinstance(entry.value, str) or not entry.value:
        return None
    return entry.value


def _monitoring_asset(names: TaskPipelineNames, task: TaskDefinition) -> AssetsDefinition:
    @asset(
        name=names.monitoring,
        group_name=names.task_id,
        description="Judge the latest model's metrics with the task type's health rule",
        required_resource_keys={TIME_SERIES_REPO},
        ins={"model": AssetIn(key=AssetKey(names.model))},
        deps=[AssetKey(TARGET_SOURCE_ASSETS[task.target])],
    )
    def monitoring(context: AssetExecutionContext, model: dict) -> dict:
        """Hourly report: bounded reads only, so the full history is never re-read."""
        try:
            report = monitor_task(task, _runtime(context), model["metrics"], as_of=taiwan_now())
        except TaskNotReady as error:
            raise _not_ready_failure(error.readiness) from error
        context.log.info(
            "%s health: %s (%s)", names.task_id, report.health.status, report.health.reason
        )
        return _report_payload(report, training_rows=model["training_rows"])

    return monitoring


def _report_payload(report: MonitoringReport, *, training_rows: int) -> dict:
    return {
        "task_id": report.task_id,
        "status": report.health.status.value,
        "health_reason": report.health.reason,
        "metrics": dict(report.metrics),
        "training_rows": training_rows,
        "target_hours": report.target_hours,
        "latest_target_time": report.latest_target_time.isoformat(),
        "latest_target_value": report.latest_target_value,
    }


def _track(
    context: AssetExecutionContext,
    task: TaskDefinition,
    metrics: dict[str, float],
    model_dir: Path,
) -> tuple[str, str | None]:
    """MLflow outages must not discard a trained model; the gap is logged and marked."""
    try:
        tracked = log_training_run(task, metrics, model_dir)
    except Exception as error:  # MLflow 任何失敗都不應讓已保存的模型失效
        context.log.warning(f"MLflow tracking skipped for {task.task_id}: {error}")
        return UNTRACKED_RUN_ID, None
    return tracked.run_id, tracked.model_version


# --- Schedules -----------------------------------------------------------------------------


def _training_schedule(
    names: TaskPipelineNames, job: Any, task: TaskDefinition
) -> ScheduleDefinition:
    @schedule(
        name=names.training_schedule,
        job=job,
        cron_schedule=task.schedule.training,
        execution_timezone=TAIWAN_TZ,
        description=f"Retrain {names.task_id} once its minimum accumulation is met",
        required_resource_keys={TIME_SERIES_REPO},
    )
    def training_schedule(context: ScheduleEvaluationContext) -> RunRequest | SkipReason:
        readiness = _schedule_readiness(context, task)
        if not readiness.ready:
            return SkipReason(readiness.reason)
        return RunRequest(run_key=tick_run_key(context))

    return training_schedule


def _monitoring_schedule(
    names: TaskPipelineNames, job: Any, task: TaskDefinition
) -> ScheduleDefinition:
    no_model_reason = (
        f"No {names.model} materialization yet; {names.monitoring_schedule} waits for "
        f"the first successful {names.training_job} run."
    )

    @schedule(
        name=names.monitoring_schedule,
        job=job,
        cron_schedule=task.schedule.monitoring,
        execution_timezone=TAIWAN_TZ,
        description=f"Report {names.task_id} health once a trained model exists",
        required_resource_keys={TIME_SERIES_REPO},
    )
    def monitoring_schedule(context: ScheduleEvaluationContext) -> RunRequest | SkipReason:
        readiness = _schedule_readiness(context, task)
        if not readiness.ready:
            return SkipReason(readiness.reason)
        if context.instance.get_latest_materialization_event(AssetKey(names.model)) is None:
            return SkipReason(no_model_reason)
        return RunRequest(run_key=tick_run_key(context))

    return monitoring_schedule


# --- Shared helpers ------------------------------------------------------------------------


def _runtime(context: AssetExecutionContext | ScheduleEvaluationContext) -> TaskRuntime:
    return TaskRuntime(repository=getattr(context.resources, TIME_SERIES_REPO))


def _schedule_readiness(
    context: ScheduleEvaluationContext, task: TaskDefinition
) -> TrainingLoadReadiness:
    return check_training_readiness(task, _runtime(context))


def _not_ready_failure(readiness: TrainingLoadReadiness) -> Failure:
    """Translate the runner's domain error into a Dagster Failure carrying the gap."""
    return Failure(
        description=readiness.reason,
        metadata={
            "valid_hours": MetadataValue.int(readiness.valid_hours),
            "required_hours": MetadataValue.int(readiness.required_hours),
            "legacy_rows": MetadataValue.int(readiness.legacy_rows),
        },
    )
