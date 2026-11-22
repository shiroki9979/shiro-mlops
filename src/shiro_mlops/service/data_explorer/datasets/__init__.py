"""The Data Explorer's eight datasets, in the order `GET /data/status` lists them."""

from collections.abc import Mapping
from types import MappingProxyType

from shiro_mlops.service.data_explorer.datasets.audits import (
    CWA_FORECAST_AUDITS,
    CWA_OBSERVATION_AUDITS,
)
from shiro_mlops.service.data_explorer.datasets.definition import Dataset
from shiro_mlops.service.data_explorer.datasets.power import (
    HOURLY_LOAD,
    NATIONAL_SUPPLY_DEMAND,
    REGIONAL_SUPPLY_DEMAND,
    UNIT_GENERATION,
)
from shiro_mlops.service.data_explorer.datasets.weather import CWA_FORECASTS, CWA_OBSERVATIONS

DATASETS: Mapping[str, Dataset] = MappingProxyType(
    {
        dataset.id: dataset
        for dataset in (
            HOURLY_LOAD,
            NATIONAL_SUPPLY_DEMAND,
            REGIONAL_SUPPLY_DEMAND,
            UNIT_GENERATION,
            CWA_OBSERVATIONS,
            CWA_FORECASTS,
            CWA_OBSERVATION_AUDITS,
            CWA_FORECAST_AUDITS,
        )
    }
)

__all__ = [
    "CWA_FORECASTS",
    "CWA_FORECAST_AUDITS",
    "CWA_OBSERVATIONS",
    "CWA_OBSERVATION_AUDITS",
    "DATASETS",
    "HOURLY_LOAD",
    "NATIONAL_SUPPLY_DEMAND",
    "REGIONAL_SUPPLY_DEMAND",
    "UNIT_GENERATION",
    "Dataset",
]
