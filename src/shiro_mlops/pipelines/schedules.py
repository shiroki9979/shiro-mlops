"""Dagster schedule definitions for Taipower MLOps pipeline."""

from dagster import (
    AssetSelection,
    ScheduleDefinition,
    define_asset_job,
)

# 1. Daily Training and Evaluation Job
daily_training_job = define_asset_job(
    name="daily_training_job",
    selection=AssetSelection.all() - AssetSelection.assets("raw_taipower_supply_demand_snapshot"),
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
