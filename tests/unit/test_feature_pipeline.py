"""Unit tests for feature source retrieval, transformation, and Feast frame seams."""

from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest
from sqlalchemy.exc import SQLAlchemyError

from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.pipelines.feature_pipeline import (
    FeatureQueryWindow,
    FeatureSourceData,
    build_feast_feature_frames,
    build_feature_query_window,
    fetch_feature_source_data,
    transform_feature_source_data,
)


def _sample_window() -> FeatureQueryWindow:
    return FeatureQueryWindow(
        start_time=datetime(2026, 8, 20, 0, 0, 0),
        end_time=datetime(2026, 8, 21, 23, 0, 0),
        location="Taipei",
        lookback_hours=24,
    )


def test_fetch_feature_source_data_uses_bounded_window_and_normalizes_storage_columns(
    taipower_raw_df: pd.DataFrame, cwa_obs_df: pd.DataFrame
) -> None:
    """Feature retrieval queries a bounded time/location window, not an unbounded scan."""
    repository = MagicMock(spec=TimeSeriesRepository)
    persisted_load = taipower_raw_df.rename(columns={"datetime": "time"}).assign(
        created_at="2026-08-20T00:00:00Z"
    )
    persisted_weather = cwa_obs_df.rename(columns={"datetime": "time"}).assign(
        created_at="2026-08-20T00:00:00Z"
    )
    repository.fetch_load_range.return_value = persisted_load
    repository.fetch_weather_range.return_value = persisted_weather
    window = _sample_window()

    source_data = fetch_feature_source_data(repository, taipower_raw_df, cwa_obs_df, window)

    assert "datetime" in source_data.load.columns
    assert "datetime" in source_data.weather.columns
    assert "created_at" not in source_data.load.columns
    assert "created_at" not in source_data.weather.columns
    assert source_data.load.equals(taipower_raw_df)
    assert source_data.weather.equals(cwa_obs_df)
    repository.fetch_load_range.assert_called_once_with(
        start_time=window.fetch_start_time,
        end_time=window.end_time,
        location=window.location,
    )
    repository.fetch_weather_range.assert_called_once_with(
        start_time=window.fetch_start_time,
        end_time=window.end_time,
        location=window.location,
    )


def test_fetch_feature_source_data_logs_and_falls_back_when_repository_is_unavailable(
    caplog, taipower_raw_df: pd.DataFrame, cwa_obs_df: pd.DataFrame
) -> None:
    """Feature retrieval preserves ingestion data when TimescaleDB is unavailable."""
    repository = MagicMock(spec=TimeSeriesRepository)
    repository.fetch_load_range.side_effect = SQLAlchemyError("TimescaleDB unavailable")

    source_data = fetch_feature_source_data(
        repository, taipower_raw_df, cwa_obs_df, _sample_window()
    )

    assert source_data.load.equals(taipower_raw_df)
    assert source_data.weather.equals(cwa_obs_df)
    assert "TimescaleDB unavailable" in caplog.text


def test_fetch_feature_source_data_propagates_unexpected_repository_errors(
    taipower_raw_df: pd.DataFrame, cwa_obs_df: pd.DataFrame
) -> None:
    """Feature retrieval exposes non-database failures for diagnosis."""
    repository = MagicMock(spec=TimeSeriesRepository)
    repository.fetch_load_range.side_effect = RuntimeError("Unexpected repository failure")

    with pytest.raises(RuntimeError, match="Unexpected repository failure"):
        fetch_feature_source_data(repository, taipower_raw_df, cwa_obs_df, _sample_window())


def test_build_feature_query_window_expands_start_by_lookback(
    taipower_raw_df: pd.DataFrame,
) -> None:
    """Training windows derive an explicit fetch start that includes lag lookback."""
    window = build_feature_query_window(taipower_raw_df, location="Taipei", lookback_hours=24)

    assert window.location == "Taipei"
    assert window.lookback_hours == 24
    assert window.fetch_start_time == window.start_time - pd.Timedelta(hours=24)
    assert window.start_time == pd.Timestamp(taipower_raw_df["datetime"].min())
    assert window.end_time == pd.Timestamp(taipower_raw_df["datetime"].max())


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


def test_feast_export_lag_features_do_not_use_future_load() -> None:
    """Feast export warm-up lags must use a non-leaking sentinel, not later load values."""
    load_df = pd.DataFrame(
        [
            {"datetime": "2026-08-20 00:00:00", "load_mw": 100.0, "location": "Taipei"},
            {"datetime": "2026-08-20 01:00:00", "load_mw": 200.0, "location": "Taipei"},
            {"datetime": "2026-08-20 02:00:00", "load_mw": 300.0, "location": "Taipei"},
            {"datetime": "2026-08-20 03:00:00", "load_mw": 8888.0, "location": "Taipei"},
        ]
    )
    weather_df = pd.DataFrame(
        [
            {
                "datetime": f"2026-08-20 0{i}:00:00",
                "temperature": 30.0,
                "relative_humidity": 70.0,
                "location": "Taipei",
            }
            for i in range(4)
        ]
    )
    features = transform_feature_source_data(FeatureSourceData(load_df, weather_df))
    exported = build_feast_feature_frames(features, weather_df).taipower.sort_values("datetime")

    assert (exported.iloc[:3]["load_mw_lag_1"] != 8888.0).all()
    assert exported.iloc[0]["load_mw_lag_1"] == 0.0
    assert exported.iloc[1]["load_mw_lag_1"] == 100.0
    assert exported.iloc[0]["load_mw_lag_24"] == 0.0
    assert exported.iloc[0]["load_mw_rolling_mean_24"] == 0.0
