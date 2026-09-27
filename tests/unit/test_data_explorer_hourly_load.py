"""Hourly-load reader exercises the typed query seam."""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from shiro_mlops.core.constants import DATETIME_COL, LOAD_MW_COL
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.service.data_explorer.cursor import CursorError
from shiro_mlops.service.data_explorer.errors import ExplorerQueryError
from shiro_mlops.service.data_explorer.hourly_load import HourlyLoadReader
from tests.helpers import TAIWAN, rfc3339


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
