"""Opt-in integration tests for TimescaleDB repository time semantics."""

import os
from uuid import uuid4

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.features.transformers import merge_weather_features

TIMESCALE_INTEGRATION_URI_ENV = "TIMESCALE_INTEGRATION_URI"


@pytest.fixture
def timescaledb_engine() -> Engine:
    """Connect to an explicitly configured local TimescaleDB instance."""
    uri = os.getenv(TIMESCALE_INTEGRATION_URI_ENV)
    if uri is None:
        pytest.skip(f"Set {TIMESCALE_INTEGRATION_URI_ENV} to run TimescaleDB integration tests.")

    engine = create_engine(uri)
    with engine.connect() as connection:
        extension_version = connection.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
        ).scalar_one_or_none()
    if extension_version is None:
        engine.dispose()
        pytest.fail("The integration database must have the TimescaleDB extension enabled.")

    yield engine
    engine.dispose()


def test_repository_preserves_taiwan_instant_across_timescaledb_storage_and_queries(
    timescaledb_engine: Engine,
) -> None:
    """Taiwan-local and UTC inputs represent one instant through storage, readback, and merge."""
    location = f"integration-{uuid4().hex}"
    repository = TimeSeriesRepository(engine=timescaledb_engine, auto_init=False)
    load_df = pd.DataFrame(
        [{"datetime": "2026-08-20T14:00:00", "load_mw": 38000.0, "location": location}]
    )
    revised_load_df = pd.DataFrame(
        [{"datetime": "2026-08-20T06:00:00Z", "load_mw": 39000.0, "location": location}]
    )
    weather_df = pd.DataFrame(
        [
            {
                "datetime": "2026-08-20T06:00:00Z",
                "temperature": 35.5,
                "relative_humidity": 55.0,
                "location": location,
            }
        ]
    )

    try:
        assert repository.upsert_taipower_load(load_df) == 1
        assert repository.upsert_taipower_load(revised_load_df) == 1
        assert repository.upsert_cwa_weather(weather_df) == 1

        with timescaledb_engine.connect() as connection:
            stored_time = connection.execute(
                text("SELECT time FROM raw_taipower_load WHERE location = :location"),
                {"location": location},
            ).scalar_one()
        assert pd.Timestamp(stored_time) == pd.Timestamp("2026-08-20T06:00:00Z")

        persisted_load = repository.fetch_load_range(
            start_time="2026-08-20T14:00:00",
            end_time="2026-08-20T14:00:00",
            location=location,
        )
        persisted_weather = repository.fetch_weather_range(
            start_time="2026-08-20T06:00:00Z",
            end_time="2026-08-20T06:00:00Z",
            location=location,
        )

        assert len(persisted_load) == 1
        assert persisted_load.iloc[0]["time"] == pd.Timestamp("2026-08-20T14:00:00")
        assert persisted_load.iloc[0]["load_mw"] == pytest.approx(39000.0)
        assert persisted_weather.iloc[0]["time"] == pd.Timestamp("2026-08-20T14:00:00")

        merged = merge_weather_features(
            persisted_load.rename(columns={"time": "datetime"}),
            persisted_weather.rename(columns={"time": "datetime"}),
        )
        assert len(merged) == 1
        assert merged.iloc[0]["temperature"] == pytest.approx(35.5)
    finally:
        with timescaledb_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM raw_cwa_weather WHERE location = :location"),
                {"location": location},
            )
            connection.execute(
                text("DELETE FROM raw_taipower_load WHERE location = :location"),
                {"location": location},
            )
