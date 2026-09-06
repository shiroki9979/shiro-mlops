"""Unit tests for supply-demand snapshot repository persistence."""

import json
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine

from shiro_mlops.data.repository import (
    TaipowerSupplyDemandRepository,
    TimeSeriesRepository,
)
from shiro_mlops.data.taipower_supply_demand import parse_supply_demand_payload

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _sample_snapshot(observed_at: datetime | None = None):
    with open(FIXTURES_DIR / "taipower_supply_demand_sample.json", encoding="utf-8") as f:
        payload = json.load(f)
    return parse_supply_demand_payload(
        payload,
        observed_at=observed_at or datetime(2026, 9, 5, 17, 30),
    )


def test_upsert_supply_demand_snapshot_insert_and_fetch(
    test_repo: TimeSeriesRepository,
) -> None:
    """成功快照應可依 observed_at 寫入並讀回 typed 欄位與 raw payload。"""
    snapshot = _sample_snapshot()
    assert test_repo.upsert_supply_demand_snapshot(snapshot) == 1

    fetched = test_repo.fetch_supply_demand_snapshot(snapshot.observed_at)
    assert fetched is not None
    assert fetched.observed_at == snapshot.observed_at
    assert fetched.curr_load_wan_kw == pytest.approx(3242.1)
    assert fetched.curr_util_rate_pct == pytest.approx(78.0)
    assert fetched.source_publish_time == datetime(2026, 9, 5, 17, 30)
    assert fetched.fore_peak_resv_indicator == "G"
    assert fetched.yday_date == snapshot.yday_date
    assert fetched.real_hr_peak_time == datetime(2026, 9, 5, 16, 47)
    assert fetched.raw_payload["records"][0]["curr_load"] == "3242.1"


def test_upsert_supply_demand_snapshot_is_idempotent_on_observed_at(
    test_repo: TimeSeriesRepository,
) -> None:
    """相同觀測 slot 重跑時應更新既有快照而非新增列。"""
    first = _sample_snapshot(datetime(2026, 9, 5, 17, 30))
    test_repo.upsert_supply_demand_snapshot(first)

    with open(FIXTURES_DIR / "taipower_supply_demand_sample.json", encoding="utf-8") as f:
        payload = json.load(f)
    payload["records"][0]["curr_load"] = "3300.0"
    payload["records"][0]["curr_util_rate"] = "80"
    revised = parse_supply_demand_payload(payload, observed_at=datetime(2026, 9, 5, 17, 30))
    assert test_repo.upsert_supply_demand_snapshot(revised) == 1

    fetched = test_repo.fetch_supply_demand_snapshot(datetime(2026, 9, 5, 17, 30))
    assert fetched is not None
    assert fetched.curr_load_wan_kw == pytest.approx(3300.0)
    assert fetched.curr_util_rate_pct == pytest.approx(80.0)

    with test_repo.engine.connect() as conn:
        count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM raw_taipower_supply_demand_snapshot"
        ).scalar()
    assert count == 1


def test_fetch_supply_demand_snapshot_rejects_invalid_raw_payload(
    test_repo: TimeSeriesRepository,
) -> None:
    """資料庫中的無效 raw_payload 應明確回報錯誤。"""
    snapshot = _sample_snapshot()
    test_repo.upsert_supply_demand_snapshot(snapshot)

    with test_repo.engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE raw_taipower_supply_demand_snapshot "
            "SET raw_payload = 'not-json' WHERE observed_at = '2026-09-05 09:30:00'"
        )

    with pytest.raises(ValueError, match="raw_payload"):
        test_repo.fetch_supply_demand_snapshot(snapshot.observed_at)


def test_upsert_supply_demand_snapshot_rejects_corrupted_payload_without_writing(
    test_repo: TimeSeriesRepository,
) -> None:
    """來源包含格式損壞的 payload 在解析時應被拒絕，且不寫入任何資料至資料庫。"""
    from shiro_mlops.data.taipower_supply_demand import SupplyDemandParseError

    invalid_payload = {
        "records": [
            {"curr_load": "corrupted", "curr_util_rate": "70"},
        ]
    }
    with pytest.raises(SupplyDemandParseError):
        parse_supply_demand_payload(invalid_payload, observed_at=datetime(2026, 9, 5, 17, 30))

    with test_repo.engine.connect() as conn:
        count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM raw_taipower_supply_demand_snapshot"
        ).scalar()
    assert count == 0


def test_upsert_supply_demand_snapshot_rejects_invalid_snapshot_directly(
    test_repo: TimeSeriesRepository,
) -> None:
    """直接傳入非法 snapshot 至 repository 時應拋出 ValueError。"""
    snapshot = _sample_snapshot()
    object.__setattr__(snapshot, "curr_load_wan_kw", float("nan"))
    with pytest.raises(ValueError, match="curr_load_wan_kw"):
        test_repo.upsert_supply_demand_snapshot(snapshot)


def test_standalone_taipower_supply_demand_repository_lifecycle(
    sqlite_engine: Engine,
) -> None:
    """獨立 TaipowerSupplyDemandRepository 應可獨立初始化、驗證、冪等 upsert 與 fetch。"""
    repo = TaipowerSupplyDemandRepository(engine=sqlite_engine)
    snapshot = _sample_snapshot()

    # 驗證首次寫入與讀取
    assert repo.upsert(snapshot) == 1
    fetched = repo.fetch(snapshot.observed_at)
    assert fetched is not None
    assert fetched.observed_at == snapshot.observed_at
    assert fetched.curr_load_wan_kw == pytest.approx(3242.1)

    # 驗證相同 slot 重跑時冪等更新
    with open(FIXTURES_DIR / "taipower_supply_demand_sample.json", encoding="utf-8") as f:
        payload = json.load(f)
    payload["records"][0]["curr_load"] = "3400.0"
    payload["records"][0]["curr_util_rate"] = "82"
    revised = parse_supply_demand_payload(payload, observed_at=snapshot.observed_at)
    assert repo.upsert(revised) == 1

    updated = repo.fetch(snapshot.observed_at)
    assert updated is not None
    assert updated.curr_load_wan_kw == pytest.approx(3400.0)
    assert updated.curr_util_rate_pct == pytest.approx(82.0)

    # 驗證直接防禦拒絕非法數值
    invalid_snapshot = _sample_snapshot(datetime(2026, 9, 5, 18, 0))
    object.__setattr__(invalid_snapshot, "curr_load_wan_kw", float("nan"))
    with pytest.raises(ValueError, match="curr_load_wan_kw"):
        repo.upsert(invalid_snapshot)
