"""Data clients for fetching Taipower load and CWA weather observations/forecasts."""

from shiro_mlops.data.cwa_client import CWAClient
from shiro_mlops.data.repository import TimeSeriesRepository
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
    "TaipowerClient",
    "TaipowerRegionalSupplyDemandClient",
    "TaipowerRegionalSupplyDemandSnapshot",
    "TaipowerSupplyDemandClient",
    "TaipowerSupplyDemandSnapshot",
    "TaipowerUnitGenerationClient",
    "TaipowerUnitGenerationSnapshot",
    "TimeSeriesRepository",
]
