"""CWA weather store: observation batches, forecast vintages and reference point weather."""

from dataclasses import replace

import pandas as pd
import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError

from shiro_mlops.core.config import settings
from shiro_mlops.data.cwa_client import CWALocation, CWAObservationBatch
from shiro_mlops.data.cwa_weather_store import FORECAST_ROW_COLUMNS, CWAWeatherStore
from tests.helpers import canonical_observation_batch

TAIPEI = CWALocation("Taipei", "466920", "63000000")


@pytest.fixture
def store(sqlite_engine: Engine) -> CWAWeatherStore:
    return CWAWeatherStore(sqlite_engine)


def test_observation_batch_write_failure_rolls_back_its_header(
    store: CWAWeatherStore, sqlite_engine: Engine, cwa_observation_batch: CWAObservationBatch
) -> None:
    """A batch whose station rows cannot be written leaves neither header nor any station row."""
    invalid = replace(cwa_observation_batch.observations[-1], station_id=None)
    batch = replace(
        cwa_observation_batch,
        observations=(*cwa_observation_batch.observations[:-1], invalid),
    )

    with pytest.raises(IntegrityError):
        store.upsert_cwa_observation_batch(batch)

    headers = pd.read_sql_query("SELECT * FROM raw_cwa_observation_batch", sqlite_engine)
    assert headers.empty
    assert store.fetch_cwa_station_observations().empty


def test_point_in_time_forecast_read_without_rows_returns_empty_frame(
    store: CWAWeatherStore,
) -> None:
    """A cutoff read before any vintage exists is an empty result, not an error."""
    rows = store.fetch_cwa_forecast_rows(geocode="63000050", issued_before="2026-08-20 12:00")

    assert rows.empty
    assert list(rows.columns) == FORECAST_ROW_COLUMNS


def test_observation_batch_is_read_back_as_reference_point_weather(
    store: CWAWeatherStore, cwa_obs_df: pd.DataFrame, cwa_observation_batch
):
    """Verify canonical observations are exposed through the training weather query."""
    affected = store.upsert_cwa_observation_batch(cwa_observation_batch)
    assert affected == len(cwa_obs_df)

    fetched_df = store.fetch_weather_range(reference_point=TAIPEI)
    assert len(fetched_df) == len(cwa_obs_df)
    assert "time" in fetched_df.columns
    assert "location" in fetched_df.columns
    assert "temperature" in fetched_df.columns
    assert "relative_humidity" in fetched_df.columns
    assert fetched_df.iloc[0]["temperature"] == pytest.approx(27.8)
    assert fetched_df.iloc[0]["relative_humidity"] == pytest.approx(80.0)


def test_fetch_weather_range_keeps_canonical_station_identity(
    store: CWAWeatherStore,
    cwa_observation_batch,
) -> None:
    """Training source rows retain StationId so strict gap handling is selected."""
    store.upsert_cwa_observation_batch(cwa_observation_batch)

    weather = store.fetch_weather_range(reference_point=TAIPEI)

    assert set(weather["station_id"]) == {"466920"}


def test_reference_point_weather_reads_the_given_location_outside_the_ingestion_catalog(
    store: CWAWeatherStore,
    cwa_observation_batch,
) -> None:
    """The station and the alias both come from the reference point passed in."""
    hualien = CWALocation("Hualien", "466990", "10015000")
    assert hualien.alias not in settings.cwa_locations
    hualien_observation = replace(
        cwa_observation_batch.observations[0], station_id=hualien.station_id
    )
    store.upsert_cwa_observation_batch(
        replace(
            cwa_observation_batch,
            observations=(*cwa_observation_batch.observations, hualien_observation),
        )
    )

    weather = store.fetch_weather_range(reference_point=hualien)

    assert list(weather["station_id"]) == ["466990"]
    assert list(weather["location"]) == ["Hualien"]
    assert weather.iloc[0]["temperature"] == pytest.approx(27.8)


def test_observation_batch_upsert_updates_an_observed_station_hour(store: CWAWeatherStore):
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
    store.upsert_cwa_observation_batch(canonical_observation_batch(initial_df))

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
    store.upsert_cwa_observation_batch(canonical_observation_batch(updated_df))

    fetched_df = store.fetch_weather_range(reference_point=TAIPEI)
    assert len(fetched_df) == 1
    assert fetched_df.iloc[0]["temperature"] == pytest.approx(29.5)
    assert fetched_df.iloc[0]["relative_humidity"] == pytest.approx(75.0)


def test_observation_batch_upsert_preserves_non_null_fields_on_partial_update(
    store: CWAWeatherStore,
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
    store.upsert_cwa_observation_batch(canonical_observation_batch(initial_df))

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
    store.upsert_cwa_observation_batch(canonical_observation_batch(partial_df))

    fetched_df = store.fetch_weather_range(reference_point=TAIPEI)
    assert len(fetched_df) == 1
    assert fetched_df.iloc[0]["temperature"] == pytest.approx(31.0)
    assert fetched_df.iloc[0]["relative_humidity"] == pytest.approx(80.0)


def test_fetch_weather_range_filters_and_sorting(store: CWAWeatherStore):
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
    store.upsert_cwa_observation_batch(canonical_observation_batch(df))

    filtered_df = store.fetch_weather_range(
        start_time="2026-08-20 01:00:00",
        end_time="2026-08-20 04:00:00",
        reference_point=TAIPEI,
    )
    assert len(filtered_df) == 1
    assert filtered_df.iloc[0]["temperature"] == pytest.approx(26.9)


def test_fetch_weather_range_propagates_database_errors(
    store: CWAWeatherStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A database outage must not appear as missing observed weather to callers."""

    def unavailable(**_: object) -> pd.DataFrame:
        raise OperationalError("SELECT", {}, Exception("connection refused"))

    monkeypatch.setattr(store, "fetch_cwa_station_observations", unavailable)

    with pytest.raises(OperationalError):
        store.fetch_weather_range(reference_point=TAIPEI)


def test_fetch_empty_results_schema(store: CWAWeatherStore):
    """Verify the weather fetch on empty tables returns an empty DataFrame with typed columns."""
    weather_df = store.fetch_weather_range(reference_point=TAIPEI)
    assert weather_df.empty
    assert "time" in weather_df.columns
    assert "location" in weather_df.columns
    assert "temperature" in weather_df.columns
    assert "relative_humidity" in weather_df.columns
    assert pd.api.types.is_datetime64_any_dtype(weather_df["time"])
