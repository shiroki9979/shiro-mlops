"""Main Dagster Definitions entrypoint."""

from dagster import Definitions, load_assets_from_modules

from shiro_mlops.core.config import settings
from shiro_mlops.core.io_managers import get_feast_parquet_io_manager, get_parquet_io_manager
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.pipelines import assets
from shiro_mlops.pipelines.schedules import (
    daily_training_job,
    daily_training_schedule,
    hourly_drift_job,
    hourly_drift_schedule,
)

all_assets = load_assets_from_modules([assets])

io_manager = get_parquet_io_manager(
    environment=settings.ENVIRONMENT,
    s3_bucket=settings.S3_BUCKET_NAME,
    data_dir=settings.DATA_DIR,
)
feast_io_manager = get_feast_parquet_io_manager(
    offline_store_type=settings.FEAST_OFFLINE_STORE_TYPE,
    s3_bucket=settings.S3_BUCKET_NAME,
    s3_prefix=settings.FEAST_S3_PREFIX,
    data_dir=settings.DATA_DIR,
)

defs = Definitions(
    assets=all_assets,
    schedules=[daily_training_schedule, hourly_drift_schedule],
    jobs=[daily_training_job, hourly_drift_job],
    resources={
        "io_manager": io_manager,
        "feast_io_manager": feast_io_manager,
        "time_series_repo": TimeSeriesRepository(),
    },
)
