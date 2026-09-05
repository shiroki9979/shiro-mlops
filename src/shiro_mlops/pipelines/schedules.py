"""Dagster schedule definitions for Taipower MLOps pipeline."""

from datetime import datetime
from zoneinfo import ZoneInfo

from dagster import (
    AssetSelection,
    RetryPolicy,
    RunRequest,
    ScheduleDefinition,
    ScheduleEvaluationContext,
    define_asset_job,
    schedule,
)

from shiro_mlops.core.datetime_utils import TAIWAN_TZ
from shiro_mlops.data.taipower_supply_demand import floor_to_ten_minutes

TAIPOWER_REALTIME_SNAPSHOT_ASSETS = (
    "raw_taipower_supply_demand_snapshot",
    "raw_taipower_regional_supply_demand_snapshot",
    "raw_taipower_unit_generation_snapshot",
)

# 暫時性來源失敗時，同一 run 內最多再試 2 次（含首次共 3 次），間隔 10 秒。
TAIPOWER_REALTIME_SNAPSHOT_RETRY_POLICY = RetryPolicy(max_retries=2, delay=10)

# 1. Daily Training and Evaluation Job
daily_training_job = define_asset_job(
    name="daily_training_job",
    selection=AssetSelection.all() - AssetSelection.assets(*TAIPOWER_REALTIME_SNAPSHOT_ASSETS),
    description="Run ingestion, feature engineering, model training, and drift evaluation",
)

daily_training_schedule = ScheduleDefinition(
    job=daily_training_job,
    cron_schedule="0 16 * * *",  # 16:00 UTC (00:00 Taipei time)
    description="Daily retrain schedule at midnight Taipei time",
)

# 2. Hourly Drift and Monitoring Job
hourly_drift_job = define_asset_job(
    name="hourly_drift_job",
    selection=AssetSelection.assets(
        "raw_taipower_load_data", "raw_weather_obs_data", "drift_monitoring_report"
    ),
    description="Check latest actual load against previous forecasts",
)

hourly_drift_schedule = ScheduleDefinition(
    job=hourly_drift_job,
    cron_schedule="0 * * * *",  # Every hour
    description="Hourly drift evaluation schedule",
)


# 3. Taipower realtime snapshot ingestion (national / regional / unit)
def build_taipower_supply_demand_snapshot_job(
    op_retry_policy: RetryPolicy | None = TAIPOWER_REALTIME_SNAPSHOT_RETRY_POLICY,
):
    """Build the Taipower realtime snapshot ingestion asset job."""
    return define_asset_job(
        name="taipower_supply_demand_snapshot_job",
        selection=AssetSelection.assets(*TAIPOWER_REALTIME_SNAPSHOT_ASSETS),
        description="Fetch Taipower national, regional, and unit realtime snapshots",
        op_retry_policy=op_retry_policy,
    )


taipower_supply_demand_snapshot_job = build_taipower_supply_demand_snapshot_job()


def _taiwan_tick_iso(scheduled_execution_time: datetime) -> str:
    """Normalize a schedule tick to a Taiwan-local 10-minute ISO observation slot."""
    if scheduled_execution_time.tzinfo is None:
        local_tick = scheduled_execution_time
    else:
        local_tick = scheduled_execution_time.astimezone(ZoneInfo(TAIWAN_TZ)).replace(tzinfo=None)
    return floor_to_ten_minutes(local_tick).isoformat(timespec="seconds")


@schedule(
    job=taipower_supply_demand_snapshot_job,
    cron_schedule="*/10 * * * *",
    execution_timezone=TAIWAN_TZ,
)
def taipower_supply_demand_snapshot_schedule(
    context: ScheduleEvaluationContext,
) -> RunRequest:
    """Every 10 minutes, materialize all realtime snapshots with a shared observed_at."""
    observed_at = _taiwan_tick_iso(context.scheduled_execution_time)
    ops_config = {
        asset_name: {"config": {"observed_at": observed_at}}
        for asset_name in TAIPOWER_REALTIME_SNAPSHOT_ASSETS
    }
    return RunRequest(
        run_key=observed_at,
        run_config={"ops": ops_config},
    )
