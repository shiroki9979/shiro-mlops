"""Dagster IO Managers that persist artifacts on the local filesystem under DATA_DIR."""

import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from dagster import InputContext, OutputContext, UPathIOManager
from upath import UPath

_PARQUET_MAGIC = b"PAR1"
_JSON_ARTIFACT_HEADER = b"SHIRO-JSON-V1\n"

# AssetIn metadata key: set to True and the input loads as None while its upstream asset has
# never materialized, instead of failing on the missing artifact. A materialized asset whose
# artifact is gone still fails, so lost data is never mistaken for a fresh instance.
NONE_BEFORE_FIRST_MATERIALIZATION = "none_before_first_materialization"


def _json_default(obj: Any) -> Any:
    """Convert domain objects to JSON values supported by Dagster artifacts."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if isinstance(obj, pd.Timestamp):
        return None if pd.isna(obj) else obj.isoformat()
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class ParquetIOManager(UPathIOManager):
    """IO Manager for Parquet DataFrames and JSON-compatible Dagster artifacts."""

    def load_input(self, context: InputContext) -> Any:
        """Honour ``NONE_BEFORE_FIRST_MATERIALIZATION`` before the usual load."""
        if (
            context.definition_metadata.get(NONE_BEFORE_FIRST_MATERIALIZATION)
            and context.has_asset_key
            and context.instance.get_latest_materialization_event(context.asset_key) is None
        ):
            return None
        return super().load_input(context)

    def dump_to_path(self, context: OutputContext, obj: Any, path: UPath) -> None:
        """Serialize DataFrame to Parquet format, with fallback for arbitrary Python objects."""
        if isinstance(obj, pd.DataFrame):
            with path.open("wb") as f:
                obj.to_parquet(f, index=False)
        else:
            try:
                payload = json.dumps(
                    obj, ensure_ascii=False, allow_nan=False, default=_json_default
                ).encode("utf-8")
            except (TypeError, ValueError) as error:
                raise TypeError("Non-DataFrame artifacts must be JSON-serializable") from error
            with path.open("wb") as f:
                f.write(_JSON_ARTIFACT_HEADER + payload)

    def load_from_path(self, context: InputContext, path: UPath) -> Any:
        """Load a Parquet DataFrame or a marked JSON artifact; reject legacy pickle files."""
        with path.open("rb") as f:
            header = f.read(max(len(_JSON_ARTIFACT_HEADER), len(_PARQUET_MAGIC)))

        if header.startswith(_PARQUET_MAGIC):
            with path.open("rb") as f:
                return pd.read_parquet(f)

        if header.startswith(_JSON_ARTIFACT_HEADER):
            with path.open("rb") as f:
                f.read(len(_JSON_ARTIFACT_HEADER))
                payload = f.read()
            try:
                return json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError(f"Invalid JSON artifact at {path}") from error

        raise ValueError(
            f"Unsupported or untrusted artifact format at {path}; "
            "legacy pickle artifacts must be regenerated"
        )


class FeastParquetIOManager(UPathIOManager):
    """IO Manager that publishes Feast-contract DataFrames to the local offline store."""

    extension = ".parquet"

    def dump_to_path(self, context: OutputContext, obj: Any, path: UPath) -> None:
        """Serialize a Feast feature DataFrame to the offline-store path."""
        if not isinstance(obj, pd.DataFrame):
            raise TypeError(f"Unsupported object type {type(obj)} for FeastParquetIOManager")

        with path.open("wb") as f:
            obj.to_parquet(f, index=False)

    def load_from_path(self, context: InputContext, path: UPath) -> pd.DataFrame:
        """Load a Feast Parquet artifact into a DataFrame."""
        with path.open("rb") as f:
            return pd.read_parquet(f)


def get_parquet_io_manager(data_dir: Path) -> ParquetIOManager:
    """建立以 DATA_DIR 為基底的 Dagster artifact I/O manager。"""
    return ParquetIOManager(base_path=UPath(data_dir.resolve()))


def get_feast_parquet_io_manager(data_dir: Path) -> FeastParquetIOManager:
    """建立 Feast offline-store 匯出專用之 I/O manager，寫入 DATA_DIR 下的特徵 Parquet。"""
    return FeastParquetIOManager(base_path=UPath(data_dir.resolve()))
