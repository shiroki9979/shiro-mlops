"""List the rolling-origin backtest origins a frozen snapshot offers (docs/reference/lab.md §2, §3).

Run before a study to see whether the snapshot leaves room for search origins and
evaluation origins on enough calendar days, without fitting any model.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import pandas as pd
from shiro_mlops.tasks.deployed import deployed_task

from lab.backtest import (
    RejectedOrigin,
    origin_runs,
    screen_origins,
    split_search_and_eval_origins,
)
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
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Also list the rejected origins, grouped by the origin check they failed.",
    )
    add_snapshot_selection_arguments(parser)
    return parse_snapshot_selection(parser, argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    task = task_for_selection(deployed_task(args.task_id), args)
    selection = {"variant": args.variant, "snapshots_dir": args.snapshots_dir}
    data = read_snapshot(task, args.as_of, **selection)
    screening = screen_origins(task, data, args.horizon_hours)
    eligible = screening.eligible
    print(f"snapshot: {snapshot_path(task, args.as_of, **selection)}")
    print(f"eligible origins: {len(eligible)}")
    print(f"calendar days: {len({origin.date() for origin in eligible})}")
    for first, last in origin_runs(eligible):
        print(f"run: {first.isoformat()} .. {last.isoformat()} ({_span_hours(first, last)} h)")
    if args.explain:
        _print_rejections(screening.rejected)
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


def _print_rejections(rejected: Sequence[RejectedOrigin]) -> None:
    """One line per run of consecutive origins failing the same check, with the run's last reason.

    The last origin's reason names the gap that still blocks the latest origins, which is
    what decides when the snapshot will offer enough of them.
    """
    for run in _rejection_runs(rejected):
        first, last = run[0], run[-1]
        print(
            f"rejected: {first.origin.isoformat()} .. {last.origin.isoformat()} "
            f"({_span_hours(first.origin, last.origin)} h): {last.check}"
        )
        print(f"  latest reason: {last.reason}")


def _rejection_runs(rejected: Sequence[RejectedOrigin]) -> list[list[RejectedOrigin]]:
    runs: list[list[RejectedOrigin]] = []
    for item in rejected:
        previous = runs[-1][-1] if runs else None
        if (
            previous is not None
            and previous.check == item.check
            and item.origin - previous.origin == pd.Timedelta(hours=1)
        ):
            runs[-1].append(item)
        else:
            runs.append([item])
    return runs


def _span_hours(first: pd.Timestamp, last: pd.Timestamp) -> int:
    return int((last - first).total_seconds() // 3600) + 1


if __name__ == "__main__":
    raise SystemExit(main())
