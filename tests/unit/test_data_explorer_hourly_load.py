"""Hourly-load reader exercises the typed query seam."""

from datetime import datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.core.constants import DATETIME_COL, LOAD_MW_COL
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.service.data_explorer.cursor import CursorError, encode_cursor
from shiro_mlops.service.data_explorer.errors import ExplorerQueryError
from shiro_mlops.service.data_explorer.hourly_load import HourlyLoadReader
from shiro_mlops.service.data_explorer.query import ExplorerQuery
from tests.helpers import TAIWAN, rfc3339


def test_hourly_load_pages_keep_microseconds_composite_key_and_window_gaps(
    sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "shiro_mlops.service.data_explorer.completeness.now_taiwan",
        lambda: datetime(2026, 9, 20, 13, 15),
    )
    rows = [
        ("2026-09-20 04:00:00.900002+00:00", "Taipei", 4.0),
        ("2026-09-20 04:00:00.900002", "Taichung", 3.0),
        ("2026-09-20 04:00:00.900001+00:00", "Taipei", 2.0),
        ("2026-09-20 02:00:00.100000+00:00", "Taipei", 1.0),
    ]
    with sqlite_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO raw_taipower_load (time, location, load_mw, source) "
                "VALUES (:time, :location, :load_mw, 'regional_snapshot_sum')"
            ),
            [
                {"time": time, "location": location, "load_mw": load}
                for time, location, load in rows
            ],
        )
    reader = HourlyLoadReader(sqlite_engine)
    params = {
        "start": "2026-09-20T10:00:00+08:00",
        "end": "2026-09-20T12:00:01+08:00",
        "limit": 1,
    }

    pages = []
    cursor = None
    while True:
        page = reader.list({**params, **({"cursor": cursor} if cursor else {})})
        pages.append(page)
        if not page.has_more:
            break
        assert page.next_cursor is not None
        cursor = page.next_cursor

    assert [page.items[0]["load_mw"] for page in pages] == [4.0, 3.0, 2.0, 1.0]
    assert [page.items[0]["datetime"] for page in pages[:3]] == ["2026-09-20T12:00:00+08:00"] * 3
    assert [page.has_more for page in pages] == [True, True, True, False]
    assert all(page.missing_slots == ["2026-09-20T11:00:00+08:00"] for page in pages)
    assert reader.list({**params, "location": "Kaohsiung"}).items == []
    assert [item["load_mw"] for item in reader.list({**params, "location": "Taipei"}).items] == [
        4.0,
    ]


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
                "INSERT INTO raw_taipower_load (time, location, load_mw, source) VALUES "
                "('2026-09-20 02:00:00', 'Taipei', 10, 'regional_snapshot_sum'), "
                "('2026-09-20 03:00:00', 'Taipei', 11, NULL), "
                "('2026-09-20 04:00:00', 'Taipei', 12, 'regional_snapshot_sum')"
            )
        )
    page = HourlyLoadReader(legacy_upgraded_engine).list(
        {
            "start": "2026-09-20T10:00:00+08:00",
            "end": "2026-09-20T12:00:00+08:00",
        }
    )

    assert [item["load_mw"] for item in page.items] == [12.0, 10.0]
    assert page.missing_slots == ["2026-09-20T11:00:00+08:00"]


def _upsert_hours(
    repo: TimeSeriesRepository, hours: list[datetime], location: str = "Taipei"
) -> None:
    frame = pd.DataFrame(
        {
            DATETIME_COL: hours,
            LOAD_MW_COL: [30000.0 + index for index in range(len(hours))],
            "location": location,
        }
    )
    repo.upsert_taipower_load(frame, default_location=location)


@pytest.mark.parametrize("hours, missing", [([10, 11], []), ([11], ["2026-09-20T10:00:00+08:00"])])
def test_hourly_load_gaps_only_include_completed_hours_inside_the_window(
    test_repo: TimeSeriesRepository, monkeypatch: pytest.MonkeyPatch, hours, missing
) -> None:
    monkeypatch.setattr(
        "shiro_mlops.service.data_explorer.completeness.now_taiwan",
        lambda: datetime(2026, 9, 20, 12, 15),
    )
    _upsert_hours(test_repo, [datetime(2026, 9, 20, hour) for hour in hours])

    page = HourlyLoadReader(test_repo.engine).list(
        {"start": "2026-09-20T09:15:00+08:00", "end": "2026-09-20T13:15:00+08:00"}
    )

    assert page.missing_slots == missing


def test_hourly_load_reader_filters_location_and_traverses_next_page(
    test_repo: TimeSeriesRepository,
) -> None:
    """逐時負載 reader 必須套用 location 篩選，並以 cursor 走到下一頁。"""
    latest = datetime.now(TAIWAN).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    hours = [latest - timedelta(hours=offset) for offset in (2, 1, 0)]
    _upsert_hours(test_repo, hours)
    _upsert_hours(test_repo, hours, location="Taichung")
    reader = HourlyLoadReader(test_repo.engine)
    params = {
        "start": rfc3339(latest - timedelta(hours=2)),
        "end": rfc3339(latest),
        "location": "Taipei",
        "limit": "1",
    }

    first = reader.list(params)

    assert first.has_more is True
    assert len(first.items) == 1
    assert first.items[0]["location"] == "Taipei"
    assert first.items[0]["datetime"] == rfc3339(latest)

    second = reader.list({**params, "cursor": first.next_cursor})

    assert second.items[0]["datetime"] == rfc3339(latest - timedelta(hours=1))
    assert second.items[0]["location"] == "Taipei"


def test_hourly_load_reader_rejects_invalid_window_and_cursor(
    test_repo: TimeSeriesRepository,
) -> None:
    """無效時間窗為 query 錯誤；不相容 cursor 必須拒絕。"""
    latest = datetime.now(TAIWAN).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    _upsert_hours(test_repo, [latest - timedelta(hours=1), latest])
    reader = HourlyLoadReader(test_repo.engine)
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
        reader.list({**params, "location": "Kaohsiung", "cursor": first.next_cursor})
    with pytest.raises(CursorError):
        reader.list({**params, "cursor": "not-a-cursor"})


@pytest.mark.parametrize("location", [["Taipei"], {"name": "Taipei"}])
def test_hourly_load_reader_rejects_nonscalar_cursor_key(
    test_repo: TimeSeriesRepository, location
) -> None:
    params = {"start": "2026-08-01T00:00:00+08:00", "end": "2026-08-02T00:00:00+08:00"}
    cursor = encode_cursor(
        dataset="hourly_load",
        filters=ExplorerQuery.from_params("hourly_load", params).filters,
        key={"time": "2026-08-01T12:00:00+08:00", "location": location},
    )

    with pytest.raises(CursorError, match="Invalid cursor key"):
        HourlyLoadReader(test_repo.engine).list({**params, "cursor": cursor})


@pytest.mark.parametrize("time_key", [0, 1758499200.5, True])
def test_hourly_load_reader_rejects_non_string_cursor_time_key(
    test_repo: TimeSeriesRepository, time_key
) -> None:
    params = {"start": "2026-08-01T00:00:00+08:00", "end": "2026-08-02T00:00:00+08:00"}
    cursor = encode_cursor(
        dataset="hourly_load",
        filters=ExplorerQuery.from_params("hourly_load", params).filters,
        key={"time": time_key, "location": "Taipei"},
    )

    with pytest.raises(CursorError, match="Invalid cursor key"):
        HourlyLoadReader(test_repo.engine).list({**params, "cursor": cursor})
