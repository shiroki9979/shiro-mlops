"""Taipower realtime snapshot assets driven by fixture source adapters and observed_at config."""

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
import pytest
from dagster import AssetsDefinition, build_asset_context, materialize

from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.taipower_regional_supply_demand import RegionalSupplyDemandParseError
from shiro_mlops.data.taipower_supply_demand import SupplyDemandParseError
from shiro_mlops.data.taipower_unit_generation import UnitGenerationParseError
from shiro_mlops.pipelines.assets import (
    TAIPOWER_REGIONAL_SUPPLY_DEMAND_SOURCE,
    TAIPOWER_SUPPLY_DEMAND_SOURCE,
    TAIPOWER_UNIT_GENERATION_SOURCE,
    SnapshotObservationConfig,
    raw_taipower_regional_supply_demand_snapshot,
    raw_taipower_supply_demand_snapshot,
    raw_taipower_unit_generation_snapshot,
)
from tests.helpers import FIXTURES_DIR, FixtureSource

OBSERVED_SLOT = datetime(2026, 9, 5, 17, 30)
# 手動補跑可能帶入非整十分的時間；asset 仍須落在同一個觀測 slot。
OFF_SLOT_OBSERVED_AT = "2026-09-05T17:37:42"


def _json_fixture(name: str) -> Callable[[], dict]:
    return lambda: json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _supply_demand_rows(repo: TimeSeriesRepository, slot: datetime) -> list:
    snapshot = repo.supply_demand_store.fetch(slot)
    return [] if snapshot is None else [snapshot]


def _revise_supply_demand(payload: dict) -> dict:
    payload["records"][0]["curr_load"] = "3400.5"
    return payload


def _revise_regional(csv_text: str) -> str:
    return csv_text.replace("1091.7", "1100.0")


def _revise_unit(payload: dict) -> dict:
    payload["aaData"][0]["淨發電量(MW)"] = "680.0"
    return payload


@dataclass(frozen=True)
class SnapshotSource:
    """One Taipower realtime source: its asset, port, fixture and how to read it back."""

    asset: AssetsDefinition
    source_key: str
    payload: Callable[[], Any]
    revise: Callable[[Any], Any]
    rows: Callable[[TimeSeriesRepository, datetime], list]
    row_count: int
    revised_value: Callable[[list], float]
    unparseable_payload: Any
    parse_error: type[Exception]
    parse_error_match: str


SOURCES = [
    SnapshotSource(
        asset=raw_taipower_supply_demand_snapshot,
        source_key=TAIPOWER_SUPPLY_DEMAND_SOURCE,
        payload=_json_fixture("taipower_supply_demand_sample.json"),
        revise=_revise_supply_demand,
        rows=_supply_demand_rows,
        row_count=1,
        revised_value=lambda rows: rows[0].curr_load_wan_kw,
        unparseable_payload={"records": [{"curr_load": "3000"}]},
        parse_error=SupplyDemandParseError,
        parse_error_match="curr_util_rate",
    ),
    SnapshotSource(
        asset=raw_taipower_regional_supply_demand_snapshot,
        source_key=TAIPOWER_REGIONAL_SUPPLY_DEMAND_SOURCE,
        payload=lambda: (FIXTURES_DIR / "taipower_regional_supply_demand_sample.csv").read_text(
            encoding="utf-8"
        ),
        revise=_revise_regional,
        rows=lambda repo, slot: repo.regional_supply_demand_store.fetch(slot),
        row_count=4,
        revised_value=lambda rows: next(row for row in rows if row.region == "北部").load_wan_kw,
        unparseable_payload="時間,區域,發電(萬瓩),用電(萬瓩)\n,,,\n",
        parse_error=RegionalSupplyDemandParseError,
        parse_error_match="No valid regional rows",
    ),
    SnapshotSource(
        asset=raw_taipower_unit_generation_snapshot,
        source_key=TAIPOWER_UNIT_GENERATION_SOURCE,
        payload=_json_fixture("taipower_unit_generation_sample.json"),
        revise=_revise_unit,
        rows=lambda repo, slot: repo.unit_generation_store.fetch(slot),
        row_count=4,
        revised_value=lambda rows: (
            next(row for row in rows if row.unit_name == "大潭CC#1").net_generation_mw
        ),
        unparseable_payload={"DateTime": "2026-09-05T17:30:00", "aaData": []},
        parse_error=UnitGenerationParseError,
        parse_error_match="No valid unit rows",
    ),
]
REVISED_VALUES = [3400.5, 1100.0, 680.0]


def _materialize(source: SnapshotSource, adapter: FixtureSource, repo, instance, observed_at):
    return materialize(
        [source.asset],
        resources={"time_series_repo": repo, source.source_key: adapter},
        run_config={"ops": {source.asset.key.path[-1]: {"config": {"observed_at": observed_at}}}},
        instance=instance,
    )


@pytest.mark.parametrize(
    ("source", "revised_value"),
    zip(SOURCES, REVISED_VALUES, strict=True),
    ids=lambda value: getattr(value, "source_key", None),
)
def test_rerunning_a_slot_updates_its_snapshots_in_place(
    source: SnapshotSource,
    revised_value: float,
    test_repo: TimeSeriesRepository,
    dagster_instance,
) -> None:
    """同一 slot 重跑以修正後的 payload 原位更新，列數不變。"""
    first = _materialize(
        source, FixtureSource(source.payload()), test_repo, dagster_instance, OFF_SLOT_OBSERVED_AT
    )
    assert first.success
    assert len(source.rows(test_repo, OBSERVED_SLOT)) == source.row_count

    revised = FixtureSource(source.revise(source.payload()))
    second = _materialize(source, revised, test_repo, dagster_instance, OFF_SLOT_OBSERVED_AT)

    assert second.success
    rows = source.rows(test_repo, OBSERVED_SLOT)
    assert len(rows) == source.row_count
    assert source.revised_value(rows) == pytest.approx(revised_value)


@pytest.mark.parametrize("source", SOURCES, ids=lambda source: source.source_key)
@pytest.mark.parametrize("failure", ["http_500", "unparseable"])
def test_a_failed_fetch_writes_nothing(
    source: SnapshotSource,
    failure: str,
    test_repo: TimeSeriesRepository,
) -> None:
    """來源回應錯誤或 payload 無法解析時 asset 失敗，且該 slot 不寫入任何快照。

    直接呼叫 asset 而非 materialize，以免區域快照的重試政策實際等待退避。
    """
    if failure == "http_500":
        adapter = FixtureSource(source.payload(), fail_first=math.inf)
        expected_error: type[Exception] = httpx.HTTPStatusError
        match = "HTTP 500"
    else:
        adapter = FixtureSource(source.unparseable_payload)
        expected_error = source.parse_error
        match = source.parse_error_match

    resources = {"time_series_repo": test_repo, source.source_key: adapter}
    config = SnapshotObservationConfig(observed_at=OBSERVED_SLOT.isoformat())
    with build_asset_context(resources=resources) as context:
        with pytest.raises(expected_error, match=match):
            source.asset(context, config)

    assert source.rows(test_repo, OBSERVED_SLOT) == []
