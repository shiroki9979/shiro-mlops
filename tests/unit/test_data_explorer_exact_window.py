"""Exact closed windows at the public list seam."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.service.data_explorer.hourly_load import HourlyLoadReader
from tests.scenarios.data_explorer_windows import (
    assert_all_dataset_windows,
    assert_completeness_windows,
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


# SQLite text storage may hold naive or aware UTC; split tables so both forms are covered.
SQLITE_NAIVE_UTC_TABLES = frozenset(
    {
        "raw_taipower_load",
        "raw_taipower_supply_demand_snapshot",
        "raw_taipower_regional_supply_demand_snapshot",
        "raw_taipower_unit_generation_snapshot",
    }
)


def test_all_dataset_windows_on_sqlite(sqlite_engine: Engine) -> None:
    assert_all_dataset_windows(sqlite_engine, SQLITE_NAIVE_UTC_TABLES)


def test_completeness_windows_on_sqlite(sqlite_engine: Engine) -> None:
    assert_completeness_windows(sqlite_engine)
