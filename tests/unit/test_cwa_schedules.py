"""Contract tests for independent CWA Dagster schedules."""

from datetime import datetime
from zoneinfo import ZoneInfo

from dagster import Backoff, build_schedule_context

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


def test_cwa_jobs_use_bounded_exponential_retry_policy() -> None:
    """docs/reference/dagster-schedules.md items 3–4: three retries backing off exponentially from thirty seconds."""
    assert CWA_INGESTION_RETRY_POLICY.max_retries == 3
    assert CWA_INGESTION_RETRY_POLICY.delay == 30
    assert CWA_INGESTION_RETRY_POLICY.backoff == Backoff.EXPONENTIAL
    assert cwa_observation_job.name == "cwa_observation_ingestion_job"
    assert cwa_forecast_job.name == "cwa_forecast_ingestion_job"
    for job in (cwa_observation_job, cwa_forecast_job):
        assert job.op_retry_policy == CWA_INGESTION_RETRY_POLICY


def test_cwa_schedules_continue_to_request_independent_runs() -> None:
    """CWA ingestion remains independent of load accumulation and continues requesting its own runs."""
    context = build_schedule_context(
        scheduled_execution_time=datetime(2026, 9, 17, 8, 10, tzinfo=ZoneInfo("Asia/Taipei"))
    )

    for cwa_schedule in (cwa_observation_schedule, cwa_forecast_schedule):
        execution = cwa_schedule.evaluate_tick(context)
        assert execution.skip_message is None
        assert len(execution.run_requests) == 1
