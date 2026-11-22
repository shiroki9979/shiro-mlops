"""Unit tests for TimeSeriesRepository and batch upsert operations."""

from dataclasses import replace
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from shiro_mlops.core.config import settings
from shiro_mlops.data.hourly_actual_load import REGIONAL_SNAPSHOT_SUM_SOURCE
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
    insert_legacy_load_row,
    township_forecast,
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


def test_upsert_taipower_load_insert_and_fetch(
    repository: TimeSeriesRepository, taipower_raw_df: pd.DataFrame
):
    """Verify upsert_taipower_load inserts records and fetch_load_range retrieves them."""
    affected = repository.upsert_taipower_load(taipower_raw_df, default_subject="nationwide")
    assert affected == len(taipower_raw_df)

    fetched_df = repository.fetch_load_range(subject="nationwide")
    assert len(fetched_df) == len(taipower_raw_df)
    assert "time" in fetched_df.columns
    assert "subject" in fetched_df.columns
    assert "load_mw" in fetched_df.columns
    assert fetched_df.iloc[0]["load_mw"] == pytest.approx(26500.0)
    assert fetched_df.iloc[0]["subject"] == "nationwide"


def test_repository_stores_taiwan_local_timestamps_as_utc_and_reads_them_back_aligned(
    repository: TimeSeriesRepository,
) -> None:
    """Persist Taiwan-local load and weather as UTC, then return aligned local feature times."""
    load_df = pd.DataFrame(
        [
            {
                "datetime": "2026-08-20T14:00:00.000",
                "load_mw": 38000.0,
                "subject": "nationwide",
            }
        ]
    )
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

    repository.upsert_taipower_load(load_df)
    repository.upsert_cwa_observation_batch(canonical_observation_batch(weather_df))

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

    persisted_load = repository.fetch_load_range(
        start_time="2026-08-20 14:00:00",
        end_time="2026-08-20 14:00:00",
        subject="nationwide",
    )
    persisted_weather = repository.fetch_weather_range(
        start_time="2026-08-20T06:00:00Z",
        end_time="2026-08-20T06:00:00Z",
        reference_point="Taipei",
    )

    assert persisted_load.iloc[0]["time"] == pd.Timestamp("2026-08-20 14:00:00")
    assert persisted_weather.iloc[0]["time"] == pd.Timestamp("2026-08-20 14:00:00")

    merged = merge_weather_features(
        persisted_load.rename(columns={"time": "datetime"}),
        persisted_weather.rename(columns={"time": "datetime"}),
    )
    assert merged.iloc[0]["temperature"] == pytest.approx(35.5)


def _stored_text(engine: Engine, table: str, columns: str) -> list[tuple[str, ...]]:
    with engine.connect() as conn:
        return [tuple(row) for row in conn.execute(text(f"SELECT {columns} FROM {table} ORDER BY {columns}"))]


def test_load_and_cwa_writes_store_one_aware_utc_text_form(
    repository: TimeSeriesRepository,
) -> None:
    """Load and CWA instants persist as aware UTC text whatever form the Taiwan-local input took."""
    repository.upsert_taipower_load(
        pd.DataFrame(
            {
                "datetime": [
                    pd.Timestamp("2026-08-20 14:00:00"),
                    "2026-08-20T07:00:00Z",
                    pd.Timestamp("2026-08-20 16:00:00.250000"),
                ],
                "load_mw": [38000.0, 38100.0, 38200.0],
            }
        )
    )
    repository.upsert_cwa_observation_batch(
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
    repository.upsert_cwa_forecast_release(
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
    repository.upsert_taipower_load(derived_hourly_load(3, datetime(2026, 8, 20, 16, 0)))
    repository.upsert_cwa_forecast_release(
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
    )

    loads = repository.fetch_load_range(
        start_time="2026-08-20T06:00:00Z", end_time=datetime(2026, 8, 20, 15, 0)
    )
    latest = repository.fetch_latest_load(at_or_before=datetime(2026, 8, 20, 15, 30))
    accumulation = repository.summarize_hourly_load_accumulation(
        at_or_before=datetime(2026, 8, 20, 15, 0)
    )
    forecasts = repository.fetch_cwa_forecast_rows(
        geocode="63000050",
        issued_before="2026-08-20T03:00:00Z",
        source_updated_before=datetime(2026, 8, 20, 11, 20),
        valid_start=datetime(2026, 8, 20, 15, 0),
        valid_end="2026-08-20 12:00",
    )

    assert list(loads["time"]) == [
        pd.Timestamp("2026-08-20 14:00"),
        pd.Timestamp("2026-08-20 15:00"),
    ]
    assert list(latest["time"]) == [pd.Timestamp("2026-08-20 15:00")]
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


def test_upsert_taipower_load_idempotency_and_update(repository: TimeSeriesRepository):
    """Verify ON CONFLICT DO UPDATE updates load_mw without creating duplicate rows."""
    initial_df = pd.DataFrame(
        [
            {"datetime": "2026-08-20 00:00:00", "load_mw": 25000.0, "subject": "nationwide"},
            {"datetime": "2026-08-20 01:00:00", "load_mw": 24000.0, "subject": "nationwide"},
        ]
    )
    repository.upsert_taipower_load(initial_df)

    revised_df = pd.DataFrame(
        [
            {"datetime": "2026-08-20 00:00:00", "load_mw": 26800.0, "subject": "nationwide"},
        ]
    )
    repository.upsert_taipower_load(revised_df)

    fetched_df = repository.fetch_load_range(subject="nationwide")
    assert len(fetched_df) == 2
    row_00 = fetched_df[fetched_df["time"] == pd.Timestamp("2026-08-20 00:00:00")].iloc[0]
    assert row_00["load_mw"] == pytest.approx(26800.0)


def test_upsert_taipower_load_marks_regional_snapshot_source(
    repository: TimeSeriesRepository,
) -> None:
    """Upserting derived load records its source and updates that source when replacing an hour."""
    load_df = pd.DataFrame([{"datetime": "2026-09-26 13:00:00", "load_mw": 30550.0}])

    repository.upsert_taipower_load(load_df)
    repository.upsert_taipower_load(load_df.assign(load_mw=30600.0))

    with repository.engine.connect() as conn:
        rows = pd.read_sql_query("SELECT subject, load_mw, source FROM raw_taipower_load", conn)
    assert rows.to_dict("records") == [
        {"subject": "nationwide", "load_mw": 30600.0, "source": "regional_snapshot_sum"}
    ]


def test_upsert_cwa_weather_insert_and_fetch(
    repository: TimeSeriesRepository, cwa_obs_df: pd.DataFrame, cwa_observation_batch
):
    """Verify canonical observations are exposed through the training weather query."""
    affected = repository.upsert_cwa_observation_batch(cwa_observation_batch)
    assert affected == len(cwa_obs_df)

    fetched_df = repository.fetch_weather_range(reference_point="Taipei")
    assert len(fetched_df) == len(cwa_obs_df)
    assert "time" in fetched_df.columns
    assert "location" in fetched_df.columns
    assert "temperature" in fetched_df.columns
    assert "relative_humidity" in fetched_df.columns
    assert fetched_df.iloc[0]["temperature"] == pytest.approx(27.8)
    assert fetched_df.iloc[0]["relative_humidity"] == pytest.approx(80.0)


def test_legacy_weather_upsert_is_rejected_before_it_can_create_canonical_provenance(
    repository: TimeSeriesRepository,
) -> None:
    """Legacy location labels must never be converted into canonical station identities."""
    legacy_weather = pd.DataFrame(
        [
            {
                "datetime": "2026-08-20 00:00:00",
                "location": "Unknown",
                "temperature": 27.0,
                "relative_humidity": 80.0,
            }
        ]
    )

    with pytest.raises(RuntimeError, match="Legacy CWA weather writes are not supported"):
        repository.upsert_cwa_weather(legacy_weather)

    assert repository.fetch_cwa_station_observations().empty


def test_fetch_weather_range_keeps_canonical_station_identity(
    repository: TimeSeriesRepository,
    cwa_observation_batch,
) -> None:
    """Training source rows retain StationId so strict gap handling is selected."""
    repository.upsert_cwa_observation_batch(cwa_observation_batch)

    weather = repository.fetch_weather_range(reference_point="Taipei")

    assert set(weather["station_id"]) == {"466920"}


def test_fetch_weather_range_uses_configured_taipei_station(
    repository: TimeSeriesRepository,
    cwa_observation_batch,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings,
        "CWA_LOCATION_ALLOWLIST",
        '{"Taipei": {"station_id": "999999", "geocode": "99999999"}}',
    )
    observation = replace(cwa_observation_batch.observations[0], station_id="999999")
    repository.upsert_cwa_observation_batch(
        replace(cwa_observation_batch, observations=(observation,))
    )

    weather = repository.fetch_weather_range(reference_point="Taipei")

    assert len(weather) == 1
    assert weather.iloc[0]["station_id"] == "999999"
    assert weather.iloc[0]["location"] == "Taipei"


def test_upsert_cwa_weather_idempotency_and_update(repository: TimeSeriesRepository):
    """Verify ON CONFLICT DO UPDATE updates temperature and relative_humidity on conflict."""
    initial_df = pd.DataFrame(
        [
            {
                "datetime": "2026-08-20 00:00:00",
                "temperature": 27.0,
                "relative_humidity": 80.0,
                "location": "Taipei",
            }
        ]
    )
    repository.upsert_cwa_observation_batch(canonical_observation_batch(initial_df))

    updated_df = pd.DataFrame(
        [
            {
                "datetime": "2026-08-20 00:00:00",
                "temperature": 29.5,
                "relative_humidity": 75.0,
                "location": "Taipei",
            }
        ]
    )
    repository.upsert_cwa_observation_batch(canonical_observation_batch(updated_df))

    fetched_df = repository.fetch_weather_range(reference_point="Taipei")
    assert len(fetched_df) == 1
    assert fetched_df.iloc[0]["temperature"] == pytest.approx(29.5)
    assert fetched_df.iloc[0]["relative_humidity"] == pytest.approx(75.0)


def test_upsert_cwa_weather_preserves_non_null_fields_on_partial_update(
    repository: TimeSeriesRepository,
):
    """Verify COALESCE logic preserves existing non-null fields on partial update."""
    initial_df = pd.DataFrame(
        [
            {
                "datetime": "2026-08-20 00:00:00",
                "temperature": 27.0,
                "relative_humidity": 80.0,
                "location": "Taipei",
            }
        ]
    )
    repository.upsert_cwa_observation_batch(canonical_observation_batch(initial_df))

    # Partial update: new temperature, relative_humidity is None/NaN
    partial_df = pd.DataFrame(
        [
            {
                "datetime": "2026-08-20 00:00:00",
                "temperature": 31.0,
                "relative_humidity": None,
                "location": "Taipei",
            }
        ]
    )
    repository.upsert_cwa_observation_batch(canonical_observation_batch(partial_df))

    fetched_df = repository.fetch_weather_range(reference_point="Taipei")
    assert len(fetched_df) == 1
    assert fetched_df.iloc[0]["temperature"] == pytest.approx(31.0)
    # Relative humidity preserved from initial insert
    assert fetched_df.iloc[0]["relative_humidity"] == pytest.approx(80.0)


def test_upsert_empty_dataframe(repository: TimeSeriesRepository):
    """Verify upsert methods gracefully handle empty DataFrames returning 0."""
    empty_df = pd.DataFrame()
    assert repository.upsert_taipower_load(empty_df) == 0
    with pytest.raises(RuntimeError, match="Legacy CWA weather writes are not supported"):
        repository.upsert_cwa_weather(empty_df)


def test_fetch_load_range_by_source_excludes_legacy_rows(legacy_upgraded_engine: Engine):
    """Under ADR-0008, source filtering excludes legacy d015046 rows with NULL source."""
    repository = TimeSeriesRepository(engine=legacy_upgraded_engine, auto_init=False)
    repository.upsert_taipower_load(derived_hourly_load(2, datetime(2026, 8, 21, 1, 0)))
    insert_legacy_load_row(legacy_upgraded_engine, datetime(2026, 8, 21, 2, 0), load_mw=99999.0)

    derived = repository.fetch_load_range(subject="nationwide", source=REGIONAL_SNAPSHOT_SUM_SOURCE)

    assert list(derived["load_mw"]) == [30000.0, 30001.0]
    assert derived["time"].max() == pd.Timestamp("2026-08-21 01:00")


def test_fetch_latest_load_returns_newest_derived_row_only(legacy_upgraded_engine: Engine):
    """Hourly drift reads only the newest derived row; newer legacy rows cannot stand in for actual load."""
    repository = TimeSeriesRepository(engine=legacy_upgraded_engine, auto_init=False)
    repository.upsert_taipower_load(derived_hourly_load(3, datetime(2026, 8, 21, 1, 0)))
    insert_legacy_load_row(legacy_upgraded_engine, datetime(2026, 8, 21, 2, 0), load_mw=99999.0)

    latest = repository.fetch_latest_load(subject="nationwide", source=REGIONAL_SNAPSHOT_SUM_SOURCE)

    assert len(latest) == 1
    assert latest.iloc[0]["time"] == pd.Timestamp("2026-08-21 01:00")
    assert latest.iloc[0]["load_mw"] == 30002.0


def test_fetch_load_range_filters_and_sorting(repository: TimeSeriesRepository):
    """Verify fetch_load_range filters by date range and prediction subject with ascending sort."""
    df = pd.DataFrame(
        [
            {"datetime": "2026-08-20 03:00:00", "load_mw": 23800.0, "subject": "nationwide"},
            {"datetime": "2026-08-20 01:00:00", "load_mw": 25200.0, "subject": "nationwide"},
            {"datetime": "2026-08-20 02:00:00", "load_mw": 24300.0, "subject": "nationwide"},
            {"datetime": "2026-08-20 02:00:00", "load_mw": 18000.0, "subject": "south"},
        ]
    )
    repository.upsert_taipower_load(df)

    # Filter by time range and prediction subject
    filtered_df = repository.fetch_load_range(
        start_time=datetime(2026, 8, 20, 1, 0),
        end_time="2026-08-20 02:00:00",
        subject="nationwide",
    )
    assert len(filtered_df) == 2
    assert list(filtered_df["load_mw"]) == [25200.0, 24300.0]

    # Verify sorting
    assert filtered_df.iloc[0]["time"] < filtered_df.iloc[1]["time"]


def test_fetch_weather_range_filters_and_sorting(repository: TimeSeriesRepository):
    """Verify fetch_weather_range filters by date range and weather reference point with ascending sort."""
    df = pd.DataFrame(
        [
            {
                "datetime": "2026-08-20 05:00:00",
                "temperature": 26.6,
                "relative_humidity": 84.0,
                "location": "Taipei",
            },
            {
                "datetime": "2026-08-20 02:00:00",
                "temperature": 26.9,
                "relative_humidity": 83.0,
                "location": "Taipei",
            },
            {
                "datetime": "2026-08-20 02:00:00",
                "temperature": 28.0,
                "relative_humidity": 80.0,
                "location": "Taichung",
            },
        ]
    )
    repository.upsert_cwa_observation_batch(canonical_observation_batch(df))

    filtered_df = repository.fetch_weather_range(
        start_time="2026-08-20 01:00:00",
        end_time="2026-08-20 04:00:00",
        reference_point="Taipei",
    )
    assert len(filtered_df) == 1
    assert filtered_df.iloc[0]["temperature"] == pytest.approx(26.9)


def test_fetch_weather_range_propagates_database_errors(
    repository: TimeSeriesRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A database outage must not appear as missing observed weather to callers."""

    def unavailable(**_: object) -> pd.DataFrame:
        raise OperationalError("SELECT", {}, Exception("connection refused"))

    monkeypatch.setattr(repository, "fetch_cwa_station_observations", unavailable)

    with pytest.raises(OperationalError):
        repository.fetch_weather_range(reference_point="Taipei")


def test_fetch_empty_results_schema(repository: TimeSeriesRepository):
    """Verify fetch methods on empty tables return empty DataFrames with correct columns and dtypes."""
    load_df = repository.fetch_load_range()
    assert load_df.empty
    assert "time" in load_df.columns
    assert "subject" in load_df.columns
    assert "load_mw" in load_df.columns
    assert pd.api.types.is_datetime64_any_dtype(load_df["time"])

    weather_df = repository.fetch_weather_range()
    assert weather_df.empty
    assert "time" in weather_df.columns
    assert "location" in weather_df.columns
    assert "temperature" in weather_df.columns
    assert "relative_humidity" in weather_df.columns
    assert pd.api.types.is_datetime64_any_dtype(weather_df["time"])
