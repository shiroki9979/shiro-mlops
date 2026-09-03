"""Unit tests for feature source retrieval, transformation, and publication seams."""

from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.pipelines.feature_pipeline import (
    FeaturePublicationTargets,
    FeatureSourceData,
    fetch_feature_source_data,
    publish_feast_features,
    transform_feature_source_data,
)


def test_fetch_feature_source_data_uses_repository_data_and_normalizes_storage_columns(
    taipower_raw_df: pd.DataFrame, cwa_obs_df: pd.DataFrame
) -> None:
    """Feature retrieval uses persisted data while returning transformer-ready frames."""
    repository = MagicMock(spec=TimeSeriesRepository)
    persisted_load = taipower_raw_df.rename(columns={"datetime": "time"}).assign(
        created_at="2026-08-20T00:00:00Z"
    )
    persisted_weather = cwa_obs_df.rename(columns={"datetime": "time"}).assign(
        created_at="2026-08-20T00:00:00Z"
    )
    repository.fetch_load_range.return_value = persisted_load
    repository.fetch_weather_range.return_value = persisted_weather

    source_data = fetch_feature_source_data(repository, taipower_raw_df, cwa_obs_df)

    assert "datetime" in source_data.load.columns
    assert "datetime" in source_data.weather.columns
    assert "created_at" not in source_data.load.columns
    assert "created_at" not in source_data.weather.columns
    assert source_data.load.equals(taipower_raw_df)
    assert source_data.weather.equals(cwa_obs_df)


def test_transform_feature_source_data_preserves_model_feature_contract(
    taipower_raw_df: pd.DataFrame, cwa_obs_df: pd.DataFrame
) -> None:
    """Feature transformation produces the existing training inputs from source data."""
    features = transform_feature_source_data(FeatureSourceData(taipower_raw_df, cwa_obs_df))

    assert not features.empty
    assert {
        "datetime",
        "load_mw",
        "temperature",
        "relative_humidity",
        "load_mw_lag_1",
        "load_mw_rolling_mean_6",
    }.issubset(features.columns)


def test_publish_feast_features_writes_existing_load_and_weather_contracts(
    tmp_path: Path, taipower_raw_df: pd.DataFrame, cwa_obs_df: pd.DataFrame
) -> None:
    """Feature publication emits independently consumable Feast Parquet artifacts."""
    source_data = FeatureSourceData(taipower_raw_df, cwa_obs_df)
    features = transform_feature_source_data(source_data)
    targets = FeaturePublicationTargets(
        data_dir=tmp_path,
        offline_store_type="file",
        taipower_uri=str(tmp_path / "taipower_features.parquet"),
        weather_uri=str(tmp_path / "weather_features.parquet"),
    )

    publication = publish_feast_features(features, source_data.weather, targets)

    load_features = pd.read_parquet(publication.taipower_path)
    weather_features = pd.read_parquet(publication.weather_path)
    assert list(load_features.columns) == [
        "datetime",
        "location",
        "load_mw",
        "load_mw_lag_1",
        "load_mw_lag_2",
        "load_mw_lag_24",
        "load_mw_rolling_mean_6",
        "load_mw_rolling_mean_24",
        "hour",
        "dayofweek",
        "is_weekend",
        "hour_sin",
        "hour_cos",
    ]
    assert list(weather_features.columns) == [
        "datetime",
        "location",
        "temperature",
        "relative_humidity",
    ]
