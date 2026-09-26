"""Contract tests for training and drift jobs reading persisted hourly actual load."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from dagster import (
    AssetMaterialization,
    Definitions,
    build_schedule_context,
    load_assets_from_modules,
)

from shiro_mlops.core.config import settings
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.pipelines import assets as assets_module
from shiro_mlops.pipelines import schedules as schedules_module
from shiro_mlops.pipelines.definitions import defs
from shiro_mlops.pipelines.schedules import (
    CWA_INGESTION_ASSETS,
    TAIPOWER_REALTIME_SNAPSHOT_ASSETS,
    daily_training_job,
    daily_training_schedule,
    hourly_drift_job,
    hourly_drift_schedule,
)
from tests.helpers import derived_hourly_load

TICK = datetime(2026, 9, 27, 0, 0, tzinfo=ZoneInfo("Asia/Taipei"))
LAST_HOUR = datetime(2026, 9, 26, 23, 0)
LOAD_FEATURE_SOURCE = "taipower_load_feature_source"
# 由區域快照推算的資產；訓練與 drift 只能讀它寫入的資料表，不能執行它。
DERIVATION_ASSET = "raw_taipower_load"


def _selected(job) -> set[str]:
    assets = load_assets_from_modules([assets_module])
    return {key.to_user_string() for key in job.selection.resolve(assets)}


def _tick(schedule, repository: TimeSeriesRepository, instance):
    context = build_schedule_context(
        instance=instance,
        scheduled_execution_time=TICK,
        resources={"time_series_repo": repository},
    )
    return schedule.evaluate_tick(context)


@pytest.fixture
def min_hours(monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(settings, "TRAINING_MIN_LOAD_HOURS", 24)
    return 24


@pytest.mark.parametrize("job", [daily_training_job, hourly_drift_job], ids=lambda job: job.name)
def test_load_consumers_read_persisted_load_without_snapshots_or_external_apis(job) -> None:
    selected = _selected(job)

    assert LOAD_FEATURE_SOURCE in selected
    assert "drift_monitoring_report" in selected
    assert selected.isdisjoint(TAIPOWER_REALTIME_SNAPSHOT_ASSETS)
    assert selected.isdisjoint(CWA_INGESTION_ASSETS)
    assert DERIVATION_ASSET not in selected


def test_training_job_runs_features_model_and_report() -> None:
    assert _selected(daily_training_job) == {
        "taipower_load_feature_source",
        "cwa_observation_feature_source",
        "engineered_features",
        "taipower_features",
        "weather_features",
        "trained_forecaster_model",
        "drift_monitoring_report",
    }


def test_deployed_definitions_provide_the_store_that_readiness_schedules_query() -> None:
    Definitions.validate_loadable(defs)

    for name in ("daily_training_schedule", "hourly_drift_schedule"):
        assert defs.resolve_schedule_def(name).required_resource_keys == {"time_series_repo"}


def test_fixed_historical_load_deferment_is_removed() -> None:
    assert not hasattr(schedules_module, "HISTORICAL_LOAD_DEFERMENT_REASON")


def test_daily_training_skips_with_accumulation_reason_during_cold_start(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int
) -> None:
    test_repo.upsert_taipower_load(derived_hourly_load(min_hours - 1, LAST_HOUR))

    execution = _tick(daily_training_schedule, test_repo, dagster_instance)

    assert execution.run_requests == []
    assert "23 valid hourly observations" in execution.skip_message
    assert "24 required" in execution.skip_message


def test_daily_training_triggers_once_accumulation_is_sufficient(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int
) -> None:
    test_repo.upsert_taipower_load(derived_hourly_load(min_hours, LAST_HOUR))

    execution = _tick(daily_training_schedule, test_repo, dagster_instance)

    assert execution.skip_message is None
    assert len(execution.run_requests) == 1


def test_hourly_drift_skips_until_a_model_has_been_trained(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int
) -> None:
    test_repo.upsert_taipower_load(derived_hourly_load(min_hours, LAST_HOUR))

    execution = _tick(hourly_drift_schedule, test_repo, dagster_instance)

    assert execution.run_requests == []
    assert "trained_forecaster_model" in execution.skip_message


def test_hourly_drift_skips_with_accumulation_reason_during_cold_start(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int
) -> None:
    execution = _tick(hourly_drift_schedule, test_repo, dagster_instance)

    assert execution.run_requests == []
    assert "0 valid hourly observations" in execution.skip_message


def test_hourly_drift_triggers_after_training_materialized_a_model(
    test_repo: TimeSeriesRepository, dagster_instance, min_hours: int
) -> None:
    test_repo.upsert_taipower_load(derived_hourly_load(min_hours, LAST_HOUR))
    dagster_instance.report_runless_asset_event(AssetMaterialization("trained_forecaster_model"))

    execution = _tick(hourly_drift_schedule, test_repo, dagster_instance)

    assert execution.skip_message is None
    assert len(execution.run_requests) == 1
