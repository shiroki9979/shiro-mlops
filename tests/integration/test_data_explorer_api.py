"""Data Explorer HTTP contracts against a real SQLite repository."""

import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from shiro_mlops.core.config import settings
from shiro_mlops.core.constants import DATETIME_COL, LOAD_MW_COL
from shiro_mlops.core.database import ensure_timescale_hypertables
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.service.api import create_app
from shiro_mlops.service.data_explorer.cursor import encode_cursor
from shiro_mlops.service.data_explorer.datasets import CWA_FORECASTS, HOURLY_LOAD
from shiro_mlops.service.data_explorer.query import ExplorerQuery
from tests.helpers import (
    TAIWAN,
    create_legacy_load_table,
    forecast_release,
    insert_legacy_load_row,
    regional_supply_demand_snapshots,
    rfc3339,
    supply_demand_snapshot,
    township_forecast,
    unit_generation_batch,
    write_derived_load,
)
from tests.scenarios.data_explorer_gaps import (
    assert_regional_gaps_list_zero_region_slots_on_every_page,
)


def _now() -> datetime:
    return datetime.now(TAIWAN).replace(tzinfo=None, second=0, microsecond=0)


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
    with TestClient(create_app(repository=test_repo)) as client:
        yield client, test_repo


def _upsert_hours(
    repo: TimeSeriesRepository, hours: list[datetime], subject: str = "nationwide"
) -> None:
    frame = pd.DataFrame(
        {DATETIME_COL: hours, LOAD_MW_COL: [30000.0 + index for index in range(len(hours))]}
    )
    write_derived_load(repo.engine, frame, subject=subject)


class _UnreachableEngine:
    """An engine whose every connection fails, as when TimescaleDB is down."""

    def connect(self):
        raise SQLAlchemyError("connection refused")


def test_data_explorer_is_unavailable_when_disabled(
    test_repo: TimeSeriesRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """未啟用時不得暴露 Data Explorer 路由。"""
    monkeypatch.setattr(settings, "DATA_EXPLORER_ENABLED", False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr("shiro_mlops.core.database.init_db", lambda: None)
    with TestClient(create_app(repository=test_repo)) as client:
        assert client.get("/data/status").status_code == 404
        assert client.get("/health").json()["data_explorer_enabled"] is False


def test_legacy_features_latest_is_removed(explorer_client) -> None:
    """過渡快照端點不得再作為營運資料來源。"""
    client, _ = explorer_client
    assert client.get("/features/latest").status_code == 404


LIST_PATHS = [
    "/data/power/load",
    "/data/power/supply-demand",
    "/data/power/regional",
    "/data/power/units",
    "/data/weather/observations",
    "/data/weather/forecasts",
    "/data/audits/cwa-observations",
    "/data/audits/cwa-forecasts",
]


@pytest.mark.parametrize("path", LIST_PATHS)
def test_all_lists_reject_v1_cursor_before_database_access(explorer_client, path: str) -> None:
    client, repo = explorer_client
    legacy = urlsafe_b64encode(b'{"v":1,"ds":"hourly_load","f":{},"k":{}}').decode().rstrip("=")
    repo.engine = _UnreachableEngine()

    response = client.get(path, params={"cursor": legacy})

    assert response.status_code == 400
    assert response.json()["detail"] == "Incompatible cursor version"


@pytest.mark.parametrize("path", LIST_PATHS)
def test_all_lists_reject_undeclared_parameters_before_database_access(
    explorer_client, path: str
) -> None:
    """打錯的篩選名稱回 422，而不是回傳未篩選的結果。"""
    client, repo = explorer_client
    repo.engine = _UnreachableEngine()

    response = client.get(path, params={"regoin": "北部", "bucket": "1h"})

    assert response.status_code == 422
    assert response.json()["detail"] == "unsupported list parameters: bucket, regoin"


def test_undeclared_list_parameter_precedes_invalid_cursor(explorer_client) -> None:
    """打錯的參數先回 422：否則使用者回到第一頁後才會看到第二個錯誤。"""
    client, _ = explorer_client

    response = client.get(
        "/data/power/regional", params={"regoin": "北部", "cursor": "not-a-cursor"}
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "unsupported list parameters: regoin"


@pytest.mark.parametrize(
    "query", [[("regoin", "")], [("regoin", "北部"), ("regoin", "")]], ids=["empty", "last-empty"]
)
def test_list_rejects_an_undeclared_parameter_sent_empty(
    explorer_client, query: list[tuple[str, str]]
) -> None:
    """值為空的未宣告參數也回 422：`?regoin=` 不得回傳未篩選的結果。"""
    client, _ = explorer_client

    response = client.get("/data/power/regional", params=query)

    assert response.status_code == 422
    assert response.json()["detail"] == "unsupported list parameters: regoin"


def test_list_reads_a_declared_filter_sent_empty_as_not_given(explorer_client) -> None:
    """值為空的已宣告篩選視為沒有篩選。"""
    client, repo = explorer_client
    hour = _now().replace(minute=0) - timedelta(hours=2)
    _upsert_hours(repo, [hour])
    window = {"start": rfc3339(hour - timedelta(hours=1)), "end": rfc3339(hour)}

    with_empty = client.get("/data/power/load", params={**window, "subject": ""})
    without = client.get("/data/power/load", params=window)

    assert with_empty.status_code == 200
    assert with_empty.json()["items"] == without.json()["items"]
    assert len(with_empty.json()["items"]) == 1


def test_malformed_v2_cursor_precedes_database_failure(
    explorer_client,
) -> None:
    client, repo = explorer_client
    window = {"start": "2026-08-01T00:00:00+08:00", "end": "2026-08-02T00:00:00+08:00"}
    filters = ExplorerQuery.from_params(HOURLY_LOAD, window).filters
    cursor = encode_cursor(
        dataset="hourly_load", filters=filters, key={"time": 123, "subject": "nationwide"}
    )
    repo.engine = _UnreachableEngine()

    response = client.get("/data/power/load", params={**window, "cursor": cursor})

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid cursor key"


def test_forecast_cursor_filter_mismatch_precedes_database_failure(
    explorer_client,
) -> None:
    client, repo = explorer_client
    window = {"start": "2026-08-01T00:00:00+08:00", "end": "2026-08-02T00:00:00+08:00"}
    filters = ExplorerQuery.from_params(CWA_FORECASTS, {**window, "geocode": "A"}).filters
    cursor = encode_cursor(
        dataset="cwa_forecasts",
        filters=filters,
        key={
            "valid_from": "2026-08-01T12:00:00+08:00",
            "issued_at": "2026-08-01T00:00:00+08:00",
            "source_updated_at": "2026-08-01T00:00:00+08:00",
            "dataset_id": "F-EDGE",
            "geocode": "A",
            "valid_to": "2026-08-01T13:00:00+08:00",
        },
    )
    repo.engine = _UnreachableEngine()

    response = client.get(
        "/data/weather/forecasts", params={**window, "geocode": "B", "cursor": cursor}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Cursor filter mismatch"


@pytest.mark.parametrize("subject", [["nationwide"], {"name": "nationwide"}])
def test_hourly_load_rejects_nonscalar_cursor_key(explorer_client, subject) -> None:
    client, _ = explorer_client
    window = {"start": "2026-08-01T00:00:00+08:00", "end": "2026-08-02T00:00:00+08:00"}
    filters = ExplorerQuery.from_params(HOURLY_LOAD, window).filters
    cursor = encode_cursor(
        dataset="hourly_load",
        filters=filters,
        key={"time": "2026-08-01T12:00:00+08:00", "subject": subject},
    )

    response = client.get("/data/power/load", params={**window, "cursor": cursor})

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid cursor key"


@pytest.mark.parametrize("field", ["issued_at", "source_updated_at"])
@pytest.mark.parametrize("value", ["not-a-date", "NaT"])
def test_invalid_forecast_version_time_returns_validation_error(
    explorer_client, field, value
) -> None:
    client, _ = explorer_client

    response = client.get("/data/weather/forecasts", params={field: value})

    assert response.status_code == 422
    assert field in response.json()["detail"]


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
    assert load_status["kind"] == "populated"
    assert load_status["freshness"] == "fresh"
    assert load_status["latest_source_at"].endswith("+08:00")
    assert load_status["ingestion_age_seconds"] is not None
    assert load_status["source_age_seconds"] is not None
    assert load_status["href"] == "/data/power/load"

    start = rfc3339(latest - timedelta(hours=1))
    end = rfc3339(latest)
    response = client.get(
        "/data/power/load", params={"start": start, "end": end, "subject": "nationwide"}
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {"items", "next_cursor", "has_more"}
    assert body["has_more"] is False
    assert len(body["items"]) == 2
    assert body["items"][0]["datetime"] >= body["items"][1]["datetime"]
    assert body["items"][0]["subject"] == "nationwide"
    assert "load_mw" in body["items"][0]
    assert "raw_payload" not in body["items"][0]
    assert all(item["datetime"].endswith("+08:00") for item in body["items"])


def test_hourly_load_explorer_ignores_legacy_rows_during_database_upgrade(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'upgraded_load.db'}")
    try:
        create_legacy_load_table(engine)
        ensure_timescale_hypertables(engine)
        repo = TimeSeriesRepository(engine=engine, auto_init=False)
        current_hour = _now().replace(minute=0)
        legacy_hour = current_hour - timedelta(hours=1)
        derived_hour = current_hour - timedelta(hours=3)
        _upsert_hours(repo, [derived_hour])
        insert_legacy_load_row(engine, legacy_hour, 99999.0)
        monkeypatch.setattr(settings, "DATA_EXPLORER_ENABLED", True)

        with TestClient(create_app(repository=repo)) as client:
            window = {"start": rfc3339(derived_hour), "end": rfc3339(current_hour)}
            page = client.get("/data/power/load", params=window)
            status = client.get("/data/status")

        assert page.status_code == 200
        assert [item["datetime"] for item in page.json()["items"]] == [rfc3339(derived_hour)]
        assert rfc3339(legacy_hour) in page.json()["missing_slots"]
        assert rfc3339(current_hour) not in page.json()["missing_slots"]
        load_status = next(
            item for item in status.json()["datasets"] if item["id"] == "hourly_load"
        )
        assert load_status["latest_source_at"] == rfc3339(derived_hour)
        assert load_status["freshness"] == "warning"
    finally:
        engine.dispose()


def test_hourly_load_empty_invalid_window_and_cursor(explorer_client) -> None:
    """無資料為 200 空列表；超時窗為 422；不相容 cursor 為 400。"""
    client, repo = explorer_client
    latest = _now().replace(minute=0)
    _upsert_hours(repo, [latest])

    empty = client.get(
        "/data/power/load",
        params={
            "start": rfc3339(latest - timedelta(hours=5)),
            "end": rfc3339(latest - timedelta(hours=4)),
            "subject": "north",
        },
    )
    assert empty.status_code == 200
    assert empty.json()["items"] == []

    too_long = client.get(
        "/data/power/load",
        params={"start": rfc3339(latest - timedelta(days=32)), "end": rfc3339(latest)},
    )
    assert too_long.status_code == 422

    invalid_time = client.get("/data/power/load", params={"start": "not-a-time"})
    assert invalid_time.status_code == 422

    _upsert_hours(repo, [latest - timedelta(hours=1), latest])
    first_page = client.get(
        "/data/power/load",
        params={
            "start": rfc3339(latest - timedelta(hours=1)),
            "end": rfc3339(latest),
            "limit": 1,
        },
    )
    cursor = first_page.json()["next_cursor"]
    assert cursor
    mismatched = client.get(
        "/data/power/load",
        params={
            "start": rfc3339(latest - timedelta(hours=1)),
            "end": rfc3339(latest),
            "subject": "south",
            "cursor": cursor,
        },
    )
    assert mismatched.status_code == 400
    assert client.get("/data/power/load", params={"cursor": "not-a-cursor"}).status_code == 400
    invalid_window_cursor = encode_cursor(
        dataset="hourly_load",
        filters={"start": "not-a-time", "end": rfc3339(latest), "dataset": "hourly_load"},
        key={"time": rfc3339(latest), "subject": "nationwide"},
    )
    assert (
        client.get("/data/power/load", params={"cursor": invalid_window_cursor}).status_code == 400
    )

    missing_key = _replace_cursor_key(cursor, {})
    malformed = client.get(
        "/data/power/load",
        params={
            "start": rfc3339(latest - timedelta(hours=1)),
            "end": rfc3339(latest),
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

    start = rfc3339(latest - timedelta(hours=2))
    end = rfc3339(latest)
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
            "start": rfc3339(gap_start),
            "end": rfc3339(gap_start + timedelta(hours=2)),
        },
    )
    assert rfc3339(gap_start + timedelta(hours=1)) in gapped_page.json()["missing_slots"]


def test_default_window_cursor_stays_valid_after_clock_advances(
    explorer_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, repo = explorer_client
    latest = _now().replace(minute=0)
    _upsert_hours(repo, [latest - timedelta(hours=1), latest])
    clock = latest + timedelta(minutes=1)
    monkeypatch.setattr("shiro_mlops.service.data_explorer.query.now_taiwan", lambda: clock)
    first = client.get("/data/power/load", params={"limit": 1})
    assert first.status_code == 200
    assert first.json()["next_cursor"]

    monkeypatch.setattr(
        "shiro_mlops.service.data_explorer.query.now_taiwan",
        lambda: clock + timedelta(seconds=1),
    )
    second = client.get(
        "/data/power/load", params={"limit": 1, "cursor": first.json()["next_cursor"]}
    )

    assert second.status_code == 200
    assert second.json()["items"][0]["datetime"] == rfc3339(latest - timedelta(hours=1))


def test_status_returns_503_when_database_unavailable(explorer_client) -> None:
    """TimescaleDB 無法連線時必須回傳 HTTP 503。"""
    client, repo = explorer_client

    repo.engine = _UnreachableEngine()
    assert client.get("/data/status").status_code == 503
    assert client.get("/data/power/load").status_code == 503
    assert client.get("/data/weather/forecasts").status_code == 503


def test_national_supply_demand_uses_mw_and_preserves_nullable_fields(explorer_client) -> None:
    """全台供需以 MW 為主顯示，並保留契約允許的空值與萬瓩欄位。"""
    client, repo = explorer_client
    observed = _now().replace(minute=30, second=0, microsecond=0)
    snapshot = supply_demand_snapshot(observed)
    earlier_snapshot = supply_demand_snapshot(observed - timedelta(minutes=20))
    repo.supply_demand_store.upsert(earlier_snapshot)
    repo.supply_demand_store.upsert(snapshot)

    body = client.get(
        "/data/power/supply-demand",
        params={"start": rfc3339(observed - timedelta(hours=1)), "end": rfc3339(observed)},
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
    assert status["kind"] == "populated"
    assert status["completeness"] == "incomplete"
    assert len(status["missing_identifiers"]) == 1


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
    repo.regional_supply_demand_store.upsert(rows)

    params = {"start": rfc3339(complete_slot), "end": rfc3339(observed), "limit": 50}
    page = client.get("/data/power/regional", params=params).json()
    north_current = next(
        item
        for item in page["items"]
        if item["region"] == "北部" and item["observed_at"] == rfc3339(observed)
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


def test_regional_missing_slots_list_zero_region_slots_on_every_page(
    test_repo: TimeSeriesRepository,
) -> None:
    """四區全缺的時段也是缺口；缺口以整個窗口計算，第 1 頁與第 2 頁相同。"""
    assert_regional_gaps_list_zero_region_slots_on_every_page(test_repo)


def test_missing_slots_exclude_slots_after_now(explorer_client, monkeypatch) -> None:
    """窗口延伸到未來時，尚未發生的時段不是缺口。"""
    client, _ = explorer_client
    monkeypatch.setattr(
        "shiro_mlops.service.data_explorer.dataset_query.now_taiwan",
        lambda: datetime(2026, 9, 6, 8, 25),
    )
    window = {"start": "2026-09-06T08:00:00+08:00", "end": "2026-09-06T09:00:00+08:00"}
    elapsed_ten_minute_slots = [
        "2026-09-06T08:00:00+08:00",
        "2026-09-06T08:10:00+08:00",
        "2026-09-06T08:20:00+08:00",
    ]

    national = client.get("/data/power/supply-demand", params=window).json()
    regional = client.get("/data/power/regional", params=window).json()
    observations = client.get(
        "/data/weather/observations", params={**window, "station_id": "466920"}
    ).json()

    assert national["missing_slots"] == elapsed_ten_minute_slots
    assert regional["missing_slots"] == elapsed_ten_minute_slots
    assert observations["missing_slots"] == ["2026-09-06T08:00:00+08:00:466920"]


def test_unit_generation_preserves_zero_and_nullable_fields(explorer_client) -> None:
    """機組零發電必須保留，契約允許空值不得被當成缺失，且不以固定數量判定不完整。"""
    client, repo = explorer_client
    observed = _now().replace(minute=10, second=0, microsecond=0)
    repo.unit_generation_store.upsert(unit_generation_batch(observed))

    page = client.get(
        "/data/power/units",
        params={"start": rfc3339(observed - timedelta(hours=1)), "end": rfc3339(observed)},
    ).json()
    names = {item["unit_name"]: item for item in page["items"]}
    assert names["大潭CC#3"]["net_generation_mw"] == 0.0
    assert names["大潭CC#3"]["remark"] == "歲修"
    assert names["離島其它(註4)"]["net_generation_mw"] is None
    assert "raw_payload" not in page["items"][0]
    filtered = client.get(
        "/data/power/units",
        params={
            "start": rfc3339(observed - timedelta(hours=1)),
            "end": rfc3339(observed),
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


_POWER_LIST_PATHS = (
    "/data/power/supply-demand",
    "/data/power/regional",
    "/data/power/units",
)


def test_power_endpoints_empty_and_invalid_queries(explorer_client) -> None:
    """電力列表無資料為 200；超時窗與非法篩選為 422；壞 cursor 為 400。"""
    client, _ = explorer_client
    observed = _now().replace(minute=30, second=0, microsecond=0)
    empty_window = {
        "start": rfc3339(observed - timedelta(hours=5)),
        "end": rfc3339(observed - timedelta(hours=4)),
    }
    too_long = {
        "start": rfc3339(observed - timedelta(days=8)),
        "end": rfc3339(observed),
    }

    for path in _POWER_LIST_PATHS:
        empty = client.get(path, params=empty_window)
        assert empty.status_code == 200
        assert empty.json()["items"] == []
        assert client.get(path, params=too_long).status_code == 422
        assert (
            client.get(path, params={**empty_window, "cursor": "not-a-cursor"}).status_code == 400
        )

    assert client.get("/data/power/regional", params={"region": "國外"}).status_code == 422
    assert client.get("/data/power/regional", params={"completeness": "bogus"}).status_code == 422


def test_power_endpoints_paginate_newest_first(explorer_client) -> None:
    """全台、區域與機組 cursor 分頁必須先回較新的 observed_at。"""
    client, repo = explorer_client
    newer = _now().replace(minute=30, second=0, microsecond=0)
    older = newer - timedelta(minutes=10)
    start = rfc3339(older)
    end = rfc3339(newer)
    newer_at = rfc3339(newer)
    older_at = rfc3339(older)

    repo.supply_demand_store.upsert(supply_demand_snapshot(older))
    repo.supply_demand_store.upsert(supply_demand_snapshot(newer))
    repo.regional_supply_demand_store.upsert(regional_supply_demand_snapshots(older))
    repo.regional_supply_demand_store.upsert(regional_supply_demand_snapshots(newer))
    repo.unit_generation_store.upsert(unit_generation_batch(older))
    repo.unit_generation_store.upsert(unit_generation_batch(newer))

    pages = (
        ("/data/power/supply-demand", 1),
        ("/data/power/regional", 4),
        ("/data/power/units", 4),
    )
    for path, limit in pages:
        first = client.get(path, params={"start": start, "end": end, "limit": limit})
        assert first.status_code == 200
        assert first.json()["has_more"] is True
        assert {item["observed_at"] for item in first.json()["items"]} == {newer_at}
        second = client.get(
            path,
            params={
                "start": start,
                "end": end,
                "limit": limit,
                "cursor": first.json()["next_cursor"],
            },
        )
        assert second.status_code == 200
        assert {item["observed_at"] for item in second.json()["items"]} == {older_at}


def test_regional_completeness_filter_reaches_older_matching_slots(explorer_client) -> None:
    """完整度篩選必須在分頁截斷前生效，較舊的符合 slot 仍需可達。"""
    client, repo = explorer_client
    newest = _now().replace(minute=30, second=0, microsecond=0)
    middle = newest - timedelta(minutes=10)
    oldest = newest - timedelta(minutes=20)
    repo.regional_supply_demand_store.upsert(regional_supply_demand_snapshots(newest))
    repo.regional_supply_demand_store.upsert(regional_supply_demand_snapshots(middle))
    repo.regional_supply_demand_store.upsert(regional_supply_demand_snapshots(oldest)[:1])

    response = client.get(
        "/data/power/regional",
        params={
            "start": rfc3339(oldest),
            "end": rfc3339(newest),
            "limit": 1,
            "completeness": "incomplete",
        },
    )

    assert response.status_code == 200
    assert [item["observed_at"] for item in response.json()["items"]] == [rfc3339(oldest)]


def test_cwa_observations_and_audits_exclude_raw_payload(explorer_client) -> None:
    """測站觀測與 audit 必須支援 station/status 篩選，且不得回傳 raw payload。"""
    from shiro_mlops.data.cwa_client import CWAObservationBatch, CWAStationObservation

    client, repo = explorer_client
    observed = _now().replace(minute=0)
    repo.cwa_weather_store.upsert_cwa_observation_batch(
        CWAObservationBatch(
            fetched_at=observed,
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
            "start": rfc3339(observed - timedelta(hours=1)),
            "end": rfc3339(observed),
            "station_id": "466920",
        },
    ).json()
    assert observations["items"][0]["temperature_c"] is None
    assert observations["items"][0]["precipitation_mm"] == 0.0
    assert "raw_payload" not in observations["items"][0]
    audits = client.get(
        "/data/audits/cwa-observations",
        params={
            "start": rfc3339(observed - timedelta(hours=1)),
            "end": rfc3339(observed),
            "status": "incomplete",
            "missing_station_id": "467490",
        },
    ).json()
    assert audits["items"][0]["missing_station_ids"] == ["467490"]
    assert "raw_payload" not in audits["items"][0]
    empty_history = client.get(
        "/data/audits/cwa-observations",
        params={
            "start": rfc3339(observed - timedelta(days=10)),
            "end": rfc3339(observed - timedelta(days=9)),
        },
    )
    assert empty_history.status_code == 200
    assert empty_history.json()["items"] == []


def test_cwa_forecasts_default_to_latest_vintage_and_keep_all_vintages(explorer_client) -> None:
    """未指定版本時預設最新發布；明確條件可取得全部 vintages，且分開 serving stale。"""
    client, repo = explorer_client
    older = _now().replace(minute=0) - timedelta(hours=2)
    newer = older + timedelta(hours=1)
    valid = newer + timedelta(hours=3)

    def release(issued_at: datetime, temperature: float):
        return forecast_release(
            issued_at,
            (township_forecast(valid, temperature, relative_humidity_pct=70.0),),
            raw_payload={"secret": "do-not-return"},
        )

    repo.cwa_weather_store.upsert_cwa_forecast_releases([release(older, 28.0)])
    repo.cwa_weather_store.upsert_cwa_forecast_releases([release(newer, 31.0)])
    latest_page = client.get(
        "/data/weather/forecasts",
        params={"start": rfc3339(valid - timedelta(hours=1)), "end": rfc3339(valid)},
    ).json()
    assert len(latest_page["items"]) == 1
    assert latest_page["items"][0]["temperature_c"] == 31.0
    assert latest_page["items"][0]["issued_at"] == rfc3339(newer)
    assert latest_page["items"][0]["location_name"] == "臺北"
    assert "raw_payload" not in latest_page["items"][0]
    all_vintages = client.get(
        "/data/weather/forecasts",
        params={
            "start": rfc3339(valid - timedelta(hours=1)),
            "end": rfc3339(valid),
            "all_vintages": "true",
        },
    ).json()
    assert len(all_vintages["items"]) == 2
    older_vintage = client.get(
        "/data/weather/forecasts",
        params={
            "start": rfc3339(valid - timedelta(hours=1)),
            "end": rfc3339(valid),
            "source_updated_at": rfc3339(older),
        },
    ).json()
    assert [item["temperature_c"] for item in older_vintage["items"]] == [28.0]
    issued_vintage = client.get(
        "/data/weather/forecasts",
        params={
            "start": rfc3339(valid - timedelta(hours=1)),
            "end": rfc3339(valid),
            "issued_at": rfc3339(older),
        },
    ).json()
    assert [item["temperature_c"] for item in issued_vintage["items"]] == [28.0]
    audits = client.get(
        "/data/audits/cwa-forecasts",
        params={"start": rfc3339(older - timedelta(hours=1)), "end": rfc3339(newer)},
    ).json()
    assert {item["issued_at"] for item in audits["items"]} == {rfc3339(older), rfc3339(newer)}
    assert "raw_payload" not in audits["items"][0]
    status = next(
        item
        for item in client.get("/data/status").json()["datasets"]
        if item["id"] == "cwa_forecasts"
    )
    assert status["latest_release_stale"] is False
    assert status["freshness"] in {"fresh", "warning"}


def test_latest_forecast_cursor_stays_on_original_vintage(explorer_client) -> None:
    """分頁期間新增 release 時，既有 cursor 必須繼續讀取原本解析出的最新版本。"""
    client, repo = explorer_client
    issued_at = _now().replace(minute=0) - timedelta(hours=2)
    valid_from = issued_at + timedelta(hours=3)

    def release(issued: datetime, temperatures: tuple[float, ...]):
        return forecast_release(
            issued,
            tuple(
                township_forecast(
                    valid_from + timedelta(hours=index),
                    temperature,
                    valid_to=valid_from + timedelta(hours=index + 1),
                )
                for index, temperature in enumerate(temperatures)
            ),
        )

    repo.cwa_weather_store.upsert_cwa_forecast_releases([release(issued_at, (28.0, 29.0))])
    params = {
        "start": rfc3339(valid_from),
        "end": rfc3339(valid_from + timedelta(hours=1)),
        "limit": 1,
    }
    first = client.get("/data/weather/forecasts", params=params)
    assert first.status_code == 200
    assert first.json()["has_more"] is True

    repo.cwa_weather_store.upsert_cwa_forecast_releases(
        [release(issued_at + timedelta(hours=1), (31.0,))]
    )
    second = client.get(
        "/data/weather/forecasts",
        params={**params, "cursor": first.json()["next_cursor"]},
    )

    assert second.status_code == 200
    assert second.json()["items"][0]["issued_at"] == rfc3339(issued_at)


def test_forecast_cursor_distinguishes_rows_by_valid_to(explorer_client) -> None:
    """只有 valid_to 不同的預報列也必須能跨頁完整讀取。"""
    client, repo = explorer_client
    issued_at = _now().replace(minute=0) - timedelta(hours=1)
    valid_from = issued_at + timedelta(hours=2)
    release = forecast_release(
        issued_at,
        tuple(
            township_forecast(
                valid_from,
                temperature,
                valid_to=valid_from + timedelta(hours=hours),
            )
            for hours, temperature in ((1, 28.0), (2, 31.0))
        ),
    )
    repo.cwa_weather_store.upsert_cwa_forecast_releases([release])
    params = {
        "start": rfc3339(valid_from),
        "end": rfc3339(valid_from),
        "limit": 1,
    }

    first = client.get("/data/weather/forecasts", params=params)
    second = client.get(
        "/data/weather/forecasts",
        params={**params, "cursor": first.json()["next_cursor"]},
    )

    assert first.status_code == 200
    assert first.json()["has_more"] is True
    assert [item["temperature_c"] for item in first.json()["items"]] == [31.0]
    assert second.status_code == 200
    assert [item["temperature_c"] for item in second.json()["items"]] == [28.0]


@pytest.mark.parametrize("path", ["/data/audits/cwa-observations", "/data/audits/cwa-forecasts"])
def test_audit_status_filter_accepts_only_ingestion_completeness(explorer_client, path) -> None:
    """審計 status 篩選只接受 complete 與 incomplete，其他值回 422。"""
    client, _ = explorer_client
    observed = _now().replace(minute=0)
    window = {"start": rfc3339(observed - timedelta(hours=1)), "end": rfc3339(observed)}

    statuses = {
        value: client.get(path, params={**window, "status": value}).status_code
        for value in ("complete", "incomplete", "partial", "failed")
    }

    assert statuses == {"complete": 200, "incomplete": 200, "partial": 422, "failed": 422}


# --- malformed and hostile request values ---------------------------------------------------

SERIES_PATHS = [f"{path}/series" for path in LIST_PATHS]


@pytest.mark.parametrize("path", [*LIST_PATHS, *SERIES_PATHS])
def test_an_unencoded_plus_in_the_offset_is_refused_instead_of_read_as_another_window(
    explorer_client, path: str
) -> None:
    """`+08:00` sent without URL-encoding arrives as ` 08:00`; guessing it queried 08:00–08:00."""
    client, repo = explorer_client
    repo.engine = _UnreachableEngine()

    response = client.get(f"{path}?start=2026-11-20T00:00:00+08:00&end=2026-11-20T12:00:00+08:00")

    assert response.status_code == 422
    assert response.json()["detail"] == "start and end must be valid RFC 3339 timestamps"


@pytest.mark.parametrize("path", [*LIST_PATHS, *SERIES_PATHS])
@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("0001-01-01T00:00:00", "0001-01-02T00:00:00"),
        ("1500-01-01T00:00:00", "1500-01-02T00:00:00"),
        ("1677-09-21T00:00:00", "1677-09-22T00:00:00"),
        ("3000-01-01T00:00:00", "3000-01-02T00:00:00"),
        ("9999-12-30T00:00:00", "9999-12-31T23:59:59"),
        ("now", "today"),
        ("2026-11-20", "2026-11-21"),
    ],
    ids=[
        "year-1",
        "year-1500",
        "before-nanosecond-range",
        "year-3000",
        "year-9999",
        "words",
        "dates",
    ],
)
def test_windows_no_dataset_can_hold_are_refused_on_every_endpoint(
    explorer_client, path: str, start: str, end: str
) -> None:
    client, _ = explorer_client

    response = client.get(path, params={"start": start, "end": end})

    assert response.status_code == 422
    assert response.json()["detail"] == "start and end must be valid RFC 3339 timestamps"


@pytest.mark.parametrize(
    ("path", "parameter"),
    [
        ("/data/power/load", "subject"),
        ("/data/power/load/series", "subject"),
        ("/data/weather/forecasts", "geocode"),
        ("/data/weather/forecasts", "dataset_id"),
        ("/data/weather/observations", "station_id"),
        ("/data/audits/cwa-observations", "missing_station_id"),
        ("/data/power/load", "cursor"),
        ("/data/power/load", "start"),
    ],
)
def test_a_nul_byte_in_any_parameter_is_refused_before_database_access(
    explorer_client, path: str, parameter: str
) -> None:
    client, repo = explorer_client
    repo.engine = _UnreachableEngine()

    response = client.get(path, params={parameter: "a\x00b"})

    assert response.status_code == 422
    assert response.json()["detail"] == f"{parameter} must not contain control characters"


def test_a_cursor_key_with_a_nul_byte_is_an_invalid_cursor(explorer_client) -> None:
    client, repo = explorer_client
    now = _now().replace(minute=0)
    _upsert_hours(repo, [now - timedelta(hours=offset) for offset in range(3)])
    window = {"start": rfc3339(now - timedelta(hours=3)), "end": rfc3339(now), "limit": 1}
    cursor = client.get("/data/power/load", params=window).json()["next_cursor"]

    tampered = _replace_cursor_key(cursor, {"time": rfc3339(now), "subject": "nation\x00wide"})
    response = client.get("/data/power/load", params={**window, "cursor": tampered})

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid cursor key"


@pytest.mark.parametrize("path", LIST_PATHS)
def test_deeply_nested_cursor_is_a_bad_request_on_every_list(explorer_client, path: str) -> None:
    client, repo = explorer_client
    repo.engine = _UnreachableEngine()
    nested = urlsafe_b64encode(b"[" * 3000).decode().rstrip("=")
    oversized = urlsafe_b64encode(b"[" * 12000).decode().rstrip("=")

    for cursor in (nested, oversized):
        response = client.get(path, params={"cursor": cursor})

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid cursor"


def _incomplete_observation_batch(repo: TimeSeriesRepository, observed: datetime) -> None:
    from shiro_mlops.data.cwa_client import CWAObservationBatch

    repo.cwa_weather_store.upsert_cwa_observation_batch(
        CWAObservationBatch(
            fetched_at=observed,
            missing_station_ids=("467490",),
            raw_payload={},
            observations=(),
        )
    )


@pytest.mark.parametrize(
    ("missing_station_id", "matches"),
    [
        ("467490", True),
        ("%", False),
        ("4674_0", False),
        ("46749%", False),
        ("_67490", False),
        ("\\", False),
        ("467490\\", False),
    ],
)
def test_missing_member_filter_matches_the_identifier_literally(
    explorer_client, missing_station_id: str, matches: bool
) -> None:
    """`%` and `_` are LIKE wildcards; unescaped they listed batches missing other stations."""
    client, repo = explorer_client
    observed = _now().replace(minute=0)
    _incomplete_observation_batch(repo, observed)

    response = client.get(
        "/data/audits/cwa-observations",
        params={
            "start": rfc3339(observed - timedelta(hours=1)),
            "end": rfc3339(observed),
            "missing_station_id": missing_station_id,
        },
    )

    assert response.status_code == 200
    assert bool(response.json()["items"]) is matches


def test_the_load_list_reads_an_empty_limit_as_not_given_like_every_other_list(
    explorer_client,
) -> None:
    client, repo = explorer_client
    hour = _now().replace(minute=0) - timedelta(hours=2)
    _upsert_hours(repo, [hour])
    window = {"start": rfc3339(hour - timedelta(hours=1)), "end": rfc3339(hour)}

    responses = [
        client.get(path, params={**window, "limit": ""})
        for path in ("/data/power/load", "/data/power/supply-demand")
    ]

    assert [response.status_code for response in responses] == [200, 200]
    assert (
        responses[0].json()["items"]
        == client.get("/data/power/load", params=window).json()["items"]
    )


@pytest.mark.parametrize("flag", ["true", "TRUE", "1", "yes", "on", "y", "t"])
def test_every_spelling_the_series_accepts_as_true_lists_every_vintage(
    explorer_client, flag: str
) -> None:
    """The series validates the flag as a boolean, so the list must read the same words as true."""
    client, repo = explorer_client
    issued = _now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
    repo.cwa_weather_store.upsert_cwa_forecast_releases(
        [
            forecast_release(
                issued - timedelta(hours=offset),
                (township_forecast(issued + timedelta(hours=1), 28.0 + offset),),
            )
            for offset in (0, 6)
        ]
    )
    window = {"start": rfc3339(issued), "end": rfc3339(issued + timedelta(hours=2))}

    listed = client.get("/data/weather/forecasts", params={**window, "all_vintages": flag})
    charted = client.get("/data/weather/forecasts/series", params={**window, "all_vintages": flag})

    assert listed.status_code == 200
    assert len({item["issued_at"] for item in listed.json()["items"]}) == 2
    assert charted.status_code == 200
    assert len(charted.json()["series"]) == 2


def test_a_regional_page_reads_its_window_present_regions_once(explorer_client) -> None:
    """The page's missing regions and the window's missing slots come from one read."""
    from sqlalchemy import event

    client, repo = explorer_client
    distinct_reads: list[str] = []

    def count(conn, cursor, statement, *_args) -> None:
        if statement.lstrip().startswith("SELECT DISTINCT"):
            distinct_reads.append(statement)

    end = _now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    repo.regional_supply_demand_store.upsert(
        regional_supply_demand_snapshots(end - timedelta(minutes=30))
    )
    event.listen(repo.engine, "before_cursor_execute", count)
    try:
        response = client.get(
            "/data/power/regional",
            params={"start": rfc3339(end - timedelta(hours=2)), "end": rfc3339(end)},
        )
    finally:
        event.remove(repo.engine, "before_cursor_execute", count)

    assert response.status_code == 200
    assert response.json()["items"]
    assert len(distinct_reads) == 1
