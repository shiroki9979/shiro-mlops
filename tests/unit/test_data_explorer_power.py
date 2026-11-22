"""Power dataset readers preserve MW conversion, completeness, and nullable fields."""

from datetime import datetime, timedelta

import pytest

from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.taipower_regional_supply_demand import (
    TaipowerRegionalSupplyDemandSnapshot,
)
from shiro_mlops.service.data_explorer.errors import ExplorerQueryError
from shiro_mlops.service.data_explorer.power import (
    NationalSupplyDemandReader,
    RegionalSupplyDemandReader,
    UnitGenerationReader,
)
from tests.helpers import (
    rfc3339,
    supply_demand_snapshot,
    unit_generation_snapshots,
)
from tests.scenarios.data_explorer_power import (
    assert_national_reader_pages,
    assert_regional_reader_pages,
    assert_unit_reader_pages,
)


def _freeze_clock(monkeypatch: pytest.MonkeyPatch, now: datetime) -> None:
    """Missing slots stop at "now", so a fixed clock keeps the window's slots in the past."""
    monkeypatch.setattr("shiro_mlops.service.data_explorer.completeness.now_taiwan", lambda: now)


def test_national_reader_converts_mw_and_preserves_nullable_fields(
    test_repo: TimeSeriesRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """全台供需 reader 必須以 MW 為主顯示，並保留契約允許的空值與萬瓩欄位。"""
    observed = datetime(2026, 9, 5, 17, 30)
    _freeze_clock(monkeypatch, observed + timedelta(hours=1))
    test_repo.upsert_supply_demand_snapshot(
        supply_demand_snapshot(observed - timedelta(minutes=20))
    )
    test_repo.upsert_supply_demand_snapshot(supply_demand_snapshot(observed))

    page = NationalSupplyDemandReader(test_repo.engine).list(
        {"start": rfc3339(observed - timedelta(hours=1)), "end": rfc3339(observed)}
    )
    item = page.items[0]
    assert item["curr_load_mw"] == pytest.approx(32421.0)
    assert item["curr_load_wan_kw"] == pytest.approx(3242.1)
    assert "raw_payload" not in item
    assert item["observed_at"].endswith("+08:00")
    assert rfc3339(observed - timedelta(minutes=10)) in page.missing_slots


def test_regional_reader_marks_incomplete_slots_and_filters_completeness(
    test_repo: TimeSeriesRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """缺少任一區時該 slot 必須標記 incomplete；completeness 篩選不得改變此判定。"""
    observed = datetime(2026, 9, 5, 17, 20)
    _freeze_clock(monkeypatch, observed + timedelta(hours=1))
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
    test_repo.upsert_regional_supply_demand_snapshots(rows)
    reader = RegionalSupplyDemandReader(test_repo.engine)
    params = {"start": rfc3339(complete_slot), "end": rfc3339(observed), "limit": "50"}

    page = reader.list(params)
    north_current = next(
        item
        for item in page.items
        if item["region"] == "北部" and item["observed_at"] == rfc3339(observed)
    )
    assert north_current["slot_complete"] is False
    assert "東部" in north_current["missing_regions"]
    complete_east = next(item for item in page.items if item["region"] == "東部")
    assert complete_east["generation_wan_kw"] is None
    assert complete_east["slot_complete"] is True

    incomplete = reader.list({**params, "completeness": "incomplete"})
    assert all(item["slot_complete"] is False for item in incomplete.items)

    with pytest.raises(ExplorerQueryError, match="region"):
        reader.list({**params, "region": "國外"})


def test_unit_generation_reader_preserves_zero_and_nullable_fields(
    test_repo: TimeSeriesRepository,
) -> None:
    """機組零發電必須保留，契約允許空值不得被當成缺失。"""
    observed = datetime(2026, 9, 5, 17, 10)
    test_repo.upsert_unit_generation_snapshots(unit_generation_snapshots(observed))
    reader = UnitGenerationReader(test_repo.engine)
    window = {
        "start": rfc3339(observed - timedelta(hours=1)),
        "end": rfc3339(observed),
    }

    page = reader.list(window)
    names = {item["unit_name"]: item for item in page.items}
    assert names["大潭CC#3"]["net_generation_mw"] == 0.0
    assert names["大潭CC#3"]["remark"] == "歲修"
    assert names["離島其它(註4)"]["net_generation_mw"] is None
    assert "raw_payload" not in page.items[0]

    filtered = reader.list({**window, "unit_type": "燃氣", "unit_name": "大潭CC#1"})
    assert len(filtered.items) == 1
    assert filtered.items[0]["unit_name"] == "大潭CC#1"


def test_national_reader_paginates_raw_microseconds_without_losing_window_gaps(
    test_repo: TimeSeriesRepository,
) -> None:
    assert_national_reader_pages(test_repo)


def test_regional_reader_filters_before_limit_and_projects_complete_slots_across_pages(
    test_repo: TimeSeriesRepository,
) -> None:
    assert_regional_reader_pages(test_repo)


def test_unit_reader_paginates_full_composite_key_and_preserves_nulls(
    test_repo: TimeSeriesRepository,
) -> None:
    assert_unit_reader_pages(test_repo)
