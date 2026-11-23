"""Data clients for Taipower realtime snapshots and CWA weather observations/forecasts."""

from shiro_mlops.data.cwa_client import (
    DEFAULT_CWA_LOCATIONS,
    CWAClient,
    CWAForecastRelease,
    CWALocation,
    CWAObservationBatch,
    CWAStationObservation,
    CWATownshipForecast,
    parse_forecast_release,
    parse_observation_batch,
)
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.taipower_regional_supply_demand import (
    TaipowerRegionalSupplyDemandClient,
    TaipowerRegionalSupplyDemandSnapshot,
)
from shiro_mlops.data.taipower_regional_supply_demand_repository import (
    TaipowerRegionalSupplyDemandRepository,
)
from shiro_mlops.data.taipower_supply_demand import (
    TaipowerSupplyDemandClient,
    TaipowerSupplyDemandSnapshot,
)
from shiro_mlops.data.taipower_supply_demand_repository import TaipowerSupplyDemandRepository
from shiro_mlops.data.taipower_unit_generation import (
    TaipowerUnitGenerationClient,
    TaipowerUnitGenerationSnapshot,
)
from shiro_mlops.data.taipower_unit_generation_repository import (
    TaipowerUnitGenerationRepository,
)

__all__ = [
    "CWAClient",
    "CWALocation",
    "CWAObservationBatch",
    "CWAStationObservation",
    "CWAForecastRelease",
    "CWATownshipForecast",
    "DEFAULT_CWA_LOCATIONS",
    "parse_observation_batch",
    "parse_forecast_release",
    "TaipowerRegionalSupplyDemandClient",
    "TaipowerRegionalSupplyDemandRepository",
    "TaipowerRegionalSupplyDemandSnapshot",
    "TaipowerSupplyDemandClient",
    "TaipowerSupplyDemandRepository",
    "TaipowerSupplyDemandSnapshot",
    "TaipowerUnitGenerationClient",
    "TaipowerUnitGenerationRepository",
    "TaipowerUnitGenerationSnapshot",
    "TimeSeriesRepository",
]
