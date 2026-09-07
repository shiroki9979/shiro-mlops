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

# 將短暫網路抖動限制在 20 秒內，避免重試延伸至下一個 10 分鐘排程 slot。
# 含首次嘗試最多重試 2 次，每次間隔 10 秒。
TAIPOWER_REALTIME_SNAPSHOT_RETRY_POLICY = RetryPolicy(max_retries=2, delay=10)

CWA_INGESTION_RETRY_POLICY = RetryPolicy(max_retries=2, delay=10)
CWA_OBSERVATION_ASSET = "raw_cwa_station_observation"
CWA_FORECAST_ASSET = "raw_cwa_township_forecast"
CWA_INGESTION_ASSETS = (CWA_OBSERVATION_ASSET, CWA_FORECAST_ASSET)

# 1. Daily Training and Evaluation Job
daily_training_job = define_asset_job(
    name="daily_training_job",
    selection=(
        AssetSelection.all()
        - AssetSelection.assets(*TAIPOWER_REALTIME_SNAPSHOT_ASSETS)
        - AssetSelection.assets(*CWA_INGESTION_ASSETS)
    ),
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
    selection=AssetSelection.assets("raw_taipower_load_data", "drift_monitoring_report"),
    description="Check latest actual load against previous forecasts",
)

hourly_drift_schedule = ScheduleDefinition(
    job=hourly_drift_job,
    cron_schedule="0 * * * *",  # Every hour
    description="Hourly drift evaluation schedule",
)


cwa_observation_job = define_asset_job(
    name="cwa_observation_ingestion_job",
    selection=AssetSelection.assets(CWA_OBSERVATION_ASSET),
    description="Fetch canonical CWA hourly station observations",
    op_retry_policy=CWA_INGESTION_RETRY_POLICY,
)

cwa_observation_schedule = ScheduleDefinition(
    job=cwa_observation_job,
    cron_schedule="10 * * * *",
    execution_timezone=TAIWAN_TZ,
    description="Fetch CWA station observations at ten minutes past each hour",
)


cwa_forecast_job = define_asset_job(
    name="cwa_forecast_ingestion_job",
    selection=AssetSelection.assets(CWA_FORECAST_ASSET),
    description="Fetch canonical CWA township forecast vintages",
    op_retry_policy=CWA_INGESTION_RETRY_POLICY,
)

cwa_forecast_schedule = ScheduleDefinition(
    job=cwa_forecast_job,
    cron_schedule="40 * * * *",
    execution_timezone=TAIWAN_TZ,
    description="Fetch CWA township forecasts at forty minutes past each hour",
)


# 3. 台電即時快照擷取（全台／區域／機組）
def build_taipower_supply_demand_snapshot_job(
    op_retry_policy: RetryPolicy | None = TAIPOWER_REALTIME_SNAPSHOT_RETRY_POLICY,
):
    """建立台電即時快照擷取資產工作。"""
    return define_asset_job(
        name="taipower_supply_demand_snapshot_job",
        selection=AssetSelection.assets(*TAIPOWER_REALTIME_SNAPSHOT_ASSETS),
        description="Fetch Taipower national, regional, and unit realtime snapshots",
        op_retry_policy=op_retry_policy,
    )


taipower_supply_demand_snapshot_job = build_taipower_supply_demand_snapshot_job()


def _taiwan_tick_iso(scheduled_execution_time: datetime) -> str:
    """將排程 tick 正規化為台灣本地時間的十分快照觀測 slot。"""
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
    """每十分鐘 materialize 全部即時快照，並共用同一個 observed_at。"""
    observed_at = _taiwan_tick_iso(context.scheduled_execution_time)
    ops_config = {
        asset_name: {"config": {"observed_at": observed_at}}
        for asset_name in TAIPOWER_REALTIME_SNAPSHOT_ASSETS
    }
    return RunRequest(
        run_key=observed_at,
        run_config={"ops": ops_config},
    )
