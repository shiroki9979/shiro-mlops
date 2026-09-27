"""Power dataset readers preserve MW conversion, completeness, and nullable fields."""

from dataclasses import replace
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
    TAIWAN,
    regional_supply_demand_snapshots,
    rfc3339,
    supply_demand_snapshot,
    unit_generation_snapshots,
)


def test_national_reader_converts_mw_and_preserves_nullable_fields(
    test_repo: TimeSeriesRepository,
) -> None:
    """全台供需 reader 必須以 MW 為主顯示，並保留契約允許的空值與萬瓩欄位。"""
    observed = datetime.now(TAIWAN).replace(tzinfo=None, minute=30, second=0, microsecond=0)
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
    test_repo: TimeSeriesRepository,
) -> None:
    """缺少任一區時該 slot 必須標記 incomplete；completeness 篩選不得改變此判定。"""
    observed = datetime.now(TAIWAN).replace(tzinfo=None, minute=20, second=0, microsecond=0)
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
    observed = datetime.now(TAIWAN).replace(tzinfo=None, minute=10, second=0, microsecond=0)
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


def _all_pages(reader, params: dict, identity) -> tuple[list, list]:
    items = []
    gaps = []
    cursor = None
    seen_cursors = set()
    while True:
        page = reader.list({**params, **({"cursor": cursor} if cursor else {})})
        items.extend(identity(item) for item in page.items)
        gaps.append(page.missing_slots)
        assert page.has_more is (page.next_cursor is not None)
        if not page.has_more:
            break
        cursor = page.next_cursor
        assert cursor not in seen_cursors
        seen_cursors.add(cursor)
    return items, gaps


def assert_national_reader_pages(
    test_repo: TimeSeriesRepository,
) -> None:
    observed = datetime(2026, 9, 5, 17, 30)
    moments = [
        observed.replace(microsecond=700000),
        observed.replace(microsecond=200000),
        observed - timedelta(minutes=20),
    ]
    for index, moment in enumerate(moments):
        test_repo.upsert_supply_demand_snapshot(
            replace(supply_demand_snapshot(moment), curr_load_wan_kw=1000.0 + index)
        )
    params = {
        "start": rfc3339(observed - timedelta(minutes=20)),
        "end": rfc3339(observed + timedelta(seconds=1)),
        "limit": 1,
    }

    loads, gaps = _all_pages(
        NationalSupplyDemandReader(test_repo.engine), params, lambda item: item["curr_load_wan_kw"]
    )

    assert loads == [1000.0, 1001.0, 1002.0]
    assert gaps == [[rfc3339(observed - timedelta(minutes=10)), rfc3339(observed)]] * 3


def assert_regional_reader_pages(
    test_repo: TimeSeriesRepository,
) -> None:
    observed = datetime(2026, 9, 5, 17, 30)
    complete = observed.replace(microsecond=200000)
    newer = observed.replace(microsecond=700000)
    older = observed - timedelta(minutes=10)
    rows = regional_supply_demand_snapshots(complete)
    rows += [replace(row, observed_at=newer, load_wan_kw=900.0) for row in rows[:1]]
    rows += [replace(row, observed_at=older, load_wan_kw=800.0) for row in rows[:1]]
    test_repo.upsert_regional_supply_demand_snapshots(rows)
    reader = RegionalSupplyDemandReader(test_repo.engine)
    params = {"start": rfc3339(older), "end": rfc3339(observed + timedelta(seconds=1)), "limit": 1}

    regions, gaps = _all_pages(reader, params, lambda item: (item["region"], item["slot_complete"]))
    assert regions == [
        ("北部", False),
        ("東部", True),
        ("南部", True),
        ("北部", True),
        ("中部", True),
        ("北部", False),
    ]
    assert gaps == [[rfc3339(newer), rfc3339(older)]] * 6

    complete_north, _ = _all_pages(
        reader,
        {**params, "region": "北部", "completeness": "complete"},
        lambda item: (item["region"], item["slot_complete"], item["missing_regions"]),
    )
    assert complete_north == [("北部", True, [])]
    incomplete, _ = _all_pages(
        reader,
        {**params, "completeness": "incomplete"},
        lambda item: item["load_wan_kw"],
    )
    assert incomplete == [900.0, 800.0]


def assert_unit_reader_pages(
    test_repo: TimeSeriesRepository,
) -> None:
    observed = datetime(2026, 9, 5, 17, 30)
    seed = unit_generation_snapshots(observed)[0]
    rows = [
        replace(
            seed,
            observed_at=observed.replace(microsecond=700000),
            unit_type="燃氣",
            unit_name="B",
            net_generation_mw=70.0,
        ),
        replace(
            seed,
            observed_at=observed.replace(microsecond=200000),
            unit_type="燃煤",
            unit_name="A",
            net_generation_mw=20.0,
        ),
        replace(seed, unit_type="燃煤", unit_name="B", net_generation_mw=3.0),
        replace(seed, unit_type="燃煤", unit_name="A", net_generation_mw=0.0),
        replace(seed, unit_type="燃氣", unit_name="B", net_generation_mw=None),
        replace(seed, unit_type="燃氣", unit_name="A", net_generation_mw=1.0),
    ]
    test_repo.upsert_unit_generation_snapshots(rows)
    reader = UnitGenerationReader(test_repo.engine)
    params = {
        "start": rfc3339(observed),
        "end": rfc3339(observed + timedelta(seconds=1)),
        "limit": 1,
    }

    units, gaps = _all_pages(
        reader,
        params,
        lambda item: (item["unit_type"], item["unit_name"], item["net_generation_mw"]),
    )

    assert units == [
        ("燃氣", "B", 70.0),
        ("燃煤", "A", 20.0),
        ("燃煤", "B", 3.0),
        ("燃煤", "A", 0.0),
        ("燃氣", "B", None),
        ("燃氣", "A", 1.0),
    ]
    assert gaps == [[]] * 6
    filtered, _ = _all_pages(
        reader, {**params, "unit_type": "燃氣", "unit_name": "A"}, lambda item: item["unit_name"]
    )
    assert filtered == ["A"]


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
