"""Chart series specs for the national and regional supply-demand snapshots.

Both tables store Taipower's 萬瓩 columns; power fields are exposed in MW (萬瓩 × 10) under
the same names the list endpoints use, and percentages stay as stored.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from shiro_mlops.data.taipower_regional_supply_demand import REGIONAL_SUPPLY_DEMAND_REGIONS
from shiro_mlops.service.data_explorer.errors import ExplorerQueryError
from shiro_mlops.service.data_explorer.series import SeriesField, SeriesSpec
from shiro_mlops.service.data_explorer.values import WAN_KW_TO_MW

POWER_UNIT = "MW"
PERCENT_UNIT = "%"


def _power(wan_kw_column: str) -> SeriesField:
    return SeriesField(sql=f"{wan_kw_column} * {WAN_KW_TO_MW}", unit=POWER_UNIT)


def _percent(column: str) -> SeriesField:
    return SeriesField(sql=column, unit=PERCENT_UNIT)


def _no_filters(filters: Mapping[str, str]) -> tuple[list[str], dict[str, Any]]:
    del filters
    return [], {}


# SYNC(frontend/apps/engineering-console/src/components/data-explorer/catalog.ts): NATIONAL_FIELD_OPTIONS, fields and units.
class NationalSeriesField(StrEnum):
    """National supply-demand power (MW) and percentage fields a series request may name."""

    CURR_LOAD_MW = "curr_load_mw"
    REAL_HR_MAXI_SPLY_CAPACITY_MW = "real_hr_maxi_sply_capacity_mw"
    CURR_UTIL_RATE_PCT = "curr_util_rate_pct"
    FORE_MAXI_SPLY_CAPACITY_MW = "fore_maxi_sply_capacity_mw"
    FORE_PEAK_DEMA_LOAD_MW = "fore_peak_dema_load_mw"
    FORE_PEAK_RESV_CAPACITY_MW = "fore_peak_resv_capacity_mw"
    FORE_PEAK_RESV_RATE_PCT = "fore_peak_resv_rate_pct"
    YDAY_MAXI_SPLY_CAPACITY_MW = "yday_maxi_sply_capacity_mw"
    YDAY_PEAK_DEMA_LOAD_MW = "yday_peak_dema_load_mw"
    YDAY_PEAK_RESV_CAPACITY_MW = "yday_peak_resv_capacity_mw"
    YDAY_PEAK_RESV_RATE_PCT = "yday_peak_resv_rate_pct"


def _national_field(name: NationalSeriesField) -> SeriesField:
    if name.value.endswith("_pct"):
        return _percent(name.value)
    return _power(name.value.removesuffix("_mw") + "_wan_kw")


NATIONAL_SERIES_DEFAULT_FIELDS = (
    NationalSeriesField.CURR_LOAD_MW,
    NationalSeriesField.REAL_HR_MAXI_SPLY_CAPACITY_MW,
)

NATIONAL_SERIES = SeriesSpec(
    dataset="national_supply_demand",
    table="raw_taipower_supply_demand_snapshot",
    time_column="observed_at",
    fields={name.value: _national_field(name) for name in NationalSeriesField},
    default_fields=tuple(name.value for name in NATIONAL_SERIES_DEFAULT_FIELDS),
    group_columns=(),
    filter_keys=frozenset(),
    filters=_no_filters,
)


# SYNC(frontend/apps/engineering-console/src/components/data-explorer/catalog.ts): REGIONAL_FIELD_OPTIONS, fields and units.
class RegionalSeriesField(StrEnum):
    """Regional supply-demand power fields a series request may name."""

    LOAD_MW = "load_mw"
    GENERATION_MW = "generation_mw"


def regional_series_filters(filters: Mapping[str, str]) -> tuple[list[str], dict[str, Any]]:
    """Apply the optional region filter with the list endpoint's validation."""
    region = filters.get("region")
    if not region:
        return [], {}
    if region not in REGIONAL_SUPPLY_DEMAND_REGIONS:
        raise ExplorerQueryError("region must be one of 北部, 中部, 南部, 東部")
    return ["region = :region"], {"region": region}


REGIONAL_SERIES = SeriesSpec(
    dataset="regional_supply_demand",
    table="raw_taipower_regional_supply_demand_snapshot",
    time_column="observed_at",
    fields={
        RegionalSeriesField.LOAD_MW.value: _power("load_wan_kw"),
        RegionalSeriesField.GENERATION_MW.value: _power("generation_wan_kw"),
    },
    default_fields=(RegionalSeriesField.LOAD_MW.value,),
    group_columns=("region",),
    filter_keys=frozenset({"region"}),
    filters=regional_series_filters,
)
