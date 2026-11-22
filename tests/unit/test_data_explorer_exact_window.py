"""Exact closed windows at the public list seam."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

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
                "INSERT INTO raw_taipower_load (time, subject, load_mw, source) "
                "VALUES (:time, :subject, :load, 'regional_snapshot_sum')"
            ),
            [
                {"time": timestamp, "subject": f"edge-{index}", "load": float(index)}
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


def test_all_dataset_windows_on_sqlite(sqlite_engine: Engine) -> None:
    assert_all_dataset_windows(sqlite_engine)


def test_completeness_windows_on_sqlite(sqlite_engine: Engine) -> None:
    assert_completeness_windows(sqlite_engine)


@pytest.mark.parametrize(
    ("scenario", "existing_time"),
    [
        pytest.param(
            assert_all_dataset_windows, datetime(2045, 9, 21, 4, tzinfo=UTC), id="all-datasets"
        ),
        pytest.param(
            assert_completeness_windows,
            datetime(2026, 9, 20, 4, tzinfo=UTC),
            id="completeness",
        ),
    ],
)
def test_window_acceptance_preserves_existing_rows(
    sqlite_engine: Engine, scenario: Callable[[Engine], None], existing_time: datetime
) -> None:
    with sqlite_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO raw_taipower_load (time, subject, load_mw, source) "
                "VALUES (:time, 'existing-row', 99, 'legacy')"
            ),
            {"time": existing_time},
        )

    scenario(sqlite_engine)

    with sqlite_engine.connect() as connection:
        remaining = connection.execute(
            text("SELECT COUNT(*) FROM raw_taipower_load WHERE subject = 'existing-row'")
        ).scalar_one()
    assert remaining == 1


def test_failed_window_fixture_insert_preserves_existing_row(sqlite_engine: Engine) -> None:
    existing_time = datetime(2026, 9, 20, 4, tzinfo=UTC)
    with sqlite_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO raw_taipower_supply_demand_snapshot "
                "(observed_at, curr_load_wan_kw, curr_util_rate_pct, raw_payload) "
                "VALUES (:time, 99, 50, '{}')"
            ),
            {"time": existing_time},
        )

    with pytest.raises(IntegrityError):
        assert_completeness_windows(sqlite_engine)

    with sqlite_engine.connect() as connection:
        retained = connection.execute(
            text(
                "SELECT curr_load_wan_kw FROM raw_taipower_supply_demand_snapshot "
                "WHERE observed_at = :time"
            ),
            {"time": existing_time},
        ).scalar_one()
    assert retained == 99
