"""Unit-generation series HTTP scenarios shared by SQLite and the opt-in TimescaleDB run."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from shiro_mlops.data.repository import TimeSeriesRepository
from tests.helpers import TAIWAN, rfc3339
from tests.scenarios.data_explorer_series import series_client

UNIT_SERIES_PATH = "/data/power/units/series"
TEN_MINUTES = timedelta(minutes=10)


@contextmanager
def _seeded_units(
    repo: TimeSeriesRepository,
    readings: list[tuple[datetime, str, str, float | None]],
) -> Iterator[tuple[TestClient, str]]:
    """Seed Taipei-time unit readings under a unique name tag, and remove them afterwards.

    Rows go in as aware UTC instants, so a non-UTC TimescaleDB session stores the same
    instants as SQLite does.
    """
    tag = uuid4().hex[:8]
    records = [
        {
            "observed_at": observed_at.replace(tzinfo=TAIWAN).astimezone(UTC),
            "unit_type": unit_type,
            "unit_name": f"{name}-{tag}",
            "net_generation_mw": value,
        }
        for observed_at, unit_type, name, value in readings
    ]
    with repo.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO raw_taipower_unit_generation_snapshot "
                "(observed_at, unit_type, unit_name, source_time, capacity_mw, "
                "net_generation_mw) VALUES (:observed_at, :unit_type, "
                ":unit_name, :observed_at, 500.0, :net_generation_mw)"
            ),
            records,
        )
    try:
        with series_client(repo) as client:
            yield client, tag
    finally:
        with repo.engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM raw_taipower_unit_generation_snapshot WHERE unit_name LIKE :pattern"
                ),
                {"pattern": f"%-{tag}"},
            )


def _points_by_group(body: dict) -> dict[str, list[tuple[str, float | None]]]:
    return {
        "/".join(series["group"].values()): [(point["t"], point["v"]) for point in series["points"]]
        for series in body["series"]
    }


def assert_member_sum_precedes_hourly_max(repo: TimeSeriesRepository) -> None:
    """燃氣 A 100..150 與 B 60..0 在同一小時，1h max 是時點總和的最大值 160，不是 210。"""
    hour = datetime(2026, 10, 5, 10, 0)
    unit_a = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
    unit_b = [60.0, 40.0, 30.0, 20.0, 10.0, 0.0]
    readings = [
        (hour + step * TEN_MINUTES, "燃氣", name, value)
        for name, values in (("A", unit_a), ("B", unit_b))
        for step, value in enumerate(values)
    ]
    with _seeded_units(repo, readings) as (client, _tag):
        response = client.get(
            UNIT_SERIES_PATH,
            params={
                "start": rfc3339(hour),
                "end": rfc3339(hour + timedelta(minutes=50)),
                "bucket": "1h",
                "agg": "max",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["series"][0]["field"] == "net_generation_mw"
    assert body["series"][0]["unit"] == "MW"
    assert _points_by_group(body) == {"燃氣": [("2026-10-05T10:00:00+08:00", 160.0)]}


def assert_ungrouped_total_subtracts_storage_load(repo: TimeSeriesRepository) -> None:
    """不分組的總淨發電量會扣掉儲能負載的 −300。"""
    slot = datetime(2026, 10, 6, 12, 0)
    readings = [
        (slot, "燃氣", "G1", 1000.0),
        (slot, "太陽能", "S1", 500.0),
        (slot, "儲能負載(Energy Storage System Load)", "ESS", -300.0),
    ]
    with _seeded_units(repo, readings) as (client, _tag):
        response = client.get(
            UNIT_SERIES_PATH,
            params={
                "start": rfc3339(slot),
                "end": rfc3339(slot),
                "group_by": "none",
                "bucket": "raw",
            },
        )

    assert response.status_code == 200
    assert _points_by_group(response.json()) == {"": [("2026-10-06T12:00:00+08:00", 1200.0)]}


def assert_null_member_is_skipped_not_zero(repo: TimeSeriesRepository) -> None:
    """某機組在某時點為 NULL，該時點的總和等於其他機組相加；全為 NULL 的時點仍是 null。"""
    first = datetime(2026, 10, 7, 9, 0)
    second = first + TEN_MINUTES
    readings = [
        (first, "燃煤", "C1", 400.0),
        (first, "燃煤", "C2", None),
        (first, "燃煤", "C3", 250.0),
        (second, "燃煤", "C1", None),
        (second, "燃煤", "C2", None),
    ]
    with _seeded_units(repo, readings) as (client, _tag):
        raw = client.get(
            UNIT_SERIES_PATH,
            params={"start": rfc3339(first), "end": rfc3339(second), "bucket": "raw"},
        )
        hourly_min = client.get(
            UNIT_SERIES_PATH,
            params={
                "start": rfc3339(first),
                "end": rfc3339(second),
                "bucket": "1h",
                "agg": "min",
            },
        )

    assert _points_by_group(raw.json()) == {
        "燃煤": [("2026-10-07T09:00:00+08:00", 650.0), ("2026-10-07T09:10:00+08:00", None)]
    }
    assert _points_by_group(hourly_min.json()) == {"燃煤": [("2026-10-07T09:00:00+08:00", 650.0)]}


def assert_unit_filters_narrow_the_summed_members(repo: TimeSeriesRepository) -> None:
    """unit_type 與 unit_name 篩選先縮小成員範圍，再做加總。"""
    slot = datetime(2026, 10, 8, 15, 0)
    readings = [
        (slot, "燃氣", "G1", 700.0),
        (slot, "燃氣", "G2", 300.0),
        (slot, "風力", "W1", 90.0),
    ]
    with _seeded_units(repo, readings) as (client, tag):
        window = {"start": rfc3339(slot), "end": rfc3339(slot), "bucket": "raw"}
        by_type = client.get(
            UNIT_SERIES_PATH, params={**window, "unit_type": "燃氣", "group_by": "none"}
        )
        by_name = client.get(UNIT_SERIES_PATH, params={**window, "unit_name": f"G2-{tag}"})

    assert _points_by_group(by_type.json()) == {"": [("2026-10-08T15:00:00+08:00", 1000.0)]}
    assert _points_by_group(by_name.json()) == {"燃氣": [("2026-10-08T15:00:00+08:00", 300.0)]}


def assert_auto_bucket_counts_every_unit_type(repo: TimeSeriesRepository) -> None:
    """7 天窗口依 12 種類型分組時，raw 合計點數超過 10,000，auto 解析為 1h；總和則是 raw。"""
    end = datetime(2026, 10, 16, 0, 0)
    readings = [(end, f"type-{index:02d}", "U", 10.0) for index in range(12)]
    with _seeded_units(repo, readings) as (client, _tag):
        window = {"start": rfc3339(end - timedelta(days=7)), "end": rfc3339(end)}
        by_type = client.get(UNIT_SERIES_PATH, params=window)
        total = client.get(UNIT_SERIES_PATH, params={**window, "group_by": "none"})

    assert by_type.status_code == 200
    assert len(by_type.json()["series"]) == 12
    assert by_type.json()["bucket"] == "1h"
    assert total.json()["bucket"] == "raw"


def assert_unit_series_rejects_unlisted_parameters(repo: TimeSeriesRepository) -> None:
    """白名單外的 fields、group_by，以及非數值欄位，都回 422。"""
    slot = datetime(2026, 10, 9, 8, 0)
    with _seeded_units(repo, [(slot, "燃氣", "G1", 100.0)]) as (client, _tag):
        window = {"start": rfc3339(slot), "end": rfc3339(slot)}
        statuses = [
            client.get(UNIT_SERIES_PATH, params={**window, "fields": "remark"}).status_code,
            client.get(UNIT_SERIES_PATH, params={**window, "group_by": "unit_name"}).status_code,
            client.get(UNIT_SERIES_PATH, params={**window, "agg": "sum"}).status_code,
        ]

    assert statuses == [422, 422, 422]


UNIT_SERIES_SCENARIOS = (
    assert_member_sum_precedes_hourly_max,
    assert_ungrouped_total_subtracts_storage_load,
    assert_null_member_is_skipped_not_zero,
    assert_unit_filters_narrow_the_summed_members,
    assert_auto_bucket_counts_every_unit_type,
    assert_unit_series_rejects_unlisted_parameters,
)
