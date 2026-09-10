"""CWA observation, forecast, and audit readers behind the typed query seam."""

from __future__ import annotations

from typing import Any

from shiro_mlops.service.data_explorer.completeness import observation_gaps
from shiro_mlops.service.data_explorer.dataset_reader import DatasetReader
from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.errors import ExplorerQueryError
from shiro_mlops.service.data_explorer.pagination import apply_cursor
from shiro_mlops.service.data_explorer.query import ExplorerQuery
from shiro_mlops.service.data_explorer.timefmt import format_taiwan_time, to_sql_utc
from shiro_mlops.service.data_explorer.values import is_truthy, json_list, to_float, to_taiwan


def latest_forecast_version(db: ExplorerDb, dataset_id: str | None) -> dict[str, Any] | None:
    """Return the newest persisted forecast release, optionally scoped to one dataset."""
    clauses = []
    params: dict[str, Any] = {}
    if dataset_id:
        clauses.append("dataset_id = :dataset_id")
        params["dataset_id"] = dataset_id
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    row = db.latest_row(
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


def _audit_status(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    if value not in {"complete", "incomplete"}:
        raise ExplorerQueryError("status must be complete or incomplete")
    return value


class ObservationReader(DatasetReader):
    """List persisted CWA station observations newest first."""

    dataset = "cwa_observations"

    def fetch_page(
        self,
        query: ExplorerQuery,
        cursor: dict[str, Any] | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        station_id = query.filters.get("station_id")
        clauses = ["observed_at >= :start_time", "observed_at <= :end_time"]
        sql_params: dict[str, Any] = {
            "start_time": query.window.as_utc()[0],
            "end_time": query.window.as_utc()[1],
        }
        if station_id:
            clauses.append("station_id = :station_id")
            sql_params["station_id"] = station_id
        where, cursor_params = apply_cursor(clauses, cursor, ("observed_at", "station_id"))
        sql_params.update(cursor_params)
        sql = f"""
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
        for row in self.db.fetch(sql, sql_params):
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
        return items, observation_gaps(self.db, query.window, station_id)


class ForecastReader(DatasetReader):
    """List persisted CWA township forecasts newest first."""

    dataset = "cwa_forecasts"

    def build_query(self, params: dict[str, Any]) -> ExplorerQuery:
        query_params = dict(params)
        if (
            not query_params.get("issued_at")
            and not query_params.get("source_updated_at")
            and not is_truthy(query_params.get("all_vintages"))
        ):
            latest = latest_forecast_version(self.db, query_params.get("dataset_id"))
            if latest is not None:
                query_params["dataset_id"] = latest["latest_dataset_id"]
                query_params["issued_at"] = format_taiwan_time(
                    to_taiwan(latest["latest_issued_at"])
                )
                query_params["source_updated_at"] = format_taiwan_time(
                    to_taiwan(latest["latest_source_updated_at"])
                )
        return ExplorerQuery.from_params(self.dataset, query_params)

    def fetch_page(
        self,
        query: ExplorerQuery,
        cursor: dict[str, Any] | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        clauses = ["valid_from >= :start_time", "valid_from <= :end_time"]
        sql_params: dict[str, Any] = {
            "start_time": query.window.as_utc()[0],
            "end_time": query.window.as_utc()[1],
        }
        if query.filters.get("dataset_id"):
            clauses.append("dataset_id = :dataset_id")
            sql_params["dataset_id"] = query.filters["dataset_id"]
        if query.filters.get("geocode"):
            clauses.append("geocode = :geocode")
            sql_params["geocode"] = query.filters["geocode"]
        if query.filters.get("issued_at"):
            clauses.append("issued_at = :issued_at")
            sql_params["issued_at"] = to_sql_utc(query.filters["issued_at"])
        if query.filters.get("source_updated_at"):
            clauses.append("source_updated_at = :source_updated_at")
            sql_params["source_updated_at"] = to_sql_utc(query.filters["source_updated_at"])
        where, cursor_params = apply_cursor(
            clauses,
            cursor,
            ("valid_from", "issued_at", "source_updated_at", "dataset_id", "geocode"),
        )
        sql_params.update(cursor_params)
        sql = f"""
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
        for row in self.db.fetch(sql, sql_params):
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


class ObservationAuditReader(DatasetReader):
    """List CWA observation batch audit headers without raw payloads."""

    dataset = "cwa_observation_audits"

    def fetch_page(
        self,
        query: ExplorerQuery,
        cursor: dict[str, Any] | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        status = _audit_status(query.filters.get("status"))
        clauses = ["fetched_at >= :start_time", "fetched_at <= :end_time"]
        sql_params: dict[str, Any] = {
            "start_time": query.window.as_utc()[0],
            "end_time": query.window.as_utc()[1],
        }
        if status:
            clauses.append("status = :status")
            sql_params["status"] = status
        if query.filters.get("missing_station_id"):
            clauses.append("CAST(missing_station_ids AS TEXT) LIKE :missing_station")
            sql_params["missing_station"] = f'%"{query.filters["missing_station_id"]}"%'
        where, cursor_params = apply_cursor(clauses, cursor, ("fetched_at",))
        sql_params.update(cursor_params)
        sql = f"""
            SELECT fetched_at, status, missing_station_ids, created_at
            FROM raw_cwa_observation_batch
            WHERE {where}
            ORDER BY fetched_at DESC
            LIMIT :limit
        """
        sql_params["limit"] = limit
        items = []
        for row in self.db.fetch(sql, sql_params):
            items.append(
                {
                    "fetched_at": format_taiwan_time(to_taiwan(row["fetched_at"])),
                    "status": row["status"],
                    "missing_station_ids": [
                        str(item) for item in json_list(row["missing_station_ids"])
                    ],
                    "ingested_at": format_taiwan_time(to_taiwan(row["created_at"])),
                }
            )
        return items, []


class ForecastAuditReader(DatasetReader):
    """List CWA forecast release audit headers without raw payloads."""

    dataset = "cwa_forecast_audits"

    def fetch_page(
        self,
        query: ExplorerQuery,
        cursor: dict[str, Any] | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        status = _audit_status(query.filters.get("status"))
        clauses = ["issued_at >= :start_time", "issued_at <= :end_time"]
        sql_params: dict[str, Any] = {
            "start_time": query.window.as_utc()[0],
            "end_time": query.window.as_utc()[1],
        }
        if query.filters.get("dataset_id"):
            clauses.append("dataset_id = :dataset_id")
            sql_params["dataset_id"] = query.filters["dataset_id"]
        if status:
            clauses.append("status = :status")
            sql_params["status"] = status
        if query.filters.get("missing_geocode"):
            clauses.append("CAST(missing_geocodes AS TEXT) LIKE :missing_geocode")
            sql_params["missing_geocode"] = f'%"{query.filters["missing_geocode"]}"%'
        where, cursor_params = apply_cursor(
            clauses, cursor, ("issued_at", "source_updated_at", "dataset_id")
        )
        sql_params.update(cursor_params)
        sql = f"""
            SELECT dataset_id, issued_at, source_updated_at, fetched_at, status,
                   missing_geocodes, created_at
            FROM raw_cwa_forecast_release
            WHERE {where}
            ORDER BY issued_at DESC, source_updated_at DESC, dataset_id DESC
            LIMIT :limit
        """
        sql_params["limit"] = limit
        items = []
        for row in self.db.fetch(sql, sql_params):
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
