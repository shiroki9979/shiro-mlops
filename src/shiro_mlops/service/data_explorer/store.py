"""Read persisted canonical datasets for Data Explorer without raw payloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from shiro_mlops.core.config import settings
from shiro_mlops.data.repository_utils import deserialize_raw_payload, utc_instant_to_taiwan
from shiro_mlops.data.taipower_regional_supply_demand import REGIONAL_SUPPLY_DEMAND_REGIONS
from shiro_mlops.service.data_explorer.cursor import CursorError, decode_cursor, encode_cursor
from shiro_mlops.service.data_explorer.schemas import DatasetStatus, ListEnvelope, StatusResponse
from shiro_mlops.service.data_explorer.status import derive_overall, evaluate_freshness
from shiro_mlops.service.data_explorer.timefmt import (
    format_taiwan_time,
    now_taiwan,
    parse_api_time,
    to_sql_utc,
)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
WAN_KW_TO_MW = 10.0
FORECAST_SERVING_STALE = timedelta(hours=7)
CURSOR_TIME_COLS = {
    "time",
    "observed_at",
    "fetched_at",
    "issued_at",
    "source_updated_at",
    "valid_from",
    "valid_to",
    "ingested_at",
}

DATASET_SPECS: dict[str, dict[str, Any]] = {
    "hourly_load": {
        "label": "逐時用電負載",
        "cadence": 3600,
        "max_days": 31,
        "href": "/data/power/load",
        "sort": ("time", "location"),
    },
    "national_supply_demand": {
        "label": "全台供需",
        "cadence": 600,
        "max_days": 7,
        "href": "/data/power/supply-demand",
        "sort": ("observed_at",),
    },
    "regional_supply_demand": {
        "label": "區域供需",
        "cadence": 600,
        "max_days": 7,
        "href": "/data/power/regional",
        "sort": ("observed_at", "region"),
    },
    "unit_generation": {
        "label": "機組發電",
        "cadence": 600,
        "max_days": 7,
        "href": "/data/power/units",
        "sort": ("observed_at", "unit_type", "unit_name"),
    },
    "cwa_observations": {
        "label": "CWA 測站觀測",
        "cadence": 3600,
        "max_days": 31,
        "href": "/data/weather/observations",
        "sort": ("observed_at", "station_id"),
    },
    "cwa_forecasts": {
        "label": "CWA 鄉鎮預報",
        "cadence": 3600,
        "max_days": 14,
        "href": "/data/weather/forecasts",
        "sort": ("valid_from", "issued_at", "source_updated_at", "dataset_id", "geocode"),
    },
    "cwa_observation_audits": {
        "label": "CWA 觀測批次審計",
        "cadence": 3600,
        "max_days": 31,
        "href": "/data/audits?type=observations",
        "sort": ("fetched_at",),
    },
    "cwa_forecast_audits": {
        "label": "CWA 預報版本審計",
        "cadence": 3600,
        "max_days": 31,
        "href": "/data/audits?type=forecasts",
        "sort": ("issued_at", "source_updated_at", "dataset_id"),
    },
}


class ExplorerQueryError(ValueError):
    """Raised when a list query uses an invalid bounded window or filter."""


@dataclass(frozen=True)
class TimeWindow:
    """Inclusive Taiwan-local query window."""

    start: datetime
    end: datetime

    def as_utc(self) -> tuple[datetime, datetime]:
        # SQLite 對 aware/naive 時間字串比較會漏掉邊界列，因此將閉區間略為放寬。
        return (
            to_sql_utc(self.start) - timedelta(seconds=1),
            to_sql_utc(self.end) + timedelta(seconds=1),
        )


class DataExplorerStore:
    """Query TimescaleDB canonical tables for the Data Explorer HTTP surface."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list_hourly_load(self, params: dict[str, Any]) -> ListEnvelope:
        """List persisted hourly load rows newest first."""
        return self._list_dataset("hourly_load", params, self._query_hourly_load)

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
            and not _truthy(query_params.get("all_vintages"))
        ):
            latest = self._latest_forecast_version(query_params.get("dataset_id"))
            if latest is not None:
                query_params["dataset_id"] = latest["latest_dataset_id"]
                query_params["issued_at"] = format_taiwan_time(_taiwan(latest["latest_issued_at"]))
                query_params["source_updated_at"] = format_taiwan_time(
                    _taiwan(latest["latest_source_updated_at"])
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
            cursor_key = _sql_cursor_key(raw_key, spec["sort"])
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
                key=_public_cursor_key(items[-1], spec["sort"]),
            )
        return ListEnvelope(
            items=items, next_cursor=next_cursor, has_more=has_more, missing_slots=missing
        )

    def _query_hourly_load(
        self, window: TimeWindow, params: dict[str, Any], cursor: dict[str, Any] | None, limit: int
    ) -> tuple[list[dict[str, Any]], list[str]]:
        clauses = ["time >= :start_time", "time <= :end_time"]
        sql_params: dict[str, Any] = {
            "start_time": window.as_utc()[0],
            "end_time": window.as_utc()[1],
        }
        if params.get("location"):
            clauses.append("location = :location")
            sql_params["location"] = params["location"]
        where, cursor_params = _apply_cursor(clauses, cursor, ("time", "location"))
        sql_params.update(cursor_params)
        query = f"""
            SELECT time, location, load_mw, created_at
            FROM raw_taipower_load
            WHERE {where}
            ORDER BY time DESC, location DESC
            LIMIT :limit
        """
        sql_params["limit"] = limit
        items = []
        for row in self._fetch(query, sql_params):
            observed = _taiwan(row["time"])
            ingested = _taiwan(row["created_at"])
            items.append(
                {
                    "datetime": format_taiwan_time(observed),
                    "location": row["location"],
                    "load_mw": float(row["load_mw"]),
                    "ingested_at": format_taiwan_time(ingested),
                }
            )
        missing = self._hourly_gaps(window, params.get("location"))
        return items, missing

    def _query_national(
        self, window: TimeWindow, params: dict[str, Any], cursor: dict[str, Any] | None, limit: int
    ) -> tuple[list[dict[str, Any]], list[str]]:
        del params
        clauses = ["observed_at >= :start_time", "observed_at <= :end_time"]
        sql_params: dict[str, Any] = {
            "start_time": window.as_utc()[0],
            "end_time": window.as_utc()[1],
        }
        where, cursor_params = _apply_cursor(clauses, cursor, ("observed_at",))
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
            observed = _taiwan(row["observed_at"])
            items.append(
                {
                    "observed_at": format_taiwan_time(observed),
                    "source_publish_time": _optional_time(row["source_publish_time"]),
                    "curr_load_mw": _mw(row["curr_load_wan_kw"]),
                    "curr_load_wan_kw": _float(row["curr_load_wan_kw"]),
                    "curr_util_rate_pct": _float(row["curr_util_rate_pct"]),
                    "fore_maxi_sply_capacity_mw": _mw(row["fore_maxi_sply_capacity_wan_kw"]),
                    "fore_maxi_sply_capacity_wan_kw": _float(row["fore_maxi_sply_capacity_wan_kw"]),
                    "fore_peak_dema_load_mw": _mw(row["fore_peak_dema_load_wan_kw"]),
                    "fore_peak_dema_load_wan_kw": _float(row["fore_peak_dema_load_wan_kw"]),
                    "fore_peak_resv_capacity_mw": _mw(row["fore_peak_resv_capacity_wan_kw"]),
                    "fore_peak_resv_capacity_wan_kw": _float(row["fore_peak_resv_capacity_wan_kw"]),
                    "fore_peak_resv_rate_pct": _float(row["fore_peak_resv_rate_pct"]),
                    "fore_peak_resv_indicator": row["fore_peak_resv_indicator"],
                    "fore_peak_hour_range": row["fore_peak_hour_range"],
                    "yday_date": str(row["yday_date"]) if row["yday_date"] is not None else None,
                    "yday_maxi_sply_capacity_mw": _mw(row["yday_maxi_sply_capacity_wan_kw"]),
                    "yday_maxi_sply_capacity_wan_kw": _float(row["yday_maxi_sply_capacity_wan_kw"]),
                    "yday_peak_dema_load_mw": _mw(row["yday_peak_dema_load_wan_kw"]),
                    "yday_peak_dema_load_wan_kw": _float(row["yday_peak_dema_load_wan_kw"]),
                    "yday_peak_resv_capacity_mw": _mw(row["yday_peak_resv_capacity_wan_kw"]),
                    "yday_peak_resv_capacity_wan_kw": _float(row["yday_peak_resv_capacity_wan_kw"]),
                    "yday_peak_resv_rate_pct": _float(row["yday_peak_resv_rate_pct"]),
                    "yday_peak_resv_indicator": row["yday_peak_resv_indicator"],
                    "real_hr_maxi_sply_capacity_mw": _mw(row["real_hr_maxi_sply_capacity_wan_kw"]),
                    "real_hr_maxi_sply_capacity_wan_kw": _float(
                        row["real_hr_maxi_sply_capacity_wan_kw"]
                    ),
                    "real_hr_peak_time": _optional_time(row["real_hr_peak_time"]),
                    "ingested_at": format_taiwan_time(_taiwan(row["created_at"])),
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
        where, cursor_params = _apply_cursor(clauses, cursor, ("observed_at", "region"))
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
            observed = _taiwan(row["observed_at"])
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
                    "source_time": format_taiwan_time(_taiwan(row["source_time"])),
                    "generation_mw": _mw(row["generation_wan_kw"]),
                    "generation_wan_kw": _float(row["generation_wan_kw"]),
                    "load_mw": _mw(row["load_wan_kw"]),
                    "load_wan_kw": _float(row["load_wan_kw"]),
                    "slot_complete": slot_complete,
                    "missing_regions": missing_regions,
                    "ingested_at": format_taiwan_time(_taiwan(row["created_at"])),
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
        where, cursor_params = _apply_cursor(
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
                    "observed_at": format_taiwan_time(_taiwan(row["observed_at"])),
                    "unit_type": row["unit_type"],
                    "unit_name": row["unit_name"],
                    "source_time": format_taiwan_time(_taiwan(row["source_time"])),
                    "capacity_mw": _float(row["capacity_mw"]),
                    "net_generation_mw": _float(row["net_generation_mw"]),
                    "capacity_ratio_pct": _float(row["capacity_ratio_pct"]),
                    "remark": row["remark"],
                    "ingested_at": format_taiwan_time(_taiwan(row["created_at"])),
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
        where, cursor_params = _apply_cursor(clauses, cursor, ("observed_at", "station_id"))
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
                    "observed_at": format_taiwan_time(_taiwan(row["observed_at"])),
                    "station_id": row["station_id"],
                    "station_name": row["station_name"],
                    "town_code": row["town_code"],
                    "temperature_c": _float(row["temperature_c"]),
                    "relative_humidity_pct": _float(row["relative_humidity_pct"]),
                    "air_pressure_hpa": _float(row["air_pressure_hpa"]),
                    "precipitation_mm": _float(row["precipitation_mm"]),
                    "wind_speed_m_s": _float(row["wind_speed_m_s"]),
                    "wind_direction_deg": _float(row["wind_direction_deg"]),
                    "ingested_at": format_taiwan_time(_taiwan(row["created_at"])),
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
        where, cursor_params = _apply_cursor(
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
                    "issued_at": format_taiwan_time(_taiwan(row["issued_at"])),
                    "source_updated_at": format_taiwan_time(_taiwan(row["source_updated_at"])),
                    "valid_from": format_taiwan_time(_taiwan(row["valid_from"])),
                    "valid_to": format_taiwan_time(_taiwan(row["valid_to"])),
                    "geocode": row["geocode"],
                    "location_name": row["location_name"],
                    "temperature_c": _float(row["temperature_c"]),
                    "dew_point_c": _float(row["dew_point_c"]),
                    "apparent_temperature_c": _float(row["apparent_temperature_c"]),
                    "relative_humidity_pct": _float(row["relative_humidity_pct"]),
                    "probability_of_precipitation_pct": _float(
                        row["probability_of_precipitation_pct"]
                    ),
                    "wind_speed_m_s": _float(row["wind_speed_m_s"]),
                    "wind_direction": row["wind_direction"],
                    "ingested_at": format_taiwan_time(_taiwan(row["created_at"])),
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
        where, cursor_params = _apply_cursor(clauses, cursor, ("fetched_at",))
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
            missing_ids = [str(item) for item in _json_list(row["missing_station_ids"])]
            items.append(
                {
                    "fetched_at": format_taiwan_time(_taiwan(row["fetched_at"])),
                    "status": row["status"],
                    "missing_station_ids": missing_ids,
                    "ingested_at": format_taiwan_time(_taiwan(row["created_at"])),
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
        where, cursor_params = _apply_cursor(
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
                    "issued_at": format_taiwan_time(_taiwan(row["issued_at"])),
                    "source_updated_at": format_taiwan_time(_taiwan(row["source_updated_at"])),
                    "fetched_at": format_taiwan_time(_taiwan(row["fetched_at"])),
                    "status": row["status"],
                    "missing_geocodes": [str(item) for item in _json_list(row["missing_geocodes"])],
                    "ingested_at": format_taiwan_time(_taiwan(row["created_at"])),
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
            latest_source = _taiwan(latest["source_at"])
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
                window = TimeWindow(_taiwan(earliest["source_at"]), latest_source)
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
            slot = _taiwan(latest["source_at"])
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
            source_at = _taiwan(latest["source_at"])
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
        source_at = _taiwan(latest["source_at"])
        ingested_at = _taiwan(latest["ingested_at"])
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
        clauses = ["time >= :start_time", "time <= :end_time"]
        params: dict[str, Any] = {"start_time": window.as_utc()[0], "end_time": window.as_utc()[1]}
        if location:
            clauses.append("location = :location")
            params["location"] = location
        rows = self._fetch(
            f"SELECT DISTINCT time FROM raw_taipower_load WHERE {' AND '.join(clauses)}",
            params,
        )
        present = {_taiwan(row["time"]).replace(minute=0, second=0, microsecond=0) for row in rows}
        start = window.start.replace(minute=0, second=0, microsecond=0)
        expected = pd.date_range(start, window.end, freq="h")
        return [
            format_taiwan_time(ts.to_pydatetime())
            for ts in expected
            if ts.to_pydatetime() not in present
        ]

    def _ten_minute_gaps(
        self, table: str, window: TimeWindow, slot_complete: bool | None
    ) -> list[str]:
        del slot_complete
        rows = self._fetch(
            f"SELECT DISTINCT observed_at FROM {table} "
            "WHERE observed_at >= :start_time AND observed_at <= :end_time",
            {"start_time": window.as_utc()[0], "end_time": window.as_utc()[1]},
        )
        present = {_taiwan(row["observed_at"]) for row in rows}
        start = _floor_ten_minutes(window.start)
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
                _taiwan(row["observed_at"]).replace(minute=0, second=0, microsecond=0),
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
            grouped.setdefault(_taiwan(row["observed_at"]), set()).add(row["region"])
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
            "fetched_at": _taiwan(row["fetched_at"]),
            "status": row["status"],
            "missing_station_ids": [str(item) for item in _json_list(row["missing_station_ids"])],
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
            "missing_geocodes": [str(item) for item in _json_list(row["missing_geocodes"])],
        }

    def _fetch(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(text(query), params or {}).mappings()]

    def _latest_row(
        self, query: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        rows = self._fetch(query, params)
        return rows[0] if rows else None

    def _scalar(self, query: str) -> Any:
        with self.engine.connect() as conn:
            return conn.execute(text(query)).scalar()


class DatabaseUnavailableError(RuntimeError):
    """Raised when the operational store cannot be queried."""


def resolve_window(
    start: str | datetime | None, end: str | datetime | None, max_days: int
) -> TimeWindow:
    """Require a bounded window and reject ranges that exceed the dataset maximum."""
    clock = now_taiwan()
    try:
        parsed_end = parse_api_time(end) if end is not None else clock
        parsed_start = (
            parse_api_time(start) if start is not None else parsed_end - timedelta(hours=24)
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ExplorerQueryError("start and end must be valid RFC 3339 timestamps") from exc
    if parsed_start > parsed_end:
        raise ExplorerQueryError("start must be earlier than or equal to end")
    if parsed_end - parsed_start > timedelta(days=max_days):
        raise ExplorerQueryError(f"time range cannot exceed {max_days} days")
    return TimeWindow(parsed_start, parsed_end)


def resolve_limit(limit: int | str | None) -> int:
    """Clamp page size to the shared default and maximum."""
    if limit is None or limit == "":
        return DEFAULT_LIMIT
    try:
        parsed = int(limit)
    except (TypeError, ValueError) as exc:
        raise ExplorerQueryError("limit must be an integer") from exc
    if parsed < 1 or parsed > MAX_LIMIT:
        raise ExplorerQueryError(f"limit must be between 1 and {MAX_LIMIT}")
    return parsed


def bound_filters(dataset: str, params: dict[str, Any], window: TimeWindow) -> dict[str, Any]:
    """Canonical filter payload stored inside a keyset cursor."""
    filters = {
        "start": format_taiwan_time(window.start),
        "end": format_taiwan_time(window.end),
    }
    for key in (
        "location",
        "region",
        "completeness",
        "unit_type",
        "unit_name",
        "station_id",
        "dataset_id",
        "geocode",
        "issued_at",
        "source_updated_at",
        "status",
        "missing_station_id",
        "missing_geocode",
        "all_vintages",
    ):
        value = params.get(key)
        if value not in (None, ""):
            filters[key] = str(value)
    filters["dataset"] = dataset
    return filters


def _apply_cursor(
    clauses: list[str], cursor: dict[str, Any] | None, columns: tuple[str, ...]
) -> tuple[str, dict[str, Any]]:
    params: dict[str, Any] = {}
    if not cursor:
        return " AND ".join(clauses), params
    parts: list[str] = []
    for index, column in enumerate(columns):
        equal = " AND ".join(f"{item} = :k_{item}" for item in columns[:index])
        comparison = f"{column} < :k_{column}"
        parts.append(f"({equal} AND {comparison})" if equal else comparison)
        params[f"k_{column}"] = cursor[column]
    clauses.append("(" + " OR ".join(parts) + ")")
    return " AND ".join(clauses), params


def _sql_cursor_key(key: dict[str, Any], columns: tuple[str, ...]) -> dict[str, Any]:
    converted: dict[str, Any] = {}
    for column in columns:
        if column not in key or key[column] is None:
            raise CursorError("Invalid cursor key")
        value = key[column]
        try:
            converted[column] = (
                to_sql_utc(value) if column in CURSOR_TIME_COLS or column.endswith("_at") else value
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise CursorError("Invalid cursor key") from exc
    return converted


def _public_cursor_key(item: dict[str, Any], columns: tuple[str, ...]) -> dict[str, Any]:
    mapping = {"time": "datetime"}
    public = {}
    for column in columns:
        field = mapping.get(column, column)
        public[column] = item[field]
    return public


def _taiwan(value: object) -> datetime:
    converted = utc_instant_to_taiwan(value)
    if converted is None:
        raise ValueError("Timestamp is required")
    return converted


def _optional_time(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    return format_taiwan_time(_taiwan(value))


def _float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _mw(value: object) -> float | None:
    wan_kw = _float(value)
    if wan_kw is None:
        return None
    return wan_kw * WAN_KW_TO_MW


def _json_list(value: object) -> list[Any]:
    if value in (None, ""):
        return []
    parsed = deserialize_raw_payload(value)
    if parsed is None:
        return []
    if isinstance(parsed, list):
        return parsed
    return list(parsed)


def _floor_ten_minutes(value: datetime) -> datetime:
    return value.replace(minute=(value.minute // 10) * 10, second=0, microsecond=0)


def _truthy(value: object) -> bool:
    return str(value).lower() in {"1", "true", "yes"}
