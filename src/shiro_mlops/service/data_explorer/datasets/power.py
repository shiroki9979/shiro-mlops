"""Power datasets: hourly load, national and regional supply-demand, unit generation.

The supply-demand tables store Taipower's 萬瓩 columns; power fields are exposed in MW
(萬瓩 × 10) under the same names in the list and the series, and percentages stay as stored.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any

from shiro_mlops.data.hourly_actual_load import REGIONAL_SNAPSHOT_SUM_SOURCE
from shiro_mlops.data.taipower_regional_supply_demand import REGIONAL_SUPPLY_DEMAND_REGIONS
from shiro_mlops.service.data_explorer.completeness import (
    gaps_until_now,
    hourly_gaps,
    missing_regional_identifiers,
    regional_gaps,
    regional_slot_map,
    ten_minute_gaps,
)
from shiro_mlops.service.data_explorer.datasets.definition import (
    Clauses,
    Dataset,
    Exact,
    OneOf,
    Pinned,
    Row,
    each,
)
from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.query import ExplorerQuery
from shiro_mlops.service.data_explorer.series import SeriesField, SeriesOptions
from shiro_mlops.service.data_explorer.values import (
    WAN_KW_TO_MW,
    format_row_time,
    optional_time,
    row_time,
    to_float,
    to_mw,
)

POWER_UNIT = "MW"
PERCENT_UNIT = "%"
TEN_MINUTES = timedelta(minutes=10)
COMPLETENESS_VALUES = ("complete", "incomplete")


class HourlyLoadSeriesField(StrEnum):
    """Hourly load fields a series request may name."""

    LOAD_MW = "load_mw"


HOURLY_LOAD_SERIES = SeriesOptions(
    fields={HourlyLoadSeriesField.LOAD_MW.value: SeriesField(sql="load_mw", unit=POWER_UNIT)},
    group_columns=("subject",),
    slot_lag=timedelta(hours=1),
)


def _power(wan_kw_column: str) -> SeriesField:
    return SeriesField(sql=f"{wan_kw_column} * {WAN_KW_TO_MW}", unit=POWER_UNIT)


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
        return SeriesField(sql=name.value, unit=PERCENT_UNIT)
    return _power(name.value.removesuffix("_mw") + "_wan_kw")


NATIONAL_SERIES_DEFAULT_FIELDS = (
    NationalSeriesField.CURR_LOAD_MW,
    NationalSeriesField.REAL_HR_MAXI_SPLY_CAPACITY_MW,
)

NATIONAL_SERIES = SeriesOptions(
    fields={name.value: _national_field(name) for name in NationalSeriesField},
    default_fields=tuple(name.value for name in NATIONAL_SERIES_DEFAULT_FIELDS),
    group_columns=(),
)


# SYNC(frontend/apps/engineering-console/src/components/data-explorer/catalog.ts): REGIONAL_FIELD_OPTIONS, fields and units.
class RegionalSeriesField(StrEnum):
    """Regional supply-demand power fields a series request may name."""

    LOAD_MW = "load_mw"
    GENERATION_MW = "generation_mw"


REGIONAL_SERIES = SeriesOptions(
    fields={
        RegionalSeriesField.LOAD_MW.value: _power("load_wan_kw"),
        RegionalSeriesField.GENERATION_MW.value: _power("generation_wan_kw"),
    },
    default_fields=(RegionalSeriesField.LOAD_MW.value,),
    group_columns=("region",),
)


class UnitSeriesField(StrEnum):
    """Additive unit-generation power fields a series request may name."""

    NET_GENERATION_MW = "net_generation_mw"
    CAPACITY_MW = "capacity_mw"


# SYNC(frontend/apps/engineering-console/src/components/data-explorer/catalog.ts): unit_generation groupOptions, default first.
class UnitGroupBy(StrEnum):
    """Unit-generation series grouping: per unit type, or one total over every member."""

    UNIT_TYPE = "unit_type"
    NONE = "none"


UNIT_GENERATION_SERIES = SeriesOptions(
    fields={
        UnitSeriesField.NET_GENERATION_MW.value: SeriesField(
            sql="net_generation_mw", unit=POWER_UNIT
        ),
        UnitSeriesField.CAPACITY_MW.value: SeriesField(sql="capacity_mw", unit=POWER_UNIT),
    },
    group_columns=("unit_type",),
    member_sum=True,
    default_fields=(UnitSeriesField.NET_GENERATION_MW.value,),
    group_options={UnitGroupBy.UNIT_TYPE.value: ("unit_type",), UnitGroupBy.NONE.value: ()},
)


def _hourly_load_item(row: Row) -> dict[str, Any]:
    return {
        "datetime": format_row_time(row, "time"),
        "subject": row["subject"],
        "load_mw": float(row["load_mw"]),
        "ingested_at": format_row_time(row, "created_at"),
    }


def _hourly_load_gaps(db: ExplorerDb, query: ExplorerQuery) -> list[str]:
    return hourly_gaps(db, query.window, query.filters.get("subject"))


HOURLY_LOAD = Dataset(
    id="hourly_load",
    label="逐時用電負載",
    href="/data/power/load",
    cadence=timedelta(hours=1),
    max_days=31,
    table="raw_taipower_load",
    time_column="time",
    sort=("time", "subject"),
    instant_columns=frozenset({"time"}),
    list_columns=("time", "subject", "load_mw", "created_at"),
    project=each(_hourly_load_item),
    pinned=(Pinned("source = :source", {"source": REGIONAL_SNAPSHOT_SUM_SOURCE}),),
    filters=(Exact(name="subject"),),
    list_gaps=_hourly_load_gaps,
    series=HOURLY_LOAD_SERIES,
)


def _national_item(row: Row) -> dict[str, Any]:
    return {
        "observed_at": format_row_time(row, "observed_at"),
        "source_publish_time": optional_time(row["source_publish_time"]),
        "curr_load_mw": to_mw(row["curr_load_wan_kw"]),
        "curr_load_wan_kw": to_float(row["curr_load_wan_kw"]),
        "curr_util_rate_pct": to_float(row["curr_util_rate_pct"]),
        "fore_maxi_sply_capacity_mw": to_mw(row["fore_maxi_sply_capacity_wan_kw"]),
        "fore_maxi_sply_capacity_wan_kw": to_float(row["fore_maxi_sply_capacity_wan_kw"]),
        "fore_peak_dema_load_mw": to_mw(row["fore_peak_dema_load_wan_kw"]),
        "fore_peak_dema_load_wan_kw": to_float(row["fore_peak_dema_load_wan_kw"]),
        "fore_peak_resv_capacity_mw": to_mw(row["fore_peak_resv_capacity_wan_kw"]),
        "fore_peak_resv_capacity_wan_kw": to_float(row["fore_peak_resv_capacity_wan_kw"]),
        "fore_peak_resv_rate_pct": to_float(row["fore_peak_resv_rate_pct"]),
        "fore_peak_resv_indicator": row["fore_peak_resv_indicator"],
        "fore_peak_hour_range": row["fore_peak_hour_range"],
        "yday_date": str(row["yday_date"]) if row["yday_date"] is not None else None,
        "yday_maxi_sply_capacity_mw": to_mw(row["yday_maxi_sply_capacity_wan_kw"]),
        "yday_maxi_sply_capacity_wan_kw": to_float(row["yday_maxi_sply_capacity_wan_kw"]),
        "yday_peak_dema_load_mw": to_mw(row["yday_peak_dema_load_wan_kw"]),
        "yday_peak_dema_load_wan_kw": to_float(row["yday_peak_dema_load_wan_kw"]),
        "yday_peak_resv_capacity_mw": to_mw(row["yday_peak_resv_capacity_wan_kw"]),
        "yday_peak_resv_capacity_wan_kw": to_float(row["yday_peak_resv_capacity_wan_kw"]),
        "yday_peak_resv_rate_pct": to_float(row["yday_peak_resv_rate_pct"]),
        "yday_peak_resv_indicator": row["yday_peak_resv_indicator"],
        "real_hr_maxi_sply_capacity_mw": to_mw(row["real_hr_maxi_sply_capacity_wan_kw"]),
        "real_hr_maxi_sply_capacity_wan_kw": to_float(row["real_hr_maxi_sply_capacity_wan_kw"]),
        "real_hr_peak_time": optional_time(row["real_hr_peak_time"]),
        "ingested_at": format_row_time(row, "created_at"),
    }


def _national_gaps(db: ExplorerDb, query: ExplorerQuery) -> list[str]:
    return gaps_until_now(query.window, lambda window: ten_minute_gaps(db, window))


NATIONAL_SUPPLY_DEMAND = Dataset(
    id="national_supply_demand",
    label="全台供需",
    href="/data/power/supply-demand",
    cadence=TEN_MINUTES,
    max_days=7,
    table="raw_taipower_supply_demand_snapshot",
    time_column="observed_at",
    sort=("observed_at",),
    instant_columns=frozenset({"observed_at"}),
    list_columns=(
        "observed_at",
        "source_publish_time",
        "curr_load_wan_kw",
        "curr_util_rate_pct",
        "fore_maxi_sply_capacity_wan_kw",
        "fore_peak_dema_load_wan_kw",
        "fore_peak_resv_capacity_wan_kw",
        "fore_peak_resv_rate_pct",
        "fore_peak_resv_indicator",
        "fore_peak_hour_range",
        "yday_date",
        "yday_maxi_sply_capacity_wan_kw",
        "yday_peak_dema_load_wan_kw",
        "yday_peak_resv_capacity_wan_kw",
        "yday_peak_resv_rate_pct",
        "yday_peak_resv_indicator",
        "real_hr_maxi_sply_capacity_wan_kw",
        "real_hr_peak_time",
        "created_at",
    ),
    project=each(_national_item),
    list_gaps=_national_gaps,
    series=NATIONAL_SERIES,
)

REGIONAL_TABLE = "raw_taipower_regional_supply_demand_snapshot"


@dataclass(frozen=True, kw_only=True)
class SlotCompleteness(OneOf):
    """Keep rows whose 10-minute slot holds every region (`complete`) or fewer (`incomplete`)."""

    def clause(self, db: ExplorerDb, value: str) -> Clauses:
        self.validate(value)
        params: dict[str, Any] = {}
        placeholders = []
        for index, region in enumerate(REGIONAL_SUPPLY_DEMAND_REGIONS):
            name = f"expected_region_{index}"
            placeholders.append(f":{name}")
            params[name] = region
        params["expected_region_count"] = len(REGIONAL_SUPPLY_DEMAND_REGIONS)
        comparison = "=" if value == "complete" else "<"
        clause = (
            "(SELECT COUNT(DISTINCT completeness_row.region) "
            f"FROM {REGIONAL_TABLE} AS completeness_row "
            f"WHERE completeness_row.observed_at = {REGIONAL_TABLE}.observed_at "
            f"AND completeness_row.region IN ({', '.join(placeholders)})) "
            f"{comparison} :expected_region_count"
        )
        return [clause], params


def _regional_item(row: Row, present: set[str]) -> dict[str, Any]:
    missing_regions = missing_regional_identifiers(present)
    return {
        "observed_at": format_row_time(row, "observed_at"),
        "region": row["region"],
        "source_time": format_row_time(row, "source_time"),
        "generation_mw": to_mw(row["generation_wan_kw"]),
        "generation_wan_kw": to_float(row["generation_wan_kw"]),
        "load_mw": to_mw(row["load_wan_kw"]),
        "load_wan_kw": to_float(row["load_wan_kw"]),
        "slot_complete": not missing_regions,
        "missing_regions": missing_regions,
        "ingested_at": format_row_time(row, "created_at"),
    }


def _regional_page(db: ExplorerDb, query: ExplorerQuery, rows: list[Row]) -> list[dict[str, Any]]:
    slot_regions = regional_slot_map(db, query.window)
    return [
        _regional_item(row, slot_regions.get(row_time(row, "observed_at"), set())) for row in rows
    ]


def _regional_gaps(db: ExplorerDb, query: ExplorerQuery) -> list[str]:
    return gaps_until_now(query.window, lambda window: regional_gaps(db, window))


REGIONAL_SUPPLY_DEMAND = Dataset(
    id="regional_supply_demand",
    label="區域供需",
    href="/data/power/regional",
    cadence=TEN_MINUTES,
    max_days=7,
    table=REGIONAL_TABLE,
    time_column="observed_at",
    sort=("observed_at", "region"),
    instant_columns=frozenset({"observed_at"}),
    list_columns=(
        "observed_at",
        "region",
        "source_time",
        "generation_wan_kw",
        "load_wan_kw",
        "created_at",
    ),
    project=_regional_page,
    filters=(
        OneOf(name="region", values=REGIONAL_SUPPLY_DEMAND_REGIONS),
        SlotCompleteness(name="completeness", values=COMPLETENESS_VALUES, in_series=False),
    ),
    list_gaps=_regional_gaps,
    series=REGIONAL_SERIES,
)


def _unit_item(row: Row) -> dict[str, Any]:
    return {
        "observed_at": format_row_time(row, "observed_at"),
        "unit_type": row["unit_type"],
        "unit_name": row["unit_name"],
        "source_time": format_row_time(row, "source_time"),
        "capacity_mw": to_float(row["capacity_mw"]),
        "net_generation_mw": to_float(row["net_generation_mw"]),
        "capacity_ratio_pct": to_float(row["capacity_ratio_pct"]),
        "remark": row["remark"],
        "ingested_at": format_row_time(row, "created_at"),
    }


UNIT_GENERATION = Dataset(
    id="unit_generation",
    label="機組發電",
    href="/data/power/units",
    cadence=TEN_MINUTES,
    max_days=7,
    table="raw_taipower_unit_generation_snapshot",
    time_column="observed_at",
    sort=("observed_at", "unit_type", "unit_name"),
    instant_columns=frozenset({"observed_at"}),
    list_columns=(
        "observed_at",
        "unit_type",
        "unit_name",
        "source_time",
        "capacity_mw",
        "net_generation_mw",
        "capacity_ratio_pct",
        "remark",
        "created_at",
    ),
    project=each(_unit_item),
    filters=(Exact(name="unit_type"), Exact(name="unit_name")),
    series=UNIT_GENERATION_SERIES,
)
