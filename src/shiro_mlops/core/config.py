"""Configuration settings with Pydantic."""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    TAIPOWER_API_URL: str = (
        "https://data.taipower.com.tw/opendata/apply/file/d015046/台灣電力公司_過去電力供需資訊.csv"
    )
    TAIPOWER_SUPPLY_DEMAND_API_URL: str = (
        "https://service.taipower.com.tw/data/opendata/apply/file/d006020/001.json"
    )

    # API Serving
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    # TimescaleDB / Operational Time-Series Store
    TIMESCALE_HOST: str = "localhost"
    TIMESCALE_PORT: int = 5432
    TIMESCALE_DB: str = "shiro_timeseries"
    TIMESCALE_USER: str = "postgres"
    TIMESCALE_PASSWORD: str = "postgrespassword"

    @property
    def timescale_uri(self) -> str:
        """Return the PostgreSQL/TimescaleDB connection URI."""
        return (
            f"postgresql://{self.TIMESCALE_USER}:{self.TIMESCALE_PASSWORD}@"
            f"{self.TIMESCALE_HOST}:{self.TIMESCALE_PORT}/{self.TIMESCALE_DB}"
        )


settings = Settings()
