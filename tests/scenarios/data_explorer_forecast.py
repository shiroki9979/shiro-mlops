"""Forecast pagination scenarios shared across database dialects."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from shiro_mlops.data.cwa_client import CWAForecastRelease
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.service.data_explorer.cursor import CursorError
from shiro_mlops.service.data_explorer.datasets import CWA_FORECAST_AUDITS, CWA_FORECASTS
from tests.helpers import DatasetLister, township_forecast


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
    repo.cwa_weather_store.upsert_cwa_forecast_releases(
        [
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
        ]
    )
    newer_release = _release(
        "F-D0047-089",
        issued.replace(microsecond=901),
        source.replace(microsecond=101),
        forecasts=(township_forecast(valid, 50.0),),
    )
    reader = DatasetLister(repo.engine, CWA_FORECASTS)
    params = {
        "start": "2026-09-27T13:59:59+08:00",
        "end": "2026-09-27T14:00:01+08:00",
        "limit": 1,
    }
    explicit_version = {
        "issued_at": "2026-09-27T12:00:00.000501+08:00",
        "source_updated_at": "2026-09-27T12:00:00.000703+08:00",
    }

    first = reader.list(params)
    repo.cwa_weather_store.upsert_cwa_forecast_releases([newer_release])
    with patch(
        "shiro_mlops.service.data_explorer.query.now_taiwan",
        return_value=second + timedelta(days=3),
    ):
        second_page = reader.list({"cursor": first.next_cursor, "limit": 1})
        third_page = reader.list({"cursor": second_page.next_cursor, "limit": 1})
    explicit = reader.list({**params, **explicit_version})
    all_vintages = reader.list({**params, "all_vintages": "true", "limit": 10})

    pages = (first, second_page, third_page)
    assert [page.items[0]["temperature_c"] for page in pages] == [40.0, 31.0, 28.0]
    assert [page.has_more for page in pages] == [True, True, False]
    assert [bool(page.next_cursor) for page in pages] == [True, True, False]
    assert all(
        item["issued_at"] == "2026-09-27T12:00:00+08:00" for page in pages for item in page.items
    )
    assert [item["temperature_c"] for item in explicit.items] == [40.0]
    assert [item["temperature_c"] for item in all_vintages.items] == [40.0, 50.0, 31.0, 28.0]
    with pytest.raises(CursorError, match="filter mismatch"):
        reader.list({"cursor": first.next_cursor, "geocode": "99999999"})


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
        repo.cwa_weather_store.upsert_cwa_forecast_releases(
            [
                _release(
                    dataset_id, issued, source, status="incomplete", missing_geocodes=("63000050",)
                )
            ]
        )
    repo.cwa_weather_store.upsert_cwa_forecast_releases(
        [_release("E", high, low, missing_geocodes=("63000050",))]
    )
    repo.cwa_weather_store.upsert_cwa_forecast_releases(
        [_release("F", high, low, status="incomplete", missing_geocodes=("other",))]
    )
    reader = DatasetLister(repo.engine, CWA_FORECAST_AUDITS)
    params = {
        "start": "2026-09-27T11:59:59+08:00",
        "end": "2026-09-27T12:00:01+08:00",
        "status": "incomplete",
        "missing_geocode": "63000050",
        "limit": 1,
    }

    pages = [reader.list(params)]
    for _ in range(3):
        pages.append(reader.list({**params, "cursor": pages[-1].next_cursor}))
    absent = reader.list({**params, "dataset_id": "absent"})

    assert [[item["dataset_id"] for item in page.items] for page in pages] == [
        ["B"],
        ["A"],
        ["C"],
        ["D"],
    ]
    assert all(page.items[0]["missing_geocodes"] == ["63000050"] for page in pages)
    assert all("raw_payload" not in page.items[0] for page in pages)
    assert [page.has_more for page in pages] == [True, True, True, False]
    assert [bool(page.next_cursor) for page in pages] == [True, True, True, False]
    assert absent.items == []
