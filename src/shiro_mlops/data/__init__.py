"""Data clients for fetching Taipower load and CWA weather observations/forecasts."""

from shiro_mlops.data.cwa_client import CWAClient
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.taipower_client import TaipowerClient
from shiro_mlops.data.taipower_supply_demand import (
    TaipowerSupplyDemandClient,
    TaipowerSupplyDemandSnapshot,
)

__all__ = [
    "CWAClient",
    "TaipowerClient",
    "TaipowerSupplyDemandClient",
    "TaipowerSupplyDemandSnapshot",
    "TimeSeriesRepository",
]
