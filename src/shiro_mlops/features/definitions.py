"""Feast Feature Store Entity and FeatureView definitions."""

from datetime import timedelta

from feast import Entity, FeatureView, Field, FileSource, ValueType
from feast.types import Float32, Int64

from shiro_mlops.core.config import settings

# 1. Location Entity
location_entity = Entity(
    name="location",
    value_type=ValueType.STRING,
    description="Prediction subject (e.g. nationwide); name frozen by ADR-0009",
    join_keys=["location"],
)


# 2. Offline Parquet Sources
def create_load_source(path: str | None = None) -> FileSource:
    """Create Taipower load FileSource reading the feature Parquet under DATA_DIR."""
    target_path = path or settings.taipower_parquet_uri
    return FileSource(
        name="taipower_load_source",
        path=target_path,
        timestamp_field="datetime",
    )


def create_weather_source(path: str | None = None) -> FileSource:
    """Create CWA weather FileSource reading the feature Parquet under DATA_DIR."""
    target_path = path or settings.weather_parquet_uri
    return FileSource(
        name="cwa_weather_source",
        path=target_path,
        timestamp_field="datetime",
    )


load_source = create_load_source()
weather_source = create_weather_source()


# 3. Feature Views
def create_taipower_load_feature_view(source: FileSource | None = None) -> FeatureView:
    """Create taipower_load_features FeatureView."""
    return FeatureView(
        name="taipower_load_features",
        entities=[location_entity],
        ttl=timedelta(days=30),
        schema=[
            Field(name="load_mw", dtype=Float32),
            Field(name="load_mw_lag_1", dtype=Float32),
            Field(name="load_mw_lag_2", dtype=Float32),
            Field(name="load_mw_lag_24", dtype=Float32),
            Field(name="load_mw_rolling_mean_6", dtype=Float32),
            Field(name="load_mw_rolling_mean_24", dtype=Float32),
            Field(name="hour", dtype=Int64),
            Field(name="dayofweek", dtype=Int64),
            Field(name="is_weekend", dtype=Int64),
            Field(name="is_day_off", dtype=Int64),
            Field(name="hour_sin", dtype=Float32),
            Field(name="hour_cos", dtype=Float32),
        ],
        online=True,
        source=source or create_load_source(),
    )


def create_weather_feature_view(source: FileSource | None = None) -> FeatureView:
    """Create cwa_weather_features FeatureView."""
    return FeatureView(
        name="cwa_weather_features",
        entities=[location_entity],
        ttl=timedelta(days=7),
        schema=[
            Field(name="temperature", dtype=Float32),
            Field(name="relative_humidity", dtype=Float32),
        ],
        online=True,
        source=source or create_weather_source(),
    )


taipower_load_feature_view = create_taipower_load_feature_view(load_source)
weather_feature_view = create_weather_feature_view(weather_source)
