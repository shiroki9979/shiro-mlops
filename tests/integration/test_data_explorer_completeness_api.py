"""Data Explorer completeness policies observed through the HTTP list and status routes."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from shiro_mlops.core.config import settings
from shiro_mlops.data.cwa_client import CWAObservationBatch, CWAStationObservation
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.service.api import create_app
from tests.helpers import (
    forecast_release,
    regional_supply_demand_snapshots,
    rfc3339,
    supply_demand_snapshot,
    township_forecast,
)


@pytest.fixture
def client(test_repo: TimeSeriesRepository, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "DATA_EXPLORER_ENABLED", True)
    with TestClient(create_app(repository=test_repo)) as client:
        yield client


def _status(client: TestClient) -> dict[str, dict]:
    return {item["id"]: item for item in client.get("/data/status").json()["datasets"]}


def _observation(observed_at: datetime, station_id: str = "466920") -> CWAStationObservation:
    return CWAStationObservation(
        observed_at=observed_at,
        station_id=station_id,
        station_name="臺北",
        town_code="63000050",
        temperature_c=30.0,
        relative_humidity_pct=None,
        air_pressure_hpa=None,
        precipitation_mm=None,
        wind_speed_m_s=None,
        wind_direction_deg=None,
    )


def test_regional_completeness_lists_only_absent_allowlisted_regions(
    client: TestClient, test_repo: TimeSeriesRepository
) -> None:
    """區域完整度只看北中南東 allowlist：列表逐列標出缺的區，狀態只看最新 slot。"""
    partial = datetime(2026, 9, 5, 17, 30)
    complete = partial - timedelta(minutes=10)
    test_repo.regional_supply_demand_store.upsert(
        regional_supply_demand_snapshots(complete) + regional_supply_demand_snapshots(partial)[:2]
    )

    page = client.get(
        "/data/power/regional", params={"start": rfc3339(complete), "end": rfc3339(partial)}
    ).json()
    regional = _status(client)["regional_supply_demand"]

    missing_by_row = {
        (item["observed_at"], item["region"]): item["missing_regions"] for item in page["items"]
    }
    assert missing_by_row == {
        (rfc3339(partial), "北部"): ["南部", "東部"],
        (rfc3339(partial), "中部"): ["南部", "東部"],
        (rfc3339(complete), "北部"): [],
        (rfc3339(complete), "中部"): [],
        (rfc3339(complete), "南部"): [],
        (rfc3339(complete), "東部"): [],
    }
    assert regional["missing_identifiers"] == ["南部", "東部"]
    assert regional["missing_slot_count"] == 2


@pytest.mark.parametrize(
    ("missing_station_ids", "missing_geocodes", "observation_ids", "forecast_ids"),
    [
        (("467490",), ("63000050",), ["467490"], ["63000050"]),
        ((), (), ["incomplete_batch"], ["incomplete_release"]),
    ],
    ids=["named-ids", "placeholders"],
)
def test_audit_status_reports_missing_ids_or_an_incomplete_placeholder(
    client: TestClient,
    test_repo: TimeSeriesRepository,
    missing_station_ids: tuple[str, ...],
    missing_geocodes: tuple[str, ...],
    observation_ids: list[str],
    forecast_ids: list[str],
) -> None:
    """觀測缺站、預報缺 geocode；incomplete 卻未列 id 時以 placeholder 揭露。"""
    observed_at = datetime(2026, 9, 20, 12)
    test_repo.upsert_cwa_observation_batch(
        CWAObservationBatch(
            fetched_at=observed_at,
            status="incomplete",
            missing_station_ids=missing_station_ids,
            raw_payload={},
            observations=(_observation(observed_at),),
        )
    )
    test_repo.upsert_cwa_forecast_release(
        replace(
            forecast_release(observed_at, (township_forecast(observed_at, 30.0),)),
            status="incomplete",
            missing_geocodes=missing_geocodes,
        )
    )

    statuses = _status(client)

    for dataset_id in ("cwa_observations", "cwa_observation_audits"):
        assert statuses[dataset_id]["completeness"] == "incomplete"
        assert statuses[dataset_id]["missing_identifiers"] == observation_ids
    for dataset_id in ("cwa_forecasts", "cwa_forecast_audits"):
        assert statuses[dataset_id]["completeness"] == "incomplete"
        assert statuses[dataset_id]["missing_identifiers"] == forecast_ids


def test_national_list_reports_the_ten_minute_hole_between_snapshots(
    client: TestClient, test_repo: TimeSeriesRepository
) -> None:
    """全台供需每個 slot 預期一筆；20 分鐘間隔必須揭露中間缺口。"""
    later = datetime(2026, 9, 5, 17, 30)
    earlier = later - timedelta(minutes=20)
    test_repo.supply_demand_store.upsert(supply_demand_snapshot(earlier))
    test_repo.supply_demand_store.upsert(supply_demand_snapshot(later))

    page = client.get(
        "/data/power/supply-demand", params={"start": rfc3339(earlier), "end": rfc3339(later)}
    ).json()

    assert page["missing_slots"] == [rfc3339(earlier + timedelta(minutes=10))]


def test_observation_list_without_station_expects_every_allowlisted_station_hour(
    client: TestClient, test_repo: TimeSeriesRepository
) -> None:
    """未指定測站時，測站缺口依 allowlist 的每站逐時 slot 計算。"""
    observed = datetime(2026, 8, 20, 14, 0)
    test_repo.upsert_cwa_observation_batch(
        CWAObservationBatch(
            fetched_at=observed,
            status="complete",
            missing_station_ids=(),
            raw_payload={},
            observations=(_observation(observed),),
        )
    )
    allowlisted = [item.station_id for item in settings.cwa_locations.values()]

    page = client.get(
        "/data/weather/observations", params={"start": rfc3339(observed), "end": rfc3339(observed)}
    ).json()

    assert len(allowlisted) > 1
    assert page["missing_slots"] == [
        f"{rfc3339(observed)}:{station_id}" for station_id in allowlisted if station_id != "466920"
    ]


def test_observation_status_without_an_audit_header_is_complete(
    client: TestClient, test_repo: TimeSeriesRepository
) -> None:
    """有觀測列但沒有批次審計表頭時，觀測狀態仍為 complete，不列出缺漏 id。"""
    observed_at = datetime(2026, 9, 20, 12)
    test_repo.upsert_cwa_observation_batch(
        CWAObservationBatch(
            fetched_at=observed_at,
            status="incomplete",
            missing_station_ids=("467490",),
            raw_payload={},
            observations=(_observation(observed_at),),
        )
    )
    with test_repo.engine.begin() as conn:
        conn.execute(text("DELETE FROM raw_cwa_observation_batch"))

    observations = _status(client)["cwa_observations"]

    assert observations["availability"] == "available"
    assert observations["completeness"] == "complete"
    assert observations["missing_identifiers"] == []
    assert observations["missing_slot_count"] == 0
