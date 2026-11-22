"""Dataset status dimensions stay independent and explainable."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.weather_resolution import FORECAST_STALE_AFTER
from shiro_mlops.service.data_explorer.catalog import DatasetStatusCatalog
from shiro_mlops.service.data_explorer.status import (
    DatasetFreshness,
    derive_overall,
    evaluate_freshness,
)
from tests.helpers import derived_hourly_load, forecast_release, supply_demand_snapshot


def test_forecast_and_audit_status_follow_the_latest_release_on_each_request(
    test_repo: TimeSeriesRepository,
) -> None:
    catalog = DatasetStatusCatalog(test_repo.engine)
    for hour, missing, completeness in ((10, ("63000000",), "incomplete"), (11, (), "complete")):
        test_repo.upsert_cwa_forecast_release(
            replace(
                forecast_release(datetime(2026, 9, 20, hour), ()),
                status=completeness,
                missing_geocodes=missing,
            )
        )

        statuses = catalog.status(datetime(2026, 9, 20, 12)).datasets
        forecasts = next(item for item in statuses if item.id == "cwa_forecasts")
        audits = next(item for item in statuses if item.id == "cwa_forecast_audits")

        assert forecasts.completeness == audits.completeness == completeness
        assert forecasts.missing_identifiers == audits.missing_identifiers == list(missing)
        assert forecasts.source_age_seconds == audits.source_age_seconds == (12 - hour) * 3600
        assert forecasts.latest_release_stale is False
        assert audits.latest_release_stale is None


@pytest.mark.parametrize(
    ("age", "expected"),
    [(FORECAST_STALE_AFTER, False), (FORECAST_STALE_AFTER + timedelta(minutes=1), True)],
)
def test_latest_release_stale_shares_the_resolver_seven_hour_threshold(
    test_repo: TimeSeriesRepository, age: timedelta, expected: bool
) -> None:
    issued_at = datetime(2026, 9, 20, 5)
    test_repo.upsert_cwa_forecast_release(forecast_release(issued_at, ()))

    statuses = DatasetStatusCatalog(test_repo.engine).status(issued_at + age).datasets
    forecasts = next(item for item in statuses if item.id == "cwa_forecasts")

    assert forecasts.latest_release_stale is expected


@pytest.mark.parametrize("minute", [0, 15])
def test_complete_hourly_load_has_no_gaps_before_the_current_hour_ends(
    test_repo: TimeSeriesRepository, minute: int
) -> None:
    test_repo.upsert_taipower_load(derived_hourly_load(24, datetime(2026, 9, 20, 11)))

    status = DatasetStatusCatalog(test_repo.engine).status(datetime(2026, 9, 20, 12, minute))
    load = next(dataset for dataset in status.datasets if dataset.id == "hourly_load")

    assert load.completeness == "complete"
    assert load.missing_slot_count == 0
    assert load.missing_identifiers == []


def test_national_supply_demand_window_includes_the_snapshot_a_day_before_the_latest(
    test_repo: TimeSeriesRepository,
) -> None:
    """全國供需目錄的 24 小時窗含起點：恰好早一天的快照撐開窗，中間的 10 分鐘 slot 皆列為缺漏。"""
    for observed_at in (datetime(2026, 9, 4, 17, 30), datetime(2026, 9, 5, 17, 30)):
        test_repo.upsert_supply_demand_snapshot(supply_demand_snapshot(observed_at))

    status = DatasetStatusCatalog(test_repo.engine).status(datetime(2026, 9, 5, 17, 35))
    national = next(item for item in status.datasets if item.id == "national_supply_demand")

    assert national.completeness == "incomplete"
    assert national.missing_slot_count == 143
    assert national.missing_identifiers[0] == "2026-09-04T17:40:00+08:00"
    assert national.missing_identifiers[-1] == "2026-09-05T17:20:00+08:00"


def test_freshness_uses_dataset_cadence_and_two_missed_cycles() -> None:
    """超過兩個預期週期未更新才標 warning；ingestion 與 source age 分開計算。"""
    as_of = datetime(2026, 8, 20, 14, 0)
    source_at = datetime(2026, 8, 20, 13, 50)
    ingested_at = datetime(2026, 8, 20, 13, 55)

    fresh = evaluate_freshness(
        cadence_seconds=600,
        as_of=as_of,
        latest_source_at=source_at,
        latest_ingested_at=ingested_at,
    )
    assert fresh.state == "fresh"
    assert fresh.source_age_seconds == 600
    assert fresh.ingestion_age_seconds == 300

    stale = evaluate_freshness(
        cadence_seconds=3600,
        as_of=as_of,
        latest_source_at=datetime(2026, 8, 20, 11, 0),
        latest_ingested_at=datetime(2026, 8, 20, 11, 5),
    )
    assert stale.state == "warning"
    assert stale.source_age_seconds == 3 * 3600


def test_freshness_unknown_when_timestamps_missing() -> None:
    """沒有來源或入庫時間時 freshness 必須是 unknown。"""
    result = evaluate_freshness(
        cadence_seconds=3600,
        as_of=datetime(2026, 8, 20, 14, 0),
        latest_source_at=None,
        latest_ingested_at=None,
    )
    assert result == DatasetFreshness("unknown", None, None)


def test_overall_severity_maps_availability_and_warnings() -> None:
    """資料庫不可用為 critical；過期、不完整或空資料為 warning。"""
    assert derive_overall("unavailable", "unknown", "unknown") == "critical"
    assert derive_overall("empty", "unknown", "unknown") == "warning"
    assert derive_overall("available", "warning", "complete") == "warning"
    assert derive_overall("available", "fresh", "incomplete") == "warning"
    assert derive_overall("available", "fresh", "complete") == "healthy"
