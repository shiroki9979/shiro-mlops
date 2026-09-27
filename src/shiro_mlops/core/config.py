"""Configuration settings with Pydantic."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from shiro_mlops.data.cwa_client import CWALocation


class Settings(BaseSettings):
    """Application settings supporting local and AWS environments."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Environment
    ENVIRONMENT: Literal["local", "aws", "test"] = "local"

    # Storage paths / AWS S3
    DATA_DIR: Path = Path("data")
    S3_BUCKET_NAME: str = "shiro-mlops-artifacts"
    AWS_REGION: str = "ap-northeast-1"
    FEAST_OFFLINE_STORE_TYPE: Literal["file", "s3"] = "file"
    FEAST_S3_PREFIX: str = "features"

    @property
    def taipower_parquet_uri(self) -> str:
        """Return the target URI (local path or s3://) for Taipower feature Parquet."""
        if self.FEAST_OFFLINE_STORE_TYPE == "s3":
            return f"s3://{self.S3_BUCKET_NAME}/{self.FEAST_S3_PREFIX}/taipower_features.parquet"
        return str((self.DATA_DIR / "taipower_features.parquet").resolve())

    @property
    def weather_parquet_uri(self) -> str:
        """Return the target URI (local path or s3://) for CWA weather feature Parquet."""
        if self.FEAST_OFFLINE_STORE_TYPE == "s3":
            return f"s3://{self.S3_BUCKET_NAME}/{self.FEAST_S3_PREFIX}/weather_features.parquet"
        return str((self.DATA_DIR / "weather_features.parquet").resolve())

    @property
    def models_dir(self) -> Path:
        """Root of the per-task model directories (ADR-0010)."""
        return self.DATA_DIR / "models"

    # MLflow
    MLFLOW_TRACKING_URI: str = "http://localhost:5001"
    MLFLOW_EXPERIMENT_NAME: str = "taipower_load_forecasting"

    # Feast Feature Store
    FEAST_REPO_PATH: Path = Path("src/shiro_mlops/features")
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None

    # External APIs
    CWA_API_KEY: str = ""
    CWA_LOCATION_ALLOWLIST: str = ""
    TAIPOWER_SUPPLY_DEMAND_API_URL: str = (
        "https://service.taipower.com.tw/data/opendata/apply/file/d006020/001.json"
    )
    TAIPOWER_REGIONAL_SUPPLY_DEMAND_API_URL: str = (
        "https://service.taipower.com.tw/data/opendata/apply/file/d006019/001.csv"
    )
    TAIPOWER_UNIT_GENERATION_API_URL: str = (
        "https://service.taipower.com.tw/data/opendata/apply/file/d006001/001.json"
    )

    # Nationwide hourly actual load derived from regional snapshots (ADR-0008)
    HOURLY_LOAD_MIN_SAMPLES: PositiveInt = 4
    HOURLY_LOAD_RECOMPUTE_HOURS: PositiveInt = 3

    # API Serving
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    DATA_EXPLORER_ENABLED: bool = False

    # TimescaleDB / Operational Time-Series Store
    TIMESCALE_HOST: str = "localhost"
    TIMESCALE_PORT: int = 5432
    TIMESCALE_DB: str = "shiro_timeseries"
    TIMESCALE_USER: str = "postgres"
    TIMESCALE_PASSWORD: str = "postgrespassword"

    @property
    def cwa_locations(self) -> dict[str, CWALocation]:
        """Return the configured CWA location catalog or its safe defaults."""
        from shiro_mlops.data.cwa_client import DEFAULT_CWA_LOCATIONS, CWALocation

        if not self.CWA_LOCATION_ALLOWLIST.strip():
            return DEFAULT_CWA_LOCATIONS.copy()
        try:
            raw = json.loads(self.CWA_LOCATION_ALLOWLIST)
        except json.JSONDecodeError as exc:
            raise ValueError("CWA_LOCATION_ALLOWLIST must be valid JSON") from exc
        if not isinstance(raw, dict):
            raise ValueError("CWA_LOCATION_ALLOWLIST must be a JSON object")
        locations: dict[str, CWALocation] = {}
        for alias, values in raw.items():
            if not isinstance(values, dict):
                raise ValueError(f"CWA location {alias!r} must be an object")
            try:
                locations[str(alias)] = CWALocation(
                    alias=str(alias),
                    station_id=str(values["station_id"]),
                    geocode=str(values["geocode"]),
                )
            except KeyError as exc:
                raise ValueError(f"CWA location {alias!r} is missing {exc.args[0]}") from exc
        if not locations:
            raise ValueError("CWA_LOCATION_ALLOWLIST cannot be empty")
        return locations

    def weather_reference_point(self, alias: str) -> CWALocation:
        """Resolve a weather reference point alias against the CWA ingestion catalog."""
        catalog = self.cwa_locations
        if alias not in catalog:
            raise ValueError(
                f"Weather reference point {alias!r} is not in the CWA ingestion catalog; "
                f"known aliases: {sorted(catalog)}"
            )
        return catalog[alias]

    @property
    def timescale_uri(self) -> str:
        """Return the PostgreSQL/TimescaleDB connection URI."""
        return (
            f"postgresql://{self.TIMESCALE_USER}:{self.TIMESCALE_PASSWORD}@"
            f"{self.TIMESCALE_HOST}:{self.TIMESCALE_PORT}/{self.TIMESCALE_DB}"
        )


settings = Settings()
