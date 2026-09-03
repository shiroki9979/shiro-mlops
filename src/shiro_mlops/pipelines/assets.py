"""Dagster Software-Defined Assets for Taipower load forecasting MLOps pipeline."""

import mlflow
import numpy as np
import pandas as pd
from dagster import AssetExecutionContext, Output, asset

from shiro_mlops.core.config import settings
from shiro_mlops.core.constants import (
    DEFAULT_EXPERIMENT_NAME,
    LOAD_MW_COL,
)
from shiro_mlops.data.cwa_client import CWAClient
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.taipower_client import TaipowerClient
from shiro_mlops.features.transformers import build_feature_pipeline
from shiro_mlops.models.evaluator import evaluate_forecast
from shiro_mlops.models.forecaster import LightGBMRecursiveForecaster


def _get_time_series_repo(context: AssetExecutionContext) -> TimeSeriesRepository:
    """Retrieve TimeSeriesRepository from Dagster resources or instantiate default."""
    return getattr(context.resources, "time_series_repo", None) or TimeSeriesRepository()


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

    repo = _get_time_series_repo(context)
    try:
        upserted = repo.upsert_taipower_load(df)
        context.log.info(f"Persisted {upserted} Taipower load records to TimescaleDB.")
    except Exception as e:
        if settings.ENVIRONMENT == "test":
            context.log.warning(f"Database persistence skipped in test environment: {e}")
        else:
            raise

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

    repo = _get_time_series_repo(context)
    try:
        upserted = repo.upsert_cwa_weather(df)
        context.log.info(f"Persisted {upserted} CWA weather records to TimescaleDB.")
    except Exception as e:
        if settings.ENVIRONMENT == "test":
            context.log.warning(f"Database persistence skipped in test environment: {e}")
        else:
            raise

    return df


@asset(
    group_name="features",
    description="Build lag, rolling, calendar, and weather features for model training and Feast",
    required_resource_keys={"time_series_repo"},
)
def engineered_features(
    context: AssetExecutionContext,
    raw_taipower_load_data: pd.DataFrame,
    raw_weather_obs_data: pd.DataFrame,
) -> pd.DataFrame:
    """Asset: Extract clean time-series from TimescaleDB, engineer features, and export Feast Parquet artifacts."""
    repo = _get_time_series_repo(context)

    # 1. Fetch clean time-series from TimescaleDB (fallback to upstream assets if empty)
    try:
        db_load_df = repo.fetch_load_range()
        db_weather_df = repo.fetch_weather_range()
    except Exception as e:
        context.log.warning(
            f"Failed to fetch from repository, falling back to upstream assets: {e}"
        )
        db_load_df = pd.DataFrame()
        db_weather_df = pd.DataFrame()

    load_df = db_load_df.copy() if not db_load_df.empty else raw_taipower_load_data.copy()
    weather_df = db_weather_df.copy() if not db_weather_df.empty else raw_weather_obs_data.copy()

    # 2. Normalize columns
    if "time" in load_df.columns and "datetime" not in load_df.columns:
        load_df = load_df.rename(columns={"time": "datetime"})
    if "time" in weather_df.columns and "datetime" not in weather_df.columns:
        weather_df = weather_df.rename(columns={"time": "datetime"})

    if "created_at" in load_df.columns:
        load_df = load_df.drop(columns=["created_at"])
    if "created_at" in weather_df.columns:
        weather_df = weather_df.drop(columns=["created_at"])

    # 3. Build engineered features
    features_df = build_feature_pipeline(
        load_df=load_df,
        weather_df=weather_df,
    )
    context.log.info(f"Constructed engineered features table with shape: {features_df.shape}")

    # 4. Export Feast Parquet artifacts to settings.DATA_DIR
    data_dir = settings.DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)

    # Compile taipower_features.parquet
    taipower_export_df = features_df.copy()
    if "location" not in taipower_export_df.columns:
        taipower_export_df["location"] = "Taipei"
    if "datetime" not in taipower_export_df.columns and "time" in taipower_export_df.columns:
        taipower_export_df["datetime"] = taipower_export_df["time"]

    dt_series = pd.to_datetime(taipower_export_df["datetime"])

    # Ensure required calendar fields
    if "hour" not in taipower_export_df.columns:
        taipower_export_df["hour"] = dt_series.dt.hour
    if "dayofweek" not in taipower_export_df.columns:
        taipower_export_df["dayofweek"] = dt_series.dt.dayofweek
    if "is_weekend" not in taipower_export_df.columns:
        taipower_export_df["is_weekend"] = (taipower_export_df["dayofweek"] >= 5).astype(int)
    if "hour_sin" not in taipower_export_df.columns:
        taipower_export_df["hour_sin"] = np.sin(2 * np.pi * taipower_export_df["hour"] / 24.0)
    if "hour_cos" not in taipower_export_df.columns:
        taipower_export_df["hour_cos"] = np.cos(2 * np.pi * taipower_export_df["hour"] / 24.0)

    # Ensure required lag fields for Feast schema
    for lag in [1, 2, 24]:
        col_name = f"load_mw_lag_{lag}"
        if col_name not in taipower_export_df.columns:
            taipower_export_df[col_name] = taipower_export_df.groupby("location")[
                "load_mw"
            ].transform(lambda s: s.shift(lag).bfill().ffill())
            if taipower_export_df[col_name].isna().any():
                fallback_val = (
                    float(taipower_export_df["load_mw"].mean())
                    if not taipower_export_df["load_mw"].isna().all()
                    else 0.0
                )
                taipower_export_df[col_name] = taipower_export_df[col_name].fillna(fallback_val)

    # Ensure required rolling fields for Feast schema
    for w in [6, 24]:
        mean_col = f"load_mw_rolling_mean_{w}"
        if mean_col not in taipower_export_df.columns:
            taipower_export_df[mean_col] = taipower_export_df.groupby("location")[
                "load_mw"
            ].transform(
                lambda s: s.shift(1).rolling(window=w, min_periods=1).mean().bfill().ffill()
            )
            if taipower_export_df[mean_col].isna().any():
                fallback_val = (
                    float(taipower_export_df["load_mw"].mean())
                    if not taipower_export_df["load_mw"].isna().all()
                    else 0.0
                )
                taipower_export_df[mean_col] = taipower_export_df[mean_col].fillna(fallback_val)

    float_fields = [
        "load_mw",
        "load_mw_lag_1",
        "load_mw_lag_2",
        "load_mw_lag_24",
        "load_mw_rolling_mean_6",
        "load_mw_rolling_mean_24",
        "hour_sin",
        "hour_cos",
    ]
    int_fields = ["hour", "dayofweek", "is_weekend"]

    for f in float_fields:
        taipower_export_df[f] = (
            pd.to_numeric(taipower_export_df[f], errors="coerce").fillna(0.0).astype("float32")
        )

    for f in int_fields:
        taipower_export_df[f] = (
            pd.to_numeric(taipower_export_df[f], errors="coerce").fillna(0).astype("int64")
        )

    taipower_cols = ["datetime", "location"] + float_fields[:6] + int_fields + float_fields[6:]
    taipower_parquet_path = data_dir / "taipower_features.parquet"
    taipower_export_df = (
        taipower_export_df[taipower_cols]
        .drop_duplicates(subset=["datetime", "location"], keep="last")
        .sort_values(["location", "datetime"])
        .reset_index(drop=True)
    )
    taipower_export_df.to_parquet(taipower_parquet_path, index=False)

    # Compile weather_features.parquet
    weather_export_df = weather_df.copy()
    if "location" not in weather_export_df.columns:
        weather_export_df["location"] = "Taipei"
    if "datetime" not in weather_export_df.columns and "time" in weather_export_df.columns:
        weather_export_df["datetime"] = weather_export_df["time"]

    if "temperature" not in weather_export_df.columns:
        weather_export_df["temperature"] = 25.0
    if "relative_humidity" not in weather_export_df.columns:
        weather_export_df["relative_humidity"] = 70.0

    weather_export_df["temperature"] = (
        pd.to_numeric(weather_export_df["temperature"], errors="coerce")
        .fillna(25.0)
        .astype("float32")
    )
    weather_export_df["relative_humidity"] = (
        pd.to_numeric(weather_export_df["relative_humidity"], errors="coerce")
        .fillna(70.0)
        .astype("float32")
    )

    weather_cols = ["datetime", "location", "temperature", "relative_humidity"]
    weather_parquet_path = data_dir / "weather_features.parquet"
    weather_export_df = (
        weather_export_df[weather_cols]
        .drop_duplicates(subset=["datetime", "location"], keep="last")
        .sort_values(["location", "datetime"])
        .reset_index(drop=True)
    )
    weather_export_df.to_parquet(weather_parquet_path, index=False)

    context.log.info(
        f"Exported Feast Parquet files: {taipower_parquet_path}, {weather_parquet_path}"
    )
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
    model_path = settings.DATA_DIR / "model.joblib"
    forecaster.save(model_path)

    # MLflow logging (safe in test/local environments)
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
