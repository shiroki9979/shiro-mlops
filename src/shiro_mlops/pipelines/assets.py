"""Dagster Software-Defined Assets for Taipower load forecasting MLOps pipeline."""

from collections.abc import Callable

import mlflow
import pandas as pd
from dagster import AssetExecutionContext, AssetOut, Config, Output, asset, multi_asset

from shiro_mlops.core.config import settings
from shiro_mlops.core.constants import (
    DEFAULT_EXPERIMENT_NAME,
    DEFAULT_LOCATION,
    LOAD_MW_COL,
)
from shiro_mlops.data.cwa_client import (
    CWAClient,
    CWAForecastRelease,
    CWAObservationBatch,
)
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.taipower_client import TaipowerClient
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
from shiro_mlops.models.evaluator import evaluate_forecast
from shiro_mlops.models.forecaster import LightGBMRecursiveForecaster
from shiro_mlops.pipelines.feature_pipeline import (
    FallbackFeatureSources,
    build_feast_feature_frames,
    build_feature_query_window,
    fetch_feature_source_data,
    transform_feature_source_data,
)


def _get_time_series_repo(context: AssetExecutionContext) -> TimeSeriesRepository:
    """Retrieve TimeSeriesRepository from Dagster resources or instantiate default."""
    return getattr(context.resources, "time_series_repo", None) or TimeSeriesRepository()


class SnapshotObservationConfig(Config):
    """提供選用的排程 tick，讓即時快照共用同一個觀測 slot。"""

    observed_at: str | None = None


def _persist_ingested_data(
    context: AssetExecutionContext,
    df: pd.DataFrame,
    persist: Callable[[pd.DataFrame], int],
    data_name: str,
) -> None:
    """Persist an ingestion asset while preserving the test-environment fallback policy."""
    try:
        upserted = persist(df)
        context.log.info(f"Persisted {upserted} {data_name} records to TimescaleDB.")
    except Exception as error:
        if settings.ENVIRONMENT == "test":
            context.log.warning(f"Database persistence skipped in test environment: {error}")
        else:
            raise


def compute_engineered_feature_outputs(
    repository: TimeSeriesRepository,
    fallbacks: FallbackFeatureSources,
    location: str | None = DEFAULT_LOCATION,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """計算模型訓練特徵矩陣與 Feast 資料合約，儲存目標交由 I/O Manager 決定。"""
    query_window = build_feature_query_window(fallbacks.load, location=location)
    source_data = fetch_feature_source_data(
        repository,
        fallbacks,
        query_window,
    )
    features_df = transform_feature_source_data(source_data, window=query_window)
    feast_frames = build_feast_feature_frames(features_df, source_data.weather)
    return features_df, feast_frames.taipower, feast_frames.weather


@asset(
    group_name="ingestion",
    description="Fetch raw hourly load data from Taipower Open Data",
    required_resource_keys={"time_series_repo"},
)
def raw_taipower_load_data(context: AssetExecutionContext) -> pd.DataFrame:
    """Asset: Raw Taipower load data."""
    client = TaipowerClient(base_url=settings.TAIPOWER_API_URL)
    df = client.fetch_load_data()
    context.log.info(f"Fetched {len(df)} Taipower load records.")

    _persist_ingested_data(
        context, df, _get_time_series_repo(context).upsert_taipower_load, "Taipower load"
    )

    return df


@asset(
    group_name="ingestion",
    description="Fetch raw weather observation data from CWA Open Data",
    required_resource_keys={"time_series_repo"},
)
def raw_weather_obs_data(context: AssetExecutionContext) -> pd.DataFrame:
    """Asset: Raw CWA weather observation data."""
    client = CWAClient(api_key=settings.CWA_API_KEY)
    df = client.fetch_observations()
    context.log.info(f"Fetched {len(df)} CWA weather observation records.")

    _persist_ingested_data(
        context, df, _get_time_series_repo(context).upsert_cwa_weather, "CWA weather"
    )

    return df


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
    description="Read canonical CWA station observations for training features",
    required_resource_keys={"time_series_repo"},
)
def cwa_observation_feature_source(context: AssetExecutionContext) -> pd.DataFrame:
    """Asset: repository-only weather source consumed by feature engineering."""
    observations = _get_time_series_repo(context).fetch_cwa_station_observations()
    if observations.empty:
        raise RuntimeError("No canonical CWA station observations available for training")
    return observations.rename(
        columns={
            "observed_at": "datetime",
            "temperature_c": "temperature",
            "relative_humidity_pct": "relative_humidity",
        }
    )


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
        repository.upsert_cwa_forecast_release(release)
        releases.append(release)
        if release.status != "complete":
            missing[dataset_id] = release.missing_geocodes
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


@multi_asset(
    outs={
        "engineered_features": AssetOut(
            group_name="features",
            description="Lag, rolling, calendar, and weather features for model training",
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
    required_resource_keys={"time_series_repo"},
)
def engineered_feature_set(
    context: AssetExecutionContext,
    raw_taipower_load_data: pd.DataFrame,
    cwa_observation_feature_source: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build training features and Feast frames; I/O Manager selects local or S3 publication."""
    fallbacks = FallbackFeatureSources(
        load=raw_taipower_load_data,
        weather=cwa_observation_feature_source,
    )
    features_df, taipower_features, weather_features = compute_engineered_feature_outputs(
        _get_time_series_repo(context),
        fallbacks,
    )
    context.log.info(
        "Constructed engineered features table with shape %s; Feast frames ready for I/O Manager",
        features_df.shape,
    )
    return features_df, taipower_features, weather_features


@asset(
    group_name="modeling",
    description="Train LightGBM Recursive Forecaster and log artifacts to MLflow",
)
def trained_forecaster_model(
    context: AssetExecutionContext,
    engineered_features: pd.DataFrame,
) -> Output[dict]:
    """Asset: Train recursive forecaster, evaluate with out-of-time validation, and log to MLflow."""
    df = engineered_features.copy()
    split_idx = int(len(df) * 0.8)
    train_df = df.iloc[:split_idx]
    val_df = df.iloc[split_idx:]

    forecaster = getattr(context.resources, "forecaster", None)
    if forecaster is None:
        if settings.ENVIRONMENT == "test":
            forecaster = LightGBMRecursiveForecaster(
                params={"n_estimators": 2, "min_child_samples": 1, "verbose": -1}
            )
        else:
            forecaster = LightGBMRecursiveForecaster()

    forecaster.fit(train_df)

    x_val = val_df[forecaster.feature_names]
    y_val = val_df[LOAD_MW_COL].values
    if len(x_val) > 0 and forecaster.model is not None:
        y_pred = forecaster.model.predict(x_val)
        metrics = evaluate_forecast(y_val, y_pred)
    else:
        metrics = {"mape": 0.0, "rmse": 0.0, "mae": 0.0}

    model_path = settings.DATA_DIR / "model.joblib"
    forecaster.save(model_path)

    try:
        mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)
        mlflow.set_experiment(settings.MLFLOW_EXPERIMENT_NAME or DEFAULT_EXPERIMENT_NAME)
        with mlflow.start_run(run_name="dagster_daily_training") as run:
            mlflow.log_metrics(metrics)
            mlflow.log_params(forecaster.params)
            mlflow.log_artifact(str(model_path), artifact_path="model")
            run_id = run.info.run_id
    except Exception as e:
        context.log.warning(f"MLflow logging skipped or failed: {e}")
        run_id = "local_run"

    return Output(
        value={"metrics": metrics, "run_id": run_id, "model_path": str(model_path)},
        metadata={"mape": metrics["mape"], "rmse": metrics["rmse"], "mae": metrics["mae"]},
    )


@asset(
    group_name="monitoring",
    description="Evaluate model drift and generate monitoring reports",
)
def drift_monitoring_report(
    context: AssetExecutionContext,
    trained_forecaster_model: dict,
    engineered_features: pd.DataFrame,
) -> dict:
    """Asset: Calculate summary metrics and generate drift report metadata."""
    metrics = trained_forecaster_model.get("metrics", {})
    report = {
        "status": "HEALTHY" if metrics.get("mape", 0.0) < 10.0 else "WARNING",
        "metrics": metrics,
        "feature_count": engineered_features.shape[1],
        "sample_count": engineered_features.shape[0],
    }
    context.log.info(f"Drift monitoring status: {report['status']}")
    return report
