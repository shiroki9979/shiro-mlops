"""Dagster Software-Defined Assets for Taipower load forecasting MLOps pipeline."""

from datetime import datetime

import mlflow
import pandas as pd
from dagster import (
    AssetExecutionContext,
    AssetKey,
    AssetOut,
    Backoff,
    Config,
    Failure,
    MetadataValue,
    Output,
    RetryPolicy,
    asset,
    multi_asset,
)

from shiro_mlops.core.config import settings
from shiro_mlops.core.constants import (
    DATETIME_COL,
    DEFAULT_EXPERIMENT_NAME,
    LOAD_MW_COL,
    STORAGE_TIME_COL,
)
from shiro_mlops.core.datetime_utils import TAIWAN_TZ
from shiro_mlops.data.cwa_client import (
    CWAClient,
    CWAForecastRelease,
    CWAObservationBatch,
)
from shiro_mlops.data.hourly_actual_load import (
    REGIONAL_SNAPSHOT_SUM_SOURCE,
    derive_hourly_actual_load,
    recent_completed_hours,
    resolve_evaluation_time,
)
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.taipower_regional_supply_demand import (
    TaipowerRegionalSupplyDemandClient,
    TaipowerRegionalSupplyDemandSnapshot,
)
from shiro_mlops.data.taipower_supply_demand import (
    TaipowerSupplyDemandClient,
    TaipowerSupplyDemandSnapshot,
    resolve_snapshot_observed_at,
)
from shiro_mlops.data.taipower_unit_generation import (
    TaipowerUnitGenerationClient,
    TaipowerUnitGenerationSnapshot,
)
from shiro_mlops.features.feast_export import build_feast_feature_frames
from shiro_mlops.tasks.accumulation import TrainingLoadReadiness
from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task
from shiro_mlops.tasks.model_store import save_model
from shiro_mlops.tasks.runner import (
    TaskNotReady,
    TaskRuntime,
    check_training_readiness,
    load_observed_weather,
    load_training_data,
    train_task,
)
from shiro_mlops.tasks.types.base import Trained, TrainingData


def _get_time_series_repo(context: AssetExecutionContext) -> TimeSeriesRepository:
    """Retrieve TimeSeriesRepository from Dagster resources or instantiate default."""
    return getattr(context.resources, "time_series_repo", None) or TimeSeriesRepository()


def _task() -> TaskDefinition:
    """The task these assets train; the per-task asset factory replaces this (#67)."""
    return deployed_task(DYNAMIC_HORIZON_FORECAST)


def _runtime(context: AssetExecutionContext) -> TaskRuntime:
    return TaskRuntime(repository=_get_time_series_repo(context))


def _taiwan_now() -> datetime:
    """Training decisions are point-in-time at the run's start, in Taiwan-local naive time."""
    return pd.Timestamp.now(tz=TAIWAN_TZ).tz_localize(None).to_pydatetime()


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


def _require_training_data(context: AssetExecutionContext) -> TrainingData:
    try:
        return load_training_data(_task(), _runtime(context), as_of=_taiwan_now())
    except TaskNotReady as error:
        raise _not_ready_failure(error.readiness) from error


def _train(context: AssetExecutionContext, task: TaskDefinition) -> Trained:
    try:
        return train_task(task, _runtime(context), as_of=_taiwan_now())
    except TaskNotReady as error:
        raise _not_ready_failure(error.readiness) from error


def _require_training_readiness(context: AssetExecutionContext) -> TrainingLoadReadiness:
    readiness = check_training_readiness(_task(), _runtime(context))
    if not readiness.ready:
        raise _not_ready_failure(readiness)
    return readiness


class SnapshotObservationConfig(Config):
    """提供選用的排程 tick，讓即時快照共用同一個觀測 slot。"""

    observed_at: str | None = None


class HourlyActualLoadConfig(Config):
    """提供選用的排程 tick，讓重算窗口不受 run 實際啟動延遲影響。"""

    evaluated_at: str | None = None


# 區域快照是全台逐時實際負載的唯一來源且無法回補，故重試比其他即時快照更久；
# Dagster 指數退避等待 (2^n - 1) × delay，即 10、30、70 秒，約 110 秒內結束，
# 仍早於下一個 10 分鐘 slot。
TAIPOWER_REGIONAL_SNAPSHOT_RETRY_POLICY = RetryPolicy(
    max_retries=3,
    delay=10,
    backoff=Backoff.EXPONENTIAL,
)


@asset(
    name="raw_cwa_station_observation",
    group_name="ingestion",
    description="Fetch and persist canonical CWA station observations",
    required_resource_keys={"time_series_repo"},
)
def raw_cwa_station_observation(context: AssetExecutionContext) -> CWAObservationBatch:
    """Asset: canonical CWA station observation batch."""
    client = CWAClient(api_key=settings.CWA_API_KEY)
    batch = client.fetch_observation_batch(locations=settings.cwa_locations)
    repository = _get_time_series_repo(context)
    persisted = repository.upsert_cwa_observation_batch(batch)
    context.log.info("Persisted %s canonical CWA station observations.", persisted)
    if batch.status != "complete":
        missing = ", ".join(batch.missing_station_ids)
        raise RuntimeError(f"CWA observation batch incomplete; missing station IDs: {missing}")
    return batch


@asset(
    name="cwa_observation_feature_source",
    group_name="features",
    description="Read observed weather at the task's weather reference point",
    required_resource_keys={"time_series_repo"},
)
def cwa_observation_feature_source(context: AssetExecutionContext) -> pd.DataFrame:
    """Asset: repository-only observed weather consumed by the Feast export."""
    observations = load_observed_weather(_task(), _runtime(context))
    if observations.empty:
        raise RuntimeError("No canonical CWA station observations available for training")
    return observations


@asset(
    name="raw_cwa_township_forecast",
    group_name="ingestion",
    description="Fetch and persist canonical CWA township forecast vintages",
    required_resource_keys={"time_series_repo"},
)
def raw_cwa_township_forecast(context: AssetExecutionContext) -> list[CWAForecastRelease]:
    """Asset: canonical CWA township forecast releases for three-day and weekly products."""
    client = CWAClient(api_key=settings.CWA_API_KEY)
    repository = _get_time_series_repo(context)
    releases: list[CWAForecastRelease] = []
    missing: dict[str, tuple[str, ...]] = {}
    for dataset_id in ("F-D0047-089", "F-D0047-091"):
        release = client.fetch_forecast_release(dataset_id, locations=settings.cwa_locations)
        releases.append(release)
        if release.status != "complete":
            missing[dataset_id] = release.missing_geocodes
    repository.upsert_cwa_forecast_releases(releases)
    if missing:
        details = "; ".join(
            f"{dataset}: {', '.join(values)}" for dataset, values in missing.items()
        )
        raise RuntimeError(f"CWA forecast release incomplete; missing Geocodes: {details}")
    return releases


@asset(
    group_name="ingestion",
    description="Fetch current Taipower power supply-demand snapshot",
    required_resource_keys={"time_series_repo"},
)
def raw_taipower_supply_demand_snapshot(
    context: AssetExecutionContext,
    config: SnapshotObservationConfig,
) -> TaipowerSupplyDemandSnapshot:
    """Asset: Taipower supply-demand snapshot upserted by observation slot."""
    client = TaipowerSupplyDemandClient(base_url=settings.TAIPOWER_SUPPLY_DEMAND_API_URL)
    snapshot = client.fetch_snapshot(observed_at=resolve_snapshot_observed_at(config.observed_at))
    context.log.info(
        "Fetched supply-demand snapshot for observed_at=%s curr_load=%s",
        snapshot.observed_at.isoformat(),
        snapshot.curr_load_wan_kw,
    )
    _get_time_series_repo(context).upsert_supply_demand_snapshot(snapshot)
    return snapshot


@asset(
    group_name="ingestion",
    description="Fetch current Taipower regional supply-demand snapshots",
    required_resource_keys={"time_series_repo"},
    retry_policy=TAIPOWER_REGIONAL_SNAPSHOT_RETRY_POLICY,
)
def raw_taipower_regional_supply_demand_snapshot(
    context: AssetExecutionContext,
    config: SnapshotObservationConfig,
) -> list[TaipowerRegionalSupplyDemandSnapshot]:
    """Asset: regional supply-demand snapshots upserted by observation slot and region."""
    client = TaipowerRegionalSupplyDemandClient(
        base_url=settings.TAIPOWER_REGIONAL_SUPPLY_DEMAND_API_URL
    )
    snapshots = client.fetch_snapshots(observed_at=resolve_snapshot_observed_at(config.observed_at))
    context.log.info(
        "Fetched %s regional supply-demand snapshots for observed_at=%s",
        len(snapshots),
        snapshots[0].observed_at.isoformat(),
    )
    _get_time_series_repo(context).upsert_regional_supply_demand_snapshots(snapshots)
    return snapshots


@asset(
    group_name="ingestion",
    description="Derive nationwide hourly actual load from regional supply-demand snapshots",
    required_resource_keys={"time_series_repo"},
    deps=[raw_taipower_regional_supply_demand_snapshot],
)
def raw_taipower_load(
    context: AssetExecutionContext,
    config: HourlyActualLoadConfig,
) -> pd.DataFrame:
    """Asset: recompute recent completed hours from stored snapshots and upsert them."""
    window = recent_completed_hours(
        resolve_evaluation_time(config.evaluated_at),
        hours=settings.HOURLY_LOAD_RECOMPUTE_HOURS,
    )
    repository = _get_time_series_repo(context)
    snapshots = repository.fetch_regional_supply_demand_snapshots_by_source_time(
        window.start, window.end
    )
    hourly_load = derive_hourly_actual_load(
        snapshots,
        completed_before=window.end,
        min_samples=settings.HOURLY_LOAD_MIN_SAMPLES,
    )
    upserted = repository.upsert_taipower_load(hourly_load)
    context.log.info(
        "Derived %s of %s hours in [%s, %s) from %s regional snapshots",
        upserted,
        settings.HOURLY_LOAD_RECOMPUTE_HOURS,
        window.start.isoformat(),
        window.end.isoformat(),
        len(snapshots),
    )
    return hourly_load


@asset(
    group_name="ingestion",
    description="Fetch current Taipower unit net-generation snapshots",
    required_resource_keys={"time_series_repo"},
)
def raw_taipower_unit_generation_snapshot(
    context: AssetExecutionContext,
    config: SnapshotObservationConfig,
) -> list[TaipowerUnitGenerationSnapshot]:
    """Asset: unit net-generation snapshots upserted by observation slot and unit identity."""
    client = TaipowerUnitGenerationClient(base_url=settings.TAIPOWER_UNIT_GENERATION_API_URL)
    snapshots = client.fetch_snapshots(observed_at=resolve_snapshot_observed_at(config.observed_at))
    context.log.info(
        "Fetched %s unit-generation snapshots for observed_at=%s",
        len(snapshots),
        snapshots[0].observed_at.isoformat(),
    )
    _get_time_series_repo(context).upsert_unit_generation_snapshots(snapshots)
    return snapshots


@asset(
    group_name="features",
    description="Read the task's derived hourly actual load once minimum accumulation is met",
    required_resource_keys={"time_series_repo"},
    deps=[raw_taipower_load],
)
def taipower_load_feature_source(context: AssetExecutionContext) -> pd.DataFrame:
    """Asset: repository-only load source, so training never reads snapshot tables.

    Fails before any feature or model work when the minimum accumulation is unmet.
    """
    load = _require_training_data(context).load
    context.log.info("Read %s derived hourly actual load rows.", len(load))
    return load


@multi_asset(
    outs={
        "engineered_features": AssetOut(
            group_name="features",
            description="Hourly training table: target load joined with observed weather",
        ),
        "taipower_features": AssetOut(
            group_name="features",
            io_manager_key="feast_io_manager",
            description="Feast Taipower offline Parquet contract",
        ),
        "weather_features": AssetOut(
            group_name="features",
            io_manager_key="feast_io_manager",
            description="Feast CWA weather offline Parquet contract",
        ),
    },
)
def engineered_feature_set(
    context: AssetExecutionContext,
    taipower_load_feature_source: pd.DataFrame,
    cwa_observation_feature_source: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build the training table and Feast frames; the task type engineers its own features."""
    training_table = taipower_load_feature_source.merge(
        cwa_observation_feature_source, on=DATETIME_COL, how="left"
    )
    feast_frames = build_feast_feature_frames(
        taipower_load_feature_source, cwa_observation_feature_source
    )
    context.log.info(
        "Constructed training table with shape %s; Feast frames ready for I/O Manager",
        training_table.shape,
    )
    return training_table, feast_frames.taipower, feast_frames.weather


@asset(
    group_name="modeling",
    description="Train the task through the runner, save its native model, and log to MLflow",
    required_resource_keys={"time_series_repo"},
    deps=[AssetKey("engineered_features")],
)
def trained_forecaster_model(context: AssetExecutionContext) -> Output[dict]:
    """Asset: train with out-of-time validation, persist the model directory, log to MLflow."""
    task = _task()
    trained = _train(context, task)
    metrics = {name: float(value) for name, value in trained.metrics.items()}
    model_dir = save_model(settings.models_dir, task.task_id, trained.model)

    try:
        mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)
        mlflow.set_experiment(settings.MLFLOW_EXPERIMENT_NAME or DEFAULT_EXPERIMENT_NAME)
        with mlflow.start_run(run_name="dagster_daily_training") as run:
            mlflow.log_metrics(metrics)
            mlflow.log_params(_flatten_params(task))
            mlflow.log_artifacts(str(model_dir), artifact_path="model")
            run_id = run.info.run_id
    except Exception as e:
        context.log.warning(f"MLflow logging skipped or failed: {e}")
        run_id = "local_run"

    return Output(
        value={"metrics": metrics, "run_id": run_id, "model_path": str(model_dir)},
        metadata={"mape": metrics["mape"], "rmse": metrics["rmse"], "mae": metrics["mae"]},
    )


def _flatten_params(task: TaskDefinition) -> dict[str, object]:
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


@asset(
    group_name="monitoring",
    description="Evaluate model drift and generate monitoring reports",
    required_resource_keys={"time_series_repo"},
    deps=[raw_taipower_load],
)
def drift_monitoring_report(
    context: AssetExecutionContext,
    trained_forecaster_model: dict,
    engineered_features: pd.DataFrame,
) -> dict:
    """Asset: Summarize the latest model metrics beside the newest persisted actual load.

    Runs hourly, so it reads the valid-hour count and newest row through bounded
    queries instead of the full series; the readiness gate also keeps manual runs
    from reporting while legacy rows or too few hours remain.
    """
    readiness = _require_training_readiness(context)
    latest_actual = (
        _get_time_series_repo(context)
        .fetch_latest_load(subject=_task().subject, source=REGIONAL_SNAPSHOT_SUM_SOURCE)
        .iloc[-1]
    )
    metrics = trained_forecaster_model.get("metrics", {})
    report = {
        "status": "HEALTHY" if metrics.get("mape", 0.0) < 10.0 else "WARNING",
        "metrics": metrics,
        "feature_count": engineered_features.shape[1],
        "sample_count": engineered_features.shape[0],
        "actual_load_hours": readiness.valid_hours,
        "latest_actual_load_time": pd.Timestamp(latest_actual[STORAGE_TIME_COL]).isoformat(),
        "latest_actual_load_mw": float(latest_actual[LOAD_MW_COL]),
    }
    context.log.info(f"Drift monitoring status: {report['status']}")
    return report
