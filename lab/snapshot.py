"""Freeze and restore point-in-time training tables for lab research."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.deployed import deployed_task
from shiro_mlops.tasks.runner import (
    TaskRuntime,
    load_training_data,
    training_data_from_table,
    training_table,
)
from shiro_mlops.tasks.types.base import TrainingData

from lab.timestamps import normalize_taiwan_timestamp

DEFAULT_SNAPSHOTS_DIR = Path("data/lab/snapshots")


def write_snapshot(
    task: TaskDefinition,
    runtime: TaskRuntime,
    as_of: datetime | pd.Timestamp | str,
    *,
    snapshots_dir: Path = DEFAULT_SNAPSHOTS_DIR,
) -> Path:
    """Freeze ``training_table`` at ``as_of`` into an immutable parquet snapshot."""
    normalized_as_of = normalize_taiwan_timestamp(as_of)
    path = _snapshot_file(task, normalized_as_of, snapshots_dir)
    if path.exists():
        raise FileExistsError(
            f"Snapshot already exists for ({task.task_id}, {normalized_as_of.isoformat()}): {path}"
        )
    data = load_training_data(task, runtime, as_of=normalized_as_of.to_pydatetime())
    table = training_table(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(path, index=False)
    return path


def read_snapshot(
    task: TaskDefinition,
    as_of: datetime | pd.Timestamp | str,
    *,
    snapshots_dir: Path = DEFAULT_SNAPSHOTS_DIR,
) -> TrainingData:
    """Restore ``TrainingData`` from a frozen parquet snapshot."""
    table = pd.read_parquet(snapshot_path(task, as_of, snapshots_dir=snapshots_dir))
    return training_data_from_table(task, table)


def snapshot_path(
    task: TaskDefinition,
    as_of: datetime | pd.Timestamp | str,
    *,
    snapshots_dir: Path = DEFAULT_SNAPSHOTS_DIR,
) -> Path:
    """Return the parquet path that holds the snapshot of ``task`` at ``as_of``."""
    return _snapshot_file(task, normalize_taiwan_timestamp(as_of), snapshots_dir)


def _snapshot_file(
    task: TaskDefinition, normalized_as_of: pd.Timestamp, snapshots_dir: Path
) -> Path:
    return snapshots_dir / task.task_id / f"{normalized_as_of.isoformat()}.parquet"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m lab.snapshot",
        description="Freeze a task's point-in-time training table as an immutable parquet snapshot.",
    )
    parser.add_argument("task_id", help="Deployed task_id (e.g. dynamic_horizon_forecast).")
    parser.add_argument(
        "--as-of",
        required=True,
        dest="as_of",
        help="Point-in-time cutoff in Asia/Taipei ISO format (e.g. 2026-11-08T22:00:00).",
    )
    parser.add_argument(
        "--snapshots-dir",
        type=Path,
        default=DEFAULT_SNAPSHOTS_DIR,
        help="Root directory for snapshot files (default: data/lab/snapshots).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    task = deployed_task(args.task_id)
    runtime = TaskRuntime(repository=TimeSeriesRepository())
    path = write_snapshot(task, runtime, args.as_of, snapshots_dir=args.snapshots_dir)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
