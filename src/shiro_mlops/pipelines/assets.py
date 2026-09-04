"""Dagster Software-Defined Assets for Taipower load forecasting MLOps pipeline."""

from collections.abc import Callable

import mlflow
import pandas as pd
from dagster import AssetExecutionContext, AssetOut, Output, asset, multi_asset

from shiro_mlops.core.config import settings
from shiro_mlops.core.constants import (
    DEFAULT_EXPERIMENT_NAME,
    LOAD_MW_COL,
)
from shiro_mlops.data.cwa_client import CWAClient
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.taipower_client import TaipowerClient
from shiro_mlops.models.evaluator import evaluate_forecast
from shiro_mlops.models.forecaster import LightGBMRecursiveForecaster
from shiro_mlops.pipelines.feature_pipeline import (
    build_feast_feature_frames,
    build_feature_query_window,
    fetch_feature_source_data,
    transform_feature_source_data,
)


def _get_time_series_repo(context: AssetExecutionContext) -> TimeSeriesRepository:
    """Retrieve TimeSeriesRepository from Dagster resources or instantiate default."""
    return getattr(context.resources, "time_series_repo", None) or TimeSeriesRepository()


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
    raw_taipower_load_data: pd.DataFrame,
    raw_weather_obs_data: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Compute training features and Feast frames without selecting a storage target."""
    query_window = build_feature_query_window(raw_taipower_load_data)
    source_data = fetch_feature_source_data(
        repository,
        raw_taipower_load_data,
        raw_weather_obs_data,
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
    raw_weather_obs_data: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build training features and Feast frames; I/O Manager selects local or S3 publication."""
    features_df, taipower_features, weather_features = compute_engineered_feature_outputs(
        _get_time_series_repo(context),
        raw_taipower_load_data,
        raw_weather_obs_data,
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
