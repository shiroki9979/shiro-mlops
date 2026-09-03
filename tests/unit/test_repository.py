"""Unit tests for TimeSeriesRepository and batch upsert operations."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from sqlalchemy.engine import Engine

from shiro_mlops.data.repository import TimeSeriesRepository


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
        repo_default = TimeSeriesRepository()
        assert repo_default.engine is mock_engine
        mock_get_engine.assert_called_once()


def test_upsert_taipower_load_insert_and_fetch(
    repository: TimeSeriesRepository, taipower_raw_df: pd.DataFrame
):
    """Verify upsert_taipower_load inserts records and fetch_load_range retrieves them."""
    affected = repository.upsert_taipower_load(taipower_raw_df, default_location="Taipei")
    assert affected == len(taipower_raw_df)

    fetched_df = repository.fetch_load_range(location="Taipei")
    assert len(fetched_df) == len(taipower_raw_df)
    assert "time" in fetched_df.columns
    assert "location" in fetched_df.columns
    assert "load_mw" in fetched_df.columns
    assert fetched_df.iloc[0]["load_mw"] == pytest.approx(26500.0)
    assert fetched_df.iloc[0]["location"] == "Taipei"


def test_upsert_taipower_load_idempotency_and_update(repository: TimeSeriesRepository):
    """Verify ON CONFLICT DO UPDATE updates load_mw without creating duplicate rows."""
    initial_df = pd.DataFrame(
        [
            {"datetime": "2026-08-20 00:00:00", "load_mw": 25000.0, "location": "Taipei"},
            {"datetime": "2026-08-20 01:00:00", "load_mw": 24000.0, "location": "Taipei"},
        ]
    )
    repository.upsert_taipower_load(initial_df)

    revised_df = pd.DataFrame(
        [
            {"datetime": "2026-08-20 00:00:00", "load_mw": 26800.0, "location": "Taipei"},
        ]
    )
    repository.upsert_taipower_load(revised_df)

    fetched_df = repository.fetch_load_range(location="Taipei")
    assert len(fetched_df) == 2
    row_00 = fetched_df[fetched_df["time"] == pd.Timestamp("2026-08-20 00:00:00")].iloc[0]
    assert row_00["load_mw"] == pytest.approx(26800.0)


def test_upsert_cwa_weather_insert_and_fetch(
    repository: TimeSeriesRepository, cwa_obs_df: pd.DataFrame
):
    """Verify upsert_cwa_weather inserts records and fetch_weather_range retrieves them."""
    affected = repository.upsert_cwa_weather(cwa_obs_df, default_location="Taipei")
    assert affected == len(cwa_obs_df)

    fetched_df = repository.fetch_weather_range(location="Taipei")
    assert len(fetched_df) == len(cwa_obs_df)
    assert "time" in fetched_df.columns
    assert "location" in fetched_df.columns
    assert "temperature" in fetched_df.columns
    assert "relative_humidity" in fetched_df.columns
    assert fetched_df.iloc[0]["temperature"] == pytest.approx(27.8)
    assert fetched_df.iloc[0]["relative_humidity"] == pytest.approx(80.0)


def test_upsert_cwa_weather_idempotency_and_update(repository: TimeSeriesRepository):
    """Verify ON CONFLICT DO UPDATE updates temperature and relative_humidity on conflict."""
    initial_df = pd.DataFrame(
        [
            {
                "time": "2026-08-20 00:00:00",
                "temperature": 27.0,
                "relative_humidity": 80.0,
                "location": "Taipei",
            }
        ]
    )
    repository.upsert_cwa_weather(initial_df)

    updated_df = pd.DataFrame(
        [
            {
                "time": "2026-08-20 00:00:00",
                "temperature": 29.5,
                "relative_humidity": 75.0,
                "location": "Taipei",
            }
        ]
    )
    repository.upsert_cwa_weather(updated_df)

    fetched_df = repository.fetch_weather_range(location="Taipei")
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
                "time": "2026-08-20 00:00:00",
                "temperature": 27.0,
                "relative_humidity": 80.0,
                "location": "Taipei",
            }
        ]
    )
    repository.upsert_cwa_weather(initial_df)

    # Partial update: new temperature, relative_humidity is None/NaN
    partial_df = pd.DataFrame(
        [
            {
                "time": "2026-08-20 00:00:00",
                "temperature": 31.0,
                "relative_humidity": None,
                "location": "Taipei",
            }
        ]
    )
    repository.upsert_cwa_weather(partial_df)

    fetched_df = repository.fetch_weather_range(location="Taipei")
    assert len(fetched_df) == 1
    assert fetched_df.iloc[0]["temperature"] == pytest.approx(31.0)
    # Relative humidity preserved from initial insert
    assert fetched_df.iloc[0]["relative_humidity"] == pytest.approx(80.0)


def test_upsert_empty_dataframe(repository: TimeSeriesRepository):
    """Verify upsert methods gracefully handle empty DataFrames returning 0."""
    empty_df = pd.DataFrame()
    assert repository.upsert_taipower_load(empty_df) == 0
    assert repository.upsert_cwa_weather(empty_df) == 0


def test_fetch_load_range_filters_and_sorting(repository: TimeSeriesRepository):
    """Verify fetch_load_range filters by date range and location with ascending sort."""
    df = pd.DataFrame(
        [
            {"datetime": "2026-08-20 03:00:00", "load_mw": 23800.0, "location": "Taipei"},
            {"datetime": "2026-08-20 01:00:00", "load_mw": 25200.0, "location": "Taipei"},
            {"datetime": "2026-08-20 02:00:00", "load_mw": 24300.0, "location": "Taipei"},
            {"datetime": "2026-08-20 02:00:00", "load_mw": 18000.0, "location": "Kaohsiung"},
        ]
    )
    repository.upsert_taipower_load(df)

    # Filter by time range and location
    filtered_df = repository.fetch_load_range(
        start_time=datetime(2026, 8, 20, 1, 0),
        end_time="2026-08-20 02:00:00",
        location="Taipei",
    )
    assert len(filtered_df) == 2
    assert list(filtered_df["load_mw"]) == [25200.0, 24300.0]

    # Verify sorting
    assert filtered_df.iloc[0]["time"] < filtered_df.iloc[1]["time"]


def test_fetch_weather_range_filters_and_sorting(repository: TimeSeriesRepository):
    """Verify fetch_weather_range filters by date range and location with ascending sort."""
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
    repository.upsert_cwa_weather(df)

    filtered_df = repository.fetch_weather_range(
        start_time="2026-08-20 01:00:00",
        end_time="2026-08-20 04:00:00",
        location="Taipei",
    )
    assert len(filtered_df) == 1
    assert filtered_df.iloc[0]["temperature"] == pytest.approx(26.9)


def test_fetch_empty_results_schema(repository: TimeSeriesRepository):
    """Verify fetch methods on empty tables return empty DataFrames with correct columns and dtypes."""
    load_df = repository.fetch_load_range()
    assert load_df.empty
    assert "time" in load_df.columns
    assert "location" in load_df.columns
    assert "load_mw" in load_df.columns
    assert pd.api.types.is_datetime64_any_dtype(load_df["time"])

    weather_df = repository.fetch_weather_range()
    assert weather_df.empty
    assert "time" in weather_df.columns
    assert "location" in weather_df.columns
    assert "temperature" in weather_df.columns
    assert "relative_humidity" in weather_df.columns
    assert pd.api.types.is_datetime64_any_dtype(weather_df["time"])
