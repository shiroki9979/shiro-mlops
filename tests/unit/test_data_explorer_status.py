"""Dataset status dimensions stay independent and explainable."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.weather_resolution import FORECAST_STALE_AFTER
from shiro_mlops.service.data_explorer.dataset_query import DatasetQuery
from shiro_mlops.service.data_explorer.schemas import StatusResponse
from shiro_mlops.service.data_explorer.status import derive_overall, evaluate_freshness
from tests.helpers import (
    derived_hourly_load,
    forecast_release,
    supply_demand_snapshot,
    write_derived_load,
)


def test_forecast_and_audit_status_follow_the_latest_release_on_each_request(
    test_repo: TimeSeriesRepository,
) -> None:
    catalog = DatasetQuery(test_repo.engine)
    for hour, missing, completeness in ((10, ("63000000",), "incomplete"), (11, (), "complete")):
        test_repo.cwa_weather_store.upsert_cwa_forecast_releases(
            [
                replace(
                    forecast_release(datetime(2026, 9, 20, hour), ()),
                    missing_geocodes=missing,
                )
            ]
        )

        statuses = catalog.status(datetime(2026, 9, 20, 12)).datasets
        forecasts = next(item for item in statuses if item.id == "cwa_forecasts")
        audits = next(item for item in statuses if item.id == "cwa_forecast_audits")

        assert forecasts.completeness == audits.completeness == completeness
        assert forecasts.missing_identifiers == audits.missing_identifiers == list(missing)
        assert forecasts.source_age_seconds == audits.source_age_seconds == (12 - hour) * 3600
        assert forecasts.latest_release_stale is False
        assert audits.latest_release_stale is None


def test_forecast_ingestion_age_follows_the_latest_fetch_of_the_current_release(
    test_repo: TimeSeriesRepository,
) -> None:
    """預報版本每小時重新擷取；擷取年齡看最近一次擷取，來源年齡看發布時間（#374）。"""
    release = forecast_release(datetime(2026, 9, 20, 5), ())
    for fetched_hour in (5, 6, 7):
        test_repo.cwa_weather_store.upsert_cwa_forecast_releases(
            [replace(release, fetched_at=datetime(2026, 9, 20, fetched_hour, 40))]
        )

    statuses = DatasetQuery(test_repo.engine).status(datetime(2026, 9, 20, 8)).datasets

    for dataset_id in ("cwa_forecasts", "cwa_forecast_audits"):
        status = next(item for item in statuses if item.id == dataset_id)
        assert status.ingestion_age_seconds == 20 * 60
        assert status.source_age_seconds == 3 * 3600


@pytest.mark.parametrize(
    ("age", "expected"),
    [(FORECAST_STALE_AFTER, False), (FORECAST_STALE_AFTER + timedelta(minutes=1), True)],
)
def test_latest_release_stale_shares_the_resolver_seven_hour_threshold(
    test_repo: TimeSeriesRepository, age: timedelta, expected: bool
) -> None:
    issued_at = datetime(2026, 9, 20, 5)
    test_repo.cwa_weather_store.upsert_cwa_forecast_releases([forecast_release(issued_at, ())])

    statuses = DatasetQuery(test_repo.engine).status(issued_at + age).datasets
    forecasts = next(item for item in statuses if item.id == "cwa_forecasts")

    assert forecasts.latest_release_stale is expected


@pytest.mark.parametrize(
    ("age", "freshness"),
    [
        (timedelta(hours=2, seconds=1), "fresh"),
        (timedelta(hours=12), "fresh"),
        (timedelta(hours=12, seconds=1), "warning"),
    ],
)
def test_forecast_freshness_follows_the_release_interval_not_the_chart_slot(
    test_repo: TimeSeriesRepository, age: timedelta, freshness: str
) -> None:
    """預報約每 6 小時發布一版：錯過兩版（12 小時）才 warning，不以圖表的 1 小時時段判定（#373）。"""
    issued_at = datetime(2026, 9, 20, 11)
    test_repo.cwa_weather_store.upsert_cwa_forecast_releases([forecast_release(issued_at, ())])

    statuses = DatasetQuery(test_repo.engine).status(issued_at + age).datasets

    for dataset_id in ("cwa_forecasts", "cwa_forecast_audits"):
        status = next(item for item in statuses if item.id == dataset_id)
        assert (status.freshness, status.completeness) == (freshness, "complete")
        assert status.overall == ("healthy" if freshness == "fresh" else "warning")


@pytest.mark.parametrize("minute", [0, 15])
def test_complete_hourly_load_has_no_gaps_before_the_current_hour_ends(
    test_repo: TimeSeriesRepository, minute: int
) -> None:
    write_derived_load(test_repo.engine, derived_hourly_load(24, datetime(2026, 9, 20, 11)))

    status = DatasetQuery(test_repo.engine).status(datetime(2026, 9, 20, 12, minute))
    load = next(dataset for dataset in status.datasets if dataset.id == "hourly_load")

    assert load.completeness == "complete"
    assert load.missing_identifiers == []


@pytest.mark.parametrize(
    ("as_of", "expected"),
    [
        (datetime(2026, 9, 20, 13, 0, 1), ("fresh", "complete", [])),
        (datetime(2026, 9, 20, 13, 4), ("fresh", "complete", [])),
        (datetime(2026, 9, 20, 13, 9, 59), ("fresh", "complete", [])),
        (
            datetime(2026, 9, 20, 13, 10, 1),
            ("fresh", "incomplete", ["2026-09-20T12:00:00+08:00"]),
        ),
        (
            datetime(2026, 9, 20, 14, 10, 1),
            ("warning", "incomplete", ["2026-09-20T12:00:00+08:00", "2026-09-20T13:00:00+08:00"]),
        ),
    ],
)
def test_hourly_load_waits_for_the_scheduled_derivation_before_reporting_the_hour(
    test_repo: TimeSeriesRepository, as_of: datetime, expected: tuple[str, str, list[str]]
) -> None:
    """12:00 那一小時由 13:05 的推算寫入：寬限過後才列缺漏，錯過兩次推算才標過期（#373）。"""
    write_derived_load(test_repo.engine, derived_hourly_load(24, datetime(2026, 9, 20, 11)))

    status = DatasetQuery(test_repo.engine).status(as_of)
    load = next(dataset for dataset in status.datasets if dataset.id == "hourly_load")

    assert (load.freshness, load.completeness, load.missing_identifiers) == expected


def test_national_supply_demand_window_includes_the_snapshot_a_day_before_the_latest(
    test_repo: TimeSeriesRepository,
) -> None:
    """全國供需目錄的 24 小時窗含起點：恰好早一天的快照撐開窗，中間的 10 分鐘 slot 皆列為缺漏。"""
    for observed_at in (datetime(2026, 9, 4, 17, 30), datetime(2026, 9, 5, 17, 30)):
        test_repo.supply_demand_store.upsert(supply_demand_snapshot(observed_at))

    status = DatasetQuery(test_repo.engine).status(datetime(2026, 9, 5, 17, 35))
    national = next(item for item in status.datasets if item.id == "national_supply_demand")

    assert national.completeness == "incomplete"
    assert len(national.missing_identifiers) == 143
    assert national.missing_identifiers[0] == "2026-09-04T17:40:00+08:00"
    assert national.missing_identifiers[-1] == "2026-09-05T17:20:00+08:00"


def test_freshness_uses_the_update_interval_and_two_missed_cycles() -> None:
    """超過兩個預期週期未更新才標 warning；ingestion 與 source age 分開計算。"""
    as_of = datetime(2026, 8, 20, 14, 0)
    source_at = datetime(2026, 8, 20, 13, 50)
    ingested_at = datetime(2026, 8, 20, 13, 55)

    fresh = evaluate_freshness(
        update_interval=timedelta(minutes=10),
        as_of=as_of,
        latest_source_at=source_at,
        latest_ingested_at=ingested_at,
        arrival_lag=timedelta(0),
    )
    assert fresh.state == "fresh"
    assert fresh.source_age_seconds == 600
    assert fresh.ingestion_age_seconds == 300

    stale = evaluate_freshness(
        update_interval=timedelta(hours=1),
        as_of=as_of,
        latest_source_at=datetime(2026, 8, 20, 11, 0),
        latest_ingested_at=datetime(2026, 8, 20, 11, 5),
        arrival_lag=timedelta(0),
    )
    assert stale.state == "warning"
    assert stale.source_age_seconds == 3 * 3600


def test_overall_severity_maps_stale_or_incomplete_data_to_warning() -> None:
    """過期或不完整為 warning，兩者皆無才是 healthy。"""
    assert derive_overall("warning", "complete") == "warning"
    assert derive_overall("fresh", "incomplete") == "warning"
    assert derive_overall("fresh", "complete") == "healthy"


def test_status_contract_has_an_empty_and_a_populated_shape() -> None:
    """無資料只帶識別、連結與 warning；新鮮度與完整度只存在於有資料的形狀，且沒有 unknown。"""
    shapes = StatusResponse.model_json_schema()["$defs"]
    empty = shapes["EmptyDatasetStatus"]["properties"]
    populated = shapes["PopulatedDatasetStatus"]

    assert set(empty) == {"kind", "id", "label", "overall", "href"}
    assert (empty["kind"]["const"], empty["overall"]["const"]) == ("empty", "warning")
    assert populated["properties"]["kind"]["const"] == "populated"
    assert populated["properties"]["freshness"]["enum"] == ["fresh", "warning"]
    assert populated["properties"]["completeness"]["enum"] == ["complete", "incomplete"]
    assert populated["properties"]["overall"]["enum"] == ["healthy", "warning"]
    assert set(populated["properties"]) - set(populated["required"]) == {
        "kind",
        "latest_release_stale",
    }
