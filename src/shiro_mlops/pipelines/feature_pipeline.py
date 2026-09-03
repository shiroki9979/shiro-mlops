"""Feature pipeline boundaries for retrieval, transformation, and Feast publication."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from shiro_mlops.core.constants import LOAD_MW_COL
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.features.storage import publish_parquet_feature
from shiro_mlops.features.transformers import build_feature_pipeline


@dataclass(frozen=True)
class FeatureSourceData:
    """Transformer-ready load and weather source frames."""

    load: pd.DataFrame
    weather: pd.DataFrame


@dataclass(frozen=True)
class FeaturePublicationTargets:
    """Destinations for local and optional S3 Feast feature artifacts."""

    data_dir: Path
    offline_store_type: Literal["file", "s3"]
    taipower_uri: str
    weather_uri: str


@dataclass(frozen=True)
class FeaturePublication:
    """Local Feast artifact paths created by a publication."""

    taipower_path: Path
    weather_path: Path


def _to_transformer_input(df: pd.DataFrame) -> pd.DataFrame:
    """Remove storage-only columns and restore the feature datetime name."""
    result = df.copy()
    if "time" in result.columns and "datetime" not in result.columns:
        result = result.rename(columns={"time": "datetime"})
    return result.drop(columns=["created_at"], errors="ignore")


def fetch_feature_source_data(
    repository: TimeSeriesRepository,
    fallback_load: pd.DataFrame,
    fallback_weather: pd.DataFrame,
) -> FeatureSourceData:
    """Fetch persisted sources, falling back to ingestion asset outputs when unavailable."""
    try:
        persisted_load = repository.fetch_load_range()
        persisted_weather = repository.fetch_weather_range()
    except Exception:
        persisted_load = pd.DataFrame()
        persisted_weather = pd.DataFrame()

    load = persisted_load if not persisted_load.empty else fallback_load
    weather = persisted_weather if not persisted_weather.empty else fallback_weather
    return FeatureSourceData(_to_transformer_input(load), _to_transformer_input(weather))


def transform_feature_source_data(source_data: FeatureSourceData) -> pd.DataFrame:
    """Create the existing model-training feature matrix from source observations."""
    return build_feature_pipeline(load_df=source_data.load, weather_df=source_data.weather)


def _build_taipower_export(features_df: pd.DataFrame) -> pd.DataFrame:
    """Build the Taipower Feast schema from engineered features."""
    result = features_df.copy()
    if "location" not in result.columns:
        result["location"] = "Taipei"
    if "datetime" not in result.columns and "time" in result.columns:
        result["datetime"] = result["time"]

    datetime_values = pd.to_datetime(result["datetime"])
    if "hour" not in result.columns:
        result["hour"] = datetime_values.dt.hour
    if "dayofweek" not in result.columns:
        result["dayofweek"] = datetime_values.dt.dayofweek
    if "is_weekend" not in result.columns:
        result["is_weekend"] = (result["dayofweek"] >= 5).astype(int)
    if "hour_sin" not in result.columns:
        result["hour_sin"] = np.sin(2 * np.pi * result["hour"] / 24.0)
    if "hour_cos" not in result.columns:
        result["hour_cos"] = np.cos(2 * np.pi * result["hour"] / 24.0)

    for lag in [1, 2, 24]:
        column = f"load_mw_lag_{lag}"
        if column not in result.columns:
            result[column] = result.groupby("location")[LOAD_MW_COL].transform(
                lambda values: values.shift(lag).bfill().ffill()
            )

    for window in [6, 24]:
        column = f"load_mw_rolling_mean_{window}"
        if column not in result.columns:
            result[column] = result.groupby("location")[LOAD_MW_COL].transform(
                lambda values: (
                    values.shift(1).rolling(window=window, min_periods=1).mean().bfill().ffill()
                )
            )

    float_columns = [
        "load_mw",
        "load_mw_lag_1",
        "load_mw_lag_2",
        "load_mw_lag_24",
        "load_mw_rolling_mean_6",
        "load_mw_rolling_mean_24",
        "hour_sin",
        "hour_cos",
    ]
    int_columns = ["hour", "dayofweek", "is_weekend"]
    for column in float_columns:
        result[column] = (
            pd.to_numeric(result[column], errors="coerce").fillna(0.0).astype("float32")
        )
    for column in int_columns:
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0).astype("int64")

    columns = ["datetime", "location"] + float_columns[:6] + int_columns + float_columns[6:]
    return (
        result[columns]
        .drop_duplicates(subset=["datetime", "location"], keep="last")
        .sort_values(["location", "datetime"])
        .reset_index(drop=True)
    )


def _build_weather_export(weather_df: pd.DataFrame) -> pd.DataFrame:
    """Build the CWA Feast schema from weather source observations."""
    result = weather_df.copy()
    if "location" not in result.columns:
        result["location"] = "Taipei"
    if "datetime" not in result.columns and "time" in result.columns:
        result["datetime"] = result["time"]
    if "temperature" not in result.columns:
        result["temperature"] = 25.0
    if "relative_humidity" not in result.columns:
        result["relative_humidity"] = 70.0

    result["temperature"] = (
        pd.to_numeric(result["temperature"], errors="coerce").fillna(25.0).astype("float32")
    )
    result["relative_humidity"] = (
        pd.to_numeric(result["relative_humidity"], errors="coerce").fillna(70.0).astype("float32")
    )
    columns = ["datetime", "location", "temperature", "relative_humidity"]
    return (
        result[columns]
        .drop_duplicates(subset=["datetime", "location"], keep="last")
        .sort_values(["location", "datetime"])
        .reset_index(drop=True)
    )


def publish_feast_features(
    features_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    targets: FeaturePublicationTargets,
    publisher: Callable[[pd.DataFrame, str], str] = publish_parquet_feature,
) -> FeaturePublication:
    """Publish stable Taipower and CWA Feast Parquet schemas to configured targets."""
    targets.data_dir.mkdir(parents=True, exist_ok=True)
    taipower_features = _build_taipower_export(features_df)
    weather_features = _build_weather_export(weather_df)
    taipower_path = targets.data_dir / "taipower_features.parquet"
    weather_path = targets.data_dir / "weather_features.parquet"
    publisher(taipower_features, str(taipower_path))
    publisher(weather_features, str(weather_path))

    if targets.offline_store_type == "s3":
        publisher(taipower_features, targets.taipower_uri)
        publisher(weather_features, targets.weather_uri)

    return FeaturePublication(taipower_path=taipower_path, weather_path=weather_path)
