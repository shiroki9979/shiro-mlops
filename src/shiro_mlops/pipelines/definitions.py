"""Main Dagster Definitions entrypoint."""

from dagster import Definitions, InitResourceContext, load_assets_from_modules, resource

from shiro_mlops.core.config import settings
from shiro_mlops.core.forecast_view_publisher import ForecastViewPublisher
from shiro_mlops.core.io_managers import get_feast_parquet_io_manager, get_parquet_io_manager
from shiro_mlops.data.cwa_client import CWAClient
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.taipower_regional_supply_demand import TaipowerRegionalSupplyDemandClient
from shiro_mlops.data.taipower_supply_demand import TaipowerSupplyDemandClient
from shiro_mlops.data.taipower_unit_generation import TaipowerUnitGenerationClient
from shiro_mlops.pipelines import assets
from shiro_mlops.pipelines.forecast_track_record import (
    forecast_track_record,
    forecast_track_record_job,
    forecast_track_record_schedule,
)
from shiro_mlops.pipelines.forecast_view_export import (
    FORECAST_VIEW_PUBLISHER,
    forecast_view_export,
    forecast_view_export_job,
    forecast_view_export_schedule,
)
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
    forecast_view_export,
]

io_manager = get_parquet_io_manager(data_dir=settings.DATA_DIR)
feast_io_manager = get_feast_parquet_io_manager(data_dir=settings.DATA_DIR)


@resource
def time_series_repo_resource(_context: InitResourceContext) -> TimeSeriesRepository:
    """Open the database when a run needs it, not while loading definitions."""
    return TimeSeriesRepository()


@resource
def cwa_source_resource(_context: InitResourceContext) -> CWAClient:
    """Build the CWA HTTP adapter when a run needs it, authorized with the configured API key."""
    return CWAClient(api_key=settings.CWA_API_KEY)


@resource
def taipower_supply_demand_source_resource(
    _context: InitResourceContext,
) -> TaipowerSupplyDemandClient:
    """Build the Taipower nationwide supply-demand HTTP adapter when a run needs it."""
    return TaipowerSupplyDemandClient(base_url=settings.TAIPOWER_SUPPLY_DEMAND_API_URL)


@resource
def taipower_regional_supply_demand_source_resource(
    _context: InitResourceContext,
) -> TaipowerRegionalSupplyDemandClient:
    """Build the Taipower regional supply-demand HTTP adapter when a run needs it."""
    return TaipowerRegionalSupplyDemandClient(
        base_url=settings.TAIPOWER_REGIONAL_SUPPLY_DEMAND_API_URL
    )


@resource
def taipower_unit_generation_source_resource(
    _context: InitResourceContext,
) -> TaipowerUnitGenerationClient:
    """Build the Taipower unit net-generation HTTP adapter when a run needs it."""
    return TaipowerUnitGenerationClient(base_url=settings.TAIPOWER_UNIT_GENERATION_API_URL)


@resource
def forecast_view_publisher_resource(_context: InitResourceContext) -> ForecastViewPublisher:
    """Build the S3 client, if any, when a run needs it, not while loading definitions."""
    return ForecastViewPublisher.from_settings(settings)


defs = Definitions(
    assets=all_assets,
    schedules=[
        *(schedule for pipeline in task_pipelines for schedule in pipeline.schedules),
        taipower_supply_demand_snapshot_schedule,
        hourly_actual_load_schedule,
        cwa_observation_schedule,
        cwa_forecast_schedule,
        issued_forecast_schedule,
        forecast_track_record_schedule,
        forecast_view_export_schedule,
    ],
    jobs=[
        *(job for pipeline in task_pipelines for job in pipeline.jobs),
        taipower_supply_demand_snapshot_job,
        hourly_actual_load_job,
        cwa_observation_job,
        cwa_forecast_job,
        issued_forecast_job,
        forecast_track_record_job,
        forecast_view_export_job,
    ],
    resources={
        "io_manager": io_manager,
        "feast_io_manager": feast_io_manager,
        "time_series_repo": time_series_repo_resource,
        assets.CWA_SOURCE: cwa_source_resource,
        assets.TAIPOWER_SUPPLY_DEMAND_SOURCE: taipower_supply_demand_source_resource,
        assets.TAIPOWER_REGIONAL_SUPPLY_DEMAND_SOURCE: (
            taipower_regional_supply_demand_source_resource
        ),
        assets.TAIPOWER_UNIT_GENERATION_SOURCE: taipower_unit_generation_source_resource,
        FORECAST_VIEW_PUBLISHER: forecast_view_publisher_resource,
    },
)
