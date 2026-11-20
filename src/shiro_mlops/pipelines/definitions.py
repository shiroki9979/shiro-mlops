"""Main Dagster Definitions entrypoint."""

from dagster import Definitions, load_assets_from_modules, resource

from shiro_mlops.core.config import settings
from shiro_mlops.core.io_managers import (
    FeastPublicationTarget,
    get_feast_parquet_io_manager,
    get_parquet_io_manager,
)
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.pipelines import assets
from shiro_mlops.pipelines.forecast_track_record import forecast_track_record
from shiro_mlops.pipelines.issued_forecast import (
    issued_forecast,
    issued_forecast_job,
    issued_forecast_schedule,
)
from shiro_mlops.pipelines.schedules import (
    cwa_forecast_job,
    cwa_forecast_schedule,
    cwa_observation_job,
    cwa_observation_schedule,
    hourly_actual_load_job,
    hourly_actual_load_schedule,
    taipower_supply_demand_snapshot_job,
    taipower_supply_demand_snapshot_schedule,
)
from shiro_mlops.pipelines.task_pipelines import build_task_pipelines
from shiro_mlops.tasks.deployed import deployed_tasks

# 任務設定錯誤須在 code location 載入時失敗，而非等到第一次訓練 run。
task_pipelines = build_task_pipelines(deployed_tasks())

all_assets = [
    *load_assets_from_modules([assets]),
    *(asset for pipeline in task_pipelines for asset in pipeline.assets),
    issued_forecast,
    forecast_track_record,
]

io_manager = get_parquet_io_manager(
    environment=settings.ENVIRONMENT,
    s3_bucket=settings.S3_BUCKET_NAME,
    data_dir=settings.DATA_DIR,
)
feast_io_manager = get_feast_parquet_io_manager(FeastPublicationTarget.from_settings(settings))


@resource
def time_series_repo_resource(_context):
    """Open the database when a run needs it, not while loading definitions."""
    return TimeSeriesRepository()


defs = Definitions(
    assets=all_assets,
    schedules=[
        *(schedule for pipeline in task_pipelines for schedule in pipeline.schedules),
        taipower_supply_demand_snapshot_schedule,
        hourly_actual_load_schedule,
        cwa_observation_schedule,
        cwa_forecast_schedule,
        issued_forecast_schedule,
    ],
    jobs=[
        *(job for pipeline in task_pipelines for job in pipeline.jobs),
        taipower_supply_demand_snapshot_job,
        hourly_actual_load_job,
        cwa_observation_job,
        cwa_forecast_job,
        issued_forecast_job,
    ],
    resources={
        "io_manager": io_manager,
        "feast_io_manager": feast_io_manager,
        "time_series_repo": time_series_repo_resource,
    },
)
