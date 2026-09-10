"""Read persisted canonical datasets for Data Explorer without raw payloads."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from shiro_mlops.core.config import settings
from shiro_mlops.data.taipower_regional_supply_demand import REGIONAL_SUPPLY_DEMAND_REGIONS
from shiro_mlops.service.data_explorer.completeness import hourly_gaps
from shiro_mlops.service.data_explorer.cursor import decode_cursor, encode_cursor
from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.errors import DatabaseUnavailableError, ExplorerQueryError
from shiro_mlops.service.data_explorer.hourly_load import HourlyLoadReader
from shiro_mlops.service.data_explorer.pagination import (
    apply_cursor,
    public_cursor_key,
    sql_cursor_key,
)
from shiro_mlops.service.data_explorer.query import (
    TimeWindow,
    bound_filters,
    resolve_limit,
    resolve_window,
)
from shiro_mlops.service.data_explorer.schemas import DatasetStatus, ListEnvelope, StatusResponse
from shiro_mlops.service.data_explorer.specs import DATASET_SPECS
from shiro_mlops.service.data_explorer.status import derive_overall, evaluate_freshness
from shiro_mlops.service.data_explorer.timefmt import format_taiwan_time, now_taiwan, to_sql_utc
from shiro_mlops.service.data_explorer.values import (
    floor_ten_minutes,
    is_truthy,
    json_list,
    optional_time,
    to_float,
    to_mw,
    to_taiwan,
)

FORECAST_SERVING_STALE = timedelta(hours=7)


class DataExplorerStore:
    """Query TimescaleDB canonical tables for the Data Explorer HTTP surface."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._db = ExplorerDb(engine)

    def list_hourly_load(self, params: dict[str, Any]) -> ListEnvelope:
        """List persisted hourly load rows newest first."""
        return HourlyLoadReader(self.engine).list(params)

    def list_national_supply_demand(self, params: dict[str, Any]) -> ListEnvelope:
        """List persisted national supply-demand snapshots newest first."""
        return self._list_dataset("national_supply_demand", params, self._query_national)

    def list_regional_supply_demand(self, params: dict[str, Any]) -> ListEnvelope:
        """List persisted regional snapshots newest first."""
        return self._list_dataset("regional_supply_demand", params, self._query_regional)

    def list_unit_generation(self, params: dict[str, Any]) -> ListEnvelope:
        """List persisted unit-generation snapshots newest first."""
        return self._list_dataset("unit_generation", params, self._query_units)

    def list_observations(self, params: dict[str, Any]) -> ListEnvelope:
        """List persisted CWA station observations newest first."""
        return self._list_dataset("cwa_observations", params, self._query_observations)

    def list_forecasts(self, params: dict[str, Any]) -> ListEnvelope:
        """List persisted CWA township forecasts newest first."""
        query_params = dict(params)
        if (
            not query_params.get("issued_at")
            and not query_params.get("source_updated_at")
            and not is_truthy(query_params.get("all_vintages"))
        ):
            latest = self._latest_forecast_version(query_params.get("dataset_id"))
            if latest is not None:
                query_params["dataset_id"] = latest["latest_dataset_id"]
                query_params["issued_at"] = format_taiwan_time(
                    to_taiwan(latest["latest_issued_at"])
                )
                query_params["source_updated_at"] = format_taiwan_time(
                    to_taiwan(latest["latest_source_updated_at"])
                )
        return self._list_dataset("cwa_forecasts", query_params, self._query_forecasts)

    def list_observation_audits(self, params: dict[str, Any]) -> ListEnvelope:
        """List CWA observation batch audit headers without raw payloads."""
        return self._list_dataset("cwa_observation_audits", params, self._query_observation_audits)

    def list_forecast_audits(self, params: dict[str, Any]) -> ListEnvelope:
        """List CWA forecast release audit headers without raw payloads."""
        return self._list_dataset("cwa_forecast_audits", params, self._query_forecast_audits)

    def status(self, as_of: datetime | None = None) -> StatusResponse:
        """Compute independent status dimensions for every v1 dataset."""
        clock = as_of or now_taiwan()
        try:
            return self._status(clock)
        except SQLAlchemyError as exc:
            raise DatabaseUnavailableError(str(exc)) from exc

    def _status(self, clock: datetime) -> StatusResponse:
        builders = (
            self._status_hourly_load,
            self._status_national,
            self._status_regional,
            self._status_units,
            self._status_observations,
            self._status_forecasts,
            self._status_observation_audits,
            self._status_forecast_audits,
        )
        return StatusResponse(datasets=[builder(clock) for builder in builders])

    def _list_dataset(self, dataset: str, params: dict[str, Any], query) -> ListEnvelope:
        spec = DATASET_SPECS[dataset]
        window = resolve_window(params.get("start"), params.get("end"), spec["max_days"])
        limit = resolve_limit(params.get("limit"))
        filters = bound_filters(dataset, params, window)
        cursor_key = None
        if params.get("cursor"):
            raw_key = decode_cursor(params["cursor"], dataset=dataset, filters=filters)
            cursor_key = sql_cursor_key(raw_key, spec["sort"])
        try:
            rows, missing = query(window, params, cursor_key, limit + 1)
        except SQLAlchemyError as exc:
            raise DatabaseUnavailableError(str(exc)) from exc
        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = None
        if has_more and items:
            next_cursor = encode_cursor(
                dataset=dataset,
                filters=filters,
                key=public_cursor_key(items[-1], spec["sort"]),
            )
        return ListEnvelope(
            items=items, next_cursor=next_cursor, has_more=has_more, missing_slots=missing
        )

    def _query_national(
        self, window: TimeWindow, params: dict[str, Any], cursor: dict[str, Any] | None, limit: int
    ) -> tuple[list[dict[str, Any]], list[str]]:
        del params
        clauses = ["observed_at >= :start_time", "observed_at <= :end_time"]
        sql_params: dict[str, Any] = {
            "start_time": window.as_utc()[0],
            "end_time": window.as_utc()[1],
        }
        where, cursor_params = apply_cursor(clauses, cursor, ("observed_at",))
        sql_params.update(cursor_params)
        query = f"""
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
        for row in self._fetch(query, sql_params):
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
        return items, self._ten_minute_gaps(
            "raw_taipower_supply_demand_snapshot", window, slot_complete=None
        )

    def _query_regional(
        self, window: TimeWindow, params: dict[str, Any], cursor: dict[str, Any] | None, limit: int
    ) -> tuple[list[dict[str, Any]], list[str]]:
        completeness = params.get("completeness")
        if completeness not in (None, "", "complete", "incomplete"):
            raise ExplorerQueryError("completeness must be complete or incomplete")
        clauses = ["observed_at >= :start_time", "observed_at <= :end_time"]
        sql_params: dict[str, Any] = {
            "start_time": window.as_utc()[0],
            "end_time": window.as_utc()[1],
        }
        if params.get("region"):
            if params["region"] not in REGIONAL_SUPPLY_DEMAND_REGIONS:
                raise ExplorerQueryError("region must be one of 北部, 中部, 南部, 東部")
            clauses.append("region = :region")
            sql_params["region"] = params["region"]
        where, cursor_params = apply_cursor(clauses, cursor, ("observed_at", "region"))
        sql_params.update(cursor_params)
        query = f"""
            SELECT observed_at, region, source_time, generation_wan_kw, load_wan_kw, created_at
            FROM raw_taipower_regional_supply_demand_snapshot
            WHERE {where}
            ORDER BY observed_at DESC, region DESC
            LIMIT :limit
        """
        sql_params["limit"] = limit * 4 if completeness else limit
        rows = self._fetch(query, sql_params)
        slot_regions = self._regional_slot_map(window)
        items = []
        for row in rows:
            observed = to_taiwan(row["observed_at"])
            present = slot_regions.get(observed, set())
            missing_regions = [
                name for name in REGIONAL_SUPPLY_DEMAND_REGIONS if name not in present
            ]
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

    def _query_units(
        self, window: TimeWindow, params: dict[str, Any], cursor: dict[str, Any] | None, limit: int
    ) -> tuple[list[dict[str, Any]], list[str]]:
        clauses = ["observed_at >= :start_time", "observed_at <= :end_time"]
        sql_params: dict[str, Any] = {
            "start_time": window.as_utc()[0],
            "end_time": window.as_utc()[1],
        }
        if params.get("unit_type"):
            clauses.append("unit_type = :unit_type")
            sql_params["unit_type"] = params["unit_type"]
        if params.get("unit_name"):
            clauses.append("unit_name = :unit_name")
            sql_params["unit_name"] = params["unit_name"]
        where, cursor_params = apply_cursor(
            clauses, cursor, ("observed_at", "unit_type", "unit_name")
        )
        sql_params.update(cursor_params)
        query = f"""
            SELECT observed_at, unit_type, unit_name, source_time, capacity_mw,
                   net_generation_mw, capacity_ratio_pct, remark, created_at
            FROM raw_taipower_unit_generation_snapshot
            WHERE {where}
            ORDER BY observed_at DESC, unit_type DESC, unit_name DESC
            LIMIT :limit
        """
        sql_params["limit"] = limit
        items = []
        for row in self._fetch(query, sql_params):
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

    def _query_observations(
        self, window: TimeWindow, params: dict[str, Any], cursor: dict[str, Any] | None, limit: int
    ) -> tuple[list[dict[str, Any]], list[str]]:
        clauses = ["observed_at >= :start_time", "observed_at <= :end_time"]
        sql_params: dict[str, Any] = {
            "start_time": window.as_utc()[0],
            "end_time": window.as_utc()[1],
        }
        if params.get("station_id"):
            clauses.append("station_id = :station_id")
            sql_params["station_id"] = params["station_id"]
        where, cursor_params = apply_cursor(clauses, cursor, ("observed_at", "station_id"))
        sql_params.update(cursor_params)
        query = f"""
            SELECT observed_at, station_id, station_name, town_code, temperature_c,
                   relative_humidity_pct, air_pressure_hpa, precipitation_mm,
                   wind_speed_m_s, wind_direction_deg, created_at
            FROM raw_cwa_station_observation
            WHERE {where}
            ORDER BY observed_at DESC, station_id DESC
            LIMIT :limit
        """
        sql_params["limit"] = limit
        items = []
        for row in self._fetch(query, sql_params):
            items.append(
                {
                    "observed_at": format_taiwan_time(to_taiwan(row["observed_at"])),
                    "station_id": row["station_id"],
                    "station_name": row["station_name"],
                    "town_code": row["town_code"],
                    "temperature_c": to_float(row["temperature_c"]),
                    "relative_humidity_pct": to_float(row["relative_humidity_pct"]),
                    "air_pressure_hpa": to_float(row["air_pressure_hpa"]),
                    "precipitation_mm": to_float(row["precipitation_mm"]),
                    "wind_speed_m_s": to_float(row["wind_speed_m_s"]),
                    "wind_direction_deg": to_float(row["wind_direction_deg"]),
                    "ingested_at": format_taiwan_time(to_taiwan(row["created_at"])),
                }
            )
        return items, self._observation_gaps(window, params.get("station_id"))

    def _query_forecasts(
        self, window: TimeWindow, params: dict[str, Any], cursor: dict[str, Any] | None, limit: int
    ) -> tuple[list[dict[str, Any]], list[str]]:
        clauses = ["valid_from >= :start_time", "valid_from <= :end_time"]
        sql_params: dict[str, Any] = {
            "start_time": window.as_utc()[0],
            "end_time": window.as_utc()[1],
        }
        if params.get("dataset_id"):
            clauses.append("dataset_id = :dataset_id")
            sql_params["dataset_id"] = params["dataset_id"]
        if params.get("geocode"):
            clauses.append("geocode = :geocode")
            sql_params["geocode"] = params["geocode"]
        if params.get("issued_at"):
            clauses.append("issued_at = :issued_at")
            sql_params["issued_at"] = to_sql_utc(params["issued_at"])
        if params.get("source_updated_at"):
            clauses.append("source_updated_at = :source_updated_at")
            sql_params["source_updated_at"] = to_sql_utc(params["source_updated_at"])
        where, cursor_params = apply_cursor(
            clauses,
            cursor,
            ("valid_from", "issued_at", "source_updated_at", "dataset_id", "geocode"),
        )
        sql_params.update(cursor_params)
        query = f"""
            SELECT dataset_id, issued_at, source_updated_at, valid_from, valid_to, geocode,
                   location_name, temperature_c, dew_point_c, apparent_temperature_c,
                   relative_humidity_pct, probability_of_precipitation_pct, wind_speed_m_s,
                   wind_direction, created_at
            FROM raw_cwa_township_forecast
            WHERE {where}
            ORDER BY valid_from DESC, issued_at DESC, source_updated_at DESC,
                     dataset_id DESC, geocode DESC
            LIMIT :limit
        """
        sql_params["limit"] = limit
        items = []
        for row in self._fetch(query, sql_params):
            items.append(
                {
                    "dataset_id": row["dataset_id"],
                    "issued_at": format_taiwan_time(to_taiwan(row["issued_at"])),
                    "source_updated_at": format_taiwan_time(to_taiwan(row["source_updated_at"])),
                    "valid_from": format_taiwan_time(to_taiwan(row["valid_from"])),
                    "valid_to": format_taiwan_time(to_taiwan(row["valid_to"])),
                    "geocode": row["geocode"],
                    "location_name": row["location_name"],
                    "temperature_c": to_float(row["temperature_c"]),
                    "dew_point_c": to_float(row["dew_point_c"]),
                    "apparent_temperature_c": to_float(row["apparent_temperature_c"]),
                    "relative_humidity_pct": to_float(row["relative_humidity_pct"]),
                    "probability_of_precipitation_pct": to_float(
                        row["probability_of_precipitation_pct"]
                    ),
                    "wind_speed_m_s": to_float(row["wind_speed_m_s"]),
                    "wind_direction": row["wind_direction"],
                    "ingested_at": format_taiwan_time(to_taiwan(row["created_at"])),
                }
            )
        return items, []

    def _query_observation_audits(
        self, window: TimeWindow, params: dict[str, Any], cursor: dict[str, Any] | None, limit: int
    ) -> tuple[list[dict[str, Any]], list[str]]:
        clauses = ["fetched_at >= :start_time", "fetched_at <= :end_time"]
        sql_params: dict[str, Any] = {
            "start_time": window.as_utc()[0],
            "end_time": window.as_utc()[1],
        }
        if params.get("status"):
            if params["status"] not in {"complete", "incomplete"}:
                raise ExplorerQueryError("status must be complete or incomplete")
            clauses.append("status = :status")
            sql_params["status"] = params["status"]
        if params.get("missing_station_id"):
            clauses.append("CAST(missing_station_ids AS TEXT) LIKE :missing_station")
            sql_params["missing_station"] = f'%"{params["missing_station_id"]}"%'
        where, cursor_params = apply_cursor(clauses, cursor, ("fetched_at",))
        sql_params.update(cursor_params)
        query = f"""
            SELECT fetched_at, status, missing_station_ids, created_at
            FROM raw_cwa_observation_batch
            WHERE {where}
            ORDER BY fetched_at DESC
            LIMIT :limit
        """
        sql_params["limit"] = limit
        items = []
        for row in self._fetch(query, sql_params):
            missing_ids = [str(item) for item in json_list(row["missing_station_ids"])]
            items.append(
                {
                    "fetched_at": format_taiwan_time(to_taiwan(row["fetched_at"])),
                    "status": row["status"],
                    "missing_station_ids": missing_ids,
                    "ingested_at": format_taiwan_time(to_taiwan(row["created_at"])),
                }
            )
        return items, []

    def _query_forecast_audits(
        self, window: TimeWindow, params: dict[str, Any], cursor: dict[str, Any] | None, limit: int
    ) -> tuple[list[dict[str, Any]], list[str]]:
        clauses = ["issued_at >= :start_time", "issued_at <= :end_time"]
        sql_params: dict[str, Any] = {
            "start_time": window.as_utc()[0],
            "end_time": window.as_utc()[1],
        }
        if params.get("dataset_id"):
            clauses.append("dataset_id = :dataset_id")
            sql_params["dataset_id"] = params["dataset_id"]
        if params.get("status"):
            if params["status"] not in {"complete", "incomplete"}:
                raise ExplorerQueryError("status must be complete or incomplete")
            clauses.append("status = :status")
            sql_params["status"] = params["status"]
        if params.get("missing_geocode"):
            clauses.append("CAST(missing_geocodes AS TEXT) LIKE :missing_geocode")
            sql_params["missing_geocode"] = f'%"{params["missing_geocode"]}"%'
        where, cursor_params = apply_cursor(
            clauses, cursor, ("issued_at", "source_updated_at", "dataset_id")
        )
        sql_params.update(cursor_params)
        query = f"""
            SELECT dataset_id, issued_at, source_updated_at, fetched_at, status,
                   missing_geocodes, created_at
            FROM raw_cwa_forecast_release
            WHERE {where}
            ORDER BY issued_at DESC, source_updated_at DESC, dataset_id DESC
            LIMIT :limit
        """
        sql_params["limit"] = limit
        items = []
        for row in self._fetch(query, sql_params):
            items.append(
                {
                    "dataset_id": row["dataset_id"],
                    "issued_at": format_taiwan_time(to_taiwan(row["issued_at"])),
                    "source_updated_at": format_taiwan_time(to_taiwan(row["source_updated_at"])),
                    "fetched_at": format_taiwan_time(to_taiwan(row["fetched_at"])),
                    "status": row["status"],
                    "missing_geocodes": [str(item) for item in json_list(row["missing_geocodes"])],
                    "ingested_at": format_taiwan_time(to_taiwan(row["created_at"])),
                }
            )
        return items, []

    def _status_hourly_load(self, as_of: datetime) -> DatasetStatus:
        latest = self._latest_row(
            "SELECT time AS source_at, created_at AS ingested_at FROM raw_taipower_load "
            "ORDER BY time DESC LIMIT 1"
        )
        window = TimeWindow(as_of - timedelta(hours=24), as_of)
        missing = self._hourly_gaps(window, None) if latest else []
        return self._build_status("hourly_load", as_of, latest, missing)

    def _status_national(self, as_of: datetime) -> DatasetStatus:
        latest = self._latest_row(
            "SELECT observed_at AS source_at, created_at AS ingested_at "
            "FROM raw_taipower_supply_demand_snapshot ORDER BY observed_at DESC LIMIT 1"
        )
        missing: list[str] = []
        if latest:
            latest_source = to_taiwan(latest["source_at"])
            earliest = self._latest_row(
                "SELECT MIN(observed_at) AS source_at "
                "FROM raw_taipower_supply_demand_snapshot "
                "WHERE observed_at >= :start_time AND observed_at <= :end_time",
                {
                    "start_time": to_sql_utc(latest_source - timedelta(hours=24)),
                    "end_time": to_sql_utc(latest_source),
                },
            )
            if earliest and earliest["source_at"] is not None:
                window = TimeWindow(to_taiwan(earliest["source_at"]), latest_source)
                missing = self._ten_minute_gaps(
                    "raw_taipower_supply_demand_snapshot", window, slot_complete=None
                )
        return self._build_status("national_supply_demand", as_of, latest, missing)

    def _status_regional(self, as_of: datetime) -> DatasetStatus:
        latest = self._latest_row(
            "SELECT observed_at AS source_at, created_at AS ingested_at "
            "FROM raw_taipower_regional_supply_demand_snapshot ORDER BY observed_at DESC LIMIT 1"
        )
        missing: list[str] = []
        if latest:
            slot = to_taiwan(latest["source_at"])
            present = self._regional_slot_map(TimeWindow(slot, slot)).get(slot, set())
            missing = [name for name in REGIONAL_SUPPLY_DEMAND_REGIONS if name not in present]
        status = self._build_status("regional_supply_demand", as_of, latest, missing)
        if missing:
            status.href = "/data/power/regional?completeness=incomplete"
        return status

    def _status_units(self, as_of: datetime) -> DatasetStatus:
        latest = self._latest_row(
            "SELECT observed_at AS source_at, created_at AS ingested_at "
            "FROM raw_taipower_unit_generation_snapshot ORDER BY observed_at DESC LIMIT 1"
        )
        count = self._scalar(
            "SELECT COUNT(*) FROM raw_taipower_unit_generation_snapshot "
            "WHERE observed_at = (SELECT MAX(observed_at) FROM raw_taipower_unit_generation_snapshot)"
        )
        status = self._build_status("unit_generation", as_of, latest, [])
        status.record_count = int(count or 0) if latest else 0
        if latest:
            status.completeness = "complete"
            status.overall = derive_overall(status.availability, status.freshness, "complete")
        return status

    def _status_observations(self, as_of: datetime) -> DatasetStatus:
        latest = self._latest_row(
            "SELECT observed_at AS source_at, created_at AS ingested_at "
            "FROM raw_cwa_station_observation ORDER BY observed_at DESC LIMIT 1"
        )
        audit = self._latest_observation_audit()
        missing = list(audit["missing_station_ids"]) if audit else []
        if audit and audit["status"] == "incomplete" and not missing:
            missing = ["incomplete_batch"]
        status = self._build_status("cwa_observations", as_of, latest, missing)
        return status

    def _status_forecasts(self, as_of: datetime) -> DatasetStatus:
        latest = self._latest_row(
            "SELECT issued_at AS source_at, fetched_at AS ingested_at "
            "FROM raw_cwa_forecast_release ORDER BY issued_at DESC, source_updated_at DESC LIMIT 1"
        )
        audit = self._latest_forecast_audit()
        missing = list(audit["missing_geocodes"]) if audit else []
        if audit and audit["status"] == "incomplete" and not missing:
            missing = ["incomplete_release"]
        status = self._build_status("cwa_forecasts", as_of, latest, missing)
        if latest:
            source_at = to_taiwan(latest["source_at"])
            status.serving_stale = (as_of - source_at) > FORECAST_SERVING_STALE
        return status

    def _status_observation_audits(self, as_of: datetime) -> DatasetStatus:
        latest = self._latest_row(
            "SELECT fetched_at AS source_at, created_at AS ingested_at "
            "FROM raw_cwa_observation_batch ORDER BY fetched_at DESC LIMIT 1"
        )
        audit = self._latest_observation_audit()
        missing = list(audit["missing_station_ids"]) if audit else []
        return self._build_status("cwa_observation_audits", as_of, latest, missing)

    def _status_forecast_audits(self, as_of: datetime) -> DatasetStatus:
        latest = self._latest_row(
            "SELECT issued_at AS source_at, fetched_at AS ingested_at "
            "FROM raw_cwa_forecast_release ORDER BY issued_at DESC, source_updated_at DESC LIMIT 1"
        )
        audit = self._latest_forecast_audit()
        missing = list(audit["missing_geocodes"]) if audit else []
        return self._build_status("cwa_forecast_audits", as_of, latest, missing)

    def _build_status(
        self,
        dataset_id: str,
        as_of: datetime,
        latest: dict[str, Any] | None,
        missing: list[str],
    ) -> DatasetStatus:
        spec = DATASET_SPECS[dataset_id]
        if latest is None:
            freshness = evaluate_freshness(
                cadence_seconds=spec["cadence"],
                as_of=as_of,
                latest_source_at=None,
                latest_ingested_at=None,
            )
            return DatasetStatus(
                id=dataset_id,
                label=spec["label"],
                availability="empty",
                freshness=freshness.state,
                completeness="unknown",
                overall=derive_overall("empty", freshness.state, "unknown"),
                href=spec["href"],
            )
        source_at = to_taiwan(latest["source_at"])
        ingested_at = to_taiwan(latest["ingested_at"])
        freshness = evaluate_freshness(
            cadence_seconds=spec["cadence"],
            as_of=as_of,
            latest_source_at=source_at,
            latest_ingested_at=ingested_at,
        )
        completeness = "incomplete" if missing else "complete"
        return DatasetStatus(
            id=dataset_id,
            label=spec["label"],
            availability="available",
            freshness=freshness.state,
            completeness=completeness,
            overall=derive_overall("available", freshness.state, completeness),
            latest_source_at=format_taiwan_time(source_at),
            latest_ingested_at=format_taiwan_time(ingested_at),
            ingestion_age_seconds=freshness.ingestion_age_seconds,
            source_age_seconds=freshness.source_age_seconds,
            missing_identifiers=missing,
            missing_slot_count=len(missing),
            href=spec["href"],
        )

    def _hourly_gaps(self, window: TimeWindow, location: str | None) -> list[str]:
        return hourly_gaps(self._db, window, location)

    def _ten_minute_gaps(
        self, table: str, window: TimeWindow, slot_complete: bool | None
    ) -> list[str]:
        del slot_complete
        rows = self._fetch(
            f"SELECT DISTINCT observed_at FROM {table} "
            "WHERE observed_at >= :start_time AND observed_at <= :end_time",
            {"start_time": window.as_utc()[0], "end_time": window.as_utc()[1]},
        )
        present = {to_taiwan(row["observed_at"]) for row in rows}
        start = floor_ten_minutes(window.start)
        expected = pd.date_range(start, window.end, freq="10min")
        return [
            format_taiwan_time(ts.to_pydatetime())
            for ts in expected
            if ts.to_pydatetime() not in present
        ]

    def _observation_gaps(self, window: TimeWindow, station_id: str | None) -> list[str]:
        allowlist = list(settings.cwa_locations.values())
        station_ids = [station_id] if station_id else [item.station_id for item in allowlist]
        rows = self._fetch(
            "SELECT observed_at, station_id FROM raw_cwa_station_observation "
            "WHERE observed_at >= :start_time AND observed_at <= :end_time",
            {"start_time": window.as_utc()[0], "end_time": window.as_utc()[1]},
        )
        present = {
            (
                to_taiwan(row["observed_at"]).replace(minute=0, second=0, microsecond=0),
                row["station_id"],
            )
            for row in rows
        }
        start = window.start.replace(minute=0, second=0, microsecond=0)
        expected_hours = pd.date_range(start, window.end, freq="h")
        missing = []
        for hour in expected_hours:
            for sid in station_ids:
                if (hour.to_pydatetime(), sid) not in present:
                    missing.append(f"{format_taiwan_time(hour.to_pydatetime())}:{sid}")
        return missing

    def _regional_slot_map(self, window: TimeWindow) -> dict[datetime, set[str]]:
        rows = self._fetch(
            "SELECT observed_at, region FROM raw_taipower_regional_supply_demand_snapshot "
            "WHERE observed_at >= :start_time AND observed_at <= :end_time",
            {"start_time": window.as_utc()[0], "end_time": window.as_utc()[1]},
        )
        grouped: dict[datetime, set[str]] = {}
        for row in rows:
            grouped.setdefault(to_taiwan(row["observed_at"]), set()).add(row["region"])
        return grouped

    def _latest_forecast_version(self, dataset_id: str | None) -> dict[str, Any] | None:
        clauses = []
        params: dict[str, Any] = {}
        if dataset_id:
            clauses.append("dataset_id = :dataset_id")
            params["dataset_id"] = dataset_id
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        row = self._latest_row(
            f"""
            SELECT dataset_id, issued_at, source_updated_at
            FROM raw_cwa_forecast_release
            {where}
            ORDER BY issued_at DESC, source_updated_at DESC
            LIMIT 1
            """,
            params,
        )
        if row is None:
            return None
        return {
            "latest_dataset_id": row["dataset_id"],
            "latest_issued_at": row["issued_at"],
            "latest_source_updated_at": row["source_updated_at"],
        }

    def _latest_observation_audit(self) -> dict[str, Any] | None:
        row = self._latest_row(
            "SELECT fetched_at, status, missing_station_ids FROM raw_cwa_observation_batch "
            "ORDER BY fetched_at DESC LIMIT 1"
        )
        if row is None:
            return None
        return {
            "fetched_at": to_taiwan(row["fetched_at"]),
            "status": row["status"],
            "missing_station_ids": [str(item) for item in json_list(row["missing_station_ids"])],
        }

    def _latest_forecast_audit(self) -> dict[str, Any] | None:
        row = self._latest_row(
            "SELECT dataset_id, issued_at, fetched_at, status, missing_geocodes "
            "FROM raw_cwa_forecast_release ORDER BY issued_at DESC, source_updated_at DESC LIMIT 1"
        )
        if row is None:
            return None
        return {
            "status": row["status"],
            "missing_geocodes": [str(item) for item in json_list(row["missing_geocodes"])],
        }

    def _fetch(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self._db.fetch(query, params)

    def _latest_row(
        self, query: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        return self._db.latest_row(query, params)

    def _scalar(self, query: str) -> Any:
        return self._db.scalar(query)
