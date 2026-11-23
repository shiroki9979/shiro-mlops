"""Contract tests for the minimum hourly-load accumulation required before training."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, text

from shiro_mlops.core.database import ensure_timescale_hypertables
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task
from shiro_mlops.tasks.runner import check_training_readiness
from tests.helpers import (
    create_legacy_load_table,
    derived_hourly_load,
    insert_legacy_load_row,
    override_task_policies,
    task_runtime,
    write_derived_load,
)

LAST_HOUR = datetime(2026, 9, 26, 13, 0)
# ADR-0008：累積滿 28 日（672 小時）前不得訓練。
TWENTY_EIGHT_DAYS_HOURS = 672


def _readiness(repository: TimeSeriesRepository, *, as_of: datetime | None = None):
    return check_training_readiness(
        deployed_task(DYNAMIC_HORIZON_FORECAST), task_runtime(repository), as_of=as_of
    )


def test_training_min_load_hours_defaults_to_twenty_eight_days() -> None:
    task = deployed_task(DYNAMIC_HORIZON_FORECAST)

    assert task.policies.min_training_hours == TWENTY_EIGHT_DAYS_HOURS


def test_empty_load_table_is_not_ready_and_discloses_the_gap(
    test_repo: TimeSeriesRepository,
) -> None:
    readiness = _readiness(test_repo)

    assert not readiness.ready
    assert readiness.valid_hours == 0
    assert readiness.latest_hour is None
    assert "0 valid hourly observations" in readiness.reason
    assert "672 required" in readiness.reason


def test_one_hour_short_of_the_threshold_is_not_ready(test_repo: TimeSeriesRepository) -> None:
    write_derived_load(test_repo.engine, derived_hourly_load(671, LAST_HOUR))

    readiness = _readiness(test_repo)

    assert not readiness.ready
    assert readiness.valid_hours == 671
    assert "671 valid hourly observations" in readiness.reason
    assert "1 more hour" in readiness.reason


def test_threshold_reached_is_ready_and_reports_latest_hour(
    test_repo: TimeSeriesRepository,
) -> None:
    write_derived_load(test_repo.engine, derived_hourly_load(672, LAST_HOUR))

    readiness = _readiness(test_repo)

    assert readiness.ready
    assert readiness.valid_hours == 672
    assert readiness.latest_hour == LAST_HOUR


def test_legacy_rows_block_training_even_when_threshold_is_met(tmp_path, monkeypatch) -> None:
    """Under ADR-0008, remove d015046 legacy rows before training to avoid mixing load bases."""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    try:
        create_legacy_load_table(engine)
        ensure_timescale_hypertables(engine)
        repository = TimeSeriesRepository(engine=engine, auto_init=False)
        write_derived_load(repository.engine, derived_hourly_load(3, LAST_HOUR))

        override_task_policies(monkeypatch, min_training_hours=3)
        readiness = _readiness(repository)
    finally:
        engine.dispose()

    assert not readiness.ready
    assert readiness.valid_hours == 3
    assert readiness.legacy_rows == 1
    assert "legacy" in readiness.reason
    assert "remove-legacy-d015046-load-rows" in readiness.reason


@pytest.mark.parametrize("legacy_subject", ["nationwide", "north"])
def test_legacy_rows_after_as_of_still_block_training(
    tmp_path, monkeypatch, legacy_subject: str
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'future-legacy.db'}")
    try:
        create_legacy_load_table(engine)
        ensure_timescale_hypertables(engine)
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM raw_taipower_load"))
        repository = TimeSeriesRepository(engine=engine, auto_init=False)
        write_derived_load(repository.engine, derived_hourly_load(3, LAST_HOUR))
        insert_legacy_load_row(
            engine, LAST_HOUR + timedelta(hours=1), 26000.0, subject=legacy_subject
        )

        override_task_policies(monkeypatch, min_training_hours=3)
        readiness = _readiness(repository, as_of=LAST_HOUR)
    finally:
        engine.dispose()

    assert not readiness.ready
    assert readiness.valid_hours == 3
    assert readiness.legacy_rows == 1
    assert readiness.latest_hour == LAST_HOUR
