"""Contract tests for the minimum hourly-load accumulation required before training."""

from datetime import datetime

from sqlalchemy import create_engine

from shiro_mlops.core.config import Settings
from shiro_mlops.core.database import ensure_timescale_hypertables
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.pipelines.readiness import check_training_load_readiness
from tests.helpers import create_legacy_load_table, derived_hourly_load

LAST_HOUR = datetime(2026, 9, 26, 13, 0)
# ADR-0008：累積滿 28 日（672 小時）前不得訓練。
TWENTY_EIGHT_DAYS_HOURS = 672


def test_training_min_load_hours_defaults_to_twenty_eight_days() -> None:
    assert Settings(_env_file=None).TRAINING_MIN_LOAD_HOURS == TWENTY_EIGHT_DAYS_HOURS


def test_empty_load_table_is_not_ready_and_discloses_the_gap(
    test_repo: TimeSeriesRepository,
) -> None:
    readiness = check_training_load_readiness(test_repo, required_hours=672)

    assert not readiness.ready
    assert readiness.valid_hours == 0
    assert readiness.latest_hour is None
    assert "0 valid hourly observations" in readiness.reason
    assert "672 required" in readiness.reason


def test_one_hour_short_of_the_threshold_is_not_ready(test_repo: TimeSeriesRepository) -> None:
    test_repo.upsert_taipower_load(derived_hourly_load(671, LAST_HOUR))

    readiness = check_training_load_readiness(test_repo, required_hours=672)

    assert not readiness.ready
    assert readiness.valid_hours == 671
    assert "671 valid hourly observations" in readiness.reason
    assert "1 more hour" in readiness.reason


def test_threshold_reached_is_ready_and_reports_latest_hour(
    test_repo: TimeSeriesRepository,
) -> None:
    test_repo.upsert_taipower_load(derived_hourly_load(672, LAST_HOUR))

    readiness = check_training_load_readiness(test_repo, required_hours=672)

    assert readiness.ready
    assert readiness.valid_hours == 672
    assert readiness.latest_hour == LAST_HOUR


def test_legacy_rows_block_training_even_when_threshold_is_met(tmp_path) -> None:
    """ADR-0008：d015046 時期舊列須清除後才能訓練，避免不同口徑混用。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    try:
        create_legacy_load_table(engine)
        ensure_timescale_hypertables(engine)
        repository = TimeSeriesRepository(engine=engine, auto_init=False)
        repository.upsert_taipower_load(derived_hourly_load(3, LAST_HOUR))

        readiness = check_training_load_readiness(repository, required_hours=3)
    finally:
        engine.dispose()

    assert not readiness.ready
    assert readiness.valid_hours == 3
    assert readiness.legacy_rows == 1
    assert "legacy" in readiness.reason
    assert "remove-legacy-d015046-load-rows" in readiness.reason
