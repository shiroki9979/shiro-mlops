"""Unit tests for Dagster ParquetIOManager."""

import pickle
from pathlib import Path

import pandas as pd
import pytest
from dagster import AssetKey, build_input_context, build_output_context
from pyarrow.lib import ArrowInvalid

from shiro_mlops.core.io_managers import get_parquet_io_manager


def test_parquet_io_manager_roundtrip_dataframe_and_json_objects(
    tmp_path: Path,
) -> None:
    """ParquetIOManager persists DataFrames and JSON-compatible objects safely."""
    manager = get_parquet_io_manager(data_dir=tmp_path)

    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    df_out_context = build_output_context(asset_key=AssetKey(["df_asset"]))
    manager.handle_output(df_out_context, df)

    df_in_context = build_input_context(asset_key=AssetKey(["df_asset"]))
    loaded_df = manager.load_input(df_in_context)
    pd.testing.assert_frame_equal(df, loaded_df)

    obj = {"status": "HEALTHY", "metrics": {"mape": 4.2}}
    obj_out_context = build_output_context(asset_key=AssetKey(["obj_asset"]))
    manager.handle_output(obj_out_context, obj)

    obj_in_context = build_input_context(asset_key=AssetKey(["obj_asset"]))
    loaded_obj = manager.load_input(obj_in_context)
    assert loaded_obj == obj


def test_parquet_io_manager_writes_artifacts_under_data_dir(tmp_path: Path) -> None:
    """Dagster artifact 只落在本機 DATA_DIR 之下，以 asset key 為相對路徑。"""
    manager = get_parquet_io_manager(data_dir=tmp_path)

    manager.handle_output(
        build_output_context(asset_key=AssetKey(["nested", "artifact"])), {"status": "HEALTHY"}
    )

    assert (tmp_path / "nested" / "artifact").is_file()


def test_parquet_io_manager_rejects_non_json_objects(tmp_path: Path) -> None:
    """非 JSON-compatible 物件應在寫入邊界明確失敗。"""
    manager = get_parquet_io_manager(data_dir=tmp_path)
    context = build_output_context(asset_key=AssetKey(["unsupported"]))

    with pytest.raises(TypeError, match="JSON-serializable"):
        manager.handle_output(context, object())


def test_parquet_io_manager_roundtrip_cwa_forecast_release(tmp_path: Path) -> None:
    """A persisted CWA forecast vintage must round-trip as a JSON artifact."""
    from datetime import datetime

    from tests.helpers import forecast_release, township_forecast

    manager = get_parquet_io_manager(data_dir=tmp_path)
    release = forecast_release(
        datetime(2026, 8, 20, 11, 40),
        (township_forecast(datetime(2026, 8, 20, 12), 31.0),),
        raw_payload={"success": "true"},
    )
    context = build_output_context(asset_key=AssetKey(["raw_cwa_township_forecast"]))

    manager.handle_output(context, [release])

    loaded = manager.load_input(
        build_input_context(asset_key=AssetKey(["raw_cwa_township_forecast"]))
    )
    assert loaded[0]["dataset_id"] == "F-D0047-089"
    assert loaded[0]["status"] == "complete"
    assert loaded[0]["forecasts"][0]["temperature_c"] == 31.0
    assert loaded[0]["raw_payload"] == {"success": "true"}


def test_parquet_io_manager_preserves_corrupt_parquet_error(
    tmp_path: Path,
) -> None:
    """損毀的 Parquet artifact 應保留原始格式錯誤。"""
    manager = get_parquet_io_manager(data_dir=tmp_path)
    (tmp_path / "corrupt").write_bytes(b"PAR1-corrupt")

    context = build_input_context(asset_key=AssetKey(["corrupt"]))
    with pytest.raises(ArrowInvalid):
        manager.load_input(context)


def test_parquet_io_manager_rejects_legacy_pickle_artifact(tmp_path: Path) -> None:
    """未標記的 legacy pickle artifact 不應被執行。"""
    manager = get_parquet_io_manager(data_dir=tmp_path)
    (tmp_path / "legacy").write_bytes(pickle.dumps({"status": "HEALTHY"}))

    context = build_input_context(asset_key=AssetKey(["legacy"]))
    with pytest.raises(ValueError, match="legacy pickle"):
        manager.load_input(context)
