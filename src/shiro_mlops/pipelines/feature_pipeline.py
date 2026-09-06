"""Feature pipeline boundaries for retrieval, transformation, and Feast frame building."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy.exc import SQLAlchemyError

from shiro_mlops.core.constants import (
    DATETIME_COL,
    DEFAULT_LAG_HOURS,
    DEFAULT_LOCATION,
    DEFAULT_ROLLING_WINDOWS,
    LOAD_MW_COL,
    LOCATION_COL,
    RELATIVE_HUMIDITY_COL,
    TEMPERATURE_COL,
)
from shiro_mlops.core.datetime_utils import standardize_taiwan_datetime
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.features.transformers import build_feature_pipeline

logger = logging.getLogger(__name__)

STORAGE_TIME_COL = "time"
STORAGE_CREATED_AT_COL = "created_at"
TAIPOWER_EXPORT_LAG_HOURS = (1, 2, 24)
TAIPOWER_EXPORT_ROLLING_WINDOWS = (6, 24)
DEFAULT_TEMPERATURE_CELSIUS = 25.0
DEFAULT_RELATIVE_HUMIDITY_PERCENT = 70.0
NON_LEAKING_LOAD_FILL = 0.0


@dataclass(frozen=True)
class FeatureQueryWindow:
    """Bounded training window used to fetch point-in-time feature sources."""

    start_time: datetime
    end_time: datetime
    location: str | None = None
    lookback_hours: int = max(max(DEFAULT_LAG_HOURS), max(DEFAULT_ROLLING_WINDOWS))

    @property
    def fetch_start_time(self) -> datetime:
        """Inclusive repository start including lag/rolling lookback history."""
        return self.start_time - timedelta(hours=self.lookback_hours)


@dataclass(frozen=True)
class FeastFeatureFrames:
    """Feast-contract DataFrames ready for I/O Manager publication."""

    taipower: pd.DataFrame
    weather: pd.DataFrame


@dataclass(frozen=True)
class FeatureSourceData:
    """Transformer-ready load and weather source frames."""

    load: pd.DataFrame
    weather: pd.DataFrame


@dataclass(frozen=True)
class FallbackFeatureSources:
    """Raw ingestion fallback frames used when persisted repository sources are unavailable."""

    load: pd.DataFrame
    weather: pd.DataFrame


def build_feature_query_window(
    reference_load: pd.DataFrame,
    *,
    location: str | None = None,
    lookback_hours: int | None = None,
) -> FeatureQueryWindow:
    """Derive an explicit time window from a reference load frame.

    Location is only applied when callers pass it explicitly, so multi-location
    repositories remain visible inside the same time bounds.
    """
    if reference_load.empty or DATETIME_COL not in reference_load.columns:
        raise ValueError("reference_load must include a non-empty datetime column")

    datetimes = standardize_taiwan_datetime(reference_load[DATETIME_COL])
    return FeatureQueryWindow(
        start_time=pd.Timestamp(datetimes.min()).to_pydatetime(),
        end_time=pd.Timestamp(datetimes.max()).to_pydatetime(),
        location=location,
        lookback_hours=(
            lookback_hours
            if lookback_hours is not None
            else max(max(DEFAULT_LAG_HOURS), max(DEFAULT_ROLLING_WINDOWS))
        ),
    )


def _to_transformer_input(df: pd.DataFrame) -> pd.DataFrame:
    """Remove storage-only columns and restore the feature datetime name."""
    result = df.copy()
    if STORAGE_TIME_COL in result.columns and DATETIME_COL not in result.columns:
        result = result.rename(columns={STORAGE_TIME_COL: DATETIME_COL})
    return result.drop(columns=[STORAGE_CREATED_AT_COL], errors="ignore")


def _normalize_export_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure an export frame has the shared Feast entity and event-time columns."""
    result = df.copy()
    if LOCATION_COL not in result.columns:
        result[LOCATION_COL] = DEFAULT_LOCATION
    if DATETIME_COL not in result.columns and STORAGE_TIME_COL in result.columns:
        result = result.rename(columns={STORAGE_TIME_COL: DATETIME_COL})
    return result


def _filter_frame_to_window(df: pd.DataFrame, window: FeatureQueryWindow) -> pd.DataFrame:
    """Keep only rows inside the training window and optional location filter."""
    if df.empty:
        return df
    result = df.copy()
    result[DATETIME_COL] = standardize_taiwan_datetime(result[DATETIME_COL])
    mask = (result[DATETIME_COL] >= window.start_time) & (result[DATETIME_COL] <= window.end_time)
    if window.location is not None and LOCATION_COL in result.columns:
        mask &= result[LOCATION_COL] == window.location
    return result.loc[mask].reset_index(drop=True)


def fetch_feature_source_data(
    repository: TimeSeriesRepository,
    fallbacks: FallbackFeatureSources,
    window: FeatureQueryWindow,
) -> FeatureSourceData:
    """根據時間窗口提取特徵來源資料；若資料庫不可用則退回使用落地備援資料。"""
    try:
        persisted_load = repository.fetch_load_range(
            start_time=window.fetch_start_time,
            end_time=window.end_time,
            location=window.location,
        )
        persisted_weather = repository.fetch_weather_range(
            start_time=window.fetch_start_time,
            end_time=window.end_time,
            location=window.location,
        )
    except SQLAlchemyError as error:
        logger.warning(
            "Could not retrieve persisted feature source data; using ingestion outputs: %s",
            error,
            exc_info=True,
        )
        persisted_load = pd.DataFrame()
        persisted_weather = pd.DataFrame()

    load = persisted_load if not persisted_load.empty else fallbacks.load
    weather = persisted_weather if not persisted_weather.empty else fallbacks.weather
    return FeatureSourceData(_to_transformer_input(load), _to_transformer_input(weather))


def transform_feature_source_data(
    source_data: FeatureSourceData,
    window: FeatureQueryWindow | None = None,
) -> pd.DataFrame:
    """Create the model-training feature matrix, optionally clipped to the training window."""
    features = build_feature_pipeline(load_df=source_data.load, weather_df=source_data.weather)
    if window is None:
        return features
    return _filter_frame_to_window(features, window)


def _fill_load_history_without_leakage(series: pd.Series) -> pd.Series:
    """Fill lag/rolling warm-up gaps without borrowing later load observations."""
    return series.ffill().fillna(NON_LEAKING_LOAD_FILL)


def _build_taipower_export(features_df: pd.DataFrame) -> pd.DataFrame:
    """Build the Taipower Feast schema from engineered features."""
    result = _normalize_export_frame(features_df)

    datetime_values = pd.to_datetime(result[DATETIME_COL])
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

    for lag in TAIPOWER_EXPORT_LAG_HOURS:
        column = f"load_mw_lag_{lag}"
        if column not in result.columns:
            result[column] = result.groupby(LOCATION_COL)[LOAD_MW_COL].transform(
                lambda values, lag_hours=lag: _fill_load_history_without_leakage(
                    values.shift(lag_hours)
                )
            )

    for window in TAIPOWER_EXPORT_ROLLING_WINDOWS:
        column = f"load_mw_rolling_mean_{window}"
        if column not in result.columns:
            result[column] = result.groupby(LOCATION_COL)[LOAD_MW_COL].transform(
                lambda values, rolling_window=window: _fill_load_history_without_leakage(
                    values.shift(1).rolling(window=rolling_window, min_periods=1).mean()
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
            pd.to_numeric(result[column], errors="coerce")
            .fillna(NON_LEAKING_LOAD_FILL)
            .astype("float32")
        )
    for column in int_columns:
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0).astype("int64")

    columns = [DATETIME_COL, LOCATION_COL] + float_columns[:6] + int_columns + float_columns[6:]
    return (
        result[columns]
        .drop_duplicates(subset=[DATETIME_COL, LOCATION_COL], keep="last")
        .sort_values([LOCATION_COL, DATETIME_COL])
        .reset_index(drop=True)
    )


def _build_weather_export(weather_df: pd.DataFrame) -> pd.DataFrame:
    """Build the CWA Feast schema from weather source observations."""
    result = _normalize_export_frame(weather_df)
    if TEMPERATURE_COL not in result.columns:
        result[TEMPERATURE_COL] = DEFAULT_TEMPERATURE_CELSIUS
    if RELATIVE_HUMIDITY_COL not in result.columns:
        result[RELATIVE_HUMIDITY_COL] = DEFAULT_RELATIVE_HUMIDITY_PERCENT

    result[TEMPERATURE_COL] = (
        pd.to_numeric(result[TEMPERATURE_COL], errors="coerce")
        .fillna(DEFAULT_TEMPERATURE_CELSIUS)
        .astype("float32")
    )
    result[RELATIVE_HUMIDITY_COL] = (
        pd.to_numeric(result[RELATIVE_HUMIDITY_COL], errors="coerce")
        .fillna(DEFAULT_RELATIVE_HUMIDITY_PERCENT)
        .astype("float32")
    )
    columns = [DATETIME_COL, LOCATION_COL, TEMPERATURE_COL, RELATIVE_HUMIDITY_COL]
    return (
        result[columns]
        .drop_duplicates(subset=[DATETIME_COL, LOCATION_COL], keep="last")
        .sort_values([LOCATION_COL, DATETIME_COL])
        .reset_index(drop=True)
    )


def build_feast_feature_frames(
    features_df: pd.DataFrame,
    weather_df: pd.DataFrame,
) -> FeastFeatureFrames:
    """Build stable Taipower and CWA Feast schemas without choosing a storage target."""
    return FeastFeatureFrames(
        taipower=_build_taipower_export(features_df),
        weather=_build_weather_export(weather_df),
    )
