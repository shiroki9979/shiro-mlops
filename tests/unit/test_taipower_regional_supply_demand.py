"""Unit tests for Taipower regional supply-demand CSV parsing."""

from datetime import datetime
from pathlib import Path

import pytest

from shiro_mlops.data.taipower_regional_supply_demand import (
    RegionalSupplyDemandParseError,
    parse_regional_supply_demand_csv,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def test_parse_regional_csv_returns_four_region_snapshots() -> None:
    """完整區域 CSV 應產出北中南東四區萬瓩 typed 快照與來源時間。"""
    csv_text = (FIXTURES_DIR / "taipower_regional_supply_demand_sample.csv").read_text(
        encoding="utf-8"
    )
    observed_at = datetime(2026, 9, 5, 17, 30)

    snapshots = parse_regional_supply_demand_csv(csv_text, observed_at=observed_at)

    assert [item.region for item in snapshots] == ["北部", "中部", "南部", "東部"]
    assert snapshots[0].observed_at == observed_at
    assert snapshots[0].source_time == datetime(2026, 9, 5, 17, 30)
    assert snapshots[0].generation_wan_kw == pytest.approx(1155.4)
    assert snapshots[0].load_wan_kw == pytest.approx(1091.7)
    assert snapshots[3].generation_wan_kw == pytest.approx(12.8)
    assert snapshots[3].load_wan_kw == pytest.approx(38.5)
    assert snapshots[0].raw_payload["區域"] == "北部"
    assert snapshots[0].raw_payload["用電(萬瓩)"] == "1091.7"


def test_parse_regional_csv_skips_rows_missing_core_fields() -> None:
    """缺少時間、區域或用電值的列應略過；發電缺少時保存為空值。"""
    csv_text = (
        "時間,區域,發電(萬瓩),用電(萬瓩)\n"
        "20260905T173000,北部,,1091.7\n"
        ",中部,1088.7,977.5\n"
        "20260905T173000,,997.0,1146.3\n"
        "20260905T173000,東部,12.8,\n"
        "20260905T173000,南部,900.0,1000.0\n"
    )

    snapshots = parse_regional_supply_demand_csv(csv_text, observed_at=datetime(2026, 9, 5, 17, 30))

    assert len(snapshots) == 2
    assert snapshots[0].region == "北部"
    assert snapshots[0].generation_wan_kw is None
    assert snapshots[0].load_wan_kw == pytest.approx(1091.7)
    assert snapshots[1].region == "南部"
    assert snapshots[1].load_wan_kw == pytest.approx(1000.0)


def test_parse_regional_csv_strips_bom_from_region() -> None:
    """區域欄位前綴 BOM 應被清除後再正規化。"""
    csv_text = "\ufeff時間,區域,發電(萬瓩),用電(萬瓩)\n20260905T173000,\ufeff北部,1155.4,1091.7\n"

    snapshots = parse_regional_supply_demand_csv(csv_text, observed_at=datetime(2026, 9, 5, 17, 30))

    assert len(snapshots) == 1
    assert snapshots[0].region == "北部"


def test_parse_regional_csv_rejects_empty_valid_rows() -> None:
    """成功回應中無任何有效區域列時必須失敗。"""
    csv_text = "時間,區域,發電(萬瓩),用電(萬瓩)\n,,,\n"

    with pytest.raises(RegionalSupplyDemandParseError, match="No valid regional rows"):
        parse_regional_supply_demand_csv(csv_text, observed_at=datetime(2026, 9, 5, 17, 30))


def test_parse_regional_csv_skips_non_agreed_format_errors() -> None:
    """非約定缺值的來源格式錯誤（如字串損壞、NaN、非法時間）不應靜默轉為 None，該列應略過並記錄。"""
    csv_text = (
        "時間,區域,發電(萬瓩),用電(萬瓩)\n"
        "20260905T173000,北部,corrupted,1091.7\n"  # 發電非約定格式錯誤，不應轉為 None 入庫
        "20260905T173000,中部,1000.0,bad-load\n"  # 用電格式錯誤
        "bad-timestamp,南部,900.0,1000.0\n"  # 時間格式錯誤
        "20260905T173000,澎湖,50.0,50.0\n"  # 非約定區域
        "20260905T173000,東部,NaN,38.5\n"  # NaN 異常
        "20260905T173000,中部,1088.7,977.5\n"  # 有效列
    )

    snapshots = parse_regional_supply_demand_csv(csv_text, observed_at=datetime(2026, 9, 5, 17, 30))

    assert len(snapshots) == 1
    assert snapshots[0].region == "中部"
    assert snapshots[0].generation_wan_kw == pytest.approx(1088.7)
    assert snapshots[0].load_wan_kw == pytest.approx(977.5)


def test_parse_regional_csv_rejects_missing_headers() -> None:
    """CSV 缺少核心欄位標頭時必須失敗。"""
    csv_text = "發電(萬瓩),用電(萬瓩)\n100.0,200.0\n"

    with pytest.raises(RegionalSupplyDemandParseError, match="Missing required CSV headers"):
        parse_regional_supply_demand_csv(csv_text, observed_at=datetime(2026, 9, 5, 17, 30))


def test_regional_snapshot_dataclass_rejects_invalid_values() -> None:
    """TaipowerRegionalSupplyDemandSnapshot dataclass 應拒絕非約定區域或非有限浮點數。"""
    from shiro_mlops.data.taipower_regional_supply_demand import (
        TaipowerRegionalSupplyDemandSnapshot,
    )

    with pytest.raises(ValueError, match="region"):
        TaipowerRegionalSupplyDemandSnapshot(
            observed_at=datetime(2026, 9, 5, 17, 30),
            region="澎湖",
            source_time=datetime(2026, 9, 5, 17, 30),
            generation_wan_kw=100.0,
            load_wan_kw=100.0,
            raw_payload={},
        )

    with pytest.raises(ValueError, match="load_wan_kw"):
        TaipowerRegionalSupplyDemandSnapshot(
            observed_at=datetime(2026, 9, 5, 17, 30),
            region="北部",
            source_time=datetime(2026, 9, 5, 17, 30),
            generation_wan_kw=100.0,
            load_wan_kw=float("nan"),
            raw_payload={},
        )

    with pytest.raises(ValueError, match="generation_wan_kw"):
        TaipowerRegionalSupplyDemandSnapshot(
            observed_at=datetime(2026, 9, 5, 17, 30),
            region="北部",
            source_time=datetime(2026, 9, 5, 17, 30),
            generation_wan_kw=float("inf"),
            load_wan_kw=100.0,
            raw_payload={},
        )
