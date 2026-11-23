"""Unit tests for TimeSeriesRepository and batch upsert operations."""

from dataclasses import replace
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from shiro_mlops.data.cwa_client import CWAObservationBatch
from shiro_mlops.data.cwa_weather_store import CWAWeatherStore
from shiro_mlops.data.repository import (
    TaipowerRegionalSupplyDemandRepository,
    TaipowerSupplyDemandRepository,
    TaipowerUnitGenerationRepository,
    TimeSeriesRepository,
)
from shiro_mlops.features.transformers import merge_weather_features
from tests.helpers import (
    canonical_observation_batch,
    derived_hourly_load,
    forecast_release,
    township_forecast,
    write_derived_load,
)


@pytest.fixture
def repository(test_repo: TimeSeriesRepository) -> TimeSeriesRepository:
    """Fixture alias returning TimeSeriesRepository backed by canonical test engine."""
    return test_repo


def test_repository_initialization(sqlite_engine: Engine):
    """Verify repository initializes with custom engine, URI, or default settings."""
    repo_engine = TimeSeriesRepository(engine=sqlite_engine)
    assert repo_engine.engine is sqlite_engine

    repo_uri = TimeSeriesRepository(uri="sqlite:///:memory:")
    assert isinstance(repo_uri.engine, Engine)

    with patch("shiro_mlops.data.repository.get_timescale_engine") as mock_get_engine:
        mock_engine = MagicMock(spec=Engine)
        mock_get_engine.return_value = mock_engine
        repo_default = TimeSeriesRepository(auto_init=False)
        assert repo_default.engine is mock_engine
        mock_get_engine.assert_called_once()


def test_repository_hands_out_a_cwa_weather_store_on_its_engine(
    sqlite_engine: Engine, cwa_observation_batch: CWAObservationBatch
) -> None:
    """Weather written through the facade's store is what any store on that engine reads."""
    store = TimeSeriesRepository(engine=sqlite_engine).cwa_weather_store

    store.upsert_cwa_observation_batch(cwa_observation_batch)

    observations = CWAWeatherStore(sqlite_engine).fetch_cwa_station_observations()
    assert len(observations) == len(cwa_observation_batch.observations)


@pytest.mark.parametrize(
    "repository_type",
    [
        TimeSeriesRepository,
        TaipowerSupplyDemandRepository,
        TaipowerRegionalSupplyDemandRepository,
        TaipowerUnitGenerationRepository,
    ],
)
def test_repository_initialization_reports_database_failure(repository_type, tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'missing' / 'database.db'}")
    try:
        with pytest.raises(SQLAlchemyError, match="unable to open database file"):
            repository_type(engine=engine)
    finally:
        engine.dispose()


def test_repository_stores_taiwan_local_timestamps_as_utc_and_reads_them_back_aligned(
    repository: TimeSeriesRepository,
) -> None:
    """Persist Taiwan-local load and weather as UTC, then return aligned local feature times."""
    load_df = pd.DataFrame([{"datetime": "2026-08-20T14:00:00.000", "load_mw": 38000.0}])
    weather_df = pd.DataFrame(
        [
            {
                "datetime": "2026-08-20T06:00:00Z",
                "temperature": 35.5,
                "relative_humidity": 55.0,
                "location": "Taipei",
            }
        ]
    )

    write_derived_load(repository.engine, load_df)
    repository.cwa_weather_store.upsert_cwa_observation_batch(
        canonical_observation_batch(weather_df)
    )

    with repository.engine.connect() as conn:
        stored_load_time = pd.read_sql_query("SELECT time FROM raw_taipower_load", conn).iloc[0][
            "time"
        ]
        stored_weather_time = pd.read_sql_query(
            "SELECT observed_at FROM raw_cwa_station_observation", conn
        ).iloc[0]["observed_at"]

    expected_utc = pd.Timestamp("2026-08-20 06:00:00+00:00")
    assert pd.Timestamp(stored_load_time) == expected_utc
    assert pd.Timestamp(stored_weather_time) == expected_utc

    persisted_load = repository.hourly_actual_load_store.series(
        start=datetime(2026, 8, 20, 14, 0), end=datetime(2026, 8, 20, 15, 0)
    )
    persisted_weather = repository.cwa_weather_store.fetch_weather_range(
        start_time="2026-08-20T06:00:00Z",
        end_time="2026-08-20T06:00:00Z",
        reference_point="Taipei",
    )

    assert persisted_load.iloc[0]["datetime"] == pd.Timestamp("2026-08-20 14:00:00")
    assert persisted_weather.iloc[0]["time"] == pd.Timestamp("2026-08-20 14:00:00")

    merged = merge_weather_features(
        persisted_load, persisted_weather.rename(columns={"time": "datetime"})
    )
    assert merged.iloc[0]["temperature"] == pytest.approx(35.5)


def _stored_text(engine: Engine, table: str, columns: str) -> list[tuple[str, ...]]:
    with engine.connect() as conn:
        return [
            tuple(row)
            for row in conn.execute(text(f"SELECT {columns} FROM {table} ORDER BY {columns}"))
        ]


def test_load_and_cwa_writes_store_one_aware_utc_text_form(
    repository: TimeSeriesRepository,
) -> None:
    """Load and CWA instants persist as aware UTC text whatever form the Taiwan-local input took."""
    write_derived_load(
        repository.engine,
        pd.DataFrame(
            {
                "datetime": [
                    pd.Timestamp("2026-08-20 14:00:00"),
                    "2026-08-20T07:00:00Z",
                    pd.Timestamp("2026-08-20 16:00:00.250000"),
                ],
                "load_mw": [38000.0, 38100.0, 38200.0],
            }
        ),
    )
    repository.cwa_weather_store.upsert_cwa_observation_batch(
        replace(
            canonical_observation_batch(
                pd.DataFrame(
                    [
                        {
                            "datetime": "2026-08-20 14:00:00",
                            "temperature": 35.5,
                            "relative_humidity": 55.0,
                            "location": "Taipei",
                        },
                        {
                            "datetime": "2026-08-20T07:00:00+00:00",
                            "temperature": 35.0,
                            "relative_humidity": 56.0,
                            "location": "Taipei",
                        },
                    ]
                )
            ),
            fetched_at=datetime(2026, 8, 20, 15, 5, 30, 123456),
        )
    )
    repository.cwa_weather_store.upsert_cwa_forecast_releases(
        [
            replace(
                forecast_release(
                    datetime(2026, 8, 20, 11, 0),
                    (
                        township_forecast(
                            datetime(2026, 8, 20, 12, 0),
                            31.0,
                            valid_to=datetime(2026, 8, 20, 15, 0),
                        ),
                    ),
                ),
                source_updated_at=pd.Timestamp("2026-08-20T11:20:00+08:00"),
                fetched_at=datetime(2026, 8, 20, 11, 25),
            )
        ]
    )

    assert _stored_text(repository.engine, "raw_taipower_load", "time") == [
        ("2026-08-20 06:00:00+00:00",),
        ("2026-08-20 07:00:00+00:00",),
        ("2026-08-20 08:00:00.250000+00:00",),
    ]
    assert _stored_text(repository.engine, "raw_cwa_observation_batch", "fetched_at") == [
        ("2026-08-20 07:05:30.123456+00:00",)
    ]
    assert _stored_text(repository.engine, "raw_cwa_station_observation", "observed_at") == [
        ("2026-08-20 06:00:00+00:00",),
        ("2026-08-20 07:00:00+00:00",),
    ]
    assert _stored_text(
        repository.engine, "raw_cwa_forecast_release", "issued_at, source_updated_at, fetched_at"
    ) == [("2026-08-20 03:00:00+00:00", "2026-08-20 03:20:00+00:00", "2026-08-20 03:25:00+00:00")]
    assert _stored_text(
        repository.engine,
        "raw_cwa_township_forecast",
        "issued_at, source_updated_at, valid_from, valid_to",
    ) == [
        (
            "2026-08-20 03:00:00+00:00",
            "2026-08-20 03:20:00+00:00",
            "2026-08-20 04:00:00+00:00",
            "2026-08-20 07:00:00+00:00",
        )
    ]


def test_load_and_cwa_reads_return_taiwan_local_naive_instants(
    repository: TimeSeriesRepository,
) -> None:
    """Every load and CWA read hands back Taiwan-local naive instants, bounds included."""
    write_derived_load(repository.engine, derived_hourly_load(3, datetime(2026, 8, 20, 16, 0)))
    repository.cwa_weather_store.upsert_cwa_forecast_releases(
        [
            replace(
                forecast_release(
                    datetime(2026, 8, 20, 11, 0),
                    (
                        township_forecast(
                            datetime(2026, 8, 20, 12, 0),
                            31.0,
                            valid_to=datetime(2026, 8, 20, 15, 0),
                        ),
                    ),
                ),
                source_updated_at=pd.Timestamp("2026-08-20 11:20"),
            )
        ]
    )

    store = repository.hourly_actual_load_store
    loads = store.series(
        start=pd.Timestamp("2026-08-20T06:00:00Z"), end=datetime(2026, 8, 20, 16, 0)
    )
    latest = store.latest_observation(datetime(2026, 8, 20, 15, 30))
    accumulation = store.accumulation(datetime(2026, 8, 20, 15, 0))
    forecasts = repository.cwa_weather_store.fetch_cwa_forecast_rows(
        geocode="63000050",
        issued_before="2026-08-20T03:00:00Z",
        source_updated_before=datetime(2026, 8, 20, 11, 20),
        valid_start=datetime(2026, 8, 20, 15, 0),
        valid_end="2026-08-20 12:00",
    )

    assert list(loads["datetime"]) == [
        pd.Timestamp("2026-08-20 14:00"),
        pd.Timestamp("2026-08-20 15:00"),
    ]
    assert latest is not None
    assert latest.hour == pd.Timestamp("2026-08-20 15:00")
    assert accumulation.valid_hours == 2
    assert accumulation.latest_hour == datetime(2026, 8, 20, 15, 0)
    assert forecasts[["issued_at", "source_updated_at", "valid_from", "valid_to"]].to_dict(
        "records"
    ) == [
        {
            "issued_at": pd.Timestamp("2026-08-20 11:00"),
            "source_updated_at": pd.Timestamp("2026-08-20 11:20"),
            "valid_from": pd.Timestamp("2026-08-20 12:00"),
            "valid_to": pd.Timestamp("2026-08-20 15:00"),
        }
    ]
