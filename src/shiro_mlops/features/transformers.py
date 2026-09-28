"""Time-series feature engineering and transformation functions."""

from collections.abc import Sequence
from datetime import timedelta

import numpy as np
import pandas as pd

from shiro_mlops.core.constants import (
    DATETIME_COL,
    LOAD_MW_COL,
    LOCATION_COL,
    RELATIVE_HUMIDITY_COL,
    TEMPERATURE_COL,
)
from shiro_mlops.core.datetime_utils import standardize_taiwan_datetime

MAX_WEATHER_AGE = timedelta(hours=2)


def create_calendar_features(df: pd.DataFrame, datetime_col: str = DATETIME_COL) -> pd.DataFrame:
    """Generate cyclical and calendar features from datetime."""
    df = df.copy()
    dt_series = standardize_taiwan_datetime(df[datetime_col])

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
    *,
    lags: Sequence[int],
    value_col: str = LOAD_MW_COL,
    location_col: str = LOCATION_COL,
) -> pd.DataFrame:
    """Generate hour-aligned lag features, isolated per location."""
    df = df.copy()
    for lag in lags:
        df[f"{value_col}_lag_{lag}"] = np.nan

    groups = df.groupby(location_col, sort=False) if location_col in df.columns else [(None, df)]
    for _, rows in groups:
        times = pd.DatetimeIndex(standardize_taiwan_datetime(rows[DATETIME_COL]))
        observed = pd.Series(rows[value_col].to_numpy(), index=times)
        for lag in lags:
            earlier = times - pd.Timedelta(lag, unit="h")
            df.loc[rows.index, f"{value_col}_lag_{lag}"] = observed.reindex(earlier).to_numpy()

    return df


def create_rolling_features(
    df: pd.DataFrame,
    *,
    windows: Sequence[int],
    value_col: str = LOAD_MW_COL,
    location_col: str = LOCATION_COL,
) -> pd.DataFrame:
    """Generate statistics over elapsed past hours, isolated per location."""
    df = df.copy()
    for w in windows:
        df[f"{value_col}_rolling_mean_{w}"] = np.nan
        df[f"{value_col}_rolling_std_{w}"] = np.nan

    groups = df.groupby(location_col, sort=False) if location_col in df.columns else [(None, df)]
    for _, rows in groups:
        times = pd.DatetimeIndex(standardize_taiwan_datetime(rows[DATETIME_COL]))
        observed = pd.Series(rows[value_col].to_numpy(), index=times).sort_index()
        for w in windows:
            past = observed.rolling(pd.Timedelta(w, unit="h"), closed="left", min_periods=1)
            df.loc[rows.index, f"{value_col}_rolling_mean_{w}"] = (
                past.mean().reindex(times).to_numpy()
            )
            df.loc[rows.index, f"{value_col}_rolling_std_{w}"] = (
                past.std().where(past.count().ne(1), 0.0).reindex(times).to_numpy()
            )

    return df


def merge_weather_features(
    load_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    datetime_col: str = DATETIME_COL,
    location_col: str = LOCATION_COL,
) -> pd.DataFrame:
    """Merge each load hour with the latest weather within two hours; older gaps stay missing."""
    load_df = load_df.copy()
    weather_df = weather_df.copy()

    load_df[datetime_col] = standardize_taiwan_datetime(load_df[datetime_col])
    weather_df[datetime_col] = standardize_taiwan_datetime(weather_df[datetime_col])

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

    return _merge_recent_weather(load_df, clean_weather, join_keys)


def _merge_recent_weather(
    load: pd.DataFrame, weather: pd.DataFrame, join_keys: list[str]
) -> pd.DataFrame:
    """Match each field to a past observation within two hours, even across load gaps."""
    result = load.copy()
    datetime_col = join_keys[0]
    ordered_load = load[join_keys].sort_values(datetime_col)
    for column in (TEMPERATURE_COL, RELATIVE_HUMIDITY_COL):
        if column not in weather.columns:
            result[column] = np.nan
            continue
        observations = weather[join_keys + [column]].dropna(subset=[column])
        matched = pd.merge_asof(
            ordered_load,
            observations.sort_values(datetime_col),
            on=datetime_col,
            by=join_keys[1:] or None,
            direction="backward",
            tolerance=MAX_WEATHER_AGE,
        )
        result[column] = pd.Series(matched[column].to_numpy(), index=ordered_load.index)
    return result


def fill_load_warmup(
    df: pd.DataFrame,
    *,
    lags: Sequence[int],
    windows: Sequence[int],
    location_col: str = LOCATION_COL,
) -> pd.DataFrame:
    """Use zero only where the requested load history predates the first observation."""
    df = df.copy()
    groups = df.groupby(location_col, sort=False) if location_col in df.columns else [(None, df)]
    for _, rows in groups:
        first_time = rows[DATETIME_COL].min()
        for lag in lags:
            warmup = rows[DATETIME_COL] - pd.Timedelta(lag, unit="h") < first_time
            index = rows.index[warmup]
            column = f"{LOAD_MW_COL}_lag_{lag}"
            df.loc[index, column] = df.loc[index, column].fillna(0.0)
        first_index = rows.index[rows[DATETIME_COL] == first_time]
        for window in windows:
            for statistic in ("mean", "std"):
                column = f"{LOAD_MW_COL}_rolling_{statistic}_{window}"
                df.loc[first_index, column] = df.loc[first_index, column].fillna(0.0)
    return df


def build_feature_pipeline(
    load_df: pd.DataFrame,
    weather_df: pd.DataFrame | None = None,
    *,
    lags: Sequence[int],
    windows: Sequence[int],
    drop_na: bool = True,
    location_col: str = LOCATION_COL,
) -> pd.DataFrame:
    """End-to-end feature pipeline building calendar, weather, lag, and rolling features isolated by location."""
    df = load_df.copy()
    df[DATETIME_COL] = standardize_taiwan_datetime(df[DATETIME_COL])

    has_location = location_col in df.columns
    sort_cols = [location_col, DATETIME_COL] if has_location else [DATETIME_COL]
    df = df.sort_values(sort_cols).reset_index(drop=True)

    if weather_df is not None:
        df = merge_weather_features(df, weather_df, location_col=location_col)

    if has_location and df[location_col].nunique() > 1:
        min_len = int(df.groupby(location_col).size().min())
    else:
        min_len = len(df)

    effective_lags = list(lags)
    effective_windows = list(windows)

    df = create_calendar_features(df)
    df = create_lag_features(
        df, value_col=LOAD_MW_COL, lags=effective_lags, location_col=location_col
    )
    df = create_rolling_features(
        df, value_col=LOAD_MW_COL, windows=effective_windows, location_col=location_col
    )

    is_short_window = min_len <= max(effective_lags)
    if is_short_window or not drop_na:
        df = fill_load_warmup(
            df, lags=effective_lags, windows=effective_windows, location_col=location_col
        )

    if drop_na and not is_short_window:
        df = df.dropna().reset_index(drop=True)
    elif drop_na and is_short_window:
        load_feature_cols = [
            col
            for col in df.columns
            if col.startswith(f"{LOAD_MW_COL}_lag_") or col.startswith(f"{LOAD_MW_COL}_rolling_")
        ]
        weather_columns = [
            column for column in (TEMPERATURE_COL, RELATIVE_HUMIDITY_COL) if column in df.columns
        ]
        df = df.dropna(subset=load_feature_cols + weather_columns).reset_index(drop=True)

    return df
