"""Taipower realtime snapshot assets driven by fixture source adapters in a scheduled run."""

import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from dagster import AssetsDefinition, RetryPolicy, graph, materialize

from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.taipower_regional_supply_demand import RegionalSupplyDemandParseError
from shiro_mlops.data.taipower_supply_demand import SupplyDemandParseError
from shiro_mlops.data.taipower_unit_generation import UnitGenerationParseError
from shiro_mlops.pipelines.assets import (
    TAIPOWER_REGIONAL_SUPPLY_DEMAND_SOURCE,
    TAIPOWER_SUPPLY_DEMAND_SOURCE,
    TAIPOWER_UNIT_GENERATION_SOURCE,
    raw_taipower_regional_supply_demand_snapshot,
    raw_taipower_supply_demand_snapshot,
    raw_taipower_unit_generation_snapshot,
)
from shiro_mlops.pipelines.schedules import taipower_supply_demand_snapshot_schedule
from tests.helpers import FIXTURES_DIR, FixtureSource, scheduled_run_tags, unit_snapshots

# daemon 晚了幾秒才評估 tick 時，asset 仍須落在 tick 所在的觀測 slot。
TICK = datetime(2026, 9, 5, 17, 30, 42, tzinfo=ZoneInfo("Asia/Taipei"))
OBSERVED_SLOT = datetime(2026, 9, 5, 17, 30)


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
        rows=unit_snapshots,
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


def _without_retries(asset: AssetsDefinition) -> AssetsDefinition:
    """``asset`` whose op runs once: invoked in a one-op graph with a no-retry policy."""

    @graph(name=f"{asset.op.name}_without_retries")
    def once():
        return asset.op.with_retry_policy(RetryPolicy(max_retries=0))()

    return AssetsDefinition.from_graph(once, keys_by_output_name={"result": asset.key})


def _materialize(source: SnapshotSource, adapter: FixtureSource, repo, instance, **kwargs):
    """Materialize ``source``'s asset in the run the schedule launches at ``TICK``."""
    return materialize(
        [source.asset],
        resources={"time_series_repo": repo, source.source_key: adapter},
        tags=scheduled_run_tags(taipower_supply_demand_snapshot_schedule, TICK),
        instance=instance,
        **kwargs,
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
    first = _materialize(source, FixtureSource(source.payload()), test_repo, dagster_instance)
    assert first.success
    assert len(source.rows(test_repo, OBSERVED_SLOT)) == source.row_count

    revised = FixtureSource(source.revise(source.payload()))
    second = _materialize(source, revised, test_repo, dagster_instance)

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
    dagster_instance,
) -> None:
    """來源回應錯誤或 payload 無法解析時 asset 失敗，且該 slot 不寫入任何快照。"""
    # 區域快照的重試政策實際等待約 110 秒退避；觀測 slot 需要真實 run，
    # 不能直接呼叫 asset，因此只在這個測試以不重試的同一個 op 執行。
    source = replace(source, asset=_without_retries(source.asset))
    if failure == "http_500":
        adapter = FixtureSource(source.payload(), fail_first=math.inf)
        expected_error: type[Exception] = httpx.HTTPStatusError
        match = "HTTP 500"
    else:
        adapter = FixtureSource(source.unparseable_payload)
        expected_error = source.parse_error
        match = source.parse_error_match

    result = _materialize(source, adapter, test_repo, dagster_instance, raise_on_error=False)

    assert not result.success
    [failure_event] = result.get_step_failure_events()
    # 重試政策用盡時 Dagster 以「超過重試次數」包住 asset 拋出的錯誤。
    raised = failure_event.step_failure_data.error.cause
    assert raised.cls_name == expected_error.__name__
    assert re.search(match, raised.message)
    assert source.rows(test_repo, OBSERVED_SLOT) == []
