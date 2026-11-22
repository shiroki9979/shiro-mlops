"""Opt-in integration tests for TimescaleDB repository time semantics."""

import os
from uuid import uuid4

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.core.database import get_timescale_engine
from shiro_mlops.data.cwa_client import parse_forecast_release
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.repository_utils import deserialize_raw_payload
from shiro_mlops.features.transformers import merge_weather_features

TIMESCALE_INTEGRATION_URI_ENV = "TIMESCALE_INTEGRATION_URI"


@pytest.fixture
def timescaledb_engine() -> Engine:
    """Connect to an explicitly configured local TimescaleDB instance."""
    uri = os.getenv(TIMESCALE_INTEGRATION_URI_ENV)
    if uri is None:
        pytest.skip(f"Set {TIMESCALE_INTEGRATION_URI_ENV} to run TimescaleDB integration tests.")

    engine = get_timescale_engine(uri)
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


def test_string_raw_payload_round_trips_through_timescaledb_jsonb(
    timescaledb_engine: Engine,
) -> None:
    """XML 預報原始檔寫入 JSONB 後讀回，反序列化得到原字串而非再解碼一次。"""
    source_xml = f"<cwaopendata><Dataset>{uuid4().hex}</Dataset></cwaopendata>"
    release = parse_forecast_release(
        {
            "records": {
                "IssueTime": "2026-08-20T11:00:00+08:00",
                "Update": "2026-08-20T11:20:00+08:00",
                "Locations": [],
            }
        },
        dataset_id="F-D0047-089",
        raw_payload=source_xml,
    )
    repository = TimeSeriesRepository(engine=timescaledb_engine, auto_init=False)
    delete_release = text(
        "DELETE FROM raw_cwa_forecast_release "
        "WHERE dataset_id = :dataset_id AND issued_at = :issued_at"
    )
    release_key = {"dataset_id": "F-D0047-089", "issued_at": pd.Timestamp("2026-08-20T03:00:00Z")}

    try:
        repository.upsert_cwa_forecast_release(release)
        with timescaledb_engine.connect() as connection:
            stored = connection.execute(
                text(
                    "SELECT raw_payload FROM raw_cwa_forecast_release "
                    "WHERE dataset_id = :dataset_id AND issued_at = :issued_at"
                ),
                release_key,
            ).scalar_one()

        assert deserialize_raw_payload(stored) == source_xml
    finally:
        with timescaledb_engine.begin() as connection:
            connection.execute(delete_release, release_key)
