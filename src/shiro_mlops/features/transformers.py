"""Time-series feature engineering and transformation functions."""

import numpy as np
import pandas as pd

from shiro_mlops.core.constants import (
    DATETIME_COL,
    DEFAULT_LAG_HOURS,
    DEFAULT_ROLLING_WINDOWS,
    LOAD_MW_COL,
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
) -> pd.DataFrame:
    """Generate lag features for the specified target value."""
    df = df.copy()
    if lags is None:
        lags = DEFAULT_LAG_HOURS

    for lag in lags:
        df[f"{value_col}_lag_{lag}"] = df[value_col].shift(lag)

    return df


def create_rolling_features(
    df: pd.DataFrame,
    value_col: str = LOAD_MW_COL,
    windows: list[int] | None = None,
) -> pd.DataFrame:
    """Generate rolling window statistics (mean, std) for the target value."""
    df = df.copy()
    if windows is None:
        windows = DEFAULT_ROLLING_WINDOWS

    for w in windows:
        # Shift 1 to prevent data leakage of the current step
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
) -> pd.DataFrame:
    """Merge load DataFrame with weather observations or forecasts."""
    load_df = load_df.copy()
    weather_df = weather_df.copy()

    load_df[datetime_col] = pd.to_datetime(load_df[datetime_col])
    weather_df[datetime_col] = pd.to_datetime(weather_df[datetime_col])

    # Keep weather columns
    weather_cols = [datetime_col]
    if TEMPERATURE_COL in weather_df.columns:
        weather_cols.append(TEMPERATURE_COL)
    if RELATIVE_HUMIDITY_COL in weather_df.columns:
        weather_cols.append(RELATIVE_HUMIDITY_COL)

    merged = pd.merge(load_df, weather_df[weather_cols], on=datetime_col, how="left")

    # Forward fill or fill mean for missing weather values
    if TEMPERATURE_COL in merged.columns:
        merged[TEMPERATURE_COL] = merged[TEMPERATURE_COL].ffill().bfill().fillna(25.0)
    if RELATIVE_HUMIDITY_COL in merged.columns:
        merged[RELATIVE_HUMIDITY_COL] = merged[RELATIVE_HUMIDITY_COL].ffill().bfill().fillna(70.0)

    return merged


def build_feature_pipeline(
    load_df: pd.DataFrame,
    weather_df: pd.DataFrame | None = None,
    lags: list[int] | None = None,
    windows: list[int] | None = None,
    drop_na: bool = True,
) -> pd.DataFrame:
    """End-to-end feature pipeline building calendar, weather, lag, and rolling features."""
    df = load_df.copy()
    df = df.sort_values(DATETIME_COL).reset_index(drop=True)

    if weather_df is not None:
        df = merge_weather_features(df, weather_df)

    if lags is None:
        if len(df) <= max(DEFAULT_LAG_HOURS):
            effective_lags = [lag for lag in DEFAULT_LAG_HOURS if lag < len(df)] or [1]
        else:
            effective_lags = DEFAULT_LAG_HOURS
    else:
        effective_lags = lags

    df = create_calendar_features(df)
    df = create_lag_features(df, value_col=LOAD_MW_COL, lags=effective_lags)

    df = create_rolling_features(df, value_col=LOAD_MW_COL, windows=windows)

    if drop_na:
        df = df.dropna().reset_index(drop=True)

    return df
