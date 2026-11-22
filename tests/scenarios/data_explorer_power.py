"""Power reader pagination scenarios shared across database dialects."""

from dataclasses import replace
from datetime import datetime, timedelta

from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.service.data_explorer.power import (
    NationalSupplyDemandReader,
    RegionalSupplyDemandReader,
    UnitGenerationReader,
)
from tests.helpers import (
    regional_supply_demand_snapshots,
    rfc3339,
    supply_demand_snapshot,
    unit_generation_snapshots,
)


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
    complete_north, _ = _all_pages(
        reader,
        {**params, "region": "北部", "completeness": "complete"},
        lambda item: (item["region"], item["slot_complete"], item["missing_regions"]),
    )
    incomplete, _ = _all_pages(
        reader,
        {**params, "completeness": "incomplete"},
        lambda item: item["load_wan_kw"],
    )

    assert regions == [
        ("北部", False),
        ("東部", True),
        ("南部", True),
        ("北部", True),
        ("中部", True),
        ("北部", False),
    ]
    assert gaps == [[rfc3339(older), rfc3339(observed)]] * 6
    assert complete_north == [("北部", True, [])]
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
    filtered, _ = _all_pages(
        reader, {**params, "unit_type": "燃氣", "unit_name": "A"}, lambda item: item["unit_name"]
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
    assert filtered == ["A"]
