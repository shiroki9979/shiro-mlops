"""Exact closed windows at the public list seam."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.service.data_explorer.completeness import (
    hourly_gaps,
    observation_gaps,
    regional_slot_map,
    ten_minute_gaps,
)
from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.hourly_load import HourlyLoadReader
from shiro_mlops.service.data_explorer.power import (
    NationalSupplyDemandReader,
    RegionalSupplyDemandReader,
    UnitGenerationReader,
)
from shiro_mlops.service.data_explorer.query import TimeWindow
from shiro_mlops.service.data_explorer.timefmt import format_taiwan_time
from shiro_mlops.service.data_explorer.weather import (
    ForecastAuditReader,
    ForecastReader,
    ObservationAuditReader,
    ObservationReader,
)


def test_hourly_load_includes_only_exact_closed_window(sqlite_engine: Engine) -> None:
    start = datetime(2045, 9, 20, 4, 0, 0, 123456, UTC)
    end = start + timedelta(seconds=1)
    times = (start - timedelta(microseconds=1), start, end, end + timedelta(microseconds=1))
    with sqlite_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO raw_taipower_load (time, location, load_mw, source) "
                "VALUES (:time, :location, :load, 'regional_snapshot_sum')"
            ),
            [
                {"time": timestamp, "location": f"edge-{index}", "load": float(index)}
                for index, timestamp in enumerate(times)
            ],
        )
    reader = HourlyLoadReader(sqlite_engine)
    params = {
        "start": start.isoformat(timespec="microseconds"),
        "end": end.isoformat(timespec="microseconds"),
    }

    page = reader.list(params)
    point = reader.list({**params, "end": params["start"]})

    assert [item["load_mw"] for item in page.items] == [2.0, 1.0]
    assert [item["load_mw"] for item in point.items] == [1.0]
    assert page.has_more is False and page.next_cursor is None


def assert_all_dataset_windows(engine: Engine) -> None:
    """Run the same four-edge fixture through every public reader on either database."""
    start = datetime(2045, 9, 21, 4, 0, 0, 123456, UTC)
    end = start + timedelta(seconds=1)
    times = (start - timedelta(microseconds=1), start, end, end + timedelta(microseconds=1))
    inserts = (
        (
            "raw_taipower_load",
            "time, location, load_mw, source",
            ":time, :location, :value, 'regional_snapshot_sum'",
            lambda t, i: {"time": t, "location": f"edge-{i}", "value": float(i)},
        ),
        (
            "raw_taipower_supply_demand_snapshot",
            "observed_at, curr_load_wan_kw, curr_util_rate_pct, raw_payload",
            ":time, :value, 50, '{}'",
            lambda t, i: {"time": t, "value": float(i)},
        ),
        (
            "raw_taipower_regional_supply_demand_snapshot",
            "observed_at, region, source_time, load_wan_kw, raw_payload",
            ":time, :region, :time, :value, '{}'",
            lambda t, i: {
                "time": t,
                "region": ("北部", "中部", "南部", "東部")[i],
                "value": float(i),
            },
        ),
        (
            "raw_taipower_unit_generation_snapshot",
            "observed_at, unit_type, unit_name, source_time, raw_payload",
            ":time, 'thermal', :name, :time, '{}'",
            lambda t, i: {"time": t, "name": f"edge-{i}"},
        ),
        (
            "raw_cwa_station_observation",
            "observed_at, station_id, temperature_c",
            ":time, :station, :value",
            lambda t, i: {"time": t, "station": f"edge-{i}", "value": float(i)},
        ),
        (
            "raw_cwa_township_forecast",
            "dataset_id, issued_at, source_updated_at, valid_from, valid_to, geocode, temperature_c",
            "'F-EDGE', :version, :version, :time, :valid_to, :geocode, :value",
            lambda t, i: {
                "version": start,
                "time": t,
                "valid_to": t + timedelta(hours=1),
                "geocode": f"edge-{i}",
                "value": float(i),
            },
        ),
        (
            "raw_cwa_observation_batch",
            "fetched_at, status, missing_station_ids, raw_payload",
            ":time, 'incomplete', :missing, '{}'",
            lambda t, i: {"time": t, "missing": f'["edge-{i}"]'},
        ),
        (
            "raw_cwa_forecast_release",
            "dataset_id, issued_at, source_updated_at, fetched_at, status, missing_geocodes, raw_payload",
            "'F-EDGE', :time, :time, :time, 'incomplete', :missing, '{}'",
            lambda t, i: {"time": t, "missing": f'["edge-{i}"]'},
        ),
    )
    readers = (
        (HourlyLoadReader, "load_mw", [2.0, 1.0]),
        (NationalSupplyDemandReader, "curr_load_wan_kw", [2.0, 1.0]),
        (RegionalSupplyDemandReader, "region", ["南部", "中部"]),
        (UnitGenerationReader, "unit_name", ["edge-2", "edge-1"]),
        (ObservationReader, "temperature_c", [2.0, 1.0]),
        (ForecastReader, "temperature_c", [2.0, 1.0]),
        (ObservationAuditReader, "missing_station_ids", [["edge-2"], ["edge-1"]]),
        (ForecastAuditReader, "missing_geocodes", [["edge-2"], ["edge-1"]]),
    )
    try:
        with engine.begin() as connection:
            for table, columns, values, params in inserts:
                timestamps = (
                    tuple(timestamp.replace(tzinfo=None) for timestamp in times)
                    if engine.dialect.name == "sqlite" and table.startswith("raw_taipower_")
                    else times
                )
                connection.execute(
                    text(f"INSERT INTO {table} ({columns}) VALUES ({values})"),
                    [params(timestamp, index) for index, timestamp in enumerate(timestamps)],
                )
        params = {
            "start": start.isoformat(timespec="microseconds"),
            "end": end.isoformat(timespec="microseconds"),
            "limit": 1,
        }
        for reader_class, field, expected in readers:
            reader = reader_class(engine)
            filters = {"all_vintages": "true"} if reader_class is ForecastReader else {}
            first = reader.list({**params, **filters})
            second = reader.list({**params, **filters, "cursor": first.next_cursor})
            point = reader.list({**params, **filters, "end": params["start"]})
            assert [first.items[0][field], second.items[0][field]] == expected
            assert [first.has_more, second.has_more] == [True, False]
            assert first.next_cursor and second.next_cursor is None
            assert first.missing_slots == second.missing_slots
            assert [item[field] for item in point.items] == [expected[1]]
    finally:
        with engine.begin() as connection:
            time_columns = {
                "raw_cwa_township_forecast": "valid_from",
                "raw_cwa_forecast_release": "issued_at",
            }
            for table, columns, _values, _params in reversed(inserts):
                column = time_columns.get(table, columns.split(",", 1)[0])
                connection.execute(
                    text(f"DELETE FROM {table} WHERE {column} BETWEEN :lower AND :upper"),
                    {
                        "lower": times[0] - timedelta(seconds=1),
                        "upper": times[-1] + timedelta(seconds=1),
                    },
                )


def test_all_dataset_windows_on_sqlite(sqlite_engine: Engine) -> None:
    assert_all_dataset_windows(sqlite_engine)


def assert_completeness_windows(engine: Engine) -> None:
    start = datetime(2026, 9, 20, 4, 0, tzinfo=UTC)
    end = start + timedelta(hours=1)
    outside = end + timedelta(microseconds=1)
    window = TimeWindow(
        start.replace(tzinfo=None) + timedelta(hours=8),
        end.replace(tzinfo=None) + timedelta(hours=8),
    )
    tables = (
        (
            "raw_taipower_load",
            "time",
            "(time, location, load_mw, source) VALUES (:time, 'edge-completeness', 1, 'regional_snapshot_sum')",
            [start, outside],
        ),
        (
            "raw_cwa_station_observation",
            "observed_at",
            "(observed_at, station_id) VALUES (:time, '466920')",
            [start, outside],
        ),
        (
            "raw_taipower_supply_demand_snapshot",
            "observed_at",
            "(observed_at, curr_load_wan_kw, curr_util_rate_pct, raw_payload) VALUES (:time, 1, 50, '{}')",
            [start, outside],
        ),
        (
            "raw_taipower_regional_supply_demand_snapshot",
            "observed_at",
            "(observed_at, region, source_time, load_wan_kw, raw_payload) VALUES (:time, '北部', :time, 1, '{}')",
            [start, outside],
        ),
    )
    try:
        with engine.begin() as connection:
            for table, _column, insert, timestamps in tables:
                connection.execute(
                    text(f"INSERT INTO {table} {insert}"), [{"time": t} for t in timestamps]
                )
            connection.execute(
                text(
                    "INSERT INTO raw_taipower_regional_supply_demand_snapshot "
                    "(observed_at, region, source_time, load_wan_kw, raw_payload) "
                    "VALUES (:time, :region, :time, 1, '{}')"
                ),
                [{"time": end, "region": region} for region in ("北部", "中部", "南部", "東部")],
            )
        db = ExplorerDb(engine)
        assert hourly_gaps(db, window, "edge-completeness") == [format_taiwan_time(window.end)]
        assert observation_gaps(db, window, "466920") == [
            f"{format_taiwan_time(window.end)}:466920"
        ]
        ten_minute = ten_minute_gaps(db, window)
        assert format_taiwan_time(window.start) not in ten_minute
        assert format_taiwan_time(window.end) in ten_minute
        assert regional_slot_map(db, window) == {
            window.start: {"北部"},
            window.end: {"北部", "中部", "南部", "東部"},
        }
        narrow = TimeWindow(window.start + timedelta(microseconds=1), window.end)
        assert format_taiwan_time(window.start) not in observation_gaps(db, narrow, "466920")
    finally:
        with engine.begin() as connection:
            for table, column, _insert, _timestamps in reversed(tables):
                connection.execute(
                    text(f"DELETE FROM {table} WHERE {column} BETWEEN :start AND :outside"),
                    {"start": start, "outside": outside},
                )


def test_completeness_windows_on_sqlite(sqlite_engine: Engine) -> None:
    assert_completeness_windows(sqlite_engine)
