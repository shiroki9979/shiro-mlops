"""Exact closed-window scenarios shared across database dialects."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

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
from shiro_mlops.service.data_explorer.weather import (
    ForecastAuditReader,
    ForecastReader,
    ObservationAuditReader,
    ObservationReader,
)


class SqlFixture(NamedTuple):
    table: str
    columns: str
    values: str
    delete_where: str
    records: list[dict[str, Any]]


@contextmanager
def _seeded_rows(engine: Engine, fixtures: tuple[SqlFixture, ...]) -> Iterator[None]:
    with engine.begin() as connection:
        for fixture in fixtures:
            connection.execute(
                text(f"INSERT INTO {fixture.table} ({fixture.columns}) VALUES ({fixture.values})"),
                fixture.records,
            )
    try:
        yield
    finally:
        with engine.begin() as connection:
            for fixture in reversed(fixtures):
                connection.execute(
                    text(f"DELETE FROM {fixture.table} WHERE {fixture.delete_where}"),
                    fixture.records,
                )


def _all_dataset_fixtures(start: datetime, times: tuple[datetime, ...]) -> tuple[SqlFixture, ...]:
    def rows(make_row: Callable[[datetime, int], dict[str, Any]]) -> list[dict[str, Any]]:
        return [make_row(timestamp, index) for index, timestamp in enumerate(times)]

    return (
        SqlFixture(
            "raw_taipower_load",
            "time, subject, load_mw, source",
            ":time, :subject, :value, 'regional_snapshot_sum'",
            "time = :time AND subject = :subject",
            rows(
                lambda t, i: {"time": t, "subject": f"edge-{i}", "value": float(i)},
            ),
        ),
        SqlFixture(
            "raw_taipower_supply_demand_snapshot",
            "observed_at, curr_load_wan_kw, curr_util_rate_pct, raw_payload",
            ":time, :value, 50, '{}'",
            "observed_at = :time",
            rows(
                lambda t, i: {"time": t, "value": float(i)},
            ),
        ),
        SqlFixture(
            "raw_taipower_regional_supply_demand_snapshot",
            "observed_at, region, source_time, load_wan_kw, raw_payload",
            ":time, :region, :time, :value, '{}'",
            "observed_at = :time AND region = :region",
            rows(
                lambda t, i: {
                    "time": t,
                    "region": ("北部", "中部", "南部", "東部")[i],
                    "value": float(i),
                },
            ),
        ),
        SqlFixture(
            "raw_taipower_unit_generation_snapshot",
            "observed_at, unit_type, unit_name, source_time, raw_payload",
            ":time, 'thermal', :name, :time, '{}'",
            "observed_at = :time AND unit_type = 'thermal' AND unit_name = :name",
            rows(
                lambda t, i: {"time": t, "name": f"edge-{i}"},
            ),
        ),
        SqlFixture(
            "raw_cwa_station_observation",
            "observed_at, station_id, temperature_c",
            ":time, :station, :value",
            "observed_at = :time AND station_id = :station",
            rows(
                lambda t, i: {"time": t, "station": f"edge-{i}", "value": float(i)},
            ),
        ),
        SqlFixture(
            "raw_cwa_township_forecast",
            "dataset_id, issued_at, source_updated_at, valid_from, valid_to, geocode, temperature_c",
            "'F-EDGE', :version, :version, :time, :valid_to, :geocode, :value",
            "dataset_id = 'F-EDGE' AND issued_at = :version "
            "AND source_updated_at = :version AND valid_from = :time "
            "AND valid_to = :valid_to AND geocode = :geocode",
            rows(
                lambda t, i: {
                    "version": start,
                    "time": t,
                    "valid_to": t + timedelta(hours=1),
                    "geocode": f"edge-{i}",
                    "value": float(i),
                },
            ),
        ),
        SqlFixture(
            "raw_cwa_observation_batch",
            "fetched_at, status, missing_station_ids, raw_payload",
            ":time, 'incomplete', :missing, '{}'",
            "fetched_at = :time",
            rows(
                lambda t, i: {"time": t, "missing": f'["edge-{i}"]'},
            ),
        ),
        SqlFixture(
            "raw_cwa_forecast_release",
            "dataset_id, issued_at, source_updated_at, fetched_at, status, missing_geocodes, raw_payload",
            "'F-EDGE', :time, :time, :time, 'incomplete', :missing, '{}'",
            "dataset_id = 'F-EDGE' AND issued_at = :time AND source_updated_at = :time",
            rows(
                lambda t, i: {"time": t, "missing": f'["edge-{i}"]'},
            ),
        ),
    )


def _assert_dataset_windows(engine: Engine, start: datetime, end: datetime) -> None:
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

        assert [first.items[0][field], second.items[0][field]] == expected, reader_class
        assert [first.has_more, second.has_more] == [True, False]
        assert first.next_cursor and second.next_cursor is None
        assert first.missing_slots == second.missing_slots
        assert [item[field] for item in point.items] == [expected[1]]


def assert_all_dataset_windows(engine: Engine) -> None:
    """Run the same four-edge fixture through every public reader on either database."""
    start = datetime(2045, 9, 21, 4, 0, 0, 123456, UTC)
    end = start + timedelta(seconds=1)
    times = (start - timedelta(microseconds=1), start, end, end + timedelta(microseconds=1))
    fixtures = _all_dataset_fixtures(start, times)
    with _seeded_rows(engine, fixtures):
        _assert_dataset_windows(engine, start, end)


def _completeness_fixtures(
    start: datetime, end: datetime, outside: datetime
) -> tuple[SqlFixture, ...]:
    return (
        SqlFixture(
            "raw_taipower_load",
            "time, subject, load_mw, source",
            ":time, 'edge-completeness', 1, 'regional_snapshot_sum'",
            "time = :time AND subject = 'edge-completeness'",
            [{"time": time} for time in (start, outside)],
        ),
        SqlFixture(
            "raw_cwa_station_observation",
            "observed_at, station_id",
            ":time, '466920'",
            "observed_at = :time AND station_id = '466920'",
            [{"time": time} for time in (start, outside)],
        ),
        SqlFixture(
            "raw_taipower_supply_demand_snapshot",
            "observed_at, curr_load_wan_kw, curr_util_rate_pct, raw_payload",
            ":time, 1, 50, '{}'",
            "observed_at = :time",
            [{"time": time} for time in (start, outside)],
        ),
        SqlFixture(
            "raw_taipower_regional_supply_demand_snapshot",
            "observed_at, region, source_time, load_wan_kw, raw_payload",
            ":time, :region, :time, 1, '{}'",
            "observed_at = :time AND region = :region",
            [{"time": time, "region": "北部"} for time in (start, outside)]
            + [{"time": end, "region": region} for region in ("北部", "中部", "南部", "東部")],
        ),
    )


def _assert_completeness_windows(engine: Engine, window: TimeWindow) -> None:
    db = ExplorerDb(engine)
    narrow = TimeWindow(window.start + timedelta(microseconds=1), window.end)
    hourly = hourly_gaps(db, window, "edge-completeness")
    observations = observation_gaps(db, window, "466920")
    narrow_observations = observation_gaps(db, narrow, "466920")
    ten_minute = ten_minute_gaps(db, window)
    regional = regional_slot_map(db, window)

    assert hourly == ["2026-09-20T13:00:00+08:00"]
    assert observations == ["2026-09-20T13:00:00+08:00:466920"]
    assert "2026-09-20T12:00:00+08:00" not in narrow_observations
    assert "2026-09-20T12:00:00+08:00" not in ten_minute
    assert "2026-09-20T13:00:00+08:00" in ten_minute
    assert regional == {
        datetime(2026, 9, 20, 12): {"北部"},
        datetime(2026, 9, 20, 13): {"北部", "中部", "南部", "東部"},
    }


def assert_completeness_windows(engine: Engine) -> None:
    start = datetime(2026, 9, 20, 4, 0, tzinfo=UTC)
    end = start + timedelta(hours=1)
    outside = end + timedelta(microseconds=1)
    window = TimeWindow(datetime(2026, 9, 20, 12), datetime(2026, 9, 20, 13))
    with _seeded_rows(engine, _completeness_fixtures(start, end, outside)):
        _assert_completeness_windows(engine, window)
