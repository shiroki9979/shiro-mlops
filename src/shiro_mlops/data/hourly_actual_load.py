"""Derive nationwide hourly actual load from Taipower regional supply-demand snapshots.

See ADR-0008 and docs/SPEC.md §1.1 for the derivation contract.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import fmean

import pandas as pd

from shiro_mlops.core.constants import DATETIME_COL, LOAD_MW_COL
from shiro_mlops.core.datetime_utils import taiwan_now
from shiro_mlops.data.taipower_regional_supply_demand import (
    REGIONAL_SUPPLY_DEMAND_REGIONS,
    TaipowerRegionalSupplyDemandSnapshot,
)

REGIONAL_SNAPSHOT_SUM_SOURCE = "regional_snapshot_sum"
SAMPLE_COUNT_COL = "sample_count"
WAN_KW_TO_MW = 10.0
ONE_HOUR = timedelta(hours=1)
_REQUIRED_REGIONS = frozenset(REGIONAL_SUPPLY_DEMAND_REGIONS)


@dataclass(frozen=True)
class HourlyLoadAccumulation:
    """Persisted derived-load inventory used to gate training.

    ``legacy_rows`` counts d015046-era rows whose NULL source marks a different
    measurement basis; ``latest_hour`` is the newest derived hour start.
    """

    valid_hours: int
    legacy_rows: int
    latest_hour: datetime | None


@dataclass(frozen=True)
class HourWindow:
    """Half-open Taiwan-local window ``[start, end)`` aligned to whole hours."""

    start: datetime
    end: datetime


def floor_to_hour(moment: datetime) -> datetime:
    """Floor a timestamp to the start of its hour."""
    return moment.replace(minute=0, second=0, microsecond=0)


def is_stale_load_anchor(anchor: datetime, evaluated_at: datetime, max_lag_hours: int) -> bool:
    """Whether the newest derived load hour exceeds the allowed age."""
    return evaluated_at - anchor > timedelta(hours=max_lag_hours)


def recent_completed_hours(now: datetime, hours: int) -> HourWindow:
    """Return the most recent ``hours`` whole hours that ended at or before ``now``."""
    if hours < 1:
        raise ValueError(f"hours must be at least 1, got {hours}")
    end = floor_to_hour(now)
    return HourWindow(start=end - hours * ONE_HOUR, end=end)


def resolve_evaluation_time(evaluated_at: str | None = None) -> datetime:
    """Resolve a schedule tick (Taiwan-local ISO string) or the current Taiwan-local time."""
    if evaluated_at is None:
        return taiwan_now().to_pydatetime()
    return datetime.fromisoformat(evaluated_at)


def derive_hourly_actual_load(
    snapshots: Iterable[TaipowerRegionalSupplyDemandSnapshot],
    *,
    completed_before: datetime,
    min_samples: int,
) -> pd.DataFrame:
    """Average valid nationwide samples per completed hour, labelled at the hour start.

    Hours with fewer than ``min_samples`` valid samples are omitted rather than
    interpolated, and hours ending after ``completed_before`` are never produced.
    """
    if min_samples < 1:
        raise ValueError(f"min_samples must be at least 1, got {min_samples}")

    samples_by_hour: dict[datetime, list[float]] = defaultdict(list)
    for source_time, total_mw in _valid_nationwide_samples(snapshots).items():
        samples_by_hour[floor_to_hour(source_time)].append(total_mw)

    rows = [
        {
            DATETIME_COL: hour,
            LOAD_MW_COL: fmean(values),
            SAMPLE_COUNT_COL: len(values),
        }
        for hour, values in sorted(samples_by_hour.items())
        if hour + ONE_HOUR <= completed_before and len(values) >= min_samples
    ]
    return _to_frame(rows)


def _valid_nationwide_samples(
    snapshots: Iterable[TaipowerRegionalSupplyDemandSnapshot],
) -> dict[datetime, float]:
    """Map each complete source_time to its four-region load sum in MW."""
    loads_by_source_time = _latest_region_loads_by_source_time(snapshots)
    return {
        source_time: sum(region_loads.values()) * WAN_KW_TO_MW
        for source_time, region_loads in loads_by_source_time.items()
        if region_loads.keys() == _REQUIRED_REGIONS
    }


def _latest_region_loads_by_source_time(
    snapshots: Iterable[TaipowerRegionalSupplyDemandSnapshot],
) -> dict[datetime, dict[str, float]]:
    """Collapse repeated captures of one source_time so each sample is counted once.

    The latest observation slot wins, keeping the result deterministic if a
    repeated capture ever disagrees with an earlier one.
    """
    loads: dict[datetime, dict[str, float]] = defaultdict(dict)
    for snapshot in sorted(snapshots, key=lambda item: item.observed_at):
        loads[snapshot.source_time][snapshot.region] = snapshot.load_wan_kw
    return loads


def _to_frame(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=[DATETIME_COL, LOAD_MW_COL, SAMPLE_COUNT_COL])
    frame[DATETIME_COL] = pd.to_datetime(frame[DATETIME_COL])
    return frame
