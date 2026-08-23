"""Feast Feature Store Entity and FeatureView definitions."""

from datetime import timedelta

from feast import Entity, FeatureView, Field, FileSource, ValueType
from feast.types import Float32, Int64

# 1. Location Entity
location_entity = Entity(
    name="location",
    value_type=ValueType.STRING,
    description="Geographical region or grid location (e.g. Taipei)",
    join_keys=["location"],
)

# 2. Offline Parquet Sources
load_source = FileSource(
    name="taipower_load_source",
    path="data/taipower_features.parquet",
    timestamp_field="datetime",
)

weather_source = FileSource(
    name="cwa_weather_source",
    path="data/weather_features.parquet",
    timestamp_field="datetime",
)

# 3. Feature Views
taipower_load_feature_view = FeatureView(
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
        Field(name="hour_sin", dtype=Float32),
        Field(name="hour_cos", dtype=Float32),
    ],
    online=True,
    source=load_source,
)

weather_feature_view = FeatureView(
    name="cwa_weather_features",
    entities=[location_entity],
    ttl=timedelta(days=7),
    schema=[
        Field(name="temperature", dtype=Float32),
        Field(name="relative_humidity", dtype=Float32),
    ],
    online=True,
    source=weather_source,
)
