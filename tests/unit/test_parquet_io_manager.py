"""Unit tests for Dagster ParquetIOManager."""

import io
import pickle
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from dagster import AssetKey, build_input_context, build_output_context
from pyarrow.lib import ArrowInvalid
from upath import UPath

from shiro_mlops.core.io_managers import get_parquet_io_manager


@pytest.fixture
def s3_objects(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """提供可控的 S3 物件儲存，驗證 I/O manager 的公開 roundtrip 行為。"""
    objects: dict[str, bytes] = {}

    class WritableMemoryFile(io.BytesIO):
        def __init__(self, key: str) -> None:
            super().__init__()
            self.key = key

        def close(self) -> None:
            if not self.closed:
                objects[self.key] = self.getvalue()
            super().close()

    def open_object(path: UPath, mode: str = "r", **kwargs: Any) -> io.BytesIO:
        key = str(path)
        if "r" in mode:
            return io.BytesIO(objects[key])
        return WritableMemoryFile(key)

    monkeypatch.setattr(UPath, "open", open_object)
    return objects


def test_parquet_io_manager_roundtrip_dataframe_and_json_objects(
    tmp_path: Path,
) -> None:
    """ParquetIOManager persists DataFrames and JSON-compatible objects safely."""
    manager = get_parquet_io_manager(
        environment="local",
        s3_bucket="unused",
        data_dir=tmp_path,
    )

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


def test_parquet_io_manager_rejects_non_json_objects(tmp_path: Path) -> None:
    """非 JSON-compatible 物件應在寫入邊界明確失敗。"""
    manager = get_parquet_io_manager(
        environment="local",
        s3_bucket="unused",
        data_dir=tmp_path,
    )
    context = build_output_context(asset_key=AssetKey(["unsupported"]))

    with pytest.raises(TypeError, match="JSON-serializable"):
        manager.handle_output(context, object())


def test_parquet_io_manager_roundtrip_cwa_forecast_release(tmp_path: Path) -> None:
    """CWA 預報版本寫入 Timescale 後必須可作為 JSON artifact 往返。"""
    from datetime import datetime

    from tests.helpers import forecast_release, township_forecast

    manager = get_parquet_io_manager(
        environment="local",
        s3_bucket="unused",
        data_dir=tmp_path,
    )
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


def test_parquet_io_manager_preserves_corrupt_parquet_error(
    tmp_path: Path,
) -> None:
    """損毀的 Parquet artifact 應保留原始格式錯誤。"""
    manager = get_parquet_io_manager(
        environment="local",
        s3_bucket="unused",
        data_dir=tmp_path,
    )
    (tmp_path / "corrupt").write_bytes(b"PAR1-corrupt")

    context = build_input_context(asset_key=AssetKey(["corrupt"]))
    with pytest.raises(ArrowInvalid):
        manager.load_input(context)


def test_parquet_io_manager_rejects_legacy_pickle_artifact(tmp_path: Path) -> None:
    """未標記的 legacy pickle artifact 不應被執行。"""
    manager = get_parquet_io_manager(
        environment="local",
        s3_bucket="unused",
        data_dir=tmp_path,
    )
    (tmp_path / "legacy").write_bytes(pickle.dumps({"status": "HEALTHY"}))

    context = build_input_context(asset_key=AssetKey(["legacy"]))
    with pytest.raises(ValueError, match="legacy pickle"):
        manager.load_input(context)


def test_parquet_io_manager_roundtrip_json_object_on_s3(
    s3_objects: dict[str, bytes],
) -> None:
    """S3 artifact 應使用安全 JSON envelope 完成 roundtrip。"""
    manager = get_parquet_io_manager(
        environment="aws",
        s3_bucket="test-bucket",
        data_dir=Path("unused"),
    )
    obj = {"status": "HEALTHY", "metrics": {"mape": 4.2}}
    output_context = build_output_context(asset_key=AssetKey(["s3_artifact"]))
    manager.handle_output(output_context, obj)

    input_context = build_input_context(asset_key=AssetKey(["s3_artifact"]))
    assert manager.load_input(input_context) == obj


def test_parquet_io_manager_rejects_legacy_pickle_artifact_on_s3(
    s3_objects: dict[str, bytes],
) -> None:
    """S3 上未標記的 legacy pickle artifact 也不應被執行。"""
    manager = get_parquet_io_manager(
        environment="aws",
        s3_bucket="test-bucket",
        data_dir=Path("unused"),
    )
    s3_objects["s3://test-bucket/data/s3_legacy"] = pickle.dumps({"status": "HEALTHY"})

    context = build_input_context(asset_key=AssetKey(["s3_legacy"]))
    with pytest.raises(ValueError, match="legacy pickle"):
        manager.load_input(context)
