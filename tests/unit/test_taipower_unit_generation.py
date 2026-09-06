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
    assert snapshots[0].raw_payload == payload
    assert len(snapshots[0].raw_payload["aaData"]) == 4

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
    """缺少機組類型或名稱、或為 null/None/空白/假識別值的列應略過。"""
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
                "機組類型": None,
                "機組名稱": "Null類型機組",
                "裝置容量(MW)": "10",
                "淨發電量(MW)": "1",
            },
            {
                "機組類型": "燃氣",
                "機組名稱": None,
                "裝置容量(MW)": "10",
                "淨發電量(MW)": "1",
            },
            {
                "機組名稱": "完全無類型機組",
                "裝置容量(MW)": "10",
                "淨發電量(MW)": "1",
            },
            {
                "機組類型": "None",
                "機組名稱": "假名機組",
                "裝置容量(MW)": "10",
                "淨發電量(MW)": "1",
            },
            {
                "機組類型": "燃氣",
                "機組名稱": "None",
                "裝置容量(MW)": "10",
                "淨發電量(MW)": "1",
            },
            {
                "機組類型": "<b>  </b>",
                "機組名稱": "HTML空類型機組",
                "裝置容量(MW)": "10",
                "淨發電量(MW)": "1",
            },
            {
                "機組類型": "燃氣",
                "機組名稱": "<b>  </b>",
                "裝置容量(MW)": "10",
                "淨發電量(MW)": "1",
            },
            {
                "機組類型": "燃氣",
                "機組名稱": "  \ufeff  ",
                "裝置容量(MW)": "10",
                "淨發電量(MW)": "1",
            },
            {
                "機組類型": "<b>燃氣</b>",
                "機組名稱": "<b>有效機組</b>",
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
    assert snapshots[0].unit_type == "燃氣"
    assert snapshots[0].capacity_mw is None
    assert snapshots[0].capacity_ratio_pct is None
    assert snapshots[0].remark == "新機組試俥"


def test_parse_unit_generation_payload_preserves_non_empty_remarks() -> None:
    """Only blank remarks are missing; non-empty source text remains observable."""
    payload = {
        "DateTime": "2026-09-05T17:30:00",
        "aaData": [
            {
                "機組類型": "燃氣",
                "機組名稱": "備註破折號機組",
                "裝置容量(MW)": "100.0",
                "淨發電量(MW)": "50.0",
                "淨發電量/裝置容量比(%)": "50%",
                "備註": "-",
            },
            {
                "機組類型": "燃氣",
                "機組名稱": "備註空白機組",
                "裝置容量(MW)": "100.0",
                "淨發電量(MW)": "50.0",
                "淨發電量/裝置容量比(%)": "50%",
                "備註": "   ",
            },
        ],
    }

    snapshots = parse_unit_generation_payload(payload, observed_at=datetime(2026, 9, 5, 17, 30))

    assert snapshots[0].remark == "-"
    assert snapshots[1].remark is None


def test_parse_unit_generation_payload_skips_non_agreed_format_errors() -> None:
    """非約定缺值的來源格式錯誤（如字串損壞、NaN、none/null字串）不應靜默轉為 None，該列應略過並記錄。"""
    payload = {
        "DateTime": "2026-09-05T17:30:00",
        "aaData": [
            {
                "機組類型": "燃氣",
                "機組名稱": "數值損壞機組1",
                "裝置容量(MW)": "not-a-number",
                "淨發電量(MW)": "10.0",
                "淨發電量/裝置容量比(%)": "50%",
            },
            {
                "機組類型": "燃氣",
                "機組名稱": "數值損壞機組2",
                "裝置容量(MW)": "100.0",
                "淨發電量(MW)": "corrupted",
                "淨發電量/裝置容量比(%)": "50%",
            },
            {
                "機組類型": "燃氣",
                "機組名稱": "比率損壞機組3",
                "裝置容量(MW)": "100.0",
                "淨發電量(MW)": "50.0",
                "淨發電量/裝置容量比(%)": "invalid%",
            },
            {
                "機組類型": "燃氣",
                "機組名稱": "重複百分比符號機組",
                "裝置容量(MW)": "100.0",
                "淨發電量(MW)": "50.0",
                "淨發電量/裝置容量比(%)": "50%%",
            },
            {
                "機組類型": "燃氣",
                "機組名稱": "NaN損壞機組4",
                "裝置容量(MW)": "NaN",
                "淨發電量(MW)": "50.0",
                "淨發電量/裝置容量比(%)": "50%",
            },
            {
                "機組類型": "燃氣",
                "機組名稱": "None字串損壞機組5",
                "裝置容量(MW)": "None",
                "淨發電量(MW)": "50.0",
                "淨發電量/裝置容量比(%)": "50%",
            },
            {
                "機組類型": "燃氣",
                "機組名稱": "Null字串損壞機組6",
                "裝置容量(MW)": "100.0",
                "淨發電量(MW)": "null",
                "淨發電量/裝置容量比(%)": "50%",
            },
            {
                "機組類型": "燃氣",
                "機組名稱": "有效機組",
                "裝置容量(MW)": "100.0",
                "淨發電量(MW)": "50.0",
                "淨發電量/裝置容量比(%)": "50%",
            },
        ],
    }

    snapshots = parse_unit_generation_payload(payload, observed_at=datetime(2026, 9, 5, 17, 30))

    assert len(snapshots) == 1
    assert snapshots[0].unit_name == "有效機組"
    assert snapshots[0].capacity_mw == pytest.approx(100.0)
    assert snapshots[0].net_generation_mw == pytest.approx(50.0)
    assert snapshots[0].capacity_ratio_pct == pytest.approx(50.0)


def test_unit_generation_snapshot_dataclass_rejects_fake_identities() -> None:
    """TaipowerUnitGenerationSnapshot dataclass 建構時應拒絕空值或假識別值。"""
    from shiro_mlops.data.taipower_unit_generation import TaipowerUnitGenerationSnapshot

    with pytest.raises(ValueError, match="unit_type"):
        TaipowerUnitGenerationSnapshot(
            observed_at=datetime(2026, 9, 5, 17, 30),
            unit_type="",
            unit_name="大潭CC#1",
            source_time=datetime(2026, 9, 5, 17, 30),
            capacity_mw=100.0,
            net_generation_mw=50.0,
            capacity_ratio_pct=50.0,
            remark=None,
            raw_payload={},
        )

    with pytest.raises(ValueError, match="unit_type"):
        TaipowerUnitGenerationSnapshot(
            observed_at=datetime(2026, 9, 5, 17, 30),
            unit_type="None",
            unit_name="大潭CC#1",
            source_time=datetime(2026, 9, 5, 17, 30),
            capacity_mw=100.0,
            net_generation_mw=50.0,
            capacity_ratio_pct=50.0,
            remark=None,
            raw_payload={},
        )

    with pytest.raises(ValueError, match="unit_name"):
        TaipowerUnitGenerationSnapshot(
            observed_at=datetime(2026, 9, 5, 17, 30),
            unit_type="燃氣",
            unit_name="  ",
            source_time=datetime(2026, 9, 5, 17, 30),
            capacity_mw=100.0,
            net_generation_mw=50.0,
            capacity_ratio_pct=50.0,
            remark=None,
            raw_payload={},
        )


def test_parse_unit_generation_payload_rejects_empty_valid_rows() -> None:
    """成功回應中無任何有效機組列時必須失敗。"""
    payload = {"DateTime": "2026-09-05T17:30:00", "aaData": []}

    with pytest.raises(UnitGenerationParseError, match="No valid unit rows"):
        parse_unit_generation_payload(payload, observed_at=datetime(2026, 9, 5, 17, 30))
