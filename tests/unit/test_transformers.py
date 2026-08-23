"""Unit tests for feature transformation functions."""

import pandas as pd

from shiro_mlops.core.constants import LOAD_MW_COL
from shiro_mlops.features.transformers import (
    build_feature_pipeline,
    create_calendar_features,
    create_lag_features,
    create_rolling_features,
    merge_weather_features,
)


def test_create_calendar_features(taipower_raw_df: pd.DataFrame) -> None:
    """Test cyclical and calendar feature creation."""
    res = create_calendar_features(taipower_raw_df)
    assert "hour" in res.columns
    assert "dayofweek" in res.columns
    assert "is_weekend" in res.columns
    assert "hour_sin" in res.columns
    assert "hour_cos" in res.columns

    # Verify cyclical bounds
    assert res["hour_sin"].between(-1.0, 1.0).all()
    assert res["hour_cos"].between(-1.0, 1.0).all()


def test_create_lag_features(taipower_raw_df: pd.DataFrame) -> None:
    """Test lag feature generation."""
    lags = [1, 2, 24]
    res = create_lag_features(taipower_raw_df, value_col=LOAD_MW_COL, lags=lags)

    for lag in lags:
        col_name = f"{LOAD_MW_COL}_lag_{lag}"
        assert col_name in res.columns
        # First `lag` entries should be NaN
        assert pd.isna(res[col_name].iloc[0])
        # Entry at index `lag` should equal original value at index 0
        assert res[col_name].iloc[lag] == taipower_raw_df[LOAD_MW_COL].iloc[0]


def test_create_rolling_features(taipower_raw_df: pd.DataFrame) -> None:
    """Test rolling window mean and standard deviation features."""
    windows = [6, 24]
    res = create_rolling_features(taipower_raw_df, value_col=LOAD_MW_COL, windows=windows)

    for w in windows:
        assert f"{LOAD_MW_COL}_rolling_mean_{w}" in res.columns
        assert f"{LOAD_MW_COL}_rolling_std_{w}" in res.columns


def test_merge_weather_features(taipower_raw_df: pd.DataFrame, cwa_obs_df: pd.DataFrame) -> None:
    """Test merging load with weather data on datetime."""
    res = merge_weather_features(taipower_raw_df, cwa_obs_df)
    assert "temperature" in res.columns
    assert "relative_humidity" in res.columns
    assert len(res) == len(taipower_raw_df)
    assert not res["temperature"].isna().any()


def test_build_feature_pipeline(taipower_raw_df: pd.DataFrame, cwa_obs_df: pd.DataFrame) -> None:
    """Test complete end-to-end feature pipeline execution."""
    lags = [1, 2]
    windows = [6]
    features_df = build_feature_pipeline(
        load_df=taipower_raw_df,
        weather_df=cwa_obs_df,
        lags=lags,
        windows=windows,
        drop_na=True,
    )

    assert not features_df.empty
    assert LOAD_MW_COL in features_df.columns
    assert f"{LOAD_MW_COL}_lag_1" in features_df.columns
    assert f"{LOAD_MW_COL}_rolling_mean_6" in features_df.columns
    assert "temperature" in features_df.columns
    assert not features_df.isna().any().any()
