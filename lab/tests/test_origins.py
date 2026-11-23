"""Offline unit tests for lab.origins (public seam: main CLI)."""

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from lab.origins import main as origins_main
from lab.snapshot import write_snapshot
from shiro_mlops.core.database import ensure_timescale_hypertables
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task
from shiro_mlops.tasks.runner import TaskRuntime
from sqlalchemy import create_engine
from tests.helpers import canonical_observation_batch, hourly_load_with_weather, write_derived_load

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
    engine = create_engine(f"sqlite:///{tmp_path / 'origins.db'}")
    ensure_timescale_hypertables(engine)
    repository = TimeSeriesRepository(engine=engine)
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    write_derived_load(repository.engine, load)
    repository.cwa_weather_store.upsert_cwa_observation_batch(
        canonical_observation_batch(weather.assign(location="Taipei"))
    )
    directory = tmp_path / "snapshots"
    write_snapshot(task, TaskRuntime(repository=repository), AS_OF, snapshots_dir=directory)
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
