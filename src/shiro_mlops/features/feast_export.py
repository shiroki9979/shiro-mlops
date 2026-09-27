"""Frozen Feast export for the dynamic horizon forecast task (ADR-0002, ADR-0009).

Feast is frozen and has no production reader, so the export computes its own
fixed schema from raw target load instead of reusing any task's feature recipe.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from shiro_mlops.core.constants import (
    DATETIME_COL,
    LOAD_MW_COL,
    LOCATION_COL,
    NATIONWIDE_SUBJECT,
    RELATIVE_HUMIDITY_COL,
    STORAGE_TIME_COL,
    SUBJECT_COL,
    TEMPERATURE_COL,
)

TAIPOWER_EXPORT_LAG_HOURS = (1, 2, 24)
TAIPOWER_EXPORT_ROLLING_WINDOWS = (6, 24)
DEFAULT_TEMPERATURE_CELSIUS = 25.0
DEFAULT_RELATIVE_HUMIDITY_PERCENT = 70.0
NON_LEAKING_LOAD_FILL = 0.0


@dataclass(frozen=True)
class FeastFeatureFrames:
    """Feast-contract DataFrames ready for I/O Manager publication."""

    taipower: pd.DataFrame
    weather: pd.DataFrame


def _normalize_export_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure an export frame has the event-time column Feast reads."""
    result = df.copy()
    if DATETIME_COL not in result.columns and STORAGE_TIME_COL in result.columns:
        result = result.rename(columns={STORAGE_TIME_COL: DATETIME_COL})
    return result


def _fill_load_history_without_leakage(series: pd.Series) -> pd.Series:
    """Fill lag/rolling warm-up gaps without borrowing later load observations."""
    return series.ffill().fillna(NON_LEAKING_LOAD_FILL)


def _with_subject(load: pd.DataFrame) -> pd.DataFrame:
    """Label unlabelled load frames with the nationwide subject they always represent."""
    if SUBJECT_COL in load.columns:
        return load
    return load.assign(**{SUBJECT_COL: NATIONWIDE_SUBJECT})


def _build_taipower_export(load_df: pd.DataFrame) -> pd.DataFrame:
    """Build the Taipower Feast schema from raw target load.

    The frozen Feast schema keeps its ``location`` entity (ADR-0009); its values
    are prediction subjects.
    """
    result = _normalize_export_frame(_with_subject(load_df))
    result = result.drop(columns=[LOCATION_COL], errors="ignore").rename(
        columns={SUBJECT_COL: LOCATION_COL}
    )
    result[DATETIME_COL] = pd.to_datetime(result[DATETIME_COL])
    result = result.sort_values([LOCATION_COL, DATETIME_COL]).reset_index(drop=True)

    result["hour"] = result[DATETIME_COL].dt.hour
    result["dayofweek"] = result[DATETIME_COL].dt.dayofweek
    result["is_weekend"] = (result["dayofweek"] >= 5).astype(int)
    result["hour_sin"] = np.sin(2 * np.pi * result["hour"] / 24.0)
    result["hour_cos"] = np.cos(2 * np.pi * result["hour"] / 24.0)

    by_subject = result.groupby(LOCATION_COL)[LOAD_MW_COL]
    for lag in TAIPOWER_EXPORT_LAG_HOURS:
        result[f"load_mw_lag_{lag}"] = by_subject.transform(
            lambda values, lag_hours=lag: _fill_load_history_without_leakage(
                values.shift(lag_hours)
            )
        )
    for window in TAIPOWER_EXPORT_ROLLING_WINDOWS:
        result[f"load_mw_rolling_mean_{window}"] = by_subject.transform(
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


def _build_weather_export(weather_df: pd.DataFrame, subjects: list[str]) -> pd.DataFrame:
    """Build the CWA Feast schema from weather source observations.

    Weather rows are keyed by the subjects they represent, so both frozen Feast
    views join on the same ``location`` entity values.
    """
    base = _normalize_export_frame(weather_df).drop(columns=[LOCATION_COL], errors="ignore")
    result = pd.concat(
        [base.assign(**{LOCATION_COL: subject}) for subject in subjects], ignore_index=True
    )
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
    load_df: pd.DataFrame,
    weather_df: pd.DataFrame,
) -> FeastFeatureFrames:
    """Build stable Taipower and CWA Feast schemas without choosing a storage target."""
    taipower = _build_taipower_export(load_df)
    subjects = sorted(taipower[LOCATION_COL].unique()) or [NATIONWIDE_SUBJECT]
    return FeastFeatureFrames(
        taipower=taipower,
        weather=_build_weather_export(weather_df, subjects),
    )
