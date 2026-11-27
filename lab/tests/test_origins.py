"""Offline unit tests for lab.origins (public seam: main CLI)."""

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest
from lab.origins import main as origins_main
from lab.snapshot import write_snapshot
from shiro_mlops.core.database import ensure_timescale_hypertables
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task
from sqlalchemy import create_engine
from tests.helpers import (
    canonical_observation_batch,
    hourly_load_with_weather,
    task_runtime,
    write_derived_load,
)

LAST_HOUR = datetime(2026, 9, 20, 23, 0)
HOURS = 24 * 21
AS_OF = "2026-09-20T23:30:00"


@pytest.fixture
def task() -> TaskDefinition:
    shipped = deployed_task(DYNAMIC_HORIZON_FORECAST)
    policies = shipped.policies.model_copy(update={"min_training_hours": 24 * 9})
    return replace(shipped, policies=policies)


@pytest.fixture
def snapshots_dir(task: TaskDefinition, tmp_path: Path) -> Path:
    return _write_snapshot(task, tmp_path)


@pytest.fixture
def gapped_snapshots_dir(task: TaskDefinition, tmp_path: Path) -> Path:
    return _write_snapshot(task, tmp_path, missing_load=LOAD_GAP)


LOAD_GAP = pd.date_range("2026-09-15T10:00", "2026-09-15T12:00", freq="h")


def _write_snapshot(
    task: TaskDefinition, tmp_path: Path, missing_load: pd.DatetimeIndex | None = None
) -> Path:
    engine = create_engine(f"sqlite:///{tmp_path / 'origins.db'}")
    ensure_timescale_hypertables(engine)
    repository = TimeSeriesRepository(engine=engine)
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    if missing_load is not None:
        load = load[~load["datetime"].isin(missing_load)]
    write_derived_load(repository.engine, load)
    repository.cwa_weather_store.upsert_cwa_observation_batch(
        canonical_observation_batch(weather.assign(location="Taipei"))
    )
    directory = tmp_path / "snapshots"
    write_snapshot(task, task_runtime(repository), AS_OF, snapshots_dir=directory)
    return directory


def _run(
    task: TaskDefinition,
    snapshots_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *extra: str,
) -> str:
    monkeypatch.setattr("lab.origins.deployed_task", lambda task_id: task)
    exit_code = origins_main(
        [task.task_id, "--as-of", AS_OF, "--snapshots-dir", str(snapshots_dir), *extra]
    )
    assert exit_code == 0
    return capsys.readouterr().out


def test_cli_lists_eligible_origins_and_a_sufficient_split(
    task: TaskDefinition,
    snapshots_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # 資料自 08-31 00:00 起；第 216 小時（09-08 23:00）達最低累積，最後一個起點須留 24 小時目標時段。
    output = _run(task, snapshots_dir, monkeypatch, capsys, "--eval-days", "3")

    assert "eligible origins: 265" in output
    assert "run: 2026-09-08T23:00:00 .. 2026-09-19T23:00:00 (265 h)" in output
    assert "eval origins: 12 (2026-09-17T00:00:00 .. 2026-09-19T18:00:00)" in output
    assert "search origins: 29 (2026-09-09T00:00:00 .. 2026-09-16T00:00:00)" in output
    assert "sufficient: yes" in output


def test_cli_reports_when_the_snapshot_cannot_cover_the_evaluation_days(
    task: TaskDefinition,
    snapshots_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = _run(task, snapshots_dir, monkeypatch, capsys, "--eval-days", "12")

    assert "split: unavailable" in output
    assert "sufficient: no" in output


def test_cli_explain_groups_rejected_origins_by_the_failed_check(
    task: TaskDefinition,
    gapped_snapshots_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # 負載缺 09-15 10:00–12:00：目標時段含缺口的 24 個起點先被拒，缺口進入 168 小時 lookback 後其餘起點全被拒。
    output = _run(task, gapped_snapshots_dir, monkeypatch, capsys, "--explain")

    assert "run: 2026-09-08T23:00:00 .. 2026-09-14T09:00:00 (131 h)" in output
    assert "rejected: 2026-08-31T00:00:00 .. 2026-09-08T22:00:00 (215 h): minimum history" in output
    assert (
        "rejected: 2026-09-14T10:00:00 .. 2026-09-15T09:00:00 (24 h): horizon load completeness"
        in output
    )
    assert (
        "rejected: 2026-09-15T10:00:00 .. 2026-09-19T23:00:00 (110 h): lookback load completeness"
        in output
    )
    assert "first missing: 2026-09-15T10:00:00" in output


def test_cli_omits_rejections_without_explain(
    task: TaskDefinition,
    gapped_snapshots_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = _run(task, gapped_snapshots_dir, monkeypatch, capsys)

    assert "rejected:" not in output
