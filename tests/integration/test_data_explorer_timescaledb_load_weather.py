"""Opt-in TimescaleDB pagination acceptance for load and station observations."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.service.data_explorer.hourly_load import HourlyLoadReader
from shiro_mlops.service.data_explorer.weather import ObservationReader
from tests.helpers import explorer_pages


def test_load_and_observation_pages_preserve_microseconds_on_timescaledb(
    data_explorer_timescaledb_engine: Engine,
) -> None:
    suffix = uuid4().hex[:8]
    subjects = (f"b-{suffix}", f"a-{suffix}")
    stations = (f"b{suffix}", f"a{suffix}")
    rows = [
        datetime(2040, 9, 20, 4, 0, 0, 900002, UTC),
        datetime(2040, 9, 20, 4, 0, 0, 900001, UTC),
        datetime(2040, 9, 20, 2, 0, 0, 100000, UTC),
    ]
    load_rows = [
        (rows[0], subjects[0], 4.0),
        (rows[0], subjects[1], 3.0),
        (rows[1], subjects[1], 2.0),
        (rows[2], subjects[1], 1.0),
    ]
    observation_rows = [
        (rows[0], stations[0], 4.0),
        (rows[0], stations[1], 3.0),
        (rows[1], stations[1], 2.0),
        (rows[2], stations[1], 1.0),
    ]
    try:
        with data_explorer_timescaledb_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO raw_taipower_load (time, subject, load_mw, source) "
                    "VALUES (:time, :subject, :load_mw, 'regional_snapshot_sum')"
                ),
                [
                    {"time": time, "subject": subject, "load_mw": load}
                    for time, subject, load in load_rows
                ],
            )
            conn.execute(
                text(
                    "INSERT INTO raw_cwa_station_observation "
                    "(observed_at, station_id, temperature_c) "
                    "VALUES (:observed_at, :station_id, :temperature_c)"
                ),
                [
                    {"observed_at": observed, "station_id": station, "temperature_c": temp}
                    for observed, station, temp in observation_rows
                ],
            )
        params = {
            "start": "2040-09-20T10:00:00+08:00",
            "end": "2040-09-20T12:00:01+08:00",
            "limit": 1,
        }
        load_pages = explorer_pages(HourlyLoadReader(data_explorer_timescaledb_engine), params)
        observation_pages = explorer_pages(
            ObservationReader(data_explorer_timescaledb_engine), params
        )

        assert [page.items[0]["load_mw"] for page in load_pages] == [4.0, 3.0, 2.0, 1.0]
        assert [page.items[0]["temperature_c"] for page in observation_pages] == [
            4.0,
            3.0,
            2.0,
            1.0,
        ]
        for pages in (load_pages, observation_pages):
            assert [page.has_more for page in pages] == [True, True, True, False]
            assert all(page.missing_slots == pages[0].missing_slots for page in pages)
    finally:
        with data_explorer_timescaledb_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM raw_cwa_station_observation WHERE station_id IN (:a, :b)"),
                {"a": stations[0], "b": stations[1]},
            )
            conn.execute(
                text("DELETE FROM raw_taipower_load WHERE subject IN (:a, :b)"),
                {"a": subjects[0], "b": subjects[1]},
            )
