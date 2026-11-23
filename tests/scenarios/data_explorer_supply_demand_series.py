"""National and regional supply-demand series scenarios shared by SQLite and TimescaleDB."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text

from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.query import TimeWindow
from tests.helpers import regional_supply_demand_snapshots, rfc3339, supply_demand_snapshot
from tests.scenarios.data_explorer_series import series_client

NATIONAL_SERIES_PATH = "/data/power/supply-demand/series"
REGIONAL_SERIES_PATH = "/data/power/regional/series"


@contextmanager
def _seeded_rows(
    repo: TimeSeriesRepository, table: str, window: TimeWindow, seed
) -> Iterator[TestClient]:
    """Seed rows inside `window`, serve HTTP, then delete every row of `table` in the window."""
    seed()
    try:
        with series_client(repo) as client:
            yield client
    finally:
        clauses, params = ExplorerDb(repo.engine).time_window("observed_at", window)
        with repo.engine.begin() as connection:
            connection.execute(text(f"DELETE FROM {table} WHERE {' AND '.join(clauses)}"), params)


def _seeded_national(
    repo: TimeSeriesRepository, window: TimeWindow, loads: dict[datetime, float], **columns
) -> Iterator[TestClient]:
    def seed() -> None:
        for observed_at, load_wan_kw in loads.items():
            snapshot = replace(
                supply_demand_snapshot(observed_at), curr_load_wan_kw=load_wan_kw, **columns
            )
            repo.supply_demand_store.upsert(snapshot)

    return _seeded_rows(repo, "raw_taipower_supply_demand_snapshot", window, seed)


def assert_national_auto_bucket_resolves_by_window_length(repo: TimeSeriesRepository) -> None:
    """全台供需的 auto 在 7 天窗口時解析為 raw、30 天為 1h、92 天為 1d。"""
    end = datetime(2026, 10, 20, 0, 0)
    window = TimeWindow(end - timedelta(days=92), end)
    with _seeded_national(repo, window, {end: 3000.0}) as client:
        resolved = {
            days: client.get(
                NATIONAL_SERIES_PATH,
                params={"start": rfc3339(end - timedelta(days=days)), "end": rfc3339(end)},
            ).json()["bucket"]
            for days in (7, 30, 92)
        }

    assert resolved == {7: "raw", 30: "1h", 92: "1d"}


def assert_national_defaults_to_load_and_capacity_in_mw(repo: TimeSeriesRepository) -> None:
    """全台供需預設畫目前用電負載與即時最大供電能力，不分組，萬瓩換算為 MW。"""
    slot = datetime(2026, 10, 21, 14, 0)
    with _seeded_national(
        repo,
        TimeWindow(slot, slot),
        {slot: 3000.0},
        real_hr_maxi_sply_capacity_wan_kw=3500.0,
        curr_util_rate_pct=85.5,
    ) as client:
        defaults = client.get(
            NATIONAL_SERIES_PATH, params={"start": rfc3339(slot), "end": rfc3339(slot)}
        )
        percent = client.get(
            NATIONAL_SERIES_PATH,
            params={"start": rfc3339(slot), "end": rfc3339(slot), "fields": "curr_util_rate_pct"},
        )

    assert defaults.status_code == 200
    assert [
        (series["field"], series["unit"], series["group"], series["points"])
        for series in defaults.json()["series"]
    ] == [
        ("curr_load_mw", "MW", {}, [{"t": "2026-10-21T14:00:00+08:00", "v": 30000.0}]),
        (
            "real_hr_maxi_sply_capacity_mw",
            "MW",
            {},
            [{"t": "2026-10-21T14:00:00+08:00", "v": 35000.0}],
        ),
    ]
    assert [(series["unit"], series["points"][0]["v"]) for series in percent.json()["series"]] == [
        ("%", 85.5)
    ]


def assert_national_fields_outside_whitelist_are_rejected(repo: TimeSeriesRepository) -> None:
    """全台供需白名單外的欄位（萬瓩原始欄位、文字欄位）與分組參數都回 422。"""
    slot = datetime(2026, 10, 21, 14, 0)
    window = {"start": rfc3339(slot), "end": rfc3339(slot)}
    with _seeded_national(repo, TimeWindow(slot, slot), {slot: 3000.0}) as client:
        statuses = [
            client.get(NATIONAL_SERIES_PATH, params={**window, "fields": field}).status_code
            for field in ("curr_load_wan_kw", "fore_peak_resv_indicator")
        ]
        statuses.append(
            client.get(NATIONAL_SERIES_PATH, params={**window, "group_by": "region"}).status_code
        )

    assert statuses == [422, 422, 422]


def _seeded_regional(
    repo: TimeSeriesRepository, window: TimeWindow, rows: list
) -> Iterator[TestClient]:
    return _seeded_rows(
        repo,
        "raw_taipower_regional_supply_demand_snapshot",
        window,
        lambda: repo.regional_supply_demand_store.upsert(rows),
    )


def _regional_rows(observed_at: datetime, load_wan_kw: float, *, without: str = "") -> list:
    return [
        replace(row, load_wan_kw=load_wan_kw)
        for row in regional_supply_demand_snapshots(observed_at)
        if row.region != without
    ]


def assert_regional_missing_region_bucket_is_null(repo: TimeSeriesRepository) -> None:
    """區域供需固定依 region 分組，窗口內某區缺值的 bucket，該區的點為 null。"""
    first, gap, last = (datetime(2026, 10, 22, 9, 0) + timedelta(minutes=10 * i) for i in range(3))
    rows = (
        _regional_rows(first, 100.0)
        + _regional_rows(gap, 200.0, without="東部")
        + _regional_rows(last, 300.0)
    )
    with _seeded_regional(repo, TimeWindow(first, last), rows) as client:
        response = client.get(
            REGIONAL_SERIES_PATH, params={"start": rfc3339(first), "end": rfc3339(last)}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["bucket"] == "raw"
    points = {
        series["group"]["region"]: [point["v"] for point in series["points"]]
        for series in body["series"]
    }
    assert points == {
        "中部": [1000.0, 2000.0, 3000.0],
        "北部": [1000.0, 2000.0, 3000.0],
        "南部": [1000.0, 2000.0, 3000.0],
        "東部": [1000.0, None, 3000.0],
    }
    assert {(series["field"], series["unit"]) for series in body["series"]} == {("load_mw", "MW")}


def assert_regional_rejects_totals_and_foreign_fields(repo: TimeSeriesRepository) -> None:
    """區域供需不提供四區合成：group_by、白名單外欄位與無效區域都回 422；generation_mw 可選。"""
    slot = datetime(2026, 10, 22, 12, 0)
    window = {"start": rfc3339(slot), "end": rfc3339(slot)}
    with _seeded_regional(repo, TimeWindow(slot, slot), _regional_rows(slot, 100.0)) as client:
        rejected = [
            client.get(REGIONAL_SERIES_PATH, params={**window, **extra}).status_code
            for extra in (
                {"group_by": "none"},
                {"fields": "curr_load_mw"},
                {"fields": "load_wan_kw"},
                {"region": "西部"},
            )
        ]
        generation = client.get(
            REGIONAL_SERIES_PATH,
            params={**window, "fields": "generation_mw", "region": "東部"},
        )

    assert rejected == [422, 422, 422, 422]
    assert [
        (series["field"], series["group"], series["points"][0]["v"])
        for series in generation.json()["series"]
    ] == [("generation_mw", {"region": "東部"}, 128.0)]


SUPPLY_DEMAND_SERIES_SCENARIOS = (
    assert_regional_missing_region_bucket_is_null,
    assert_regional_rejects_totals_and_foreign_fields,
    assert_national_auto_bucket_resolves_by_window_length,
    assert_national_defaults_to_load_and_capacity_in_mw,
    assert_national_fields_outside_whitelist_are_rejected,
)
