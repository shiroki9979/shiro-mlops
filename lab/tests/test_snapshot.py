"""Offline unit tests for lab.snapshot (public seam: write_snapshot, read_snapshot, main CLI)."""

import ast
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest
from lab.backtest import recursive_regression_params
from lab.snapshot import SnapshotWeatherMismatchError, read_snapshot, snapshot_path, write_snapshot
from lab.snapshot import main as snapshot_main
from shiro_mlops.core.database import ensure_timescale_hypertables
from shiro_mlops.data.cwa_client import DEFAULT_CWA_LOCATIONS
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.tasks.definition import TaskDefinition, build_weather_spec
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task
from shiro_mlops.tasks.runner import (
    TaskNotReady,
    TaskRuntime,
    fit_task,
    load_training_data,
    train_task,
)
from shiro_mlops.tasks.types.recursive_regression import RecursiveRegressionModel
from sqlalchemy import create_engine
from tests.helpers import (
    canonical_observation_batch,
    hourly_load_with_weather,
    task_runtime,
    write_derived_load,
)

LAST_HOUR = datetime(2026, 9, 20, 23, 0)
HOURS = 24 * 21
AS_OF = datetime(2026, 9, 20, 23, 30)


@pytest.fixture
def task() -> TaskDefinition:
    shipped = deployed_task(DYNAMIC_HORIZON_FORECAST)
    shipped_params = recursive_regression_params(shipped)
    params = shipped_params.model_copy(
        update={"model": shipped_params.model.model_copy(update={"n_estimators": 20})}
    )
    policies = shipped.policies.model_copy(update={"min_training_hours": HOURS})
    return replace(shipped, params=params, policies=policies)


@pytest.fixture
def test_repo(tmp_path: Path) -> TimeSeriesRepository:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_repo.db'}")
    ensure_timescale_hypertables(engine)
    return TimeSeriesRepository(engine=engine)


@pytest.fixture
def runtime(test_repo: TimeSeriesRepository) -> TaskRuntime:
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    write_derived_load(test_repo.engine, load)
    test_repo.cwa_weather_store.upsert_cwa_observation_batch(
        canonical_observation_batch(weather.assign(location="Taipei"))
    )
    return task_runtime(test_repo)


def test_write_and_read_snapshot_round_trip_trains_identical_model(
    task: TaskDefinition, runtime: TaskRuntime, tmp_path: Path
) -> None:
    """Seam: write_snapshot / read_snapshot -> fit_task vs load_training_data / train_task."""
    snapshots_dir = tmp_path / "snapshots"

    snapshot_path = write_snapshot(task, runtime, AS_OF, snapshots_dir=snapshots_dir)

    assert snapshot_path == snapshots_dir / task.task_id / "2026-09-20T23:30:00.parquet"
    assert snapshot_path.is_file()

    raw_parquet = pd.read_parquet(snapshot_path)
    assert list(raw_parquet.columns) == [
        "datetime",
        "subject",
        "load_mw",
        *task.weather.fields,
    ]
    assert not any(col.startswith(("lag_", "rolling_")) for col in raw_parquet.columns)

    restored = read_snapshot(task, AS_OF, snapshots_dir=snapshots_dir)
    direct = load_training_data(task, runtime, as_of=AS_OF)

    pd.testing.assert_frame_equal(restored.load, direct.load)
    pd.testing.assert_frame_equal(restored.weather, direct.weather)
    assert restored.validation_start == direct.validation_start

    restored_trained = fit_task(task, restored)
    direct_trained = train_task(task, runtime, as_of=AS_OF)
    assert restored_trained.metrics == direct_trained.metrics
    assert isinstance(restored_trained.model, RecursiveRegressionModel)
    assert isinstance(direct_trained.model, RecursiveRegressionModel)
    assert restored_trained.model.booster.model_to_string() == (
        direct_trained.model.booster.model_to_string()
    )


def test_snapshot_round_trip_with_staggered_load_and_weather_gaps_trains_identical_model(
    task: TaskDefinition, test_repo: TimeSeriesRepository, tmp_path: Path
) -> None:
    """Seam: write_snapshot / read_snapshot with staggered load (missing hour N) and weather (missing hour N+1) gaps."""
    load, weather = hourly_load_with_weather(HOURS + 1, LAST_HOUR)
    hour_n = pd.Timestamp(load["datetime"].iloc[200])
    hour_n_plus_1 = pd.Timestamp(load["datetime"].iloc[201])
    gapped_load = load[load["datetime"] != hour_n].reset_index(drop=True)
    gapped_weather = weather[weather["datetime"] != hour_n_plus_1].reset_index(drop=True)
    write_derived_load(test_repo.engine, gapped_load)
    test_repo.cwa_weather_store.upsert_cwa_observation_batch(
        canonical_observation_batch(gapped_weather.assign(location="Taipei"))
    )
    gapped_runtime = task_runtime(test_repo)
    snapshots_dir = tmp_path / "snapshots"

    write_snapshot(task, gapped_runtime, AS_OF, snapshots_dir=snapshots_dir)
    restored = read_snapshot(task, AS_OF, snapshots_dir=snapshots_dir)
    direct = load_training_data(task, gapped_runtime, as_of=AS_OF)

    pd.testing.assert_frame_equal(restored.load, direct.load)
    pd.testing.assert_frame_equal(restored.weather, direct.weather)
    assert restored.validation_start == direct.validation_start

    restored_trained = fit_task(task, restored)
    direct_trained = train_task(task, gapped_runtime, as_of=AS_OF)
    assert restored_trained.metrics == direct_trained.metrics
    assert isinstance(restored_trained.model, RecursiveRegressionModel)
    assert isinstance(direct_trained.model, RecursiveRegressionModel)
    assert restored_trained.model.booster.model_to_string() == (
        direct_trained.model.booster.model_to_string()
    )


def test_snapshot_path_resolves_tz_aware_as_of_to_written_snapshot_file(
    task: TaskDefinition, runtime: TaskRuntime, tmp_path: Path
) -> None:
    """Seam: snapshot_path locates the file write_snapshot produced, given a UTC as_of for the same instant."""
    snapshots_dir = tmp_path / "snapshots"
    written = write_snapshot(task, runtime, AS_OF, snapshots_dir=snapshots_dir)

    located = snapshot_path(task, "2026-09-20T15:30:00+00:00", snapshots_dir=snapshots_dir)

    assert located == written


def test_write_snapshot_refuses_to_overwrite_existing_snapshot(
    task: TaskDefinition, runtime: TaskRuntime, tmp_path: Path
) -> None:
    """Seam: write_snapshot raises FileExistsError on duplicate (task_id, as_of) and leaves file bytes untouched."""
    snapshots_dir = tmp_path / "snapshots"
    path = write_snapshot(task, runtime, AS_OF, snapshots_dir=snapshots_dir)
    original_bytes = path.read_bytes()

    sentinel = b"immutable-snapshot-bytes"
    path.write_bytes(sentinel)

    with pytest.raises(FileExistsError, match=task.task_id):
        write_snapshot(task, runtime, "2026-09-20T23:30:00", snapshots_dir=snapshots_dir)

    assert path.read_bytes() == sentinel
    assert original_bytes != sentinel


def test_write_snapshot_propagates_task_not_ready_when_below_minimum_accumulation(
    task: TaskDefinition, runtime: TaskRuntime, tmp_path: Path
) -> None:
    """Seam: write_snapshot propagates TaskNotReady untouched and writes no file."""
    unready_task = replace(
        task, policies=task.policies.model_copy(update={"min_training_hours": HOURS + 1})
    )
    snapshots_dir = tmp_path / "snapshots"

    with pytest.raises(TaskNotReady) as exc_info:
        write_snapshot(unready_task, runtime, AS_OF, snapshots_dir=snapshots_dir)

    assert exc_info.value.readiness.valid_hours == HOURS
    assert exc_info.value.readiness.required_hours == HOURS + 1
    assert not (snapshots_dir / task.task_id).exists()


def test_snapshot_cli_writes_parquet_at_default_relative_layout(
    task: TaskDefinition,
    runtime: TaskRuntime,
    test_repo: TimeSeriesRepository,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seam: python -m lab.snapshot <task_id> --as-of <ISO>."""
    import lab.snapshot as snapshot_mod

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(snapshot_mod, "deployed_task", lambda task_id: task)
    monkeypatch.setattr(snapshot_mod, "TimeSeriesRepository", lambda: test_repo)

    exit_code = snapshot_main([task.task_id, "--as-of", "2026-09-20T23:30:00"])

    assert exit_code == 0
    expected = (
        tmp_path / "data" / "lab" / "snapshots" / task.task_id / "2026-09-20T23:30:00.parquet"
    )
    assert expected.is_file()
    restored = read_snapshot(
        task, "2026-09-20T23:30:00", snapshots_dir=tmp_path / "data" / "lab" / "snapshots"
    )
    direct = load_training_data(task, runtime, as_of=AS_OF)
    pd.testing.assert_frame_equal(restored.load, direct.load)
    pd.testing.assert_frame_equal(restored.weather, direct.weather)
    assert restored.validation_start == direct.validation_start


THREE_POINTS = ["Taipei", "Taichung", "Kaohsiung"]
THREE_POINT_WEIGHTS = [0.5, 0.3, 0.2]


@pytest.fixture
def weighted_task(task: TaskDefinition) -> TaskDefinition:
    weather = build_weather_spec(
        THREE_POINTS, THREE_POINT_WEIGHTS, task.weather.fields, DEFAULT_CWA_LOCATIONS
    )
    return replace(task, weather=weather)


@pytest.fixture
def three_point_runtime(test_repo: TimeSeriesRepository) -> TaskRuntime:
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    write_derived_load(test_repo.engine, load)
    for offset, location in enumerate(THREE_POINTS):
        shifted = weather.assign(temperature=weather["temperature"] + offset, location=location)
        test_repo.cwa_weather_store.upsert_cwa_observation_batch(
            canonical_observation_batch(shifted)
        )
    return task_runtime(test_repo)


def test_weather_variants_of_one_as_of_are_frozen_side_by_side(
    task: TaskDefinition,
    weighted_task: TaskDefinition,
    three_point_runtime: TaskRuntime,
    tmp_path: Path,
) -> None:
    """Seam: write_snapshot / read_snapshot with variant; candidates with other weather keep their own file."""
    snapshots_dir = tmp_path / "snapshots"

    baseline_path = write_snapshot(task, three_point_runtime, AS_OF, snapshots_dir=snapshots_dir)
    weighted_path = write_snapshot(
        weighted_task,
        three_point_runtime,
        AS_OF,
        variant="three-point",
        snapshots_dir=snapshots_dir,
    )

    assert weighted_path == (
        snapshots_dir / task.task_id / "three-point" / "2026-09-20T23:30:00.parquet"
    )
    assert weighted_path == snapshot_path(
        weighted_task, AS_OF, variant="three-point", snapshots_dir=snapshots_dir
    )
    restored = read_snapshot(
        weighted_task, AS_OF, variant="three-point", snapshots_dir=snapshots_dir
    )
    direct = load_training_data(weighted_task, three_point_runtime, as_of=AS_OF)
    pd.testing.assert_frame_equal(restored.weather, direct.weather)
    baseline = read_snapshot(task, AS_OF, snapshots_dir=snapshots_dir)
    assert baseline_path.is_file()
    assert not baseline.weather["temperature"].equals(restored.weather["temperature"])


def test_reading_a_snapshot_with_other_weather_is_refused(
    task: TaskDefinition,
    weighted_task: TaskDefinition,
    three_point_runtime: TaskRuntime,
    tmp_path: Path,
) -> None:
    """Seam: read_snapshot refuses a task whose weighted weather differs from the frozen one."""
    snapshots_dir = tmp_path / "snapshots"
    write_snapshot(
        weighted_task,
        three_point_runtime,
        AS_OF,
        variant="three-point",
        snapshots_dir=snapshots_dir,
    )

    with pytest.raises(SnapshotWeatherMismatchError, match="Taichung"):
        read_snapshot(task, AS_OF, variant="three-point", snapshots_dir=snapshots_dir)


def test_snapshot_without_recorded_weather_still_reads(
    task: TaskDefinition, runtime: TaskRuntime, tmp_path: Path
) -> None:
    """Seam: snapshots frozen before weather was recorded (e.g. the 2026-11-08 study) stay readable."""
    snapshots_dir = tmp_path / "snapshots"
    path = write_snapshot(task, runtime, AS_OF, snapshots_dir=snapshots_dir)
    legacy = pd.read_parquet(path)
    legacy.attrs = {}
    legacy.to_parquet(path, index=False)

    restored = read_snapshot(task, AS_OF, snapshots_dir=snapshots_dir)

    pd.testing.assert_frame_equal(
        restored.load, load_training_data(task, runtime, as_of=AS_OF).load
    )


@pytest.mark.parametrize("variant", ["", "Three Point", "../escape", "three/point"])
def test_variant_must_be_a_plain_lowercase_name(
    task: TaskDefinition, tmp_path: Path, variant: str
) -> None:
    with pytest.raises(ValueError, match="variant"):
        snapshot_path(task, AS_OF, variant=variant, snapshots_dir=tmp_path)


def test_snapshot_cli_freezes_a_weather_variant(
    task: TaskDefinition,
    weighted_task: TaskDefinition,
    three_point_runtime: TaskRuntime,
    test_repo: TimeSeriesRepository,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seam: python -m lab.snapshot <task_id> --as-of <ISO> --variant <name> --reference-points ... --weights ..."""
    import lab.snapshot as snapshot_mod

    monkeypatch.setattr(snapshot_mod, "deployed_task", lambda task_id: task)
    monkeypatch.setattr(snapshot_mod, "TimeSeriesRepository", lambda: test_repo)
    snapshots_dir = tmp_path / "snapshots"

    exit_code = snapshot_main(
        [
            task.task_id,
            "--as-of",
            "2026-09-20T23:30:00",
            "--snapshots-dir",
            str(snapshots_dir),
            "--variant",
            "three-point",
            "--reference-points",
            *THREE_POINTS,
            "--weights",
            *(str(weight) for weight in THREE_POINT_WEIGHTS),
        ]
    )

    assert exit_code == 0
    restored = read_snapshot(
        weighted_task, AS_OF, variant="three-point", snapshots_dir=snapshots_dir
    )
    direct = load_training_data(weighted_task, three_point_runtime, as_of=AS_OF)
    pd.testing.assert_frame_equal(restored.weather, direct.weather)


def test_snapshot_cli_requires_a_variant_for_other_weather(
    task: TaskDefinition, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seam: a weather override without --variant would take the shipped weather's file name."""
    import lab.snapshot as snapshot_mod

    monkeypatch.setattr(snapshot_mod, "deployed_task", lambda task_id: task)

    with pytest.raises(SystemExit):
        snapshot_main(
            [task.task_id, "--as-of", "2026-09-20T23:30:00", "--reference-points", "Taichung"]
        )


def test_src_never_imports_lab() -> None:
    """ADR-0011: dependency direction is strictly lab -> shiro_mlops; src/ never imports lab."""
    src_dir = Path(__file__).resolve().parents[2] / "src"
    offenders: list[str] = []
    for path in src_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                alias.name.split(".")[0] == "lab" for alias in node.names
            ):
                offenders.append(str(path.relative_to(src_dir)))
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.level == 0
                and node.module.split(".")[0] == "lab"
            ):
                offenders.append(str(path.relative_to(src_dir)))

    assert offenders == []


# --- a snapshot is written whole, once, and never ahead of the clock ------------------------


def test_write_snapshot_refuses_an_as_of_the_clock_has_not_reached(
    task: TaskDefinition, runtime: TaskRuntime, tmp_path: Path
) -> None:
    """Frozen under a future label, the file would hold data only up to today and never refresh."""
    snapshots_dir = tmp_path / "snapshots"

    with pytest.raises(ValueError, match="later than the current time"):
        write_snapshot(task, runtime, "2999-01-01T00:00:00", snapshots_dir=snapshots_dir)

    assert not snapshots_dir.exists() or list(snapshots_dir.rglob("*.parquet")) == []


def test_an_interrupted_write_leaves_no_snapshot_behind(
    task: TaskDefinition,
    runtime: TaskRuntime,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial file at the final path could never be rewritten and could not be read."""
    snapshots_dir = tmp_path / "snapshots"
    real_to_parquet = pd.DataFrame.to_parquet

    def fail_mid_write(frame: pd.DataFrame, path: object, **kwargs: object) -> None:
        Path(str(path)).write_bytes(b"PAR1-truncated")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fail_mid_write)
    with pytest.raises(OSError, match="No space left"):
        write_snapshot(task, runtime, AS_OF, snapshots_dir=snapshots_dir)
    assert [path for path in snapshots_dir.rglob("*") if path.is_file()] == []

    monkeypatch.setattr(pd.DataFrame, "to_parquet", real_to_parquet)
    written = write_snapshot(task, runtime, AS_OF, snapshots_dir=snapshots_dir)

    assert [path for path in snapshots_dir.rglob("*") if path.is_file()] == [written]
    assert not read_snapshot(task, AS_OF, snapshots_dir=snapshots_dir).load.empty


def test_a_snapshot_that_appears_during_the_write_is_not_overwritten(
    task: TaskDefinition,
    runtime: TaskRuntime,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two runs freezing the same snapshot: the second to finish must lose, not replace."""
    snapshots_dir = tmp_path / "snapshots"
    target = snapshot_path(task, AS_OF, snapshots_dir=snapshots_dir)
    real_to_parquet = pd.DataFrame.to_parquet

    def another_run_finishes_first(frame: pd.DataFrame, path: object, **kwargs: object) -> None:
        real_to_parquet(frame, path, **kwargs)
        target.write_bytes(b"written-by-the-other-run")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", another_run_finishes_first)

    with pytest.raises(FileExistsError, match=task.task_id):
        write_snapshot(task, runtime, AS_OF, snapshots_dir=snapshots_dir)

    assert target.read_bytes() == b"written-by-the-other-run"
    assert [path for path in snapshots_dir.rglob("*") if path.is_file()] == [target]
