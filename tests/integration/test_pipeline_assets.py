"""Integration tests for Dagster ingestion assets and database persistence."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from dagster import build_asset_context, materialize
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from shiro_mlops.core.config import settings
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.pipelines.assets import (
    engineered_features,
    raw_taipower_load_data,
    raw_weather_obs_data,
)

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
"""


@pytest.fixture
def sqlite_engine() -> Engine:
    """Create an in-memory SQLite engine with test schema."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        for stmt in SQLITE_TEST_SCHEMA.split(";"):
            cleaned = stmt.strip()
            if cleaned:
                conn.execute(text(cleaned))
        conn.commit()
    return engine


@pytest.fixture
def test_repo(sqlite_engine: Engine) -> TimeSeriesRepository:
    """Create a TimeSeriesRepository backed by the test engine."""
    return TimeSeriesRepository(engine=sqlite_engine)


def test_raw_taipower_load_data_persists_to_db(
    test_repo: TimeSeriesRepository, taipower_raw_df: pd.DataFrame
):
    """Verify raw_taipower_load_data fetches from client, upserts to repository, and returns df."""
    context = build_asset_context(resources={"time_series_repo": test_repo})

    with patch(
        "shiro_mlops.pipelines.assets.TaipowerClient.fetch_load_data",
        return_value=taipower_raw_df,
    ):
        result_df = raw_taipower_load_data(context)

    assert isinstance(result_df, pd.DataFrame)
    assert len(result_df) == len(taipower_raw_df)

    # Verify rows were persisted into the repository's SQLite database
    persisted = test_repo.fetch_load_range(location="Taipei")
    assert len(persisted) == len(taipower_raw_df)
    assert persisted.iloc[0]["load_mw"] == pytest.approx(taipower_raw_df.iloc[0]["load_mw"])


def test_raw_weather_obs_data_persists_to_db(
    test_repo: TimeSeriesRepository, cwa_obs_df: pd.DataFrame
):
    """Verify raw_weather_obs_data fetches from client, upserts to repository, and returns df."""
    context = build_asset_context(resources={"time_series_repo": test_repo})

    with patch(
        "shiro_mlops.pipelines.assets.CWAClient.fetch_observations",
        return_value=cwa_obs_df,
    ):
        result_df = raw_weather_obs_data(context)

    assert isinstance(result_df, pd.DataFrame)
    assert len(result_df) == len(cwa_obs_df)

    # Verify rows were persisted into the repository's SQLite database
    persisted = test_repo.fetch_weather_range(location="Taipei")
    assert len(persisted) == len(cwa_obs_df)
    assert persisted.iloc[0]["temperature"] == pytest.approx(cwa_obs_df.iloc[0]["temperature"])


def test_raw_taipower_load_data_graceful_fallback_on_db_failure(
    taipower_raw_df: pd.DataFrame,
    monkeypatch,
):
    """Verify raw_taipower_load_data continues safely and returns df if database raises exception in test env."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    failing_repo = MagicMock(spec=TimeSeriesRepository)
    failing_repo.upsert_taipower_load.side_effect = RuntimeError("Database connection timed out")
    context = build_asset_context(resources={"time_series_repo": failing_repo})

    with patch(
        "shiro_mlops.pipelines.assets.TaipowerClient.fetch_load_data",
        return_value=taipower_raw_df,
    ):
        result_df = raw_taipower_load_data(context)

    # Pipeline does not throw in test mode; still returns DataFrame
    assert isinstance(result_df, pd.DataFrame)
    assert len(result_df) == len(taipower_raw_df)


def test_raw_weather_obs_data_graceful_fallback_on_db_failure(
    cwa_obs_df: pd.DataFrame,
    monkeypatch,
):
    """Verify raw_weather_obs_data continues safely and returns df if database raises exception in test env."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    failing_repo = MagicMock(spec=TimeSeriesRepository)
    failing_repo.upsert_cwa_weather.side_effect = RuntimeError("Database connection timed out")
    context = build_asset_context(resources={"time_series_repo": failing_repo})

    with patch(
        "shiro_mlops.pipelines.assets.CWAClient.fetch_observations",
        return_value=cwa_obs_df,
    ):
        result_df = raw_weather_obs_data(context)

    assert isinstance(result_df, pd.DataFrame)
    assert len(result_df) == len(cwa_obs_df)


def test_raw_taipower_load_data_raises_in_production(
    taipower_raw_df: pd.DataFrame,
    monkeypatch,
):
    """Verify raw_taipower_load_data raises exception if database fails in non-test environment."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "local")
    failing_repo = MagicMock(spec=TimeSeriesRepository)
    failing_repo.upsert_taipower_load.side_effect = RuntimeError("Database connection timed out")
    context = build_asset_context(resources={"time_series_repo": failing_repo})

    with patch(
        "shiro_mlops.pipelines.assets.TaipowerClient.fetch_load_data",
        return_value=taipower_raw_df,
    ):
        with pytest.raises(RuntimeError, match="Database connection timed out"):
            raw_taipower_load_data(context)


def test_dagster_materialize_ingestion_and_feature_pipeline(
    test_repo: TimeSeriesRepository,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
):
    """Verify Dagster materialize executes ingestion through feature engineering and persists to repository."""
    with (
        patch(
            "shiro_mlops.pipelines.assets.TaipowerClient.fetch_load_data",
            return_value=taipower_raw_df,
        ),
        patch(
            "shiro_mlops.pipelines.assets.CWAClient.fetch_observations",
            return_value=cwa_obs_df,
        ),
    ):
        res = materialize(
            assets=[raw_taipower_load_data, raw_weather_obs_data, engineered_features],
            resources={"time_series_repo": test_repo},
        )

    assert res.success
    engineered_df = res.output_for_node("engineered_features")
    assert isinstance(engineered_df, pd.DataFrame)
    assert not engineered_df.empty

    # Assert persistence to repository during materialization
    persisted_load = test_repo.fetch_load_range(location="Taipei")
    assert len(persisted_load) == len(taipower_raw_df)

    persisted_weather = test_repo.fetch_weather_range(location="Taipei")
    assert len(persisted_weather) == len(cwa_obs_df)
