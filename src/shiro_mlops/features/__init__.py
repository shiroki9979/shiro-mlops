"""Feature engineering transformers; Feast objects live in ``shiro_mlops.features.definitions``.

The Feast definitions are not re-exported here: importing this package would then import
Feast and build its file sources for every process that only needs the transformers
(each task type, each Dagster step process, the API).
"""

from shiro_mlops.features.transformers import (
    build_feature_pipeline,
    create_calendar_features,
    create_lag_features,
    create_rolling_features,
    merge_weather_features,
)

__all__ = [
    "build_feature_pipeline",
    "create_calendar_features",
    "create_lag_features",
    "create_rolling_features",
    "merge_weather_features",
]
