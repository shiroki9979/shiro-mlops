"""Contract tests for independent CWA Dagster schedules."""

from shiro_mlops.pipelines.schedules import (
    CWA_INGESTION_RETRY_POLICY,
    cwa_forecast_job,
    cwa_forecast_schedule,
    cwa_observation_job,
    cwa_observation_schedule,
)


def test_cwa_schedules_are_staggered_and_timezone_aware() -> None:
    assert cwa_observation_schedule.cron_schedule == "10 * * * *"
    assert cwa_forecast_schedule.cron_schedule == "40 * * * *"
    assert cwa_observation_schedule.execution_timezone == "Asia/Taipei"
    assert cwa_forecast_schedule.execution_timezone == "Asia/Taipei"


def test_cwa_jobs_use_bounded_retry_policy() -> None:
    assert CWA_INGESTION_RETRY_POLICY.max_retries == 2
    assert CWA_INGESTION_RETRY_POLICY.delay == 10
    assert cwa_observation_job.name == "cwa_observation_ingestion_job"
    assert cwa_forecast_job.name == "cwa_forecast_ingestion_job"
