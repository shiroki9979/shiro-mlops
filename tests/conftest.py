"""Pytest shared fixtures."""

import json
from collections.abc import Generator
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from shiro_mlops.core.config import settings
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.models.forecaster import LightGBMRecursiveForecaster

FIXTURES_DIR = Path(__file__).parent / "fixtures"

SQLITE_TEST_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_taipower_load (
    time TIMESTAMP NOT NULL,
    location VARCHAR(64) NOT NULL,
    load_mw DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (time, location)
);

CREATE TABLE IF NOT EXISTS raw_cwa_weather (
    time TIMESTAMP NOT NULL,
    location VARCHAR(64) NOT NULL,
    temperature DOUBLE PRECISION,
    relative_humidity DOUBLE PRECISION,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (time, location)
);

CREATE TABLE IF NOT EXISTS raw_taipower_supply_demand_snapshot (
    observed_at TIMESTAMP NOT NULL,
    source_publish_time TIMESTAMP,
    curr_load_wan_kw DOUBLE PRECISION NOT NULL,
    curr_util_rate_pct DOUBLE PRECISION NOT NULL,
    fore_maxi_sply_capacity_wan_kw DOUBLE PRECISION,
    fore_peak_dema_load_wan_kw DOUBLE PRECISION,
    fore_peak_resv_capacity_wan_kw DOUBLE PRECISION,
    fore_peak_resv_rate_pct DOUBLE PRECISION,
    fore_peak_resv_indicator VARCHAR(8),
    fore_peak_hour_range VARCHAR(32),
    yday_date DATE,
    yday_maxi_sply_capacity_wan_kw DOUBLE PRECISION,
    yday_peak_dema_load_wan_kw DOUBLE PRECISION,
    yday_peak_resv_capacity_wan_kw DOUBLE PRECISION,
    yday_peak_resv_rate_pct DOUBLE PRECISION,
    yday_peak_resv_indicator VARCHAR(8),
    real_hr_maxi_sply_capacity_wan_kw DOUBLE PRECISION,
    real_hr_peak_time TIMESTAMP,
    raw_payload TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (observed_at)
);
"""


@pytest.fixture(autouse=True)
def mock_mlflow_offline_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[str, None, None]:
    """Ensure MLflow never hits external network endpoints in tests; use local SQLite store."""
    mlflow_db = tmp_path / "test_mlflow.db"
    uri = f"sqlite:///{mlflow_db}"
    dagster_dir = tmp_path / "dagster"
    dagster_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "MLFLOW_TRACKING_URI", uri)
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DAGSTER_HOME", str(dagster_dir))
    yield uri


@pytest.fixture
def dagster_instance(tmp_path: Path) -> Generator:
    """Create an isolated, temporary DagsterInstance for test materializations."""
    from dagster import DagsterInstance

    temp_dir = tmp_path / "dagster_instance_dir"
    temp_dir.mkdir(parents=True, exist_ok=True)
    with DagsterInstance.local_temp(tempdir=str(temp_dir)) as instance:
        yield instance


@pytest.fixture
def sqlite_engine(tmp_path_factory: pytest.TempPathFactory) -> Generator[Engine, None, None]:
    """Create an isolated SQLite engine with canonical test schema."""
    db_file = tmp_path_factory.mktemp("db") / "test_repo.db"
    engine = create_engine(f"sqlite:///{db_file}")
    with engine.connect() as conn:
        for stmt in SQLITE_TEST_SCHEMA.split(";"):
            cleaned = stmt.strip()
            if cleaned:
                conn.execute(text(cleaned))
        conn.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def test_repo(sqlite_engine: Engine) -> TimeSeriesRepository:
    """Create an empty TimeSeriesRepository backed by the test engine."""
    return TimeSeriesRepository(engine=sqlite_engine)


@pytest.fixture
def populated_repo(
    sqlite_engine: Engine,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
) -> TimeSeriesRepository:
    """Create and populate TimeSeriesRepository with fixture data."""
    repo = TimeSeriesRepository(engine=sqlite_engine)
    repo.upsert_taipower_load(taipower_raw_df, default_location="Taipei")
    repo.upsert_cwa_weather(cwa_obs_df, default_location="Taipei")
    return repo


@pytest.fixture
def lightweight_forecaster() -> LightGBMRecursiveForecaster:
    """Create a lightweight fast forecaster for offline testing."""
    return LightGBMRecursiveForecaster(
        params={"n_estimators": 2, "min_child_samples": 1, "verbose": -1}
    )


@pytest.fixture
def taipower_raw_df() -> pd.DataFrame:
    """Load sample Taipower raw DataFrame."""
    with open(FIXTURES_DIR / "taipower_sample.json", encoding="utf-8") as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df


@pytest.fixture
def cwa_obs_df() -> pd.DataFrame:
    """Load sample CWA weather observation DataFrame."""
    with open(FIXTURES_DIR / "cwa_obs_sample.json", encoding="utf-8") as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df


@pytest.fixture
def cwa_forecast_df() -> pd.DataFrame:
    """Load sample CWA weather forecast DataFrame."""
    with open(FIXTURES_DIR / "cwa_forecast_sample.json", encoding="utf-8") as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df
