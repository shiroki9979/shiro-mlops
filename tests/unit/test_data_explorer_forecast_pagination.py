"""Forecast pages retain complete keys and the resolved vintage across requests."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from shiro_mlops.data.cwa_client import CWAForecastRelease
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.service.data_explorer.cursor import CursorError
from shiro_mlops.service.data_explorer.weather import ForecastAuditReader, ForecastReader
from tests.helpers import TAIWAN, township_forecast


def _stamp(value: datetime) -> str:
    return value.replace(tzinfo=TAIWAN).isoformat(timespec="microseconds")


def _release(
    dataset_id: str,
    issued_at: datetime,
    source_updated_at: datetime,
    *,
    status: str = "complete",
    missing_geocodes: tuple[str, ...] = (),
    forecasts: tuple = (),
) -> CWAForecastRelease:
    return CWAForecastRelease(
        dataset_id=dataset_id,
        issued_at=pd.Timestamp(issued_at),
        source_updated_at=pd.Timestamp(source_updated_at),
        fetched_at=issued_at,
        status=status,
        missing_geocodes=missing_geocodes,
        raw_payload={"private": dataset_id},
        forecasts=forecasts,
    )


def assert_forecast_pages_pin_microsecond_vintage(repo: TimeSeriesRepository) -> None:
    """A newer release cannot replace the first page's microsecond vintage."""
    second = datetime(2026, 9, 27, 12)
    issued = second.replace(microsecond=501)
    source = second.replace(microsecond=703)
    valid = second + timedelta(hours=2)
    repo.upsert_cwa_forecast_release(
        _release(
            "F-D0047-089",
            issued,
            source,
            forecasts=(
                township_forecast(valid.replace(microsecond=1), 40.0),
                township_forecast(valid, 31.0, valid_to=valid.replace(microsecond=900)),
                township_forecast(valid, 28.0, valid_to=valid.replace(microsecond=100)),
            ),
        )
    )
    reader = ForecastReader(repo.engine)
    params = {
        "start": _stamp(valid - timedelta(seconds=1)),
        "end": _stamp(valid + timedelta(seconds=1)),
        "limit": 1,
    }
    first = reader.list(params)
    assert [item["temperature_c"] for item in first.items] == [40.0]
    assert first.has_more is True
    assert first.next_cursor

    repo.upsert_cwa_forecast_release(
        _release(
            "F-D0047-089",
            issued.replace(microsecond=901),
            source.replace(microsecond=101),
            forecasts=(township_forecast(valid, 50.0),),
        )
    )
    with patch(
        "shiro_mlops.service.data_explorer.query.now_taiwan",
        return_value=second + timedelta(days=3),
    ):
        second_page = reader.list({"cursor": first.next_cursor, "limit": 1})
        third_page = reader.list({"cursor": second_page.next_cursor, "limit": 1})
    assert [item["temperature_c"] for item in second_page.items] == [31.0]
    assert [item["temperature_c"] for item in third_page.items] == [28.0]
    assert second_page.has_more is True
    assert bool(second_page.next_cursor) is True
    assert third_page.has_more is False
    assert third_page.next_cursor is None
    assert all(
        item["issued_at"] == "2026-09-27T12:00:00+08:00"
        for page in (first, second_page, third_page)
        for item in page.items
    )
    with pytest.raises(CursorError, match="filter mismatch"):
        reader.list({"cursor": first.next_cursor, "geocode": "99999999"})

    explicit = reader.list(
        {**params, "issued_at": _stamp(issued), "source_updated_at": _stamp(source)}
    )
    assert [item["temperature_c"] for item in explicit.items] == [40.0]
    all_vintages = reader.list({**params, "all_vintages": "true", "limit": 10})
    assert [item["temperature_c"] for item in all_vintages.items] == [40.0, 50.0, 31.0, 28.0]


def assert_forecast_audit_pages_keep_complete_sort_key(repo: TimeSeriesRepository) -> None:
    """Audit status and missing-geocode filters apply before three-key pagination."""
    second = datetime(2026, 9, 27, 12)
    high = second.replace(microsecond=900)
    low = second.replace(microsecond=100)
    for dataset_id, issued, source in (
        ("B", high, high),
        ("A", high, high),
        ("C", high, low),
        ("D", low, high),
    ):
        repo.upsert_cwa_forecast_release(
            _release(
                dataset_id, issued, source, status="incomplete", missing_geocodes=("63000050",)
            )
        )
    repo.upsert_cwa_forecast_release(_release("E", high, low, missing_geocodes=("63000050",)))
    repo.upsert_cwa_forecast_release(
        _release("F", high, low, status="incomplete", missing_geocodes=("other",))
    )
    reader = ForecastAuditReader(repo.engine)
    params = {
        "start": _stamp(second - timedelta(seconds=1)),
        "end": _stamp(second + timedelta(seconds=1)),
        "status": "incomplete",
        "missing_geocode": "63000050",
        "limit": 1,
    }
    cursor = None
    for expected_id, has_more in (("B", True), ("A", True), ("C", True), ("D", False)):
        page = reader.list({**params, **({"cursor": cursor} if cursor else {})})
        assert [item["dataset_id"] for item in page.items] == [expected_id]
        assert page.items[0]["missing_geocodes"] == ["63000050"]
        assert "raw_payload" not in page.items[0]
        assert page.has_more is has_more
        assert bool(page.next_cursor) is has_more
        cursor = page.next_cursor
    assert reader.list({**params, "dataset_id": "absent"}).items == []


def test_forecast_pages_pin_microsecond_vintage(test_repo: TimeSeriesRepository) -> None:
    assert_forecast_pages_pin_microsecond_vintage(test_repo)


def test_forecast_audit_pages_keep_complete_sort_key(test_repo: TimeSeriesRepository) -> None:
    assert_forecast_audit_pages_keep_complete_sort_key(test_repo)
