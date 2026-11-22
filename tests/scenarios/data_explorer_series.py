"""Series HTTP scenarios shared by the SQLite suite and the opt-in TimescaleDB run."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from uuid import uuid4

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from shiro_mlops.core.config import settings
from shiro_mlops.core.constants import DATETIME_COL, LOAD_MW_COL
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.service.api import create_app
from tests.helpers import rfc3339

LOAD_SERIES_PATH = "/data/power/load/series"


@contextmanager
def series_client(repo: TimeSeriesRepository) -> Iterator[TestClient]:
    """HTTP client bound to the given repository without running the app lifespan."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings, "DATA_EXPLORER_ENABLED", True)
        yield TestClient(create_app(repository=repo))


@contextmanager
def _seeded_load(
    repo: TimeSeriesRepository, loads: dict[datetime, float]
) -> Iterator[tuple[TestClient, str]]:
    """Seed hourly load rows under a unique subject and remove them afterwards."""
    subject = f"series-{uuid4().hex[:8]}"
    frame = pd.DataFrame(
        {DATETIME_COL: list(loads), LOAD_MW_COL: list(loads.values()), "subject": subject}
    )
    repo.upsert_taipower_load(frame, default_subject=subject)
    try:
        with series_client(repo) as client:
            yield client, subject
    finally:
        with repo.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM raw_taipower_load WHERE subject = :subject"),
                {"subject": subject},
            )


def _points(body: dict) -> list[tuple[str, float | None]]:
    (series,) = body["series"]
    return [(point["t"], point["v"]) for point in series["points"]]


def assert_daily_buckets_follow_taipei_midnight(repo: TimeSeriesRepository) -> None:
    """台北時間 11/20 23:30 與 11/21 00:30 落在兩個不同的 1d bucket。"""
    late_evening = datetime(2026, 11, 20, 23, 30)
    after_midnight = datetime(2026, 11, 21, 0, 30)
    with _seeded_load(repo, {late_evening: 100.0, after_midnight: 300.0}) as (client, subject):
        response = client.get(
            LOAD_SERIES_PATH,
            params={
                "start": rfc3339(datetime(2026, 11, 20, 23, 0)),
                "end": rfc3339(datetime(2026, 11, 21, 1, 0)),
                "subject": subject,
                "bucket": "1d",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["bucket"] == "1d"
    assert body["agg"] == "avg"
    assert body["series"][0]["field"] == "load_mw"
    assert body["series"][0]["unit"] == "MW"
    assert body["series"][0]["group"] == {"subject": subject}
    assert _points(body) == [
        ("2026-11-20T00:00:00+08:00", 100.0),
        ("2026-11-21T00:00:00+08:00", 300.0),
    ]


def assert_missing_hour_stays_as_null_bucket(repo: TimeSeriesRepository) -> None:
    """窗口內缺一小時，該 bucket 仍然存在，數值為 null。"""
    first = datetime(2026, 11, 18, 10, 0)
    loads = {first: 30000.0, first + timedelta(hours=2): 32000.0}
    with _seeded_load(repo, loads) as (client, subject):
        response = client.get(
            LOAD_SERIES_PATH,
            params={
                "start": rfc3339(first),
                "end": rfc3339(first + timedelta(hours=2)),
                "subject": subject,
                "bucket": "1h",
                "agg": "max",
            },
        )

    assert response.status_code == 200
    assert response.json()["agg"] == "max"
    assert _points(response.json()) == [
        ("2026-11-18T10:00:00+08:00", 30000.0),
        ("2026-11-18T11:00:00+08:00", None),
        ("2026-11-18T12:00:00+08:00", 32000.0),
    ]


def assert_auto_bucket_resolves_by_window_length(repo: TimeSeriesRepository) -> None:
    """auto 在 7 天與 30 天窗口時解析為 raw，在 92 天窗口時解析為 1d。"""
    end = datetime(2026, 11, 20, 0, 0)
    with _seeded_load(repo, {end: 30000.0}) as (client, subject):
        resolved = {
            days: client.get(
                LOAD_SERIES_PATH,
                params={
                    "start": rfc3339(end - timedelta(days=days)),
                    "end": rfc3339(end),
                    "subject": subject,
                },
            ).json()["bucket"]
            for days in (7, 30, 92)
        }

    assert resolved == {7: "raw", 30: "raw", 92: "1d"}


def assert_explicit_bucket_over_limit_suggests_coarser(repo: TimeSeriesRepository) -> None:
    """手動 raw 加上 92 天窗口，回 422 並建議 1d。"""
    end = datetime(2026, 11, 20, 0, 0)
    with _seeded_load(repo, {end: 30000.0}) as (client, subject):
        response = client.get(
            LOAD_SERIES_PATH,
            params={
                "start": rfc3339(end - timedelta(days=92)),
                "end": rfc3339(end),
                "subject": subject,
                "bucket": "raw",
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"]["suggested_bucket"] == "1d"


def assert_invalid_series_requests_are_rejected(repo: TimeSeriesRepository) -> None:
    """agg=sum、白名單外的欄位、93 天窗口，都回 422。"""
    end = datetime(2026, 11, 20, 0, 0)
    window = {"start": rfc3339(end - timedelta(days=1)), "end": rfc3339(end)}
    with _seeded_load(repo, {end: 30000.0}) as (client, _subject):
        statuses = [
            client.get(LOAD_SERIES_PATH, params={**window, "agg": "sum"}).status_code,
            client.get(LOAD_SERIES_PATH, params={**window, "fields": "subject"}).status_code,
            client.get(
                LOAD_SERIES_PATH,
                params={"start": rfc3339(end - timedelta(days=93)), "end": rfc3339(end)},
            ).status_code,
        ]

    assert statuses == [422, 422, 422]


def assert_partial_edge_bucket_uses_only_window_rows(repo: TimeSeriesRepository) -> None:
    """窗口只涵蓋部分的邊界 bucket，只用窗口內的資料計算。"""
    day = datetime(2026, 11, 19, 0, 0)
    loads = {day + timedelta(hours=hour): 1000.0 * (hour + 1) for hour in range(4)}
    with _seeded_load(repo, loads) as (client, subject):
        response = client.get(
            LOAD_SERIES_PATH,
            params={
                "start": rfc3339(day + timedelta(hours=2)),
                "end": rfc3339(day + timedelta(hours=3)),
                "subject": subject,
                "bucket": "1d",
                "agg": "min",
            },
        )

    assert _points(response.json()) == [("2026-11-19T00:00:00+08:00", 3000.0)]


def assert_raw_bucket_ignores_agg(repo: TimeSeriesRepository) -> None:
    """raw 不做時間聚合並忽略 agg，回應的 agg 為 null。"""
    first = datetime(2026, 11, 18, 22, 0)
    loads = {first: 30000.0, first + timedelta(hours=1): 31000.0}
    with _seeded_load(repo, loads) as (client, subject):
        response = client.get(
            LOAD_SERIES_PATH,
            params={
                "start": rfc3339(first),
                "end": rfc3339(first + timedelta(hours=1)),
                "subject": subject,
                "bucket": "raw",
                "agg": "max",
            },
        )

    assert response.json()["bucket"] == "raw"
    assert response.json()["agg"] is None
    assert _points(response.json()) == [
        ("2026-11-18T22:00:00+08:00", 30000.0),
        ("2026-11-18T23:00:00+08:00", 31000.0),
    ]


SERIES_SCENARIOS = (
    assert_daily_buckets_follow_taipei_midnight,
    assert_missing_hour_stays_as_null_bucket,
    assert_auto_bucket_resolves_by_window_length,
    assert_explicit_bucket_over_limit_suggests_coarser,
    assert_invalid_series_requests_are_rejected,
    assert_partial_edge_bucket_uses_only_window_rows,
    assert_raw_bucket_ignores_agg,
)
