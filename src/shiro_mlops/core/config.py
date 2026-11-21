"""Configuration settings with Pydantic."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import PositiveInt, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from shiro_mlops.data.cwa_client import CWALocation


class Settings(BaseSettings):
    """Application settings for the local stack and the offline test suite."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Environment
    ENVIRONMENT: Literal["local", "test"] = "local"

    # Storage paths
    DATA_DIR: Path = Path("data")

    @property
    def taipower_parquet_uri(self) -> str:
        """Return the local path of the Taipower feature Parquet under DATA_DIR."""
        return str((self.DATA_DIR / "taipower_features.parquet").resolve())

    @property
    def weather_parquet_uri(self) -> str:
        """Return the local path of the CWA weather feature Parquet under DATA_DIR."""
        return str((self.DATA_DIR / "weather_features.parquet").resolve())

    @property
    def models_dir(self) -> Path:
        """Root of the per-task model directories (ADR-0010)."""
        return self.DATA_DIR / "models"

    @property
    def published_dir(self) -> Path:
        """Local directory of the Forecast View's published JSON, served under ``/published/``."""
        return self.DATA_DIR / "published"

    # Forecast View export upload (ADR-0015 §2.3). An empty bucket exports locally only.
    FORECAST_VIEW_S3_BUCKET: str = ""
    # The dedicated upload user's key; empty values leave boto3 to its default credential chain.
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: SecretStr = SecretStr("")
    # The bucket's region: Terraform's aws_region variable (infra/terraform/variables.tf), whose
    # aws_region output this must equal. Keep the default in sync with that variable's default.
    AWS_DEFAULT_REGION: str = "ap-northeast-1"

    # MLflow
    MLFLOW_TRACKING_URI: str = "http://localhost:5001"

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
    HOURLY_LOAD_CATCHUP_MAX_HOURS: PositiveInt = 168

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

    @property
    def timescale_uri(self) -> str:
        """Return the PostgreSQL/TimescaleDB connection URI."""
        return (
            f"postgresql://{self.TIMESCALE_USER}:{self.TIMESCALE_PASSWORD}@"
            f"{self.TIMESCALE_HOST}:{self.TIMESCALE_PORT}/{self.TIMESCALE_DB}"
        )


settings = Settings()
