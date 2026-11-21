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
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task, deployed_tasks
from shiro_mlops.tasks.types import get_task_type
from shiro_mlops.tasks.types.base import TaskModel, TrainingData
from tests.helpers import create_legacy_load_table, override_task_policies

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


@pytest.fixture(autouse=True)
def isolate_forecast_view_upload_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A host bucket, AWS key or region must never turn a test's export into a real upload."""
    for name in (
        "FORECAST_VIEW_S3_BUCKET",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_DEFAULT_REGION",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def min_hours(monkeypatch: pytest.MonkeyPatch) -> int:
    """Lower every deployed task's training accumulation threshold and return the value."""
    for task_id in deployed_tasks():
        override_task_policies(monkeypatch, task_id, min_training_hours=TEST_MIN_LOAD_HOURS)
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
    repo.upsert_taipower_load(taipower_raw_df, default_subject="nationwide")
    repo.upsert_cwa_observation_batch(cwa_observation_batch)
    return repo


@pytest.fixture
def fitted_task_model(taipower_raw_df: pd.DataFrame, cwa_obs_df: pd.DataFrame) -> TaskModel:
    """Train the deployed dynamic horizon task type directly on the fixture frames."""
    task = deployed_task(DYNAMIC_HORIZON_FORECAST)
    data = TrainingData(
        load=taipower_raw_df.assign(subject=task.subject),
        weather=cwa_obs_df[["datetime", *task.weather.fields]],
        validation_start=taipower_raw_df["datetime"].max() + pd.Timedelta(hours=1),
    )
    return get_task_type(task.task_type).train(task.params, data).model


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
