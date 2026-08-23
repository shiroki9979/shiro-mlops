"""Dagster Software-Defined Assets for Taipower load forecasting MLOps pipeline."""

from pathlib import Path

import mlflow
import pandas as pd
from dagster import AssetExecutionContext, Output, asset

from shiro_mlops.core.config import settings
from shiro_mlops.core.constants import (
    DEFAULT_EXPERIMENT_NAME,
    LOAD_MW_COL,
)
from shiro_mlops.data.cwa_client import CWAClient
from shiro_mlops.data.taipower_client import TaipowerClient
from shiro_mlops.features.transformers import build_feature_pipeline
from shiro_mlops.models.evaluator import evaluate_forecast
from shiro_mlops.models.forecaster import LightGBMRecursiveForecaster


@asset(group_name="ingestion", description="Fetch raw hourly load data from Taipower Open Data")
def raw_taipower_load_data(context: AssetExecutionContext) -> pd.DataFrame:
    """Asset: Raw Taipower load data."""
    client = TaipowerClient(api_url=settings.TAIPOWER_API_URL)
    df = client.fetch_load_data()
    context.log.info(f"Fetched {len(df)} Taipower load records.")
    return df


@asset(group_name="ingestion", description="Fetch raw weather observation data from CWA Open Data")
def raw_weather_obs_data(context: AssetExecutionContext) -> pd.DataFrame:
    """Asset: Raw CWA weather observation data."""
    client = CWAClient(api_key=settings.CWA_API_KEY)
    df = client.fetch_observations()
    context.log.info(f"Fetched {len(df)} CWA weather observation records.")
    return df


@asset(
    group_name="features",
    description="Build lag, rolling, calendar, and weather features for model training",
)
def engineered_features(
    context: AssetExecutionContext,
    raw_taipower_load_data: pd.DataFrame,
    raw_weather_obs_data: pd.DataFrame,
) -> pd.DataFrame:
    """Asset: Engineered feature table for offline training and Feast."""
    features_df = build_feature_pipeline(
        load_df=raw_taipower_load_data,
        weather_df=raw_weather_obs_data,
    )
    context.log.info(f"Constructed engineered features table with shape: {features_df.shape}")
    return features_df


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

    forecaster = LightGBMRecursiveForecaster()
    forecaster.fit(train_df)

    # Evaluate on validation set
    x_val = val_df[forecaster.feature_names]
    y_val = val_df[LOAD_MW_COL].values
    y_pred = forecaster.model.predict(x_val)

    metrics = evaluate_forecast(y_val, y_pred)
    context.log.info(f"Validation metrics: {metrics}")

    # MLflow logging (safe in test/local environments)
    try:
        mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)
        mlflow.set_experiment(settings.MLFLOW_EXPERIMENT_NAME or DEFAULT_EXPERIMENT_NAME)
        with mlflow.start_run(run_name="dagster_daily_training") as run:
            mlflow.log_metrics(metrics)
            mlflow.log_params(forecaster.params)
            model_path = Path("data/model.joblib")
            forecaster.save(model_path)
            mlflow.log_artifact(str(model_path), artifact_path="model")
            run_id = run.info.run_id
    except Exception as e:
        context.log.warning(f"MLflow logging skipped or failed: {e}")
        model_path = Path("data/model.joblib")
        forecaster.save(model_path)
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
