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
from shiro_mlops.pipelines.schedules import (
    cwa_forecast_job,
    cwa_forecast_schedule,
    cwa_observation_job,
    cwa_observation_schedule,
    daily_training_job,
    daily_training_schedule,
    hourly_actual_load_job,
    hourly_actual_load_schedule,
    hourly_drift_job,
    hourly_drift_schedule,
    taipower_supply_demand_snapshot_job,
    taipower_supply_demand_snapshot_schedule,
)

all_assets = load_assets_from_modules([assets])

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
        daily_training_schedule,
        hourly_drift_schedule,
        taipower_supply_demand_snapshot_schedule,
        hourly_actual_load_schedule,
        cwa_observation_schedule,
        cwa_forecast_schedule,
    ],
    jobs=[
        daily_training_job,
        hourly_drift_job,
        taipower_supply_demand_snapshot_job,
        hourly_actual_load_job,
        cwa_observation_job,
        cwa_forecast_job,
    ],
    resources={
        "io_manager": io_manager,
        "feast_io_manager": feast_io_manager,
        "time_series_repo": time_series_repo_resource,
    },
)
