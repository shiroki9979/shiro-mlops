"""Dagster IO Managers for Local filesystem and AWS S3."""

from pathlib import Path
from typing import Any

import pandas as pd
from dagster import InputContext, OutputContext, UPathIOManager
from upath import UPath


class ParquetIOManager(UPathIOManager):
    """IO Manager that reads and writes pandas DataFrames as Parquet files."""

    def __init__(self, base_path: UPath):
        super().__init__(base_path=base_path)

    def dump_to_path(self, context: OutputContext, obj: Any, path: UPath) -> None:
        """Serialize DataFrame to Parquet format."""
        if isinstance(obj, pd.DataFrame):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as f:
                obj.to_parquet(f, index=False)
        else:
            raise TypeError(f"Unsupported object type {type(obj)} for ParquetIOManager")

    def load_from_path(self, context: InputContext, path: UPath) -> pd.DataFrame:
        """Load Parquet file into DataFrame."""
        with path.open("rb") as f:
            return pd.read_parquet(f)


def get_parquet_io_manager(environment: str, s3_bucket: str, data_dir: Path) -> ParquetIOManager:
    """Factory to create appropriate ParquetIOManager based on environment."""
    if environment == "aws":
        base_path = UPath(f"s3://{s3_bucket}/data")
    else:
        base_path = UPath(data_dir.resolve())
    return ParquetIOManager(base_path=base_path)
