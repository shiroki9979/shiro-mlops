"""Power-domain Data Explorer readers behind the typed query seam."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from shiro_mlops.data.taipower_regional_supply_demand import REGIONAL_SUPPLY_DEMAND_REGIONS
from shiro_mlops.service.data_explorer.completeness import (
    gaps_until_now,
    missing_regional_identifiers,
    regional_gaps,
    regional_slot_map,
    ten_minute_gaps,
)
from shiro_mlops.service.data_explorer.dataset_reader import DatasetReader
from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.errors import ExplorerQueryError
from shiro_mlops.service.data_explorer.query import ExplorerQuery
from shiro_mlops.service.data_explorer.series import SeriesField, SeriesSpec
from shiro_mlops.service.data_explorer.supply_demand_series import regional_series_filters
from shiro_mlops.service.data_explorer.values import (
    format_row_time,
    optional_time,
    row_time,
    to_float,
    to_mw,
)

NATIONAL_SUPPLY_DEMAND_SQL = """
    SELECT observed_at, source_publish_time, curr_load_wan_kw, curr_util_rate_pct,
           fore_maxi_sply_capacity_wan_kw, fore_peak_dema_load_wan_kw,
           fore_peak_resv_capacity_wan_kw, fore_peak_resv_rate_pct,
           fore_peak_resv_indicator, fore_peak_hour_range, yday_date,
           yday_maxi_sply_capacity_wan_kw, yday_peak_dema_load_wan_kw,
           yday_peak_resv_capacity_wan_kw, yday_peak_resv_rate_pct,
           yday_peak_resv_indicator, real_hr_maxi_sply_capacity_wan_kw,
           real_hr_peak_time, created_at
    FROM raw_taipower_supply_demand_snapshot
    WHERE {where}
    ORDER BY {order}
    LIMIT :limit
"""

REGIONAL_SUPPLY_DEMAND_SQL = """
    SELECT observed_at, region, source_time, generation_wan_kw, load_wan_kw, created_at
    FROM raw_taipower_regional_supply_demand_snapshot
    WHERE {where}
    ORDER BY {order}
    LIMIT :limit
"""


def _national_item(row: dict[str, Any]) -> dict[str, Any]:
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


def _validate_completeness(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if value not in {"complete", "incomplete"}:
        raise ExplorerQueryError("completeness must be complete or incomplete")
    return value


def _completeness_clause(completeness: str, sql_params: dict[str, Any]) -> str:
    placeholders = []
    for index, region in enumerate(REGIONAL_SUPPLY_DEMAND_REGIONS):
        name = f"expected_region_{index}"
        placeholders.append(f":{name}")
        sql_params[name] = region
    sql_params["expected_region_count"] = len(REGIONAL_SUPPLY_DEMAND_REGIONS)
    comparison = "=" if completeness == "complete" else "<"
    same_slot = (
        "completeness_row.observed_at = raw_taipower_regional_supply_demand_snapshot.observed_at"
    )
    return (
        "(SELECT COUNT(DISTINCT completeness_row.region) "
        "FROM raw_taipower_regional_supply_demand_snapshot AS completeness_row "
        f"WHERE {same_slot} "
        f"AND completeness_row.region IN ({', '.join(placeholders)})) "
        f"{comparison} :expected_region_count"
    )


def _regional_filters(db: ExplorerDb, query: ExplorerQuery) -> tuple[list[str], dict[str, Any]]:
    clauses, sql_params = db.time_window("observed_at", query.window)
    region_clauses, region_params = regional_series_filters(query.filters)
    clauses.extend(region_clauses)
    sql_params.update(region_params)
    completeness = _validate_completeness(query.filters.get("completeness"))
    if completeness:
        clauses.append(_completeness_clause(completeness, sql_params))
    return clauses, sql_params


def _regional_item(row: dict[str, Any], present: set[str]) -> dict[str, Any]:
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


class NationalSupplyDemandReader(DatasetReader):
    """List persisted national supply-demand snapshots newest first."""

    dataset = "national_supply_demand"
    select_sql = NATIONAL_SUPPLY_DEMAND_SQL

    def filters(self, query: ExplorerQuery) -> tuple[list[str], dict[str, Any]]:
        return self.db.time_window("observed_at", query.window)

    def project_page(
        self, query: ExplorerQuery, rows: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        gaps = gaps_until_now(query.window, lambda window: ten_minute_gaps(self.db, window))
        return [_national_item(row) for row in rows], gaps


class RegionalSupplyDemandReader(DatasetReader):
    """List persisted regional snapshots newest first."""

    dataset = "regional_supply_demand"
    select_sql = REGIONAL_SUPPLY_DEMAND_SQL

    def filters(self, query: ExplorerQuery) -> tuple[list[str], dict[str, Any]]:
        return _regional_filters(self.db, query)

    def project_page(
        self, query: ExplorerQuery, rows: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        slot_regions = regional_slot_map(self.db, query.window)
        items = [
            _regional_item(
                row,
                slot_regions.get(row_time(row, "observed_at"), set()),
            )
            for row in rows
        ]
        return items, gaps_until_now(query.window, lambda window: regional_gaps(self.db, window))


class UnitGenerationReader(DatasetReader):
    """List persisted unit-generation snapshots newest first."""

    dataset = "unit_generation"
    select_sql = """
        SELECT observed_at, unit_type, unit_name, source_time, capacity_mw,
               net_generation_mw, capacity_ratio_pct, remark, created_at
        FROM raw_taipower_unit_generation_snapshot
        WHERE {where}
        ORDER BY {order}
        LIMIT :limit
    """

    def filters(self, query: ExplorerQuery) -> tuple[list[str], dict[str, Any]]:
        clauses, sql_params = self.db.time_window("observed_at", query.window)
        unit_clauses, unit_params = unit_generation_filters(query.filters)
        return [*clauses, *unit_clauses], {**sql_params, **unit_params}

    def project_page(
        self, query: ExplorerQuery, rows: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        items = []
        for row in rows:
            items.append(
                {
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
            )
        return items, []


UNIT_FILTER_KEYS = ("unit_type", "unit_name")


def unit_generation_filters(filters: Mapping[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """Narrow the member units by exact `unit_type` and `unit_name`."""
    clauses = []
    params: dict[str, Any] = {}
    for name in UNIT_FILTER_KEYS:
        if filters.get(name):
            clauses.append(f"{name} = :{name}")
            params[name] = filters[name]
    return clauses, params


class UnitSeriesField(StrEnum):
    """Additive unit-generation power fields a series request may name."""

    NET_GENERATION_MW = "net_generation_mw"
    CAPACITY_MW = "capacity_mw"


# SYNC(frontend/apps/engineering-console/src/components/data-explorer/catalog.ts): unit_generation groupOptions, default first.
class UnitGroupBy(StrEnum):
    """Unit-generation series grouping: per unit type, or one total over every member."""

    UNIT_TYPE = "unit_type"
    NONE = "none"


UNIT_GENERATION_SERIES = SeriesSpec(
    dataset="unit_generation",
    table="raw_taipower_unit_generation_snapshot",
    time_column="observed_at",
    fields={
        UnitSeriesField.NET_GENERATION_MW.value: SeriesField(sql="net_generation_mw", unit="MW"),
        UnitSeriesField.CAPACITY_MW.value: SeriesField(sql="capacity_mw", unit="MW"),
    },
    group_columns=("unit_type",),
    filter_keys=frozenset(UNIT_FILTER_KEYS),
    filters=unit_generation_filters,
    member_sum=True,
    default_fields=(UnitSeriesField.NET_GENERATION_MW.value,),
    group_options={UnitGroupBy.UNIT_TYPE.value: ("unit_type",), UnitGroupBy.NONE.value: ()},
)
