"""Every dataset's gap and status policies are read from its definition, never hard-coded."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.service.data_explorer.dataset_query import DatasetQuery
from shiro_mlops.service.data_explorer.datasets import (
    DATASETS,
    HOURLY_LOAD,
    UNIT_GENERATION,
    Dataset,
)
from shiro_mlops.service.data_explorer.datasets.definition import (
    AlwaysComplete,
    Exact,
    Filter,
    LastCompletedHours,
    LatestAudit,
    LatestSlot,
    TrailingWindow,
)
from tests.helpers import DatasetLister

GAP_DATASETS = [dataset for dataset in DATASETS.values() if dataset.gaps is not None]
GAP_FILTERS = [
    pytest.param(dataset, item, id=f"{dataset.id}-{item.name}")
    for dataset in GAP_DATASETS
    for item in dataset.filters
]
NOON_UTC = datetime(2026, 9, 20, 4, tzinfo=UTC)
"""2026-09-20 12:00 in Taiwan."""
TEN_PAST_NOON_UTC = NOON_UTC + timedelta(minutes=10)
ONE_PM_UTC = NOON_UTC + timedelta(hours=1)
GAP_FILTER_CASES: dict[tuple[str, str], tuple[str, str, list[dict[str, Any]], dict[str, str]]] = {
    ("hourly_load", "subject"): (
        "INSERT INTO raw_taipower_load (time, subject, load_mw, source) "
        "VALUES (:time, :member, 1, 'regional_snapshot_sum')",
        "a",
        [{"time": NOON_UTC, "member": "a"}, {"time": ONE_PM_UTC, "member": "b"}],
        {"start": "2026-09-20T12:00:00+08:00", "end": "2026-09-20T13:00:00+08:00"},
    ),
    ("regional_supply_demand", "region"): (
        "INSERT INTO raw_taipower_regional_supply_demand_snapshot "
        "(observed_at, region, source_time, load_wan_kw, raw_payload) "
        "VALUES (:time, :member, :time, 1, '{}')",
        "北部",
        [{"time": NOON_UTC, "member": region} for region in ("北部", "中部", "南部", "東部")]
        + [{"time": TEN_PAST_NOON_UTC, "member": "北部"}],
        {"start": "2026-09-20T12:00:00+08:00", "end": "2026-09-20T12:10:00+08:00"},
    ),
    ("regional_supply_demand", "completeness"): (
        "INSERT INTO raw_taipower_regional_supply_demand_snapshot "
        "(observed_at, region, source_time, load_wan_kw, raw_payload) "
        "VALUES (:time, :member, :time, 1, '{}')",
        "incomplete",
        [{"time": NOON_UTC, "member": region} for region in ("北部", "中部", "南部", "東部")]
        + [{"time": TEN_PAST_NOON_UTC, "member": "北部"}],
        {"start": "2026-09-20T12:00:00+08:00", "end": "2026-09-20T12:10:00+08:00"},
    ),
    ("cwa_observations", "station_id"): (
        "INSERT INTO raw_cwa_station_observation (observed_at, station_id) VALUES (:time, :member)",
        "466920",
        [{"time": NOON_UTC, "member": "466920"}],
        {"start": "2026-09-20T12:00:00+08:00", "end": "2026-09-20T13:00:00+08:00"},
    ),
}
"""Per filter: rows where narrowing by `value` would change the window's missing slots."""


def test_only_subject_and_station_id_narrow_the_gap_scope() -> None:
    """data-explorer.md §4：subject、station_id 縮小缺口範圍；region、completeness 不影響。"""
    narrowing = {
        (dataset.id, item.name)
        for dataset in DATASETS.values()
        for item in dataset.filters
        if item.narrows_gaps
    }

    assert narrowing == {("hourly_load", "subject"), ("cwa_observations", "station_id")}


def test_the_four_fixed_cadence_lists_report_missing_slots() -> None:
    assert [dataset.id for dataset in GAP_DATASETS] == [
        "hourly_load",
        "national_supply_demand",
        "regional_supply_demand",
        "cwa_observations",
    ]


@pytest.mark.parametrize("dataset", GAP_DATASETS, ids=lambda dataset: dataset.id)
def test_list_gaps_and_chart_gap_fill_agree_on_when_a_slot_is_due(dataset: Dataset) -> None:
    """列表缺口與圖表補值對同一時段何時到期的判定一致（逐時負載晚一小時）。"""
    assert dataset.gaps is not None and dataset.series is not None
    assert dataset.series.gap_fill
    assert dataset.gaps.slot_lag == dataset.series.slot_lag


@pytest.mark.parametrize(
    ("dataset", "change", "problem"),
    [
        (
            UNIT_GENERATION,
            {"filters": (Exact(name="unit_type", narrows_gaps=True),)},
            "unit_type narrows gaps but the dataset declares no gap policy",
        ),
        (
            HOURLY_LOAD,
            {"gaps": replace(HOURLY_LOAD.gaps, slot_lag=timedelta(0))},
            "gaps and series must share slot_lag",
        ),
    ],
    ids=["narrows-without-gaps", "slot-lag"],
)
def test_inconsistent_gap_declarations_are_rejected(
    dataset: Dataset, change: dict[str, object], problem: str
) -> None:
    with pytest.raises(ValueError, match=problem):
        replace(dataset, **change)


def test_status_policies_follow_the_per_dataset_contract() -> None:
    """status 完整度依資料集口徑：近 24 個完成小時、最新 slot、最新 audit、機組恆為完整。"""
    policies = {dataset.id: dataset.status_policy for dataset in DATASETS.values()}
    audits = {
        dataset_id: (policy.header.table, policy.header.ids_column)
        for dataset_id, policy in policies.items()
        if isinstance(policy, LatestAudit)
    }
    stale_flags = {
        dataset_id
        for dataset_id, policy in policies.items()
        if isinstance(policy, LatestAudit) and policy.flags_stale_release
    }

    assert {
        dataset_id: policy
        for dataset_id, policy in policies.items()
        if not isinstance(policy, LatestAudit)
    } == {
        "hourly_load": LastCompletedHours(hours=24),
        "national_supply_demand": TrailingWindow(span=timedelta(hours=24)),
        "regional_supply_demand": LatestSlot(
            incomplete_href="/data/power/regional?completeness=incomplete"
        ),
        "unit_generation": AlwaysComplete(),
    }
    assert audits == {
        "cwa_observations": ("raw_cwa_observation_batch", "missing_station_ids"),
        "cwa_forecasts": ("raw_cwa_forecast_release", "missing_geocodes"),
        "cwa_observation_audits": ("raw_cwa_observation_batch", "missing_station_ids"),
        "cwa_forecast_audits": ("raw_cwa_forecast_release", "missing_geocodes"),
    }
    assert stale_flags == {"cwa_forecasts"}


def _with_narrowing(dataset: Dataset, item: Filter, narrows: bool) -> Dataset:
    filters = tuple(
        replace(other, narrows_gaps=narrows) if other is item else other
        for other in dataset.filters
    )
    return replace(dataset, filters=filters)


@pytest.mark.parametrize(("dataset", "item"), GAP_FILTERS)
@pytest.mark.parametrize("narrows", [True, False], ids=["narrowing", "not-narrowing"])
def test_declared_narrows_gaps_alone_decides_whether_a_filter_changes_missing_slots(
    sqlite_engine: Engine, dataset: Dataset, item: Filter, narrows: bool
) -> None:
    """同一份資料下，篩選是否改變缺口只由它宣告的 narrows_gaps 決定。"""
    insert, value, rows, window = GAP_FILTER_CASES[(dataset.id, item.name)]
    with sqlite_engine.begin() as connection:
        connection.execute(text(insert), rows)
    lister = DatasetLister(sqlite_engine, _with_narrowing(dataset, item, narrows))

    unfiltered = lister.list(window).missing_slots
    filtered = lister.list({**window, item.name: value}).missing_slots

    assert (filtered != unfiltered) is narrows


def test_every_gap_filter_has_a_narrowing_case() -> None:
    assert {(dataset.id, item.name) for dataset in GAP_DATASETS for item in dataset.filters} == set(
        GAP_FILTER_CASES
    )


@pytest.mark.parametrize(
    ("dataset", "last_due"),
    [
        (DATASETS["hourly_load"], "2026-09-20T12:00:00+08:00"),
        (DATASETS["national_supply_demand"], "2026-09-20T13:20:00+08:00"),
        (DATASETS["regional_supply_demand"], "2026-09-20T13:20:00+08:00"),
        (DATASETS["cwa_observations"], "2026-09-20T13:00:00+08:00"),
    ],
    ids=lambda value: value.id if isinstance(value, Dataset) else "",
)
def test_missing_slots_run_ascending_from_the_window_start_to_the_last_due_slot(
    sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch, dataset: Dataset, last_due: str
) -> None:
    """空窗口的缺口自起點遞增列到最後一個已到期時段；逐時負載晚一小時到期。"""
    monkeypatch.setattr(
        "shiro_mlops.service.data_explorer.dataset_query.now_taiwan",
        lambda: datetime(2026, 9, 20, 13, 25),
    )
    window = {"start": "2026-09-20T12:00:00+08:00", "end": "2026-09-20T14:00:00+08:00"}

    slots = [gap[:25] for gap in DatasetLister(sqlite_engine, dataset).list(window).missing_slots]

    assert slots == sorted(slots)
    assert slots[0] == "2026-09-20T12:00:00+08:00"
    assert slots[-1] == last_due


@pytest.mark.parametrize("dataset", DATASETS.values(), ids=lambda dataset: dataset.id)
def test_an_empty_dataset_reports_its_definition_and_unknown_completeness(
    sqlite_engine: Engine, dataset: Dataset
) -> None:
    statuses = DatasetQuery(sqlite_engine).status(datetime(2026, 9, 20, 12)).datasets
    status = next(item for item in statuses if item.id == dataset.id)

    assert [item.id for item in statuses] == list(DATASETS)
    assert (status.label, status.href) == (dataset.label, dataset.href)
    assert (status.availability, status.completeness, status.overall) == (
        "empty",
        "unknown",
        "warning",
    )
    assert status.missing_identifiers == []
