"""Unit tests for supply-demand snapshot repository persistence."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from shiro_mlops.data.repository import (
    TimeSeriesRepository,
    _deserialize_raw_payload,
    _serialize_raw_payload,
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


def test_raw_payload_serialization_and_deserialization_helpers() -> None:
    """Helper 函式應正確轉換 dict 為 JSON 字串，並在反序列化時正確還原。"""
    sample_dict = {"records": [{"load": 123.4}], "success": "true"}
    serialized = _serialize_raw_payload(sample_dict)
    assert isinstance(serialized, str)
    assert json.loads(serialized) == sample_dict

    # 傳入已為字串時不應被重複跳脫
    assert _serialize_raw_payload(serialized) == serialized

    # 反序列化
    deserialized = _deserialize_raw_payload(serialized)
    assert deserialized == sample_dict
    assert _deserialize_raw_payload(sample_dict) == sample_dict
