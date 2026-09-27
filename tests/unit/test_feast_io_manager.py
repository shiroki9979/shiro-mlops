"""Unit tests for Feast feature frame building and Dagster Feast I/O Manager."""

from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
from dagster import AssetKey, build_output_context

from shiro_mlops.core.io_managers import FeastPublicationTarget, get_feast_parquet_io_manager
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


def test_feast_parquet_io_manager_writes_identical_contracts_for_file_and_s3(
    tmp_path: Path, taipower_raw_df: pd.DataFrame, cwa_obs_df: pd.DataFrame
) -> None:
    """Local and S3 Feast I/O managers persist the same Parquet contract."""
    frames = build_feast_feature_frames(taipower_raw_df, cwa_obs_df)
    local_manager = get_feast_parquet_io_manager(FeastPublicationTarget.local(tmp_path))
    mock_s3 = MagicMock()
    s3_manager = get_feast_parquet_io_manager(
        FeastPublicationTarget.s3("my-s3-feast-bucket", "features", s3_client=mock_s3)
    )

    local_context = build_output_context(asset_key=AssetKey(["taipower_features"]))
    local_manager.handle_output(local_context, frames.taipower)

    s3_context = build_output_context(asset_key=AssetKey(["taipower_features"]))
    s3_manager.handle_output(s3_context, frames.taipower)

    local_path = tmp_path / "taipower_features.parquet"
    assert local_path.exists()
    local_df = pd.read_parquet(local_path)

    mock_s3.put_object.assert_called_once()
    kwargs = mock_s3.put_object.call_args.kwargs
    assert kwargs["Bucket"] == "my-s3-feast-bucket"
    assert kwargs["Key"] == "features/taipower_features.parquet"
    import io

    s3_df = pd.read_parquet(io.BytesIO(kwargs["Body"]))
    pd.testing.assert_frame_equal(local_df, s3_df)
