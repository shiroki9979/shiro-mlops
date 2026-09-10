"""Data Explorer HTTP contracts against a real SQLite repository."""

import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from shiro_mlops.core.config import settings
from shiro_mlops.core.constants import DATETIME_COL, LOAD_MW_COL
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.service.api import app

TAIWAN = ZoneInfo("Asia/Taipei")


def _now() -> datetime:
    return datetime.now(TAIWAN).replace(tzinfo=None, second=0, microsecond=0)


def _rfc3339(value: datetime) -> str:
    return value.replace(tzinfo=TAIWAN).isoformat(timespec="seconds")


def _replace_cursor_key(cursor: str, key: dict[str, str]) -> str:
    padded = cursor + "=" * (-len(cursor) % 4)
    payload = json.loads(urlsafe_b64decode(padded).decode("utf-8"))
    payload["k"] = key
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


@pytest.fixture
def explorer_client(test_repo: TimeSeriesRepository, monkeypatch: pytest.MonkeyPatch):
    """Enable Data Explorer against an isolated SQLite repository."""
    monkeypatch.setattr(settings, "DATA_EXPLORER_ENABLED", True)
    monkeypatch.setattr("shiro_mlops.service.api.repository_store", test_repo)
    with TestClient(app) as client:
        yield client, test_repo


def _upsert_hours(
    repo: TimeSeriesRepository, hours: list[datetime], location: str = "Taipei"
) -> None:
    frame = pd.DataFrame(
        {
            DATETIME_COL: hours,
            LOAD_MW_COL: [30000.0 + index for index in range(len(hours))],
            "location": location,
        }
    )
    repo.upsert_taipower_load(frame, default_location=location)


def test_data_explorer_is_unavailable_when_disabled(
    test_repo: TimeSeriesRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """未啟用時不得暴露 Data Explorer 路由。"""
    monkeypatch.setattr(settings, "DATA_EXPLORER_ENABLED", False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "aws")
    monkeypatch.setattr("shiro_mlops.service.api.repository_store", test_repo)
    monkeypatch.setattr("shiro_mlops.core.database.init_db", lambda: None)
    with TestClient(app) as client:
        assert client.get("/data/status").status_code == 404
        assert client.get("/health").json()["data_explorer_enabled"] is False


def test_legacy_features_latest_is_removed(explorer_client) -> None:
    """過渡快照端點不得再作為營運資料來源。"""
    client, _ = explorer_client
    assert client.get("/features/latest").status_code == 404


def test_data_explorer_does_not_allow_cross_origin_browser_access(explorer_client) -> None:
    """Data Explorer 不得透過 wildcard CORS 提供跨來源讀取。"""
    client, _ = explorer_client

    response = client.options(
        "/data/status",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert "access-control-allow-origin" not in response.headers


def test_status_and_hourly_load_contract(explorer_client) -> None:
    """逐時負載狀態與列表必須讀取已入庫資料，並使用 +08:00 時間與共用 envelope。"""
    client, repo = explorer_client
    latest = _now().replace(minute=0)
    _upsert_hours(repo, [latest - timedelta(hours=1), latest])

    status = client.get("/data/status")
    assert status.status_code == 200
    load_status = next(item for item in status.json()["datasets"] if item["id"] == "hourly_load")
    assert load_status["availability"] == "available"
    assert load_status["freshness"] == "fresh"
    assert load_status["latest_source_at"].endswith("+08:00")
    assert load_status["ingestion_age_seconds"] is not None
    assert load_status["source_age_seconds"] is not None
    assert load_status["href"] == "/data/power/load"

    start = _rfc3339(latest - timedelta(hours=1))
    end = _rfc3339(latest)
    response = client.get(
        "/data/power/load", params={"start": start, "end": end, "location": "Taipei"}
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {"items", "next_cursor", "has_more"}
    assert body["has_more"] is False
    assert len(body["items"]) == 2
    assert body["items"][0]["datetime"] >= body["items"][1]["datetime"]
    assert body["items"][0]["location"] == "Taipei"
    assert "load_mw" in body["items"][0]
    assert "raw_payload" not in body["items"][0]
    assert all(item["datetime"].endswith("+08:00") for item in body["items"])


def test_hourly_load_empty_invalid_window_and_cursor(explorer_client) -> None:
    """無資料為 200 空列表；超時窗為 422；不相容 cursor 為 400。"""
    client, repo = explorer_client
    latest = _now().replace(minute=0)
    _upsert_hours(repo, [latest])

    empty = client.get(
        "/data/power/load",
        params={
            "start": _rfc3339(latest - timedelta(hours=5)),
            "end": _rfc3339(latest - timedelta(hours=4)),
            "location": "Taichung",
        },
    )
    assert empty.status_code == 200
    assert empty.json()["items"] == []

    too_long = client.get(
        "/data/power/load",
        params={"start": _rfc3339(latest - timedelta(days=32)), "end": _rfc3339(latest)},
    )
    assert too_long.status_code == 422

    invalid_time = client.get("/data/power/load", params={"start": "not-a-time"})
    assert invalid_time.status_code == 422

    _upsert_hours(repo, [latest - timedelta(hours=1), latest])
    first_page = client.get(
        "/data/power/load",
        params={
            "start": _rfc3339(latest - timedelta(hours=1)),
            "end": _rfc3339(latest),
            "limit": 1,
        },
    )
    cursor = first_page.json()["next_cursor"]
    assert cursor
    mismatched = client.get(
        "/data/power/load",
        params={
            "start": _rfc3339(latest - timedelta(hours=1)),
            "end": _rfc3339(latest),
            "location": "Kaohsiung",
            "cursor": cursor,
        },
    )
    assert mismatched.status_code == 400
    assert client.get("/data/power/load", params={"cursor": "not-a-cursor"}).status_code == 400

    missing_key = _replace_cursor_key(cursor, {})
    malformed = client.get(
        "/data/power/load",
        params={
            "start": _rfc3339(latest - timedelta(hours=1)),
            "end": _rfc3339(latest),
            "limit": 1,
            "cursor": missing_key,
        },
    )
    assert malformed.status_code == 400


def test_hourly_load_pagination_and_hourly_gaps(explorer_client) -> None:
    """最新優先分頁必須穩定，且 completeness 揭露查詢區間內的小時缺口。"""
    client, repo = explorer_client
    latest = _now().replace(minute=0)
    hours = [latest - timedelta(hours=offset) for offset in (2, 1, 0)]
    _upsert_hours(repo, hours)

    start = _rfc3339(latest - timedelta(hours=2))
    end = _rfc3339(latest)
    first = client.get("/data/power/load", params={"start": start, "end": end, "limit": 1})
    assert first.status_code == 200
    assert first.json()["has_more"] is True
    second = client.get(
        "/data/power/load",
        params={"start": start, "end": end, "limit": 1, "cursor": first.json()["next_cursor"]},
    )
    assert second.status_code == 200
    assert first.json()["items"][0]["datetime"] > second.json()["items"][0]["datetime"]

    gap_start = (latest - timedelta(days=3)).replace(minute=0)
    _upsert_hours(repo, [gap_start, gap_start + timedelta(hours=2)])
    gapped_page = client.get(
        "/data/power/load",
        params={
            "start": _rfc3339(gap_start),
            "end": _rfc3339(gap_start + timedelta(hours=2)),
        },
    )
    assert _rfc3339(gap_start + timedelta(hours=1)) in gapped_page.json()["missing_slots"]


def test_status_returns_503_when_database_unavailable(explorer_client) -> None:
    """TimescaleDB 無法連線時必須回傳 HTTP 503。"""
    client, repo = explorer_client

    class BrokenEngine:
        def connect(self):
            raise SQLAlchemyError("connection refused")

    repo.engine = BrokenEngine()
    assert client.get("/data/status").status_code == 503
    assert client.get("/data/power/load").status_code == 503


def test_national_supply_demand_uses_mw_and_preserves_nullable_fields(explorer_client) -> None:
    """全台供需以 MW 為主顯示，並保留契約允許的空值與萬瓩欄位。"""
    from tests.unit.test_supply_demand_repository import _sample_snapshot

    client, repo = explorer_client
    observed = _now().replace(minute=30, second=0, microsecond=0)
    snapshot = _sample_snapshot(observed)
    earlier_snapshot = _sample_snapshot(observed - timedelta(minutes=20))
    repo.upsert_supply_demand_snapshot(earlier_snapshot)
    repo.upsert_supply_demand_snapshot(snapshot)

    body = client.get(
        "/data/power/supply-demand",
        params={"start": _rfc3339(observed - timedelta(hours=1)), "end": _rfc3339(observed)},
    ).json()
    item = body["items"][0]
    assert item["curr_load_mw"] == pytest.approx(32421.0)
    assert item["curr_load_wan_kw"] == pytest.approx(3242.1)
    assert "raw_payload" not in item
    assert item["observed_at"].endswith("+08:00")
    status = next(
        item
        for item in client.get("/data/status").json()["datasets"]
        if item["id"] == "national_supply_demand"
    )
    assert status["availability"] == "available"
    assert status["completeness"] == "incomplete"
    assert status["missing_slot_count"] == 1


def test_regional_supply_demand_marks_incomplete_slots(explorer_client) -> None:
    """缺少任一區時該 slot 必須標記 incomplete，nullable generation 不得單獨導致 incomplete。"""
    from shiro_mlops.data.taipower_regional_supply_demand import (
        TaipowerRegionalSupplyDemandSnapshot,
    )

    client, repo = explorer_client
    observed = _now().replace(minute=20, second=0, microsecond=0)
    complete_slot = observed - timedelta(minutes=10)
    rows = [
        TaipowerRegionalSupplyDemandSnapshot(
            observed_at=complete_slot,
            region=region,
            source_time=complete_slot,
            generation_wan_kw=None if region == "東部" else 100.0,
            load_wan_kw=200.0,
            raw_payload={"區域": region},
        )
        for region in ("北部", "中部", "南部", "東部")
    ]
    rows.append(
        TaipowerRegionalSupplyDemandSnapshot(
            observed_at=observed,
            region="北部",
            source_time=observed,
            generation_wan_kw=10.0,
            load_wan_kw=90.0,
            raw_payload={"區域": "北部"},
        )
    )
    repo.upsert_regional_supply_demand_snapshots(rows)

    params = {"start": _rfc3339(complete_slot), "end": _rfc3339(observed), "limit": 50}
    page = client.get("/data/power/regional", params=params).json()
    north_current = next(
        item
        for item in page["items"]
        if item["region"] == "北部" and item["observed_at"] == _rfc3339(observed)
    )
    assert north_current["slot_complete"] is False
    assert "東部" in north_current["missing_regions"]
    complete_east = next(item for item in page["items"] if item["region"] == "東部")
    assert complete_east["generation_wan_kw"] is None
    assert complete_east["slot_complete"] is True
    incomplete = client.get(
        "/data/power/regional", params={**params, "completeness": "incomplete"}
    ).json()
    assert all(item["slot_complete"] is False for item in incomplete["items"])
    status = next(
        item
        for item in client.get("/data/status").json()["datasets"]
        if item["id"] == "regional_supply_demand"
    )
    assert status["completeness"] == "incomplete"
    assert "completeness=incomplete" in status["href"]


def test_unit_generation_preserves_zero_and_nullable_fields(explorer_client) -> None:
    """機組零發電必須保留，契約允許空值不得被當成缺失，且不以固定數量判定不完整。"""
    from tests.unit.test_unit_generation_repository import _sample_snapshots

    client, repo = explorer_client
    observed = _now().replace(minute=10, second=0, microsecond=0)
    repo.upsert_unit_generation_snapshots(_sample_snapshots(observed))

    page = client.get(
        "/data/power/units",
        params={"start": _rfc3339(observed - timedelta(hours=1)), "end": _rfc3339(observed)},
    ).json()
    names = {item["unit_name"]: item for item in page["items"]}
    assert names["大潭CC#3"]["net_generation_mw"] == 0.0
    assert names["大潭CC#3"]["remark"] == "歲修"
    assert names["離島其它(註4)"]["net_generation_mw"] is None
    assert "raw_payload" not in page["items"][0]
    filtered = client.get(
        "/data/power/units",
        params={
            "start": _rfc3339(observed - timedelta(hours=1)),
            "end": _rfc3339(observed),
            "unit_type": "燃氣",
            "unit_name": "大潭CC#1",
        },
    ).json()
    assert len(filtered["items"]) == 1
    status = next(
        item
        for item in client.get("/data/status").json()["datasets"]
        if item["id"] == "unit_generation"
    )
    assert status["completeness"] == "complete"
    assert status["record_count"] == 4


def test_power_endpoints_empty_invalid_window_and_pagination(explorer_client) -> None:
    """電力列表無資料為 200；超時窗與非法篩選為 422；cursor 分頁保持最新優先。"""
    from tests.unit.test_supply_demand_repository import _sample_snapshot
    from tests.unit.test_unit_generation_repository import _sample_snapshots

    client, repo = explorer_client
    observed = _now().replace(minute=30, second=0, microsecond=0)
    empty_window = {
        "start": _rfc3339(observed - timedelta(hours=5)),
        "end": _rfc3339(observed - timedelta(hours=4)),
    }

    empty_national = client.get("/data/power/supply-demand", params=empty_window)
    assert empty_national.status_code == 200
    assert empty_national.json()["items"] == []

    empty_units = client.get("/data/power/units", params=empty_window)
    assert empty_units.status_code == 200
    assert empty_units.json()["items"] == []

    empty_regional = client.get("/data/power/regional", params=empty_window)
    assert empty_regional.status_code == 200
    assert empty_regional.json()["items"] == []

    too_long = client.get(
        "/data/power/supply-demand",
        params={"start": _rfc3339(observed - timedelta(days=8)), "end": _rfc3339(observed)},
    )
    assert too_long.status_code == 422
    assert client.get("/data/power/regional", params={"region": "國外"}).status_code == 422
    assert client.get("/data/power/regional", params={"completeness": "bogus"}).status_code == 422

    for offset in (20, 10, 0):
        repo.upsert_supply_demand_snapshot(_sample_snapshot(observed - timedelta(minutes=offset)))
    start = _rfc3339(observed - timedelta(minutes=20))
    end = _rfc3339(observed)
    first = client.get("/data/power/supply-demand", params={"start": start, "end": end, "limit": 1})
    assert first.status_code == 200
    assert first.json()["has_more"] is True
    second = client.get(
        "/data/power/supply-demand",
        params={"start": start, "end": end, "limit": 1, "cursor": first.json()["next_cursor"]},
    )
    assert second.status_code == 200
    assert first.json()["items"][0]["observed_at"] > second.json()["items"][0]["observed_at"]
    assert (
        client.get(
            "/data/power/supply-demand",
            params={"start": start, "end": end, "cursor": "not-a-cursor"},
        ).status_code
        == 400
    )
    assert (
        client.get(
            "/data/power/regional",
            params={"start": start, "end": end, "cursor": "not-a-cursor"},
        ).status_code
        == 400
    )
    assert (
        client.get(
            "/data/power/units",
            params={"start": start, "end": end, "cursor": "not-a-cursor"},
        ).status_code
        == 400
    )

    repo.upsert_unit_generation_snapshots(_sample_snapshots(observed))
    unit_page = client.get(
        "/data/power/units",
        params={
            "start": _rfc3339(observed - timedelta(hours=1)),
            "end": _rfc3339(observed),
            "limit": 1,
        },
    )
    assert unit_page.json()["has_more"] is True
    next_units = client.get(
        "/data/power/units",
        params={
            "start": _rfc3339(observed - timedelta(hours=1)),
            "end": _rfc3339(observed),
            "limit": 1,
            "cursor": unit_page.json()["next_cursor"],
        },
    )
    assert next_units.status_code == 200
    assert next_units.json()["items"]
    assert next_units.json()["items"][0] != unit_page.json()["items"][0]


def test_cwa_observations_and_audits_exclude_raw_payload(explorer_client) -> None:
    """測站觀測與 audit 必須支援 station/status 篩選，且不得回傳 raw payload。"""
    from shiro_mlops.data.cwa_client import CWAObservationBatch, CWAStationObservation

    client, repo = explorer_client
    observed = _now().replace(minute=0)
    repo.upsert_cwa_observation_batch(
        CWAObservationBatch(
            fetched_at=observed,
            status="incomplete",
            missing_station_ids=("467490",),
            raw_payload={"secret": "do-not-return"},
            observations=(
                CWAStationObservation(
                    observed_at=pd.Timestamp(observed),
                    station_id="466920",
                    station_name="臺北",
                    town_code="63000050",
                    temperature_c=None,
                    relative_humidity_pct=80.0,
                    air_pressure_hpa=None,
                    precipitation_mm=0.0,
                    wind_speed_m_s=None,
                    wind_direction_deg=None,
                ),
            ),
        )
    )
    observations = client.get(
        "/data/weather/observations",
        params={
            "start": _rfc3339(observed - timedelta(hours=1)),
            "end": _rfc3339(observed),
            "station_id": "466920",
        },
    ).json()
    assert observations["items"][0]["temperature_c"] is None
    assert observations["items"][0]["precipitation_mm"] == 0.0
    assert "raw_payload" not in observations["items"][0]
    audits = client.get(
        "/data/audits/cwa-observations",
        params={
            "start": _rfc3339(observed - timedelta(hours=1)),
            "end": _rfc3339(observed),
            "status": "incomplete",
            "missing_station_id": "467490",
        },
    ).json()
    assert audits["items"][0]["missing_station_ids"] == ["467490"]
    assert "raw_payload" not in audits["items"][0]
    empty_history = client.get(
        "/data/audits/cwa-observations",
        params={
            "start": _rfc3339(observed - timedelta(days=10)),
            "end": _rfc3339(observed - timedelta(days=9)),
        },
    )
    assert empty_history.status_code == 200
    assert empty_history.json()["items"] == []


def test_cwa_forecasts_default_to_latest_vintage_and_keep_all_vintages(explorer_client) -> None:
    """未指定版本時預設最新發布；明確條件可取得全部 vintages，且分開 serving stale。"""
    from shiro_mlops.data.cwa_client import CWAForecastRelease, CWATownshipForecast

    client, repo = explorer_client
    older = _now().replace(minute=0) - timedelta(hours=2)
    newer = older + timedelta(hours=1)
    valid = newer + timedelta(hours=3)

    def release(issued_at: datetime, temperature: float) -> CWAForecastRelease:
        return CWAForecastRelease(
            dataset_id="F-D0047-089",
            issued_at=pd.Timestamp(issued_at),
            source_updated_at=pd.Timestamp(issued_at),
            fetched_at=issued_at,
            status="complete",
            missing_geocodes=(),
            raw_payload={"secret": "do-not-return"},
            forecasts=(
                CWATownshipForecast(
                    valid_from=pd.Timestamp(valid),
                    valid_to=pd.Timestamp(valid),
                    geocode="63000050",
                    location_name="臺北",
                    temperature_c=temperature,
                    dew_point_c=None,
                    apparent_temperature_c=None,
                    relative_humidity_pct=70.0,
                    probability_of_precipitation_pct=None,
                    wind_speed_m_s=None,
                    wind_direction=None,
                ),
            ),
        )

    repo.upsert_cwa_forecast_release(release(older, 28.0))
    repo.upsert_cwa_forecast_release(release(newer, 31.0))
    latest_page = client.get(
        "/data/weather/forecasts",
        params={"start": _rfc3339(valid - timedelta(hours=1)), "end": _rfc3339(valid)},
    ).json()
    assert len(latest_page["items"]) == 1
    assert latest_page["items"][0]["temperature_c"] == 31.0
    assert latest_page["items"][0]["issued_at"] == _rfc3339(newer)
    assert latest_page["items"][0]["location_name"] == "臺北"
    assert "raw_payload" not in latest_page["items"][0]
    all_vintages = client.get(
        "/data/weather/forecasts",
        params={
            "start": _rfc3339(valid - timedelta(hours=1)),
            "end": _rfc3339(valid),
            "all_vintages": "true",
        },
    ).json()
    assert len(all_vintages["items"]) == 2
    older_vintage = client.get(
        "/data/weather/forecasts",
        params={
            "start": _rfc3339(valid - timedelta(hours=1)),
            "end": _rfc3339(valid),
            "source_updated_at": _rfc3339(older),
        },
    ).json()
    assert [item["temperature_c"] for item in older_vintage["items"]] == [28.0]
    issued_vintage = client.get(
        "/data/weather/forecasts",
        params={
            "start": _rfc3339(valid - timedelta(hours=1)),
            "end": _rfc3339(valid),
            "issued_at": _rfc3339(older),
        },
    ).json()
    assert [item["temperature_c"] for item in issued_vintage["items"]] == [28.0]
    audits = client.get(
        "/data/audits/cwa-forecasts",
        params={"start": _rfc3339(older - timedelta(hours=1)), "end": _rfc3339(newer)},
    ).json()
    assert {item["issued_at"] for item in audits["items"]} == {_rfc3339(older), _rfc3339(newer)}
    assert "raw_payload" not in audits["items"][0]
    status = next(
        item
        for item in client.get("/data/status").json()["datasets"]
        if item["id"] == "cwa_forecasts"
    )
    assert status["serving_stale"] is False
    assert status["freshness"] in {"fresh", "warning"}
