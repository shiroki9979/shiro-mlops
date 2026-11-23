"""CWA audit series HTTP scenarios shared by the SQLite suite and the opt-in TimescaleDB run."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from uuid import uuid4

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import text

from shiro_mlops.data.cwa_client import CWAForecastRelease, CWAObservationBatch
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.query import TimeWindow
from tests.helpers import rfc3339
from tests.scenarios.data_explorer_series import series_client

OBSERVATION_AUDIT_SERIES_PATH = "/data/audits/cwa-observations/series"
FORECAST_AUDIT_SERIES_PATH = "/data/audits/cwa-forecasts/series"
AUDIT_HOUR = datetime(2025, 2, 3, 10, 0)
NOTHING_MISSING: tuple[str, ...] = ()
ONE_MISSING = ("missing-id",)


@contextmanager
def _seeded_batches(
    repo: TimeSeriesRepository, batches: dict[datetime, tuple[str, ...]]
) -> Iterator[TestClient]:
    """Seed observation batch headers `{fetched_at: missing_station_ids}`; remove them afterwards."""
    for fetched_at, missing_station_ids in batches.items():
        repo.cwa_weather_store.upsert_cwa_observation_batch(
            CWAObservationBatch(
                fetched_at=fetched_at,
                missing_station_ids=missing_station_ids,
                raw_payload={},
                observations=(),
            )
        )
    try:
        with series_client(repo) as client:
            yield client
    finally:
        _delete_batches_between(repo, min(batches), max(batches))


def _delete_batches_between(repo: TimeSeriesRepository, first: datetime, last: datetime) -> None:
    clauses, params = ExplorerDb(repo.engine).time_window("fetched_at", TimeWindow(first, last))
    with repo.engine.begin() as connection:
        connection.execute(
            text(f"DELETE FROM raw_cwa_observation_batch WHERE {' AND '.join(clauses)}"), params
        )


@contextmanager
def _seeded_versions(
    repo: TimeSeriesRepository, versions: list[tuple[datetime, datetime, tuple[str, ...]]]
) -> Iterator[tuple[TestClient, str]]:
    """Seed versions `(issued_at, source_updated_at, missing_geocodes)` under a unique dataset."""
    dataset_id = f"T-{uuid4().hex[:10]}"
    repo.cwa_weather_store.upsert_cwa_forecast_releases(
        [
            CWAForecastRelease(
                dataset_id=dataset_id,
                issued_at=pd.Timestamp(issued_at),
                source_updated_at=pd.Timestamp(updated_at),
                fetched_at=updated_at,
                missing_geocodes=missing_geocodes,
                raw_payload={},
                forecasts=(),
            )
            for issued_at, updated_at, missing_geocodes in versions
        ]
    )
    try:
        with series_client(repo) as client:
            yield client, dataset_id
    finally:
        with repo.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM raw_cwa_forecast_release WHERE dataset_id = :dataset_id"),
                {"dataset_id": dataset_id},
            )


def _hour_window(**extra: str) -> dict[str, str]:
    return {
        "start": rfc3339(AUDIT_HOUR - timedelta(hours=1)),
        "end": rfc3339(AUDIT_HOUR + timedelta(hours=2)),
        **extra,
    }


def _counts_by_status(body: dict) -> dict[str, list[tuple[str, float | None]]]:
    return {
        series["group"]["status"]: [(point["t"], point["v"]) for point in series["points"]]
        for series in body["series"]
    }


def assert_observation_batches_counted_per_status(repo: TimeSeriesRepository) -> None:
    """同一個 1h bucket 內有 2 個 complete 與 1 個 incomplete 批次時，計數分別是 2 與 1。"""
    batches = {
        AUDIT_HOUR + timedelta(minutes=5, microseconds=120): NOTHING_MISSING,
        AUDIT_HOUR + timedelta(minutes=25, microseconds=340): ONE_MISSING,
        AUDIT_HOUR + timedelta(minutes=45, microseconds=560): NOTHING_MISSING,
    }
    with _seeded_batches(repo, batches) as client:
        response = client.get(OBSERVATION_AUDIT_SERIES_PATH, params=_hour_window(bucket="1h"))

    assert response.status_code == 200
    body = response.json()
    assert body["bucket"] == "1h"
    assert body["agg"] is None
    assert {(series["field"], series["unit"]) for series in body["series"]} == {
        ("batch_count", "count")
    }
    assert _counts_by_status(body) == {
        "complete": [("2025-02-03T10:00:00+08:00", 2)],
        "incomplete": [("2025-02-03T10:00:00+08:00", 1)],
    }


def assert_forecast_versions_counted_per_status(repo: TimeSeriesRepository) -> None:
    """同一個 1h bucket 內有 2 個 complete 與 1 個 incomplete 版本時，計數分別是 2 與 1。"""
    issued = AUDIT_HOUR
    versions = [
        (issued, issued + timedelta(minutes=10), NOTHING_MISSING),
        (issued, issued + timedelta(minutes=40), ONE_MISSING),
        (issued + timedelta(minutes=30), issued + timedelta(minutes=50), NOTHING_MISSING),
    ]
    with _seeded_versions(repo, versions) as (client, dataset_id):
        response = client.get(
            FORECAST_AUDIT_SERIES_PATH, params=_hour_window(bucket="1h", dataset_id=dataset_id)
        )

    assert response.status_code == 200
    body = response.json()
    assert {(series["field"], series["unit"]) for series in body["series"]} == {
        ("version_count", "count")
    }
    assert _counts_by_status(body) == {
        "complete": [("2025-02-03T10:00:00+08:00", 2)],
        "incomplete": [("2025-02-03T10:00:00+08:00", 1)],
    }


def assert_raw_audit_bucket_has_one_point_per_version(repo: TimeSeriesRepository) -> None:
    """raw 粒度時每個版本各是一個點，即使兩個版本的 issued_at 相同。"""
    issued = AUDIT_HOUR
    versions = [
        (issued, issued + timedelta(minutes=10), NOTHING_MISSING),
        (issued, issued + timedelta(minutes=40), NOTHING_MISSING),
    ]
    with _seeded_versions(repo, versions) as (client, dataset_id):
        response = client.get(
            FORECAST_AUDIT_SERIES_PATH, params=_hour_window(bucket="raw", dataset_id=dataset_id)
        )

    assert response.status_code == 200
    assert response.json()["bucket"] == "raw"
    assert _counts_by_status(response.json()) == {
        "complete": [("2025-02-03T10:00:00+08:00", 1), ("2025-02-03T10:00:00+08:00", 1)],
    }


def assert_audit_series_has_no_gap_fill(repo: TimeSeriesRepository) -> None:
    """audit 不補值：窗口內沒有批次的小時不出現在 series。"""
    batches = {
        AUDIT_HOUR + timedelta(minutes=5): NOTHING_MISSING,
        AUDIT_HOUR + timedelta(hours=2, minutes=5): NOTHING_MISSING,
    }
    with _seeded_batches(repo, batches) as client:
        response = client.get(
            OBSERVATION_AUDIT_SERIES_PATH,
            params={
                "start": rfc3339(AUDIT_HOUR),
                "end": rfc3339(AUDIT_HOUR + timedelta(hours=3)),
                "bucket": "1h",
            },
        )

    assert _counts_by_status(response.json()) == {
        "complete": [("2025-02-03T10:00:00+08:00", 1), ("2025-02-03T12:00:00+08:00", 1)],
    }


def assert_audit_series_rejects_fields_and_agg(repo: TimeSeriesRepository) -> None:
    """audit series 不接受 fields 與 agg，帶了就回 422。"""
    window = _hour_window()
    with _seeded_batches(repo, {AUDIT_HOUR + timedelta(minutes=5): NOTHING_MISSING}) as client:
        statuses = [
            client.get(path, params={**window, **extra}).status_code
            for path in (OBSERVATION_AUDIT_SERIES_PATH, FORECAST_AUDIT_SERIES_PATH)
            for extra in ({"fields": "batch_count"}, {"agg": "max"})
        ]

    assert statuses == [422, 422, 422, 422]


AUDIT_SERIES_SCENARIOS = (
    assert_observation_batches_counted_per_status,
    assert_forecast_versions_counted_per_status,
    assert_raw_audit_bucket_has_one_point_per_version,
    assert_audit_series_has_no_gap_fill,
    assert_audit_series_rejects_fields_and_agg,
)
