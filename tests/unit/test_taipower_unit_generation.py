"""Unit tests for Taipower unit net-generation snapshot parsing."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from shiro_mlops.data.taipower_unit_generation import (
    UnitGenerationParseError,
    parse_unit_generation_payload,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def test_parse_unit_generation_payload_keeps_mw_zero_and_remarks() -> None:
    """完整機組 JSON 應保存 MW、零發電、停機備註與來源時間。"""
    with open(FIXTURES_DIR / "taipower_unit_generation_sample.json", encoding="utf-8") as f:
        payload = json.load(f)

    snapshots = parse_unit_generation_payload(payload, observed_at=datetime(2026, 9, 5, 17, 30))

    assert len(snapshots) == 4
    assert snapshots[0].unit_name == "大潭CC#1"
    assert snapshots[0].unit_type == "燃氣"
    assert snapshots[0].capacity_mw == pytest.approx(742.7)
    assert snapshots[0].net_generation_mw == pytest.approx(670.4)
    assert snapshots[0].capacity_ratio_pct == pytest.approx(90.265)
    assert snapshots[0].remark is None
    assert snapshots[0].source_time == datetime(2026, 9, 5, 17, 30)
    assert snapshots[0].raw_payload["DateTime"] == "2026-09-05T17:30:00"

    offline = snapshots[1]
    assert offline.unit_name == "大潭CC#3"
    assert offline.net_generation_mw == pytest.approx(0.0)
    assert offline.remark == "歲修"

    unavailable = snapshots[2]
    assert unavailable.net_generation_mw is None
    assert unavailable.capacity_ratio_pct is None

    storage_load = snapshots[3]
    assert storage_load.unit_type == "儲能負載(Energy Storage System Load)"
    assert storage_load.unit_name == "大觀二#1"


def test_parse_unit_generation_payload_skips_rows_missing_identity() -> None:
    """缺少機組類型或名稱的列應略過。"""
    payload = {
        "DateTime": "2026-09-05T17:30:00",
        "aaData": [
            {
                "機組類型": "",
                "機組名稱": "無名機組",
                "裝置容量(MW)": "10",
                "淨發電量(MW)": "1",
                "淨發電量/裝置容量比(%)": "10%",
                "備註": "",
            },
            {
                "機組類型": "燃氣",
                "機組名稱": "",
                "裝置容量(MW)": "10",
                "淨發電量(MW)": "1",
                "淨發電量/裝置容量比(%)": "10%",
                "備註": "",
            },
            {
                "機組類型": "燃氣",
                "機組名稱": "有效機組",
                "裝置容量(MW)": "-",
                "淨發電量(MW)": "5.0",
                "淨發電量/裝置容量比(%)": "-",
                "備註": "新機組試俥",
            },
        ],
    }

    snapshots = parse_unit_generation_payload(payload, observed_at=datetime(2026, 9, 5, 17, 30))

    assert len(snapshots) == 1
    assert snapshots[0].unit_name == "有效機組"
    assert snapshots[0].capacity_mw is None
    assert snapshots[0].capacity_ratio_pct is None
    assert snapshots[0].remark == "新機組試俥"


def test_parse_unit_generation_payload_rejects_empty_valid_rows() -> None:
    """成功回應中無任何有效機組列時必須失敗。"""
    payload = {"DateTime": "2026-09-05T17:30:00", "aaData": []}

    with pytest.raises(UnitGenerationParseError, match="No valid unit rows"):
        parse_unit_generation_payload(payload, observed_at=datetime(2026, 9, 5, 17, 30))
