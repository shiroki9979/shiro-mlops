"""Unit tests for Dagster ParquetIOManager."""

from pathlib import Path

import pandas as pd
import pytest
from dagster import AssetKey, build_input_context, build_output_context
from upath import UPath

from shiro_mlops.core.io_managers import get_parquet_io_manager


def test_parquet_io_manager_roundtrip_dataframe_and_arbitrary_objects(
    tmp_path: Path,
) -> None:
    """ParquetIOManager persists DataFrames as Parquet and non-DataFrame objects via pickle."""
    manager = get_parquet_io_manager(
        environment="local",
        s3_bucket="unused",
        data_dir=tmp_path,
    )

    # 1. Test DataFrame
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    df_out_context = build_output_context(asset_key=AssetKey(["df_asset"]))
    manager.handle_output(df_out_context, df)

    df_in_context = build_input_context(asset_key=AssetKey(["df_asset"]))
    loaded_df = manager.load_input(df_in_context)
    pd.testing.assert_frame_equal(df, loaded_df)

    # 2. Test arbitrary object (dict, custom objects, etc.)
    obj = {"status": "HEALTHY", "metrics": {"mape": 4.2}}
    obj_out_context = build_output_context(asset_key=AssetKey(["obj_asset"]))
    manager.handle_output(obj_out_context, obj)

    obj_in_context = build_input_context(asset_key=AssetKey(["obj_asset"]))
    loaded_obj = manager.load_input(obj_in_context)
    assert loaded_obj == obj


def test_parquet_io_manager_does_not_create_s3_virtual_directories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3 artifact 輸出不應要求建立虛擬目錄。"""
    manager = get_parquet_io_manager(
        environment="aws",
        s3_bucket="test-bucket",
        data_dir=Path("unused"),
    )

    def fail_mkdir(*args: object, **kwargs: object) -> None:
        raise AssertionError("S3 virtual directories must not be created")

    monkeypatch.setattr(UPath, "mkdir", fail_mkdir)
    monkeypatch.setattr(manager, "dump_to_path", lambda **kwargs: None)

    context = build_output_context(asset_key=AssetKey(["artifact"]))
    manager.handle_output(context, {"status": "HEALTHY"})
