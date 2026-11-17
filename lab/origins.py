"""List the rolling-origin backtest origins a frozen snapshot offers (SPEC §7.2, §7.3).

Run before a study to see whether the snapshot leaves room for search origins and
evaluation origins on enough calendar days, without fitting any model.
"""

from __future__ import annotations

import argparse

from shiro_mlops.tasks.deployed import deployed_task

from lab.backtest import eligible_origins, origin_runs, split_search_and_eval_origins
from lab.snapshot import (
    add_snapshot_selection_arguments,
    parse_snapshot_selection,
    read_snapshot,
    snapshot_path,
    task_for_selection,
)

DEFAULT_HORIZON_HOURS = 24
# 採用判定要求評估起點至少涵蓋 7 個日曆日（GitHub #92、#98）。
DEFAULT_EVAL_CALENDAR_DAYS = 7
DEFAULT_HOUR_STEP = 6


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m lab.origins",
        description="List the backtest origins a snapshot offers and propose a search/eval split.",
    )
    parser.add_argument("task_id", help="Deployed task_id (e.g. dynamic_horizon_forecast).")
    parser.add_argument(
        "--as-of", required=True, dest="as_of", help="Snapshot as_of, Asia/Taipei ISO."
    )
    parser.add_argument("--horizon-hours", type=int, default=DEFAULT_HORIZON_HOURS)
    parser.add_argument(
        "--eval-days",
        type=int,
        default=DEFAULT_EVAL_CALENDAR_DAYS,
        help="Calendar days the evaluation origins must cover (default 7).",
    )
    parser.add_argument(
        "--hour-step",
        type=int,
        default=DEFAULT_HOUR_STEP,
        help="Use origins whose hour is a multiple of this (default 6).",
    )
    add_snapshot_selection_arguments(parser)
    return parse_snapshot_selection(parser, argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    task = task_for_selection(deployed_task(args.task_id), args)
    selection = {"variant": args.variant, "snapshots_dir": args.snapshots_dir}
    data = read_snapshot(task, args.as_of, **selection)
    eligible = eligible_origins(task, data, args.horizon_hours)
    print(f"snapshot: {snapshot_path(task, args.as_of, **selection)}")
    print(f"eligible origins: {len(eligible)}")
    print(f"calendar days: {len({origin.date() for origin in eligible})}")
    for first, last in origin_runs(eligible):
        hours = int((last - first).total_seconds() // 3600) + 1
        print(f"run: {first.isoformat()} .. {last.isoformat()} ({hours} h)")
    try:
        split = split_search_and_eval_origins(
            eligible,
            horizon_hours=args.horizon_hours,
            eval_calendar_days=args.eval_days,
            hour_step=args.hour_step,
        )
    except ValueError as error:
        print(f"split: unavailable ({error})")
        print("sufficient: no")
        return 0
    for role, origins in (("search", split.search_origins), ("eval", split.eval_origins)):
        print(
            f"{role} origins: {len(origins)} "
            f"({origins[0].isoformat()} .. {origins[-1].isoformat()})"
        )
    print(f"eval calendar days: {split.eval_calendar_days}")
    print(f"sufficient: {'yes' if split.eval_calendar_days >= args.eval_days else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
