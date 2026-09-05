"""Unit tests for Taipower power supply-demand snapshot parsing and slotting."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from shiro_mlops.data.taipower_supply_demand import (
    SupplyDemandParseError,
    floor_to_ten_minutes,
    parse_roc_datetime,
    parse_supply_demand_payload,
    resolve_manual_observed_at,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def test_parse_roc_datetime_with_weekday_and_time() -> None:
    """民國曆發布時間應解析為台灣本地 naive datetime。"""
    assert parse_roc_datetime("115.09.05(六)17:30") == datetime(2026, 9, 5, 17, 30)


def test_parse_roc_date_only() -> None:
    """僅日期的民國曆字串應解析為當日 00:00。"""
    assert parse_roc_datetime("115.09.04") == datetime(2026, 9, 4, 0, 0)


def test_floor_to_ten_minutes() -> None:
    """手動 materialize 的觀測時間應向下取整至 10 分鐘 slot。"""
    assert floor_to_ten_minutes(datetime(2026, 9, 5, 17, 37, 42)) == datetime(2026, 9, 5, 17, 30, 0)


def test_resolve_manual_observed_at_floors_provided_now() -> None:
    """手動觀測 slot 應對提供的時間向下取整。"""
    assert resolve_manual_observed_at(datetime(2026, 9, 5, 17, 37, 42)) == datetime(
        2026, 9, 5, 17, 30, 0
    )


def test_parse_supply_demand_payload_keeps_wan_kw_and_source_publish_time() -> None:
    """完整成功回應應產出 typed 萬瓩欄位、來源發布時間與原始 payload。"""
    with open(FIXTURES_DIR / "taipower_supply_demand_sample.json", encoding="utf-8") as f:
        payload = json.load(f)

    snapshot = parse_supply_demand_payload(
        payload,
        observed_at=datetime(2026, 9, 5, 17, 30),
    )

    assert snapshot.observed_at == datetime(2026, 9, 5, 17, 30)
    assert snapshot.curr_load_wan_kw == pytest.approx(3242.1)
    assert snapshot.curr_util_rate_pct == pytest.approx(78.0)
    assert snapshot.source_publish_time == datetime(2026, 9, 5, 17, 30)
    assert snapshot.fore_maxi_sply_capacity_wan_kw == pytest.approx(4537.5)
    assert snapshot.fore_peak_dema_load_wan_kw == pytest.approx(3349.9)
    assert snapshot.fore_peak_resv_capacity_wan_kw == pytest.approx(1187.6)
    assert snapshot.fore_peak_resv_rate_pct == pytest.approx(35.45)
    assert snapshot.fore_peak_resv_indicator == "G"
    assert snapshot.fore_peak_hour_range == "13:00-16:00"
    assert snapshot.yday_date == datetime(2026, 9, 4).date()
    assert snapshot.yday_maxi_sply_capacity_wan_kw == pytest.approx(4648.0)
    assert snapshot.yday_peak_dema_load_wan_kw == pytest.approx(3722.1)
    assert snapshot.yday_peak_resv_capacity_wan_kw == pytest.approx(925.8)
    assert snapshot.yday_peak_resv_rate_pct == pytest.approx(24.87)
    assert snapshot.yday_peak_resv_indicator == "G"
    assert snapshot.real_hr_maxi_sply_capacity_wan_kw == pytest.approx(4125.6)
    assert snapshot.real_hr_peak_time == datetime(2026, 9, 5, 16, 47)
    assert snapshot.raw_payload == payload


def test_parse_supply_demand_payload_allows_missing_optional_groups() -> None:
    """預估、昨日與實績資料組缺少時對應欄位為空值，仍可解析。"""
    payload = {
        "success": "true",
        "records": [{"curr_load": "3000", "curr_util_rate": "70"}],
    }

    snapshot = parse_supply_demand_payload(
        payload,
        observed_at=datetime(2026, 9, 5, 17, 30),
    )

    assert snapshot.curr_load_wan_kw == pytest.approx(3000.0)
    assert snapshot.curr_util_rate_pct == pytest.approx(70.0)
    assert snapshot.source_publish_time is None
    assert snapshot.fore_maxi_sply_capacity_wan_kw is None
    assert snapshot.yday_date is None
    assert snapshot.real_hr_maxi_sply_capacity_wan_kw is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fore_maxi_sply_capacity", "not-a-number"),
        ("publish_time", "bad-time"),
        ("publish_time", "115.13.01"),
        ("yday_date", "???"),
        ("real_hr_peak_time", "also-bad"),
        ("real_hr_peak_time", "2026.02.30 16:47"),
    ],
)
def test_parse_supply_demand_payload_rejects_invalid_optional_fields(
    field: str, value: str
) -> None:
    """非空的可選欄位無法解析時應明確拒絕快照。"""
    payload = {
        "records": [
            {"curr_load": "3000", "curr_util_rate": "70"},
            {field: value},
        ]
    }

    with pytest.raises(SupplyDemandParseError, match=field):
        parse_supply_demand_payload(
            payload,
            observed_at=datetime(2026, 9, 5, 17, 30),
        )


def test_parse_supply_demand_payload_rejects_missing_required_fields() -> None:
    """缺少目前用電量或使用率時必須失敗。"""
    payload = {"records": [{"curr_load": "3000"}]}

    with pytest.raises(SupplyDemandParseError, match="curr_util_rate"):
        parse_supply_demand_payload(payload, observed_at=datetime(2026, 9, 5, 17, 30))
