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

from sqlalchemy.engine import Engine

from shiro_mlops.core.config import settings
from shiro_mlops.core.datetime_utils import taiwan_now
from shiro_mlops.data.hourly_actual_load import HourWindow, floor_to_hour
from shiro_mlops.data.repository import TimeSeriesRepository

CLI_DESCRIPTION = (
    "Derive hourly actual load for stored regional snapshots the scheduled asset never covered."
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=CLI_DESCRIPTION)
    parser.add_argument("--start", required=True, type=datetime.fromisoformat)
    parser.add_argument("--end", required=True, type=datetime.fromisoformat)
    parser.add_argument("--min-samples", type=int, default=settings.HOURLY_LOAD_MIN_SAMPLES)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def _reject_partial_hours(start: datetime, end: datetime) -> None:
    """Both edges must be whole Taiwan-local hours, given without a UTC offset.

    An edge inside an hour would derive that hour from only the samples after it; the
    partial mean is then stored as the hour's load, and a later run never overwrites it.
    """
    for option, moment in (("--start", start), ("--end", end)):
        if moment.tzinfo is not None:
            raise SystemExit(
                f"{option} {moment.isoformat()} must be Asia/Taipei time without a UTC offset."
            )
        if moment != floor_to_hour(moment):
            raise SystemExit(f"{option} {moment.isoformat()} must be a whole hour.")


def _reject_unfinished_window(start: datetime, end: datetime) -> None:
    latest_completed = floor_to_hour(taiwan_now().to_pydatetime().replace(tzinfo=None))
    if end > latest_completed:
        raise SystemExit(
            f"--end {end.isoformat()} is later than the latest completed hour "
            f"{latest_completed.isoformat()}; unfinished hours must not be derived."
        )
    if start >= end:
        raise SystemExit(f"--start {start.isoformat()} must be earlier than --end.")


def main(argv: list[str] | None = None, engine: Engine | None = None) -> int:
    args = _parse_args(argv)
    _reject_partial_hours(args.start, args.end)
    _reject_unfinished_window(args.start, args.end)
    store = TimeSeriesRepository(engine=engine).hourly_actual_load_store
    hours = store.rederive(
        HourWindow(start=args.start, end=args.end),
        min_samples=args.min_samples,
        dry_run=args.dry_run,
    )
    action = "Would write" if args.dry_run else "Wrote"
    print(hours.to_string(index=False))
    print(f"{action} {len(hours)} hours in [{args.start.isoformat()}, {args.end.isoformat()}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
