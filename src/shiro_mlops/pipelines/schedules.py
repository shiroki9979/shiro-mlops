"""Dagster jobs and schedules for the shared ingestion assets.

Per-task training and monitoring jobs and schedules come from the asset factory
in ``pipelines/task_pipelines.py``.
"""

from dagster import (
    AssetSelection,
    Backoff,
    RetryPolicy,
    RunRequest,
    ScheduleDefinition,
    ScheduleEvaluationContext,
    define_asset_job,
    schedule,
)

from shiro_mlops.core.datetime_utils import TAIWAN_TZ
from shiro_mlops.pipelines.execution_origin import tick_run_key, tick_run_request

TAIPOWER_REALTIME_SNAPSHOT_ASSETS = (
    "raw_taipower_supply_demand_snapshot",
    "raw_taipower_regional_supply_demand_snapshot",
    "raw_taipower_unit_generation_snapshot",
)

# 將短暫網路抖動限制在 20 秒內，避免重試延伸至下一個 10 分鐘排程 slot。
# 含首次嘗試最多重試 2 次，每次間隔 10 秒。
TAIPOWER_REALTIME_SNAPSHOT_RETRY_POLICY = RetryPolicy(max_retries=2, delay=10)

# CWA 排程每小時一次，較長的指數退避可跨越短暫上游 5xx；Dagster 依序等待 30／90／210 秒，
# 用盡後仍遠早於下一個整點 slot。
CWA_INGESTION_RETRY_POLICY = RetryPolicy(max_retries=3, delay=30, backoff=Backoff.EXPONENTIAL)
CWA_OBSERVATION_ASSET = "raw_cwa_station_observation"
CWA_FORECAST_ASSET = "raw_cwa_township_forecast"
CWA_INGESTION_ASSETS = (CWA_OBSERVATION_ASSET, CWA_FORECAST_ASSET)
HOURLY_ACTUAL_LOAD_ASSET = "raw_taipower_load"


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


# 台電即時快照擷取（全台／區域／機組）
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


@schedule(
    job=taipower_supply_demand_snapshot_job,
    cron_schedule="*/10 * * * *",
    execution_timezone=TAIWAN_TZ,
)
def taipower_supply_demand_snapshot_schedule(
    context: ScheduleEvaluationContext,
) -> RunRequest:
    """每十分鐘 materialize 全部即時快照；三者從同一個 run 的 as_of 取整出同一個觀測 slot。"""
    return tick_run_request(context)


# 全台逐時實際負載推算（只讀區域快照資料表，不呼叫台電外部 API）
hourly_actual_load_job = define_asset_job(
    name="hourly_actual_load_job",
    selection=AssetSelection.assets(HOURLY_ACTUAL_LOAD_ASSET),
    description="Derive nationwide hourly actual load from stored regional snapshots",
)


@schedule(
    job=hourly_actual_load_job,
    # 第 5 分鐘觸發，讓整點前最後一個 10 分鐘快照及其重試有時間入庫。
    cron_schedule="5 * * * *",
    execution_timezone=TAIWAN_TZ,
)
def hourly_actual_load_schedule(context: ScheduleEvaluationContext) -> RunRequest:
    """Use the tick to make each hourly recompute window stable across retries.

    Manual evaluations have no tick, run key, or evaluated_at; the run chooses
    its window from the current time.
    """
    evaluated_at = tick_run_key(context)
    if evaluated_at is None:
        return RunRequest()
    return RunRequest(
        run_key=evaluated_at,
        run_config={"ops": {HOURLY_ACTUAL_LOAD_ASSET: {"config": {"evaluated_at": evaluated_at}}}},
    )
