"""Freeze and restore point-in-time training tables for lab research.

The training table stores weighted weather only (ADR-0012), so a candidate with other
reference points or weights needs its own snapshot: a named ``variant`` beside the
shipped weather's file. Each snapshot records its weather and refuses to be read by
a task whose weather differs.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from shiro_mlops.core.config import settings
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.tasks.definition import TaskDefinition, WeatherSpec, build_weather_spec
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
# variant 會成為目錄名稱，限制為小寫英數與連字號，避免路徑跳脫或大小寫不同的重複目錄。
_VARIANT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_WEATHER_ATTR = "lab_weather"


class SnapshotWeatherMismatchError(ValueError):
    """The task's weighted weather differs from the weather frozen in the snapshot."""


def write_snapshot(
    task: TaskDefinition,
    runtime: TaskRuntime,
    as_of: datetime | pd.Timestamp | str,
    *,
    variant: str | None = None,
    snapshots_dir: Path = DEFAULT_SNAPSHOTS_DIR,
) -> Path:
    """Freeze ``training_table`` at ``as_of`` into an immutable parquet snapshot.

    ``variant`` names a snapshot whose weather differs from the shipped definition.
    """
    normalized_as_of = normalize_taiwan_timestamp(as_of)
    path = _snapshot_file(task, normalized_as_of, variant, snapshots_dir)
    if path.exists():
        raise FileExistsError(
            f"Snapshot already exists for ({task.task_id}, {normalized_as_of.isoformat()}): {path}"
        )
    data = load_training_data(task, runtime, as_of=normalized_as_of.to_pydatetime())
    table = training_table(data)
    table.attrs = {_WEATHER_ATTR: _weather_record(task.weather)}
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(path, index=False)
    return path


def read_snapshot(
    task: TaskDefinition,
    as_of: datetime | pd.Timestamp | str,
    *,
    variant: str | None = None,
    snapshots_dir: Path = DEFAULT_SNAPSHOTS_DIR,
) -> TrainingData:
    """Restore ``TrainingData`` from a frozen parquet snapshot.

    Raises ``SnapshotWeatherMismatchError`` when the snapshot recorded other weather than
    ``task.weather``. Snapshots frozen before weather was recorded are not checked.
    """
    path = snapshot_path(task, as_of, variant=variant, snapshots_dir=snapshots_dir)
    table = pd.read_parquet(path)
    frozen = table.attrs.get(_WEATHER_ATTR)
    expected = _weather_record(task.weather)
    if frozen is not None and frozen != expected:
        raise SnapshotWeatherMismatchError(
            f"Snapshot {path} froze weather {frozen}, but task {task.task_id!r} uses {expected}"
        )
    return training_data_from_table(task, table)


def snapshot_path(
    task: TaskDefinition,
    as_of: datetime | pd.Timestamp | str,
    *,
    variant: str | None = None,
    snapshots_dir: Path = DEFAULT_SNAPSHOTS_DIR,
) -> Path:
    """Return the parquet path that holds the snapshot of ``task`` (and ``variant``) at ``as_of``."""
    return _snapshot_file(task, normalize_taiwan_timestamp(as_of), variant, snapshots_dir)


def _snapshot_file(
    task: TaskDefinition,
    normalized_as_of: pd.Timestamp,
    variant: str | None,
    snapshots_dir: Path,
) -> Path:
    directory = snapshots_dir / task.task_id
    if variant is not None:
        if not _VARIANT_PATTERN.fullmatch(variant):
            raise ValueError(
                f"variant must be lowercase letters, digits and hyphens, got {variant!r}"
            )
        directory = directory / variant
    return directory / f"{normalized_as_of.isoformat()}.parquet"


def _weather_record(weather: WeatherSpec) -> dict[str, Any]:
    """JSON-serializable weather identity stored in, and compared against, the parquet."""
    return {
        "reference_points": [
            [point.location.alias, point.weight] for point in weather.reference_points
        ],
        "fields": list(weather.fields),
    }


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
    add_snapshot_selection_arguments(parser)
    return parse_snapshot_selection(parser, argv)


def add_snapshot_selection_arguments(parser: argparse.ArgumentParser) -> None:
    """Arguments naming one snapshot: its directory, variant, and the weather it froze."""
    parser.add_argument(
        "--snapshots-dir",
        type=Path,
        default=DEFAULT_SNAPSHOTS_DIR,
        help="Root directory for snapshot files (default: data/lab/snapshots).",
    )
    parser.add_argument(
        "--variant",
        help="Name of a snapshot whose weather differs from the shipped task (e.g. three-point).",
    )
    parser.add_argument(
        "--reference-points",
        nargs="+",
        dest="reference_points",
        help="Weather reference points replacing the shipped ones; requires --variant.",
    )
    parser.add_argument(
        "--weights",
        nargs="+",
        type=float,
        help="One weight per --reference-points entry, summing to 1.",
    )


def parse_snapshot_selection(
    parser: argparse.ArgumentParser, argv: list[str] | None
) -> argparse.Namespace:
    """Parse ``argv``, rejecting weather overrides that would take the shipped weather's file."""
    args = parser.parse_args(argv)
    if args.weights is not None and args.reference_points is None:
        parser.error("--weights needs --reference-points")
    if args.reference_points is not None and args.variant is None:
        parser.error("--reference-points needs --variant, so the shipped weather keeps its file")
    return args


def task_for_selection(task: TaskDefinition, args: argparse.Namespace) -> TaskDefinition:
    """``task`` with the weather given by ``--reference-points``/``--weights``, if any."""
    if args.reference_points is None:
        return task
    weather = build_weather_spec(
        args.reference_points, args.weights, task.weather.fields, settings.cwa_locations
    )
    return replace(task, weather=weather)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    task = task_for_selection(deployed_task(args.task_id), args)
    repository = TimeSeriesRepository()
    runtime = TaskRuntime(
        hourly_actual_load=repository.hourly_actual_load_store,
        cwa_weather=repository.cwa_weather_store,
    )
    path = write_snapshot(
        task, runtime, args.as_of, variant=args.variant, snapshots_dir=args.snapshots_dir
    )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
