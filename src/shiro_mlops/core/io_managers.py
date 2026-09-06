"""Dagster IO Managers for Local filesystem and AWS S3."""

import io
import json
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from dagster import InputContext, OutputContext, UPathIOManager
from upath import UPath

from shiro_mlops.core.config import settings

_PARQUET_MAGIC = b"PAR1"
_JSON_ARTIFACT_HEADER = b"SHIRO-JSON-V1\n"


class ParquetIOManager(UPathIOManager):
    """IO Manager for Parquet DataFrames and JSON-compatible Dagster artifacts."""

    def __init__(self, base_path: UPath):
        super().__init__(base_path=base_path)

    def make_directory(self, path: UPath) -> None:
        """Create local parents only; S3 object stores need no directory mkdir."""
        if str(path).startswith("s3://"):
            return
        super().make_directory(path)

    def dump_to_path(self, context: OutputContext, obj: Any, path: UPath) -> None:
        """Serialize DataFrame to Parquet format, with fallback for arbitrary Python objects."""
        if not str(path).startswith("s3://"):
            path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(obj, pd.DataFrame):
            with path.open("wb") as f:
                obj.to_parquet(f, index=False)
        else:
            try:
                payload = json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")
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
    """IO Manager that publishes Feast-contract DataFrames to local FS or S3."""

    extension = ".parquet"

    def __init__(self, base_path: UPath, s3_client: Any | None = None):
        super().__init__(base_path=base_path)
        self._s3_client = s3_client

    def make_directory(self, path: UPath) -> None:
        """Create local parents only; S3 object stores need no directory mkdir."""
        if str(path).startswith("s3://"):
            return
        super().make_directory(path)

    def dump_to_path(self, context: OutputContext, obj: Any, path: UPath) -> None:
        """Serialize a Feast feature DataFrame to the configured offline-store path."""
        if not isinstance(obj, pd.DataFrame):
            raise TypeError(f"Unsupported object type {type(obj)} for FeastParquetIOManager")

        path_str = str(path)
        if path_str.startswith("s3://"):
            import boto3

            bucket_and_key = path_str[5:]
            bucket, key = bucket_and_key.split("/", 1)
            client = self._s3_client or boto3.client("s3", region_name=settings.AWS_REGION)
            buf = io.BytesIO()
            obj.to_parquet(buf, index=False)
            buf.seek(0)
            client.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
            return

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            obj.to_parquet(f, index=False)

    def load_from_path(self, context: InputContext, path: UPath) -> pd.DataFrame:
        """Load a Feast Parquet artifact into a DataFrame."""
        path_str = str(path)
        if path_str.startswith("s3://"):
            import boto3

            bucket_and_key = path_str[5:]
            bucket, key = bucket_and_key.split("/", 1)
            client = self._s3_client or boto3.client("s3", region_name=settings.AWS_REGION)
            response = client.get_object(Bucket=bucket, Key=key)
            return pd.read_parquet(io.BytesIO(response["Body"].read()))

        with path.open("rb") as f:
            return pd.read_parquet(f)


def get_parquet_io_manager(environment: str, s3_bucket: str, data_dir: Path) -> ParquetIOManager:
    """Factory to create appropriate ParquetIOManager based on environment."""
    if environment == "aws":
        base_path = UPath(f"s3://{s3_bucket}/data")
    else:
        base_path = UPath(data_dir.resolve())
    return ParquetIOManager(base_path=base_path)


def get_feast_parquet_io_manager(
    offline_store_type: Literal["file", "s3"],
    s3_bucket: str,
    s3_prefix: str,
    data_dir: Path,
    s3_client: Any | None = None,
) -> FeastParquetIOManager:
    """Factory for Feast offline-store publication; feature logic stays storage-agnostic."""
    if offline_store_type == "s3":
        base_path = UPath(f"s3://{s3_bucket}/{s3_prefix}")
    else:
        base_path = UPath(data_dir.resolve())
    return FeastParquetIOManager(base_path=base_path, s3_client=s3_client)
