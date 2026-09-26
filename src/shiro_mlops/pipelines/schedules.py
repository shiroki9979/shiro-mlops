"""Dagster schedule definitions for Taipower MLOps pipeline."""

from datetime import datetime
from zoneinfo import ZoneInfo

from dagster import (
    AssetKey,
    AssetSelection,
    Backoff,
    RetryPolicy,
    RunRequest,
    ScheduleDefinition,
    ScheduleEvaluationContext,
    SkipReason,
    define_asset_job,
    schedule,
)

from shiro_mlops.core.config import settings
from shiro_mlops.core.datetime_utils import TAIWAN_TZ
from shiro_mlops.data.taipower_supply_demand import floor_to_ten_minutes
from shiro_mlops.pipelines.readiness import TrainingLoadReadiness, check_training_load_readiness

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
# 只讀 raw_taipower_load 資料表的負載來源；推算資產本身讀區域快照表，不得進入訓練或 drift。
LOAD_FEATURE_SOURCE_ASSET = "taipower_load_feature_source"
TRAINED_MODEL_ASSET = "trained_forecaster_model"
DRIFT_REPORT_ASSET = "drift_monitoring_report"
# 明列而非以 all() 扣除，新增的擷取資產才不會被默默帶進訓練並呼叫外部 API。
TRAINING_ASSETS = (
    LOAD_FEATURE_SOURCE_ASSET,
    "cwa_observation_feature_source",
    "engineered_features",
    "taipower_features",
    "weather_features",
    TRAINED_MODEL_ASSET,
    DRIFT_REPORT_ASSET,
)
DRIFT_ASSETS = (LOAD_FEATURE_SOURCE_ASSET, DRIFT_REPORT_ASSET)
NO_TRAINED_MODEL_REASON = (
    f"No {TRAINED_MODEL_ASSET} materialization yet; "
    "hourly drift waits for the first successful daily_training_job run."
)

# 1. Daily Training and Evaluation Job
daily_training_job = define_asset_job(
    name="daily_training_job",
    selection=AssetSelection.assets(*TRAINING_ASSETS),
    description="Read persisted load and weather, engineer features, train, and report drift",
)


@schedule(
    job=daily_training_job,
    cron_schedule="0 16 * * *",  # 16:00 UTC (00:00 Taipei time)
    description="Daily retrain schedule at midnight Taipei time",
    required_resource_keys={"time_series_repo"},
)
def daily_training_schedule(context: ScheduleEvaluationContext) -> RunRequest | SkipReason:
    """Train only after the minimum hourly-load accumulation; otherwise disclose the gap."""
    readiness = _load_readiness(context)
    if not readiness.ready:
        return SkipReason(readiness.reason)
    return RunRequest(run_key=_tick_run_key(context))


# 2. Hourly Drift and Monitoring Job
hourly_drift_job = define_asset_job(
    name="hourly_drift_job",
    selection=AssetSelection.assets(*DRIFT_ASSETS),
    description="Compare the newest persisted actual load with the latest trained model",
)


@schedule(
    job=hourly_drift_job,
    cron_schedule="0 * * * *",  # Every hour
    description="Hourly drift evaluation schedule",
    required_resource_keys={"time_series_repo"},
)
def hourly_drift_schedule(context: ScheduleEvaluationContext) -> RunRequest | SkipReason:
    """Evaluate drift once load is sufficient and a trained model artifact exists."""
    readiness = _load_readiness(context)
    if not readiness.ready:
        return SkipReason(readiness.reason)
    if context.instance.get_latest_materialization_event(AssetKey(TRAINED_MODEL_ASSET)) is None:
        return SkipReason(NO_TRAINED_MODEL_REASON)
    return RunRequest(run_key=_tick_run_key(context))


def _load_readiness(context: ScheduleEvaluationContext) -> TrainingLoadReadiness:
    return check_training_load_readiness(
        context.resources.time_series_repo, settings.TRAINING_MIN_LOAD_HOURS
    )


def _tick_run_key(context: ScheduleEvaluationContext) -> str | None:
    """同一 tick 重複評估時以 run_key 去重，避免重跑訓練或 drift。"""
    if context.scheduled_execution_time is None:
        return None
    return _to_taiwan_local(context.scheduled_execution_time).isoformat(timespec="seconds")


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


def _to_taiwan_local(scheduled_execution_time: datetime) -> datetime:
    """將排程 tick 轉為無時區的台灣本地時間。"""
    if scheduled_execution_time.tzinfo is None:
        return scheduled_execution_time
    return scheduled_execution_time.astimezone(ZoneInfo(TAIWAN_TZ)).replace(tzinfo=None)


def _taiwan_tick_iso(scheduled_execution_time: datetime) -> str:
    """將排程 tick 正規化為台灣本地時間的十分快照觀測 slot。"""
    local_tick = _to_taiwan_local(scheduled_execution_time)
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


# 4. 全台逐時實際負載推算（只讀區域快照資料表，不呼叫台電外部 API）
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
    """每小時以 tick 時間重算最近已結束的小時，使重跑同一 tick 得到相同窗口。"""
    evaluated_at = _to_taiwan_local(context.scheduled_execution_time).isoformat(timespec="seconds")
    return RunRequest(
        run_key=evaluated_at,
        run_config={"ops": {HOURLY_ACTUAL_LOAD_ASSET: {"config": {"evaluated_at": evaluated_at}}}},
    )
