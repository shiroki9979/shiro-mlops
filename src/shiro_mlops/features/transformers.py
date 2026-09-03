"""Time-series feature engineering and transformation functions."""

import numpy as np
import pandas as pd

from shiro_mlops.core.constants import (
    DATETIME_COL,
    DEFAULT_LAG_HOURS,
    DEFAULT_ROLLING_WINDOWS,
    LOAD_MW_COL,
    LOCATION_COL,
    RELATIVE_HUMIDITY_COL,
    TEMPERATURE_COL,
)


def create_calendar_features(df: pd.DataFrame, datetime_col: str = DATETIME_COL) -> pd.DataFrame:
    """Generate cyclical and calendar features from datetime."""
    df = df.copy()
    dt_series = pd.to_datetime(df[datetime_col])

    df["hour"] = dt_series.dt.hour
    df["dayofweek"] = dt_series.dt.dayofweek
    df["month"] = dt_series.dt.month
    df["is_weekend"] = (df["dayofweek"] >= 5).astype(int)

    # Cyclical hour encoding
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24.0)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24.0)

    return df


def create_lag_features(
    df: pd.DataFrame,
    value_col: str = LOAD_MW_COL,
    lags: list[int] | None = None,
    location_col: str = LOCATION_COL,
) -> pd.DataFrame:
    """Generate lag features for the specified target value, isolated per location."""
    df = df.copy()
    if lags is None:
        lags = DEFAULT_LAG_HOURS

    has_location = location_col in df.columns and df[location_col].nunique() > 1

    for lag in lags:
        if has_location:
            df[f"{value_col}_lag_{lag}"] = df.groupby(location_col)[value_col].shift(lag)
        else:
            df[f"{value_col}_lag_{lag}"] = df[value_col].shift(lag)

    return df


def create_rolling_features(
    df: pd.DataFrame,
    value_col: str = LOAD_MW_COL,
    windows: list[int] | None = None,
    location_col: str = LOCATION_COL,
) -> pd.DataFrame:
    """Generate rolling window statistics for the target value, isolated per location."""
    df = df.copy()
    if windows is None:
        windows = DEFAULT_ROLLING_WINDOWS

    has_location = location_col in df.columns and df[location_col].nunique() > 1

    for w in windows:
        if has_location:
            df[f"{value_col}_rolling_mean_{w}"] = df.groupby(location_col)[value_col].transform(
                lambda s: s.shift(1).rolling(window=w, min_periods=1).mean()
            )
            df[f"{value_col}_rolling_std_{w}"] = df.groupby(location_col)[value_col].transform(
                lambda s: s.shift(1).rolling(window=w, min_periods=1).std().fillna(0.0)
            )
        else:
            shifted = df[value_col].shift(1)
            df[f"{value_col}_rolling_mean_{w}"] = shifted.rolling(window=w, min_periods=1).mean()
            df[f"{value_col}_rolling_std_{w}"] = (
                shifted.rolling(window=w, min_periods=1).std().fillna(0.0)
            )

    return df


def merge_weather_features(
    load_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    datetime_col: str = DATETIME_COL,
    location_col: str = LOCATION_COL,
) -> pd.DataFrame:
    """Merge load DataFrame with weather observations or forecasts matching datetime and location."""
    load_df = load_df.copy()
    weather_df = weather_df.copy()

    load_df[datetime_col] = pd.to_datetime(load_df[datetime_col])
    weather_df[datetime_col] = pd.to_datetime(weather_df[datetime_col])

    # Keep weather columns
    weather_cols = [datetime_col]
    both_have_location = location_col in load_df.columns and location_col in weather_df.columns
    if both_have_location:
        weather_cols.append(location_col)

    if TEMPERATURE_COL in weather_df.columns:
        weather_cols.append(TEMPERATURE_COL)
    if RELATIVE_HUMIDITY_COL in weather_df.columns:
        weather_cols.append(RELATIVE_HUMIDITY_COL)

    # Deduplicate weather data on join keys before merge
    join_keys = [datetime_col, location_col] if both_have_location else [datetime_col]
    clean_weather = weather_df[weather_cols].drop_duplicates(subset=join_keys, keep="last")

    merged = pd.merge(load_df, clean_weather, on=join_keys, how="left")

    # Forward fill or fill mean for missing weather values, isolated per location when available
    if TEMPERATURE_COL in merged.columns:
        if location_col in merged.columns and merged[location_col].nunique() > 1:
            merged[TEMPERATURE_COL] = (
                merged.groupby(location_col)[TEMPERATURE_COL]
                .transform(lambda s: s.ffill().bfill())
                .fillna(25.0)
            )
        else:
            merged[TEMPERATURE_COL] = merged[TEMPERATURE_COL].ffill().bfill().fillna(25.0)

    if RELATIVE_HUMIDITY_COL in merged.columns:
        if location_col in merged.columns and merged[location_col].nunique() > 1:
            merged[RELATIVE_HUMIDITY_COL] = (
                merged.groupby(location_col)[RELATIVE_HUMIDITY_COL]
                .transform(lambda s: s.ffill().bfill())
                .fillna(70.0)
            )
        else:
            merged[RELATIVE_HUMIDITY_COL] = (
                merged[RELATIVE_HUMIDITY_COL].ffill().bfill().fillna(70.0)
            )

    return merged


def build_feature_pipeline(
    load_df: pd.DataFrame,
    weather_df: pd.DataFrame | None = None,
    lags: list[int] | None = None,
    windows: list[int] | None = None,
    drop_na: bool = True,
    location_col: str = LOCATION_COL,
) -> pd.DataFrame:
    """End-to-end feature pipeline building calendar, weather, lag, and rolling features isolated by location."""
    df = load_df.copy()

    has_location = location_col in df.columns
    sort_cols = [location_col, DATETIME_COL] if has_location else [DATETIME_COL]
    df = df.sort_values(sort_cols).reset_index(drop=True)

    if weather_df is not None:
        df = merge_weather_features(df, weather_df, location_col=location_col)

    if lags is None:
        if has_location and df[location_col].nunique() > 1:
            min_len = int(df.groupby(location_col).size().min())
        else:
            min_len = len(df)

        if min_len <= max(DEFAULT_LAG_HOURS):
            effective_lags = [lag for lag in DEFAULT_LAG_HOURS if lag < min_len] or [1]
        else:
            effective_lags = DEFAULT_LAG_HOURS
    else:
        effective_lags = lags

    df = create_calendar_features(df)
    df = create_lag_features(
        df, value_col=LOAD_MW_COL, lags=effective_lags, location_col=location_col
    )
    df = create_rolling_features(
        df, value_col=LOAD_MW_COL, windows=windows, location_col=location_col
    )

    if drop_na:
        df = df.dropna().reset_index(drop=True)

    return df
