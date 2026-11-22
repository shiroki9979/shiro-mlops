"""Hourly-load reader exercises the typed query seam."""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.core.constants import DATETIME_COL, LOAD_MW_COL
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.service.data_explorer.cursor import CursorError, encode_cursor
from shiro_mlops.service.data_explorer.datasets import HOURLY_LOAD
from shiro_mlops.service.data_explorer.errors import ExplorerQueryError
from shiro_mlops.service.data_explorer.query import ExplorerQuery
from tests.helpers import TAIWAN, DatasetLister, explorer_pages, rfc3339


def test_hourly_load_pages_keep_microseconds_composite_key_and_window_gaps(
    sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "shiro_mlops.service.data_explorer.completeness.now_taiwan",
        lambda: datetime(2026, 9, 20, 13, 15),
    )
    rows = [
        ("2026-09-20 04:00:00.900002+00:00", "Taipei", 4.0),
        ("2026-09-20 04:00:00.900002+00:00", "Taichung", 3.0),
        ("2026-09-20 04:00:00.900001+00:00", "Taipei", 2.0),
        ("2026-09-20 02:00:00.100000+00:00", "Taipei", 1.0),
    ]
    with sqlite_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO raw_taipower_load (time, subject, load_mw, source) "
                "VALUES (:time, :subject, :load_mw, 'regional_snapshot_sum')"
            ),
            [{"time": time, "subject": subject, "load_mw": load} for time, subject, load in rows],
        )
    reader = DatasetLister(sqlite_engine, HOURLY_LOAD)
    params = {
        "start": "2026-09-20T10:00:00+08:00",
        "end": "2026-09-20T12:00:01+08:00",
        "limit": 1,
    }

    pages = explorer_pages(reader, params)

    assert [page.items[0]["load_mw"] for page in pages] == [4.0, 3.0, 2.0, 1.0]
    assert [page.items[0]["datetime"] for page in pages[:3]] == ["2026-09-20T12:00:00+08:00"] * 3
    assert [page.has_more for page in pages] == [True, True, True, False]
    assert all(page.missing_slots == ["2026-09-20T11:00:00+08:00"] for page in pages)
    assert reader.list({**params, "subject": "Kaohsiung"}).items == []
    assert [item["load_mw"] for item in reader.list({**params, "subject": "Taipei"}).items] == [
        4.0,
    ]


def test_hourly_load_cursor_orders_whole_second_before_fractional_rows(
    sqlite_engine: Engine,
) -> None:
    """A whole-second row and its microsecond neighbours page newest-first, one by one."""
    second = datetime(2026, 9, 20, 4, tzinfo=UTC)
    stored = (
        (second - timedelta(microseconds=1), 0.0),
        (second, 1.0),
        (second + timedelta(microseconds=1), 2.0),
        (second + timedelta(seconds=1), 3.0),
    )
    with sqlite_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO raw_taipower_load (time, subject, load_mw, source) "
                "VALUES (:time, 'Taipei', :load_mw, 'regional_snapshot_sum')"
            ),
            [{"time": time, "load_mw": load} for time, load in stored],
        )
    reader = DatasetLister(sqlite_engine, HOURLY_LOAD)
    params = {"start": "2026-09-20T12:00:00+08:00", "end": "2026-09-20T12:00:01+08:00", "limit": 1}

    pages = explorer_pages(reader, params)

    assert [item["load_mw"] for page in pages for item in page.items] == [3.0, 2.0, 1.0]


def test_hourly_load_excludes_legacy_source_from_rows_and_gaps(
    legacy_upgraded_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "shiro_mlops.service.data_explorer.completeness.now_taiwan",
        lambda: datetime(2026, 9, 20, 13, 15),
    )
    with legacy_upgraded_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO raw_taipower_load (time, subject, load_mw, source) VALUES "
                "('2026-09-20 02:00:00+00:00', 'Taipei', 10, 'regional_snapshot_sum'), "
                "('2026-09-20 03:00:00+00:00', 'Taipei', 11, NULL), "
                "('2026-09-20 04:00:00+00:00', 'Taipei', 12, 'regional_snapshot_sum')"
            )
        )
    page = DatasetLister(legacy_upgraded_engine, HOURLY_LOAD).list(
        {
            "start": "2026-09-20T10:00:00+08:00",
            "end": "2026-09-20T12:00:00+08:00",
        }
    )

    assert [item["load_mw"] for item in page.items] == [12.0, 10.0]
    assert page.missing_slots == ["2026-09-20T11:00:00+08:00"]


def _upsert_hours(
    repo: TimeSeriesRepository, hours: list[datetime], subject: str = "nationwide"
) -> None:
    frame = pd.DataFrame(
        {
            DATETIME_COL: hours,
            LOAD_MW_COL: [30000.0 + index for index in range(len(hours))],
            "subject": subject,
        }
    )
    repo.upsert_taipower_load(frame, default_subject=subject)


@pytest.mark.parametrize("hours, missing", [([10, 11], []), ([11], ["2026-09-20T10:00:00+08:00"])])
def test_hourly_load_gaps_only_include_completed_hours_inside_the_window(
    test_repo: TimeSeriesRepository, monkeypatch: pytest.MonkeyPatch, hours, missing
) -> None:
    monkeypatch.setattr(
        "shiro_mlops.service.data_explorer.completeness.now_taiwan",
        lambda: datetime(2026, 9, 20, 12, 15),
    )
    _upsert_hours(test_repo, [datetime(2026, 9, 20, hour) for hour in hours])

    page = DatasetLister(test_repo.engine, HOURLY_LOAD).list(
        {"start": "2026-09-20T09:15:00+08:00", "end": "2026-09-20T13:15:00+08:00"}
    )

    assert page.missing_slots == missing


def test_hourly_load_reader_filters_subject_and_traverses_next_page(
    test_repo: TimeSeriesRepository,
) -> None:
    """The hourly-load reader filters by subject and follows the next-page cursor."""
    latest = datetime.now(TAIWAN).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    hours = [latest - timedelta(hours=offset) for offset in (2, 1, 0)]
    _upsert_hours(test_repo, hours)
    _upsert_hours(test_repo, hours, subject="north")
    reader = DatasetLister(test_repo.engine, HOURLY_LOAD)
    params = {
        "start": rfc3339(latest - timedelta(hours=2)),
        "end": rfc3339(latest),
        "subject": "nationwide",
        "limit": "1",
    }

    first = reader.list(params)

    assert first.has_more is True
    assert len(first.items) == 1
    assert first.items[0]["subject"] == "nationwide"
    assert first.items[0]["datetime"] == rfc3339(latest)

    second = reader.list({**params, "cursor": first.next_cursor})

    assert second.items[0]["datetime"] == rfc3339(latest - timedelta(hours=1))
    assert second.items[0]["subject"] == "nationwide"


def test_hourly_load_reader_rejects_invalid_window_and_cursor(
    test_repo: TimeSeriesRepository,
) -> None:
    """無效時間窗為 query 錯誤；不相容 cursor 必須拒絕。"""
    latest = datetime.now(TAIWAN).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    _upsert_hours(test_repo, [latest - timedelta(hours=1), latest])
    reader = DatasetLister(test_repo.engine, HOURLY_LOAD)
    params = {
        "start": rfc3339(latest - timedelta(hours=1)),
        "end": rfc3339(latest),
        "limit": "1",
    }

    with pytest.raises(ExplorerQueryError):
        reader.list(
            {
                "start": rfc3339(latest - timedelta(days=32)),
                "end": rfc3339(latest),
            }
        )

    first = reader.list(params)
    with pytest.raises(CursorError, match="filter"):
        reader.list({**params, "subject": "south", "cursor": first.next_cursor})
    with pytest.raises(CursorError):
        reader.list({**params, "cursor": "not-a-cursor"})


@pytest.mark.parametrize("subject", [["nationwide"], {"name": "nationwide"}])
def test_hourly_load_reader_rejects_nonscalar_cursor_key(
    test_repo: TimeSeriesRepository, subject
) -> None:
    params = {"start": "2026-08-01T00:00:00+08:00", "end": "2026-08-02T00:00:00+08:00"}
    cursor = encode_cursor(
        dataset="hourly_load",
        filters=ExplorerQuery.from_params(HOURLY_LOAD, params).filters,
        key={"time": "2026-08-01T12:00:00+08:00", "subject": subject},
    )

    with pytest.raises(CursorError, match="Invalid cursor key"):
        DatasetLister(test_repo.engine, HOURLY_LOAD).list({**params, "cursor": cursor})


@pytest.mark.parametrize("time_key", [0, 1758499200.5, True])
def test_hourly_load_reader_rejects_non_string_cursor_time_key(
    test_repo: TimeSeriesRepository, time_key
) -> None:
    params = {"start": "2026-08-01T00:00:00+08:00", "end": "2026-08-02T00:00:00+08:00"}
    cursor = encode_cursor(
        dataset="hourly_load",
        filters=ExplorerQuery.from_params(HOURLY_LOAD, params).filters,
        key={"time": time_key, "subject": "nationwide"},
    )

    with pytest.raises(CursorError, match="Invalid cursor key"):
        DatasetLister(test_repo.engine, HOURLY_LOAD).list({**params, "cursor": cursor})
