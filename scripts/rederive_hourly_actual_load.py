"""Derive hourly actual load for stored regional snapshots the scheduled asset never covered.

The scheduled ``raw_taipower_load`` asset only reaches back ``HOURLY_LOAD_CATCHUP_MAX_HOURS``
after the latest derived hour, so snapshots stored before the derivation went live, or
before an outage longer than that limit, are never turned into hourly load. This one-off applies the same derivation to those stored
snapshots; it never refetches from Taipower and never overwrites a stored hour
(ADR-0008 Notes).

Usage (Asia/Taipei times):
    uv run python scripts/rederive_hourly_actual_load.py \
        --start 2026-09-06T00:00:00 --end 2026-11-10T00:00:00 --dry-run
"""

from __future__ import annotations

import argparse
from datetime import datetime
from typing import Protocol

import pandas as pd

from shiro_mlops.core.config import settings
from shiro_mlops.core.constants import NATIONWIDE_SUBJECT
from shiro_mlops.core.datetime_utils import taiwan_now
from shiro_mlops.data.hourly_actual_load import derive_hourly_actual_load, floor_to_hour
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.taipower_regional_supply_demand import (
    TaipowerRegionalSupplyDemandSnapshot,
)

DATETIME_COL = "datetime"


class LoadRepository(Protocol):
    def fetch_regional_supply_demand_snapshots_by_source_time(
        self, start_time: datetime, end_time: datetime
    ) -> list[TaipowerRegionalSupplyDemandSnapshot]: ...

    def fetch_load_range(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        subject: str | None = None,
        source: str | None = None,
    ) -> pd.DataFrame: ...

    def upsert_taipower_load(self, df: pd.DataFrame) -> int: ...


def rederive_missing_hours(
    repository: LoadRepository,
    start: datetime,
    end: datetime,
    *,
    min_samples: int,
    dry_run: bool,
) -> pd.DataFrame:
    """Derive hours in ``[start, end)`` that stored snapshots support but stored load lacks."""
    missing = _derivable_hours_missing_from_store(repository, start, end, min_samples)
    if not dry_run and not missing.empty:
        repository.upsert_taipower_load(missing)
    return missing


def _derivable_hours_missing_from_store(
    repository: LoadRepository, start: datetime, end: datetime, min_samples: int
) -> pd.DataFrame:
    snapshots = repository.fetch_regional_supply_demand_snapshots_by_source_time(start, end)
    derived = derive_hourly_actual_load(snapshots, completed_before=end, min_samples=min_samples)
    stored = repository.fetch_load_range(start, end, subject=NATIONWIDE_SUBJECT)
    stored_hours = pd.to_datetime(stored["time"])
    return derived[~derived[DATETIME_COL].isin(stored_hours)].reset_index(drop=True)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", required=True, type=datetime.fromisoformat)
    parser.add_argument("--end", required=True, type=datetime.fromisoformat)
    parser.add_argument("--min-samples", type=int, default=settings.HOURLY_LOAD_MIN_SAMPLES)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def _reject_unfinished_window(start: datetime, end: datetime) -> None:
    latest_completed = floor_to_hour(taiwan_now().to_pydatetime().replace(tzinfo=None))
    if end > latest_completed:
        raise SystemExit(
            f"--end {end.isoformat()} is later than the latest completed hour "
            f"{latest_completed.isoformat()}; unfinished hours must not be derived."
        )
    if start >= end:
        raise SystemExit(f"--start {start.isoformat()} must be earlier than --end.")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _reject_unfinished_window(args.start, args.end)
    hours = rederive_missing_hours(
        TimeSeriesRepository(),
        args.start,
        args.end,
        min_samples=args.min_samples,
        dry_run=args.dry_run,
    )
    action = "Would write" if args.dry_run else "Wrote"
    print(hours.to_string(index=False))
    print(f"{action} {len(hours)} hours in [{args.start.isoformat()}, {args.end.isoformat()}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
