"""Power-domain Data Explorer readers behind the typed query seam."""

from __future__ import annotations

from typing import Any

from shiro_mlops.data.taipower_regional_supply_demand import REGIONAL_SUPPLY_DEMAND_REGIONS
from shiro_mlops.service.data_explorer.completeness import (
    missing_regional_identifiers,
    regional_slot_map,
    ten_minute_gaps,
)
from shiro_mlops.service.data_explorer.dataset_reader import DatasetReader
from shiro_mlops.service.data_explorer.errors import ExplorerQueryError
from shiro_mlops.service.data_explorer.pagination import apply_cursor
from shiro_mlops.service.data_explorer.query import ExplorerQuery
from shiro_mlops.service.data_explorer.timefmt import format_taiwan_time
from shiro_mlops.service.data_explorer.values import optional_time, to_float, to_mw, to_taiwan


class NationalSupplyDemandReader(DatasetReader):
    """List persisted national supply-demand snapshots newest first."""

    dataset = "national_supply_demand"

    def fetch_page(
        self,
        query: ExplorerQuery,
        cursor: dict[str, Any] | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        clauses = ["observed_at >= :start_time", "observed_at <= :end_time"]
        sql_params: dict[str, Any] = {
            "start_time": query.window.as_utc()[0],
            "end_time": query.window.as_utc()[1],
        }
        where, cursor_params = apply_cursor(clauses, cursor, ("observed_at",))
        sql_params.update(cursor_params)
        sql = f"""
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
            ORDER BY observed_at DESC
            LIMIT :limit
        """
        sql_params["limit"] = limit
        items = []
        for row in self.db.fetch(sql, sql_params):
            observed = to_taiwan(row["observed_at"])
            items.append(
                {
                    "observed_at": format_taiwan_time(observed),
                    "source_publish_time": optional_time(row["source_publish_time"]),
                    "curr_load_mw": to_mw(row["curr_load_wan_kw"]),
                    "curr_load_wan_kw": to_float(row["curr_load_wan_kw"]),
                    "curr_util_rate_pct": to_float(row["curr_util_rate_pct"]),
                    "fore_maxi_sply_capacity_mw": to_mw(row["fore_maxi_sply_capacity_wan_kw"]),
                    "fore_maxi_sply_capacity_wan_kw": to_float(
                        row["fore_maxi_sply_capacity_wan_kw"]
                    ),
                    "fore_peak_dema_load_mw": to_mw(row["fore_peak_dema_load_wan_kw"]),
                    "fore_peak_dema_load_wan_kw": to_float(row["fore_peak_dema_load_wan_kw"]),
                    "fore_peak_resv_capacity_mw": to_mw(row["fore_peak_resv_capacity_wan_kw"]),
                    "fore_peak_resv_capacity_wan_kw": to_float(
                        row["fore_peak_resv_capacity_wan_kw"]
                    ),
                    "fore_peak_resv_rate_pct": to_float(row["fore_peak_resv_rate_pct"]),
                    "fore_peak_resv_indicator": row["fore_peak_resv_indicator"],
                    "fore_peak_hour_range": row["fore_peak_hour_range"],
                    "yday_date": str(row["yday_date"]) if row["yday_date"] is not None else None,
                    "yday_maxi_sply_capacity_mw": to_mw(row["yday_maxi_sply_capacity_wan_kw"]),
                    "yday_maxi_sply_capacity_wan_kw": to_float(
                        row["yday_maxi_sply_capacity_wan_kw"]
                    ),
                    "yday_peak_dema_load_mw": to_mw(row["yday_peak_dema_load_wan_kw"]),
                    "yday_peak_dema_load_wan_kw": to_float(row["yday_peak_dema_load_wan_kw"]),
                    "yday_peak_resv_capacity_mw": to_mw(row["yday_peak_resv_capacity_wan_kw"]),
                    "yday_peak_resv_capacity_wan_kw": to_float(
                        row["yday_peak_resv_capacity_wan_kw"]
                    ),
                    "yday_peak_resv_rate_pct": to_float(row["yday_peak_resv_rate_pct"]),
                    "yday_peak_resv_indicator": row["yday_peak_resv_indicator"],
                    "real_hr_maxi_sply_capacity_mw": to_mw(
                        row["real_hr_maxi_sply_capacity_wan_kw"]
                    ),
                    "real_hr_maxi_sply_capacity_wan_kw": to_float(
                        row["real_hr_maxi_sply_capacity_wan_kw"]
                    ),
                    "real_hr_peak_time": optional_time(row["real_hr_peak_time"]),
                    "ingested_at": format_taiwan_time(to_taiwan(row["created_at"])),
                }
            )
        return items, ten_minute_gaps(self.db, query.window)


class RegionalSupplyDemandReader(DatasetReader):
    """List persisted regional snapshots newest first."""

    dataset = "regional_supply_demand"

    def fetch_page(
        self,
        query: ExplorerQuery,
        cursor: dict[str, Any] | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        completeness = query.filters.get("completeness")
        if completeness not in (None, "", "complete", "incomplete"):
            raise ExplorerQueryError("completeness must be complete or incomplete")
        clauses = ["observed_at >= :start_time", "observed_at <= :end_time"]
        sql_params: dict[str, Any] = {
            "start_time": query.window.as_utc()[0],
            "end_time": query.window.as_utc()[1],
        }
        region = query.filters.get("region")
        if region:
            if region not in REGIONAL_SUPPLY_DEMAND_REGIONS:
                raise ExplorerQueryError("region must be one of 北部, 中部, 南部, 東部")
            clauses.append("region = :region")
            sql_params["region"] = region
        if completeness:
            region_params = []
            for index, expected_region in enumerate(REGIONAL_SUPPLY_DEMAND_REGIONS):
                name = f"expected_region_{index}"
                region_params.append(f":{name}")
                sql_params[name] = expected_region
            comparison = "=" if completeness == "complete" else "<"
            clauses.append(
                "(SELECT COUNT(DISTINCT completeness_row.region) "
                "FROM raw_taipower_regional_supply_demand_snapshot AS completeness_row "
                "WHERE completeness_row.observed_at = "
                "raw_taipower_regional_supply_demand_snapshot.observed_at "
                f"AND completeness_row.region IN ({', '.join(region_params)})) "
                f"{comparison} :expected_region_count"
            )
            sql_params["expected_region_count"] = len(REGIONAL_SUPPLY_DEMAND_REGIONS)
        where, cursor_params = apply_cursor(clauses, cursor, ("observed_at", "region"))
        sql_params.update(cursor_params)
        sql = f"""
            SELECT observed_at, region, source_time, generation_wan_kw, load_wan_kw, created_at
            FROM raw_taipower_regional_supply_demand_snapshot
            WHERE {where}
            ORDER BY observed_at DESC, region DESC
            LIMIT :limit
        """
        sql_params["limit"] = limit
        rows = self.db.fetch(sql, sql_params)
        slot_regions = regional_slot_map(self.db, query.window)
        items = []
        for row in rows:
            observed = to_taiwan(row["observed_at"])
            present = slot_regions.get(observed, set())
            missing_regions = missing_regional_identifiers(present)
            slot_complete = not missing_regions
            if completeness == "complete" and not slot_complete:
                continue
            if completeness == "incomplete" and slot_complete:
                continue
            items.append(
                {
                    "observed_at": format_taiwan_time(observed),
                    "region": row["region"],
                    "source_time": format_taiwan_time(to_taiwan(row["source_time"])),
                    "generation_mw": to_mw(row["generation_wan_kw"]),
                    "generation_wan_kw": to_float(row["generation_wan_kw"]),
                    "load_mw": to_mw(row["load_wan_kw"]),
                    "load_wan_kw": to_float(row["load_wan_kw"]),
                    "slot_complete": slot_complete,
                    "missing_regions": missing_regions,
                    "ingested_at": format_taiwan_time(to_taiwan(row["created_at"])),
                }
            )
            if len(items) >= limit:
                break
        missing = [
            format_taiwan_time(slot)
            for slot, present in sorted(slot_regions.items(), reverse=True)
            if present != set(REGIONAL_SUPPLY_DEMAND_REGIONS)
        ]
        return items, missing


class UnitGenerationReader(DatasetReader):
    """List persisted unit-generation snapshots newest first."""

    dataset = "unit_generation"

    def fetch_page(
        self,
        query: ExplorerQuery,
        cursor: dict[str, Any] | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        clauses = ["observed_at >= :start_time", "observed_at <= :end_time"]
        sql_params: dict[str, Any] = {
            "start_time": query.window.as_utc()[0],
            "end_time": query.window.as_utc()[1],
        }
        if query.filters.get("unit_type"):
            clauses.append("unit_type = :unit_type")
            sql_params["unit_type"] = query.filters["unit_type"]
        if query.filters.get("unit_name"):
            clauses.append("unit_name = :unit_name")
            sql_params["unit_name"] = query.filters["unit_name"]
        where, cursor_params = apply_cursor(
            clauses, cursor, ("observed_at", "unit_type", "unit_name")
        )
        sql_params.update(cursor_params)
        sql = f"""
            SELECT observed_at, unit_type, unit_name, source_time, capacity_mw,
                   net_generation_mw, capacity_ratio_pct, remark, created_at
            FROM raw_taipower_unit_generation_snapshot
            WHERE {where}
            ORDER BY observed_at DESC, unit_type DESC, unit_name DESC
            LIMIT :limit
        """
        sql_params["limit"] = limit
        items = []
        for row in self.db.fetch(sql, sql_params):
            items.append(
                {
                    "observed_at": format_taiwan_time(to_taiwan(row["observed_at"])),
                    "unit_type": row["unit_type"],
                    "unit_name": row["unit_name"],
                    "source_time": format_taiwan_time(to_taiwan(row["source_time"])),
                    "capacity_mw": to_float(row["capacity_mw"]),
                    "net_generation_mw": to_float(row["net_generation_mw"]),
                    "capacity_ratio_pct": to_float(row["capacity_ratio_pct"]),
                    "remark": row["remark"],
                    "ingested_at": format_taiwan_time(to_taiwan(row["created_at"])),
                }
            )
        return items, []
