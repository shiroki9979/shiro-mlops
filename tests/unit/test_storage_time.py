"""Behaviour of the storage-time module: the single Taiwan-local ↔ stored-instant boundary."""

import sqlite3
import warnings
from datetime import UTC, datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlalchemy import text

from shiro_mlops.core.database import get_timescale_engine
from shiro_mlops.core.storage_time import (
    from_storage_time,
    from_storage_time_or_none,
    from_storage_time_series,
    half_open_window,
    to_storage_time,
    to_storage_time_or_none,
)


def test_naive_taiwan_local_instant_is_stored_as_aware_utc_eight_hours_earlier():
    stored = to_storage_time(datetime(2026, 1, 1, 8, 0))

    assert stored == datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    assert stored.utcoffset().total_seconds() == 0


def test_aware_input_keeps_the_instant_it_states():
    tokyo_nine = datetime(2026, 3, 1, 9, 0, tzinfo=timezone(timedelta(hours=9)))

    assert to_storage_time(tokyo_nine) == datetime(2026, 3, 1, 0, 0, tzinfo=UTC)


def test_early_morning_taiwan_local_crosses_back_to_the_previous_utc_day():
    assert to_storage_time(datetime(2026, 1, 1, 3, 30)) == datetime(
        2025, 12, 31, 19, 30, tzinfo=UTC
    )


@pytest.mark.parametrize("month", [1, 4, 7, 10])
def test_offset_is_eight_hours_all_year(month):
    assert to_storage_time(datetime(2026, month, 15, 12, 0)) == datetime(
        2026, month, 15, 4, 0, tzinfo=UTC
    )


def test_pandas_timestamp_becomes_a_plain_datetime_sqlite_can_bind():
    stored = to_storage_time(pd.Timestamp("2026-01-01 08:00:00.123456"))

    assert type(stored) is datetime
    assert stored == datetime(2026, 1, 1, 0, 0, 0, 123456, tzinfo=UTC)


@pytest.mark.parametrize("missing", [None, pd.NaT])
def test_missing_instant_is_refused(missing):
    with pytest.raises(ValueError, match="instant is required"):
        to_storage_time(missing)


def test_nullable_column_write_passes_none_through():
    assert to_storage_time_or_none(None) is None
    assert to_storage_time_or_none(pd.NaT) is None
    assert to_storage_time_or_none(datetime(2026, 1, 1, 8, 0)) == datetime(
        2026, 1, 1, 0, 0, tzinfo=UTC
    )


@pytest.mark.parametrize(
    ("stored", "taiwan_local"),
    [
        ("2026-01-01 00:00:00+00:00", datetime(2026, 1, 1, 8, 0)),
        ("2026-01-01 01:00:00.123456+00:00", datetime(2026, 1, 1, 9, 0, 0, 123456)),
        ("2026-01-01 00:00:00", datetime(2026, 1, 1, 8, 0)),
        ("2025-12-31 23:00:00.000005", datetime(2026, 1, 1, 7, 0, 0, 5)),
        (datetime(2025, 12, 31, 16, 0, tzinfo=UTC), datetime(2026, 1, 1, 0, 0)),
        (
            datetime(2026, 1, 1, 8, 0, tzinfo=timezone(timedelta(hours=8))),
            datetime(2026, 1, 1, 8, 0),
        ),
    ],
)
def test_stored_value_reads_back_as_naive_taiwan_local(stored, taiwan_local):
    read = from_storage_time(stored, column="observed_at")

    assert read == taiwan_local
    assert type(read) is datetime
    assert read.tzinfo is None


@pytest.mark.parametrize("missing", [None, pd.NaT, float("nan")])
def test_not_null_column_holding_null_is_treated_as_corrupt_storage(missing):
    with pytest.raises(ValueError, match="observed_at"):
        from_storage_time(missing, column="observed_at")


def test_nullable_column_reads_null_as_none():
    assert from_storage_time_or_none(None) is None
    assert from_storage_time_or_none("2026-01-01 00:00:00+00:00") == datetime(2026, 1, 1, 8, 0)


def test_stored_column_frame_reads_back_as_naive_taiwan_local_series():
    stored = pd.Series(
        [
            "2026-01-01 00:00:00+00:00",
            "2026-01-01 01:00:00.123456+00:00",
            "2026-01-01 02:00:00",
            "2025-12-31 23:00:00.000005",
        ],
        name="time",
    )

    read = from_storage_time_series(stored)

    assert read.dt.tz is None
    assert read.name == "time"
    assert read.tolist() == [
        pd.Timestamp("2026-01-01 08:00:00"),
        pd.Timestamp("2026-01-01 09:00:00.123456"),
        pd.Timestamp("2026-01-01 10:00:00"),
        pd.Timestamp("2026-01-01 07:00:00.000005"),
    ]


def test_aware_stored_series_reads_back_as_naive_taiwan_local():
    stored = pd.Series(pd.to_datetime(["2025-12-31 16:00:00"]).tz_localize("UTC"))

    assert from_storage_time_series(stored).tolist() == [pd.Timestamp("2026-01-01 00:00:00")]


def test_empty_stored_series_reads_back_as_empty_datetimes():
    read = from_storage_time_series(pd.Series([], dtype=object, name="time"))

    assert read.empty
    assert pd.api.types.is_datetime64_dtype(read)


def test_null_in_a_stored_not_null_column_series_is_treated_as_corrupt_storage():
    with pytest.raises(ValueError, match="time"):
        from_storage_time_series(pd.Series(["2026-01-01 00:00:00+00:00", None], name="time"))


@pytest.fixture
def instants_engine(tmp_path):
    engine = get_timescale_engine(uri=f"sqlite:///{tmp_path / 'storage_time.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE instants (observed_at TIMESTAMPTZ PRIMARY KEY)"))
    yield engine
    engine.dispose()


def _store(engine, *taiwan_local: datetime) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO instants (observed_at) VALUES (:observed_at)"),
            [{"observed_at": to_storage_time(instant)} for instant in taiwan_local],
        )


def _select_window(engine, start: datetime, end: datetime) -> list[datetime]:
    window = half_open_window("observed_at", start, end)
    with engine.connect() as conn:
        rows = conn.execute(
            text(f"SELECT observed_at FROM instants WHERE {window.sql} ORDER BY observed_at"),
            window.params,
        ).scalars()
        return [from_storage_time(row, column="observed_at") for row in rows]


def test_half_open_window_includes_start_and_excludes_end_on_sqlite(instants_engine):
    _store(
        instants_engine,
        datetime(2026, 1, 1, 7, 0),
        datetime(2026, 1, 1, 8, 0),
        datetime(2026, 1, 1, 9, 0),
        datetime(2026, 1, 1, 10, 0),
    )

    assert _select_window(
        instants_engine, datetime(2026, 1, 1, 8, 0), datetime(2026, 1, 1, 10, 0)
    ) == [datetime(2026, 1, 1, 8, 0), datetime(2026, 1, 1, 9, 0)]


def test_fractional_seconds_order_and_window_correctly_beside_whole_seconds(instants_engine):
    _store(
        instants_engine,
        datetime(2026, 1, 1, 9, 0, 0, 500000),
        datetime(2026, 1, 1, 9, 0),
        datetime(2026, 1, 1, 8, 59, 59, 999999),
        datetime(2026, 1, 1, 9, 0, 1),
    )

    assert _select_window(
        instants_engine, datetime(2026, 1, 1, 9, 0), datetime(2026, 1, 1, 9, 0, 1)
    ) == [datetime(2026, 1, 1, 9, 0), datetime(2026, 1, 1, 9, 0, 0, 500000)]


def test_same_instant_given_naive_or_aware_matches_the_stored_row(instants_engine):
    _store(instants_engine, datetime(2026, 1, 1, 8, 0))
    aware_same_instant = to_storage_time(datetime(2026, 1, 1, 0, 0, tzinfo=UTC))

    with instants_engine.connect() as conn:
        matches = conn.execute(
            text("SELECT COUNT(*) FROM instants WHERE observed_at = :at"),
            {"at": aware_same_instant},
        ).scalar_one()

    assert matches == 1


def test_window_params_are_named_after_the_column_so_two_windows_can_share_a_query():
    window = half_open_window(
        "forecast.valid_from", datetime(2026, 1, 1, 8, 0), datetime(2026, 1, 2, 8, 0)
    )

    assert window.sql == (
        "forecast.valid_from >= :valid_from_start AND forecast.valid_from < :valid_from_end"
    )
    assert window.params == {
        "valid_from_start": datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        "valid_from_end": datetime(2026, 1, 2, 0, 0, tzinfo=UTC),
    }


def test_self_join_names_each_window_parameter_explicitly():
    window = half_open_window(
        "neighbor.observed_at", datetime(2026, 1, 1), datetime(2026, 1, 2), param="neighbor"
    )

    assert window.sql == (
        "neighbor.observed_at >= :neighbor_start AND neighbor.observed_at < :neighbor_end"
    )
    assert set(window.params) == {"neighbor_start", "neighbor_end"}


@pytest.mark.parametrize(
    ("bound", "stored_text"),
    [
        (datetime(2026, 1, 1, 0, 0, tzinfo=UTC), "2026-01-01 00:00:00+00:00"),
        (datetime(2026, 1, 1, 1, 0, 0, 123456, tzinfo=UTC), "2026-01-01 01:00:00.123456+00:00"),
        (datetime(2026, 1, 1, 0, 0), "2026-01-01 00:00:00"),
        (datetime(2025, 12, 31, 23, 0, 0, 5), "2025-12-31 23:00:00.000005"),
    ],
)
def test_sqlite_engine_binds_datetimes_explicitly_in_the_existing_text_form(
    tmp_path, monkeypatch, bound, stored_text
):
    monkeypatch.delitem(sqlite3.adapters, (datetime, sqlite3.PrepareProtocol), raising=False)
    engine = get_timescale_engine(uri=f"sqlite:///{tmp_path / 'adapter.db'}")

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE instants (observed_at TIMESTAMPTZ)"))
            conn.execute(text("INSERT INTO instants VALUES (:at)"), {"at": bound})
            stored = conn.execute(text("SELECT observed_at FROM instants")).scalar_one()
    engine.dispose()

    assert stored == stored_text


def test_reversed_window_is_refused():
    with pytest.raises(ValueError, match="end"):
        half_open_window("observed_at", datetime(2026, 1, 2), datetime(2026, 1, 1))
