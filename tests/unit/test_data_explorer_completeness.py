"""Dataset completeness policies stay independently testable."""

from datetime import datetime, timedelta

from shiro_mlops.core.config import settings
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.service.data_explorer.completeness import (
    NATIONAL_SNAPSHOT_TABLE,
    audit_missing_identifiers,
    missing_regional_identifiers,
    observation_gaps,
    ten_minute_gaps,
)
from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.query import TimeWindow
from shiro_mlops.service.data_explorer.timefmt import format_taiwan_time
from tests.unit.test_supply_demand_repository import _sample_snapshot


def test_missing_regional_identifiers_lists_absent_allowlisted_regions() -> None:
    """區域完整度只看北中南東 allowlist，不以 nullable generation 判定。"""
    assert missing_regional_identifiers({"北部", "中部", "南部", "東部"}) == []
    assert missing_regional_identifiers({"北部", "中部"}) == ["南部", "東部"]


def test_audit_missing_identifiers_preserve_station_geocode_and_placeholders() -> None:
    """觀測缺站、預報缺 geocode，以及 incomplete 但未列 id 的 placeholder 必須可獨立驗證。"""
    assert audit_missing_identifiers(
        {"status": "incomplete", "missing_station_ids": ["467490"]},
        "missing_station_ids",
        incomplete_placeholder="incomplete_batch",
    ) == ["467490"]
    assert audit_missing_identifiers(
        {"status": "incomplete", "missing_station_ids": []},
        "missing_station_ids",
        incomplete_placeholder="incomplete_batch",
    ) == ["incomplete_batch"]
    assert audit_missing_identifiers(
        {"status": "incomplete", "missing_geocodes": ["63000050"]},
        "missing_geocodes",
        incomplete_placeholder="incomplete_release",
    ) == ["63000050"]
    assert audit_missing_identifiers(
        {"status": "incomplete", "missing_geocodes": []},
        "missing_geocodes",
        incomplete_placeholder="incomplete_release",
    ) == ["incomplete_release"]
    assert audit_missing_identifiers(None, "missing_station_ids") == []


def test_ten_minute_gaps_report_national_snapshot_holes(
    test_repo: TimeSeriesRepository,
) -> None:
    """全台供需每個 slot 預期一筆；20 分鐘間隔必須揭露中間缺口。"""
    later = datetime(2026, 9, 5, 17, 30)
    earlier = later - timedelta(minutes=20)
    test_repo.upsert_supply_demand_snapshot(_sample_snapshot(earlier))
    test_repo.upsert_supply_demand_snapshot(_sample_snapshot(later))
    db = ExplorerDb(test_repo.engine)

    missing = ten_minute_gaps(db, NATIONAL_SNAPSHOT_TABLE, TimeWindow(earlier, later))

    assert format_taiwan_time(earlier + timedelta(minutes=10)) in missing
    assert format_taiwan_time(earlier) not in missing
    assert format_taiwan_time(later) not in missing


def test_observation_gaps_use_allowlisted_station_hours(
    test_repo: TimeSeriesRepository,
) -> None:
    """測站缺口必須依 allowlist 的逐時 slot 計算。"""
    from shiro_mlops.data.cwa_client import CWAObservationBatch, CWAStationObservation

    observed = datetime(2026, 8, 20, 14, 0)
    test_repo.upsert_cwa_observation_batch(
        CWAObservationBatch(
            fetched_at=observed,
            status="complete",
            missing_station_ids=(),
            raw_payload={},
            observations=(
                CWAStationObservation(
                    observed_at=observed,
                    station_id="466920",
                    station_name="臺北",
                    town_code="63000050",
                    temperature_c=30.0,
                    relative_humidity_pct=None,
                    air_pressure_hpa=None,
                    precipitation_mm=None,
                    wind_speed_m_s=None,
                    wind_direction_deg=None,
                ),
            ),
        )
    )
    db = ExplorerDb(test_repo.engine)
    window = TimeWindow(observed, observed)
    allowlisted = [item.station_id for item in settings.cwa_locations.values()]

    missing = observation_gaps(db, window, None)

    assert f"{format_taiwan_time(observed)}:466920" not in missing
    for station_id in allowlisted:
        if station_id != "466920":
            assert f"{format_taiwan_time(observed)}:{station_id}" in missing
