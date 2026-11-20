"""Unit tests for Feast feature frame building and Dagster Feast I/O Manager."""

from pathlib import Path

import pandas as pd
from dagster import AssetKey, build_output_context

from shiro_mlops.core.io_managers import get_feast_parquet_io_manager
from shiro_mlops.features.feast_export import build_feast_feature_frames


def test_build_feast_feature_frames_returns_contracts_without_storage_side_effects(
    tmp_path: Path, taipower_raw_df: pd.DataFrame, cwa_obs_df: pd.DataFrame
) -> None:
    """Feature calculation emits Feast frames and never writes Feast Parquet artifacts."""
    frames = build_feast_feature_frames(taipower_raw_df, cwa_obs_df)

    assert list(frames.taipower.columns) == [
        "datetime",
        "location",
        "load_mw",
        "load_mw_lag_1",
        "load_mw_lag_2",
        "load_mw_lag_24",
        "load_mw_rolling_mean_6",
        "load_mw_rolling_mean_24",
        "hour",
        "dayofweek",
        "is_weekend",
        "is_day_off",
        "hour_sin",
        "hour_cos",
    ]
    assert list(frames.weather.columns) == [
        "datetime",
        "location",
        "temperature",
        "relative_humidity",
    ]
    assert not list(tmp_path.glob("*.parquet"))
    assert not list(tmp_path.glob("**/taipower_features.parquet"))
    assert not list(tmp_path.glob("**/weather_features.parquet"))


def test_feast_parquet_io_manager_writes_contracts_under_data_dir(
    tmp_path: Path, taipower_raw_df: pd.DataFrame, cwa_obs_df: pd.DataFrame
) -> None:
    """Feast I/O manager persists the Parquet contract at the DATA_DIR path Feast reads."""
    frames = build_feast_feature_frames(taipower_raw_df, cwa_obs_df)
    manager = get_feast_parquet_io_manager(data_dir=tmp_path)

    manager.handle_output(
        build_output_context(asset_key=AssetKey(["taipower_features"])), frames.taipower
    )

    written = pd.read_parquet(tmp_path / "taipower_features.parquet")
    pd.testing.assert_frame_equal(written, frames.taipower.reset_index(drop=True))


def test_feast_parquet_io_manager_creates_missing_nested_directories(
    tmp_path: Path, taipower_raw_df: pd.DataFrame, cwa_obs_df: pd.DataFrame
) -> None:
    """寫入尚不存在的巢狀目錄時，Feast I/O manager 仍能落地 Parquet。"""
    frames = build_feast_feature_frames(taipower_raw_df, cwa_obs_df)
    data_dir = tmp_path / "not_yet_created"
    manager = get_feast_parquet_io_manager(data_dir=data_dir)

    manager.handle_output(
        build_output_context(asset_key=AssetKey(["feast", "weather_features"])), frames.weather
    )

    written = pd.read_parquet(data_dir / "feast" / "weather_features.parquet")
    pd.testing.assert_frame_equal(written, frames.weather.reset_index(drop=True))
