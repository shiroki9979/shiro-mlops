"""CWA weather store: observation batches, forecast vintages and reference point weather."""

from dataclasses import replace

import pandas as pd
import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError

from shiro_mlops.core.config import settings
from shiro_mlops.data.cwa_client import CWALocation, CWAObservationBatch
from shiro_mlops.data.cwa_weather_store import FORECAST_ROW_COLUMNS, CWAWeatherStore
from tests.helpers import canonical_observation_batch, forecast_release, township_forecast

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


def _releases_every_six_hours(days: int, *, last_issue: pd.Timestamp) -> list:
    """Three-day releases for one geocode, each holding the next twelve hours."""
    issues = pd.date_range(end=last_issue, periods=days * 4, freq="6h")
    return [
        forecast_release(
            issued.to_pydatetime(),
            tuple(
                replace(
                    township_forecast(
                        (issued + pd.Timedelta(hours=offset)).to_pydatetime(), 20.0 + offset
                    ),
                    geocode="63000050",
                )
                for offset in range(1, 13)
            ),
        )
        for issued in issues
    ]


LAST_ISSUE = pd.Timestamp("2026-08-20 11:00")
CUTOFF = LAST_ISSUE + pd.Timedelta(minutes=30)


@pytest.fixture
def week_of_releases(store: CWAWeatherStore) -> CWAWeatherStore:
    store.upsert_cwa_forecast_releases(_releases_every_six_hours(7, last_issue=LAST_ISSUE))
    return store


def test_a_lower_issue_bound_keeps_the_newest_release_it_admits(
    week_of_releases: CWAWeatherStore,
) -> None:
    rows = week_of_releases.fetch_cwa_forecast_rows(
        geocode="63000050",
        issued_before=CUTOFF,
        source_updated_before=CUTOFF,
        issued_after=CUTOFF - pd.Timedelta(hours=7),
        valid_start=LAST_ISSUE + pd.Timedelta(hours=1),
        valid_end=LAST_ISSUE + pd.Timedelta(hours=3),
    )

    assert set(rows["issued_at"]) == {LAST_ISSUE}
    assert rows["valid_from"].tolist() == list(
        pd.date_range(LAST_ISSUE + pd.Timedelta(hours=1), periods=3, freq="h")
    )


def test_a_lower_issue_bound_admits_a_release_issued_exactly_on_it(
    week_of_releases: CWAWeatherStore,
) -> None:
    """Seven hours old is still fresh; only older is stale."""
    cutoff = LAST_ISSUE + pd.Timedelta(hours=7)
    rows = week_of_releases.fetch_cwa_forecast_rows(
        geocode="63000050",
        issued_before=cutoff,
        source_updated_before=cutoff,
        issued_after=cutoff - pd.Timedelta(hours=7),
    )

    assert set(rows["issued_at"]) == {LAST_ISSUE}


def test_no_release_inside_the_lower_issue_bound_reads_nothing(
    week_of_releases: CWAWeatherStore,
) -> None:
    """Every release is older than the bound, which serving would discard as stale anyway."""
    cutoff = LAST_ISSUE + pd.Timedelta(hours=8)

    rows = week_of_releases.fetch_cwa_forecast_rows(
        geocode="63000050",
        issued_before=cutoff,
        source_updated_before=cutoff,
        issued_after=cutoff - pd.Timedelta(hours=7),
    )

    assert rows.empty
    assert list(rows.columns) == FORECAST_ROW_COLUMNS


def test_a_point_in_time_read_returns_only_rows_of_the_selected_release(
    week_of_releases: CWAWeatherStore,
) -> None:
    """Older releases overlap the window too; only the newest release's rows come back."""
    rows = week_of_releases.fetch_cwa_forecast_rows(
        geocode="63000050",
        issued_before=CUTOFF,
        source_updated_before=CUTOFF,
        valid_start=LAST_ISSUE - pd.Timedelta(hours=3),
        valid_end=LAST_ISSUE + pd.Timedelta(hours=3),
        include_adjacent_points=True,
    )

    assert set(rows["issued_at"]) == {LAST_ISSUE}
    assert rows["valid_from"].min() == LAST_ISSUE + pd.Timedelta(hours=1)


def test_a_point_in_time_read_with_a_lower_bound_reads_only_recent_vintages(
    week_of_releases: CWAWeatherStore, sqlite_engine: Engine
) -> None:
    """Without the bound, choosing a version read every vintage the geocode ever had."""
    statements: list[tuple[str, dict]] = []

    def record(conn, cursor, statement, parameters, *_args) -> None:
        statements.append((statement, parameters))

    event.listen(sqlite_engine, "before_cursor_execute", record)
    try:
        week_of_releases.fetch_cwa_forecast_rows(
            geocode="63000050",
            issued_before=CUTOFF,
            source_updated_before=CUTOFF,
            issued_after=CUTOFF - pd.Timedelta(hours=7),
            valid_start=LAST_ISSUE + pd.Timedelta(hours=1),
            valid_end=LAST_ISSUE + pd.Timedelta(hours=3),
            include_adjacent_points=True,
        )
    finally:
        event.remove(sqlite_engine, "before_cursor_execute", record)

    reads = [statement for statement, _ in statements if "raw_cwa_" in statement]
    assert reads
    assert all("issued_at >= " in statement or "issued_at = " in statement for statement in reads)
