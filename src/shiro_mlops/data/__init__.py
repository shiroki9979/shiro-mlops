"""Data clients for fetching Taipower load and CWA weather observations/forecasts."""

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
from shiro_mlops.data.repository import (
    TaipowerRegionalSupplyDemandRepository,
    TaipowerSupplyDemandRepository,
    TaipowerUnitGenerationRepository,
    TimeSeriesRepository,
)
from shiro_mlops.data.taipower_client import TaipowerClient
from shiro_mlops.data.taipower_regional_supply_demand import (
    TaipowerRegionalSupplyDemandClient,
    TaipowerRegionalSupplyDemandSnapshot,
)
from shiro_mlops.data.taipower_supply_demand import (
    TaipowerSupplyDemandClient,
    TaipowerSupplyDemandSnapshot,
)
from shiro_mlops.data.taipower_unit_generation import (
    TaipowerUnitGenerationClient,
    TaipowerUnitGenerationSnapshot,
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
    "TaipowerClient",
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
