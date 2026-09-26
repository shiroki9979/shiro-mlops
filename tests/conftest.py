"""Pytest shared fixtures."""

import json
from collections.abc import Generator
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from shiro_mlops.core.config import settings
from shiro_mlops.core.database import SQLITE_DEFAULT_SCHEMA, ensure_timescale_hypertables
from shiro_mlops.data.cwa_client import CWAObservationBatch, CWAStationObservation
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.models.forecaster import LightGBMRecursiveForecaster
from tests.helpers import create_legacy_load_table

FIXTURES_DIR = Path(__file__).parent / "fixtures"

SQLITE_TEST_SCHEMA = SQLITE_DEFAULT_SCHEMA
# 以一日門檻取代 672 小時預設，讓排程與 smoke check 測試不需建立 28 日資料。
TEST_MIN_LOAD_HOURS = 24


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
def min_hours(monkeypatch: pytest.MonkeyPatch) -> int:
    """Lower the training accumulation threshold and return the value in effect."""
    monkeypatch.setattr(settings, "TRAINING_MIN_LOAD_HOURS", TEST_MIN_LOAD_HOURS)
    return TEST_MIN_LOAD_HOURS


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
    """Create an isolated SQLite engine with canonical test schema derived from production DDL."""
    db_file = tmp_path_factory.mktemp("db") / "test_repo.db"
    engine = create_engine(f"sqlite:///{db_file}")
    ensure_timescale_hypertables(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def legacy_upgraded_engine(tmp_path: Path) -> Generator[Engine, None, None]:
    """An upgraded d015046-era database: one legacy row whose source is NULL."""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy_upgraded.db'}")
    create_legacy_load_table(engine)
    ensure_timescale_hypertables(engine)
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
    cwa_observation_batch: CWAObservationBatch,
) -> TimeSeriesRepository:
    """Create and populate TimeSeriesRepository with fixture data."""
    repo = TimeSeriesRepository(engine=sqlite_engine)
    repo.upsert_taipower_load(taipower_raw_df, default_location="Taipei")
    repo.upsert_cwa_observation_batch(cwa_observation_batch)
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
def cwa_observation_batch(cwa_obs_df: pd.DataFrame) -> CWAObservationBatch:
    """Build a canonical Taipei observation batch from the stable weather fixture."""
    return CWAObservationBatch(
        fetched_at=cwa_obs_df["datetime"].max().to_pydatetime(),
        status="complete",
        missing_station_ids=(),
        raw_payload={"fixture": "cwa_obs_sample"},
        observations=tuple(
            CWAStationObservation(
                observed_at=row.datetime.to_pydatetime(),
                station_id="466920",
                station_name="臺北",
                town_code="63000050",
                temperature_c=float(row.temperature),
                relative_humidity_pct=float(row.relative_humidity),
                air_pressure_hpa=None,
                precipitation_mm=None,
                wind_speed_m_s=None,
                wind_direction_deg=None,
            )
            for row in cwa_obs_df.itertuples()
        ),
    )


@pytest.fixture
def cwa_forecast_df() -> pd.DataFrame:
    """Load sample CWA weather forecast DataFrame."""
    with open(FIXTURES_DIR / "cwa_forecast_sample.json", encoding="utf-8") as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df
