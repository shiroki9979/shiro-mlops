"""CWA observation, forecast, and audit readers and chart series specs behind the typed seams."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from enum import StrEnum
from functools import partial
from typing import Any, NamedTuple

from shiro_mlops.service.data_explorer.completeness import gaps_until_now, observation_gaps
from shiro_mlops.service.data_explorer.dataset_reader import DatasetReader
from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.errors import ExplorerQueryError
from shiro_mlops.service.data_explorer.query import ExplorerQuery
from shiro_mlops.service.data_explorer.series import SeriesField, SeriesSpec
from shiro_mlops.service.data_explorer.timefmt import format_taiwan_time, to_sql_utc
from shiro_mlops.service.data_explorer.values import is_truthy, json_list, to_float, to_taiwan


class PinnedForecastVersion(NamedTuple):
    """A forecast vintage the explorer pins across pages; instants are Taiwan-local."""

    dataset_id: str
    issued_at: datetime
    source_updated_at: datetime


def latest_forecast_version(
    db: ExplorerDb, dataset_id: str | None, *, preferred_dataset_id: str | None = None
) -> PinnedForecastVersion | None:
    """Return the newest persisted forecast release in Taiwan time, optionally for one dataset.

    Among releases sharing the newest `issued_at`, `preferred_dataset_id` wins before the
    newest `source_updated_at` does.
    """
    clauses = []
    params: dict[str, Any] = {"preferred_dataset_id": preferred_dataset_id}
    if dataset_id:
        clauses.append("dataset_id = :dataset_id")
        params["dataset_id"] = dataset_id
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    row = db.fetch_one(
        f"""
        SELECT dataset_id, issued_at, source_updated_at
        FROM raw_cwa_forecast_release
        {where}
        ORDER BY {db.time_operand("issued_at")} DESC,
                 CASE WHEN dataset_id = :preferred_dataset_id THEN 0 ELSE 1 END,
                 {db.time_operand("source_updated_at")} DESC
        LIMIT 1
        """,
        params,
    )
    if row is None:
        return None
    return PinnedForecastVersion(
        dataset_id=row["dataset_id"],
        issued_at=to_taiwan(row["issued_at"]),
        source_updated_at=to_taiwan(row["source_updated_at"]),
    )


def _audit_status(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    if value not in {"complete", "incomplete"}:
        raise ExplorerQueryError("status must be complete or incomplete")
    return value


def observation_audit_filters(filters: Mapping[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """Observation batch filters shared by the list and the series: status, missing station."""
    clauses: list[str] = []
    params: dict[str, Any] = {}
    status = _audit_status(filters.get("status"))
    if status:
        clauses.append("status = :status")
        params["status"] = status
    if filters.get("missing_station_id"):
        clauses.append("CAST(missing_station_ids AS TEXT) LIKE :missing_station")
        params["missing_station"] = f'%"{filters["missing_station_id"]}"%'
    return clauses, params


def forecast_audit_filters(filters: Mapping[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """Forecast release filters shared by the list and the series: dataset, status, geocode."""
    clauses: list[str] = []
    params: dict[str, Any] = {}
    status = _audit_status(filters.get("status"))
    if filters.get("dataset_id"):
        clauses.append("dataset_id = :dataset_id")
        params["dataset_id"] = filters["dataset_id"]
    if status:
        clauses.append("status = :status")
        params["status"] = status
    if filters.get("missing_geocode"):
        clauses.append("CAST(missing_geocodes AS TEXT) LIKE :missing_geocode")
        params["missing_geocode"] = f'%"{filters["missing_geocode"]}"%'
    return clauses, params


def _has_explicit_forecast_version(params: dict[str, Any]) -> bool:
    return bool(
        params.get("issued_at")
        or params.get("source_updated_at")
        or is_truthy(params.get("all_vintages"))
    )


def _cursor_forecast_version(cursor_filters: dict[str, Any] | None) -> dict[str, Any]:
    filters = cursor_filters or {}
    return filters if filters.get("issued_at") and filters.get("source_updated_at") else {}


def _pin_forecast_version(
    db: ExplorerDb,
    params: dict[str, Any],
    cursor_filters: dict[str, Any] | None,
) -> dict[str, Any]:
    query_params = _restore_cursor_forecast_version(params, cursor_filters or {})
    # A cursor resumes the filters resolved on its first page, including no pinned version.
    if cursor_filters is not None or _has_explicit_forecast_version(query_params):
        return query_params

    latest = latest_forecast_version(db, query_params.get("dataset_id"))
    if latest is not None:
        query_params.update(_version_filters(latest))
    return query_params


def _version_filters(version: PinnedForecastVersion) -> dict[str, str]:
    """Pin a version as query filters; microseconds keep near-simultaneous releases apart."""
    return {
        "dataset_id": version.dataset_id,
        "issued_at": format_taiwan_time(version.issued_at, timespec="microseconds"),
        "source_updated_at": format_taiwan_time(version.source_updated_at, timespec="microseconds"),
    }


def _restore_cursor_forecast_version(
    params: dict[str, Any], cursor_filters: dict[str, Any]
) -> dict[str, Any]:
    query_params = dict(params)
    if _has_explicit_forecast_version(query_params):
        return query_params
    version = _cursor_forecast_version(cursor_filters)
    if version:
        query_params.setdefault("dataset_id", version.get("dataset_id"))
        query_params["issued_at"] = version["issued_at"]
        query_params["source_updated_at"] = version["source_updated_at"]
    return query_params


def _forecast_filters(db: ExplorerDb, query: ExplorerQuery) -> tuple[list[str], dict[str, Any]]:
    clauses, params = db.time_window("valid_from", query.window)
    version_clauses, version_params = _forecast_version_filters(db, query.filters)
    return [*clauses, *version_clauses], {**params, **version_params}


def _forecast_version_filters(
    db: ExplorerDb, filters: Mapping[str, Any]
) -> tuple[list[str], dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    for name in ("dataset_id", "geocode"):
        if filters.get(name):
            clauses.append(f"{name} = :{name}")
            params[name] = filters[name]
    for name in ("issued_at", "source_updated_at"):
        if filters.get(name):
            clauses.append(db.time_equals(name, name))
            try:
                params[name] = to_sql_utc(filters[name])
            except (TypeError, ValueError, OverflowError) as exc:
                raise ExplorerQueryError(f"{name} must be a valid RFC 3339 timestamp") from exc
    return clauses, params


def _forecast_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
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
        "probability_of_precipitation_pct": to_float(row["probability_of_precipitation_pct"]),
        "wind_speed_m_s": to_float(row["wind_speed_m_s"]),
        "wind_direction": row["wind_direction"],
        "ingested_at": format_taiwan_time(to_taiwan(row["created_at"])),
    }


class ObservationReader(DatasetReader):
    """List persisted CWA station observations newest first."""

    dataset = "cwa_observations"
    select_sql = """
        SELECT observed_at, station_id, station_name, town_code, temperature_c,
               relative_humidity_pct, air_pressure_hpa, precipitation_mm,
               wind_speed_m_s, wind_direction_deg, created_at
        FROM raw_cwa_station_observation
        WHERE {where}
        ORDER BY {order}
        LIMIT :limit
    """

    def filters(self, query: ExplorerQuery) -> tuple[list[str], dict[str, Any]]:
        clauses, sql_params = self.db.time_window("observed_at", query.window)
        station_clauses, station_params = observation_filters(query.filters)
        return [*clauses, *station_clauses], {**sql_params, **station_params}

    def project_page(
        self, query: ExplorerQuery, rows: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        items = []
        for row in rows:
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
        station_id = query.filters.get("station_id")
        gaps = gaps_until_now(
            query.window, lambda window: observation_gaps(self.db, window, station_id)
        )
        return items, gaps


def observation_filters(filters: Mapping[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """Apply the optional station filter shared by the observation list and series."""
    station_id = filters.get("station_id")
    if not station_id:
        return [], {}
    return ["station_id = :station_id"], {"station_id": station_id}


class ObservationSeriesField(StrEnum):
    """Numeric observation fields a series request may name.

    Wind direction is left out: an average of compass bearings is not a direction.
    """

    TEMPERATURE_C = "temperature_c"
    RELATIVE_HUMIDITY_PCT = "relative_humidity_pct"
    AIR_PRESSURE_HPA = "air_pressure_hpa"
    PRECIPITATION_MM = "precipitation_mm"
    WIND_SPEED_M_S = "wind_speed_m_s"


OBSERVATION_FIELD_UNITS = {
    ObservationSeriesField.TEMPERATURE_C: "°C",
    ObservationSeriesField.RELATIVE_HUMIDITY_PCT: "%",
    ObservationSeriesField.AIR_PRESSURE_HPA: "hPa",
    ObservationSeriesField.PRECIPITATION_MM: "mm",
    ObservationSeriesField.WIND_SPEED_M_S: "m/s",
}

OBSERVATION_SERIES = SeriesSpec(
    dataset="cwa_observations",
    table="raw_cwa_station_observation",
    time_column="observed_at",
    fields={
        field.value: SeriesField(sql=field.value, unit=unit)
        for field, unit in OBSERVATION_FIELD_UNITS.items()
    },
    group_columns=("station_id",),
    filter_keys=frozenset({"station_id"}),
    filters=observation_filters,
    default_fields=(ObservationSeriesField.TEMPERATURE_C.value,),
)
"""Stations are never combined, so there is no `group_by`: one series per station."""


class ForecastReader(DatasetReader):
    """List persisted CWA township forecasts newest first."""

    dataset = "cwa_forecasts"
    select_sql = """
        SELECT dataset_id, issued_at, source_updated_at, valid_from, valid_to, geocode,
               location_name, temperature_c, dew_point_c, apparent_temperature_c,
               relative_humidity_pct, probability_of_precipitation_pct, wind_speed_m_s,
               wind_direction, created_at
        FROM raw_cwa_township_forecast
        WHERE {where}
        ORDER BY {order}
        LIMIT :limit
    """

    @classmethod
    def cursor_query_params(
        cls, params: dict[str, Any], cursor_filters: dict[str, Any]
    ) -> dict[str, Any]:
        return _restore_cursor_forecast_version(params, cursor_filters)

    def build_query(
        self, params: dict[str, Any], cursor_filters: dict[str, Any] | None
    ) -> ExplorerQuery:
        query_params = _pin_forecast_version(self.db, params, cursor_filters)
        return ExplorerQuery.from_params(self.dataset, query_params, cursor_filters=cursor_filters)

    def filters(self, query: ExplorerQuery) -> tuple[list[str], dict[str, Any]]:
        return _forecast_filters(self.db, query)

    def project_page(
        self, query: ExplorerQuery, rows: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        return [_forecast_item(row) for row in rows], []


class ForecastSeriesField(StrEnum):
    """Numeric township forecast fields a series request may name."""

    TEMPERATURE_C = "temperature_c"
    APPARENT_TEMPERATURE_C = "apparent_temperature_c"
    DEW_POINT_C = "dew_point_c"
    RELATIVE_HUMIDITY_PCT = "relative_humidity_pct"
    PROBABILITY_OF_PRECIPITATION_PCT = "probability_of_precipitation_pct"
    WIND_SPEED_M_S = "wind_speed_m_s"


FORECAST_FIELD_UNITS = {
    ForecastSeriesField.TEMPERATURE_C: "°C",
    ForecastSeriesField.APPARENT_TEMPERATURE_C: "°C",
    ForecastSeriesField.DEW_POINT_C: "°C",
    ForecastSeriesField.RELATIVE_HUMIDITY_PCT: "%",
    ForecastSeriesField.PROBABILITY_OF_PRECIPITATION_PCT: "%",
    ForecastSeriesField.WIND_SPEED_M_S: "m/s",
}
FORECAST_VINTAGE_COLUMNS = ("geocode", "dataset_id", "issued_at")
SERIES_PREFERRED_FORECAST_DATASET_ID = "F-D0047-089"
"""Both datasets usually share `issued_at` and the weekly one is updated seconds later, so
picking by `source_updated_at` alone would chart the 12-hourly weekly forecast by default."""
NEWEST_CORRECTION_SQL = """
    (dataset_id, issued_at, geocode, source_updated_at) IN (
        SELECT dataset_id, issued_at, geocode, MAX(source_updated_at)
        FROM raw_cwa_township_forecast
        {where}
        GROUP BY dataset_id, issued_at, geocode
    )
"""


def _unplanned_forecast_filters(filters: Mapping[str, Any]) -> tuple[list[str], dict[str, Any]]:
    raise RuntimeError("forecast series filters are bound by plan_forecast_series")


FORECAST_SERIES = SeriesSpec(
    dataset="cwa_forecasts",
    table="raw_cwa_township_forecast",
    time_column="valid_from",
    fields={
        field.value: SeriesField(sql=field.value, unit=unit)
        for field, unit in FORECAST_FIELD_UNITS.items()
    },
    group_columns=("geocode",),
    filter_keys=frozenset(
        {"dataset_id", "geocode", "issued_at", "source_updated_at", "all_vintages"}
    ),
    filters=_unplanned_forecast_filters,
    gap_fill=False,
    default_fields=(ForecastSeriesField.TEMPERATURE_C.value,),
    instant_group_columns=frozenset({"issued_at"}),
    rows_share_time=True,
)
"""Forecast series template; `plan_forecast_series` binds its filters and grouping."""


def plan_forecast_series(
    db: ExplorerDb, params: Mapping[str, str]
) -> tuple[SeriesSpec, dict[str, str]]:
    """Resolve the forecast version the way the list does, so chart and table agree.

    Without an explicit version the latest release is pinned and each geocode is one series;
    unlike the list, the three-day dataset wins when both datasets share the newest issue.
    Otherwise (`all_vintages` or a version filter) one series per geocode and issue, drawn
    from the issue's newest correction unless `source_updated_at` names one; two releases
    are never merged into one line.
    """
    if _has_explicit_forecast_version(params):
        spec = replace(
            FORECAST_SERIES,
            group_columns=FORECAST_VINTAGE_COLUMNS,
            filters=partial(_forecast_vintage_series_filters, db),
        )
        return spec, dict(params)
    pinned = dict(params)
    latest = latest_forecast_version(
        db, params.get("dataset_id"), preferred_dataset_id=SERIES_PREFERRED_FORECAST_DATASET_ID
    )
    if latest is not None:
        pinned.update(_version_filters(latest))
    return replace(FORECAST_SERIES, filters=partial(_forecast_version_filters, db)), pinned


def _forecast_vintage_series_filters(
    db: ExplorerDb, filters: Mapping[str, Any]
) -> tuple[list[str], dict[str, Any]]:
    """Keep each issue's newest correction; the inner query repeats the outer filters."""
    clauses, params = _forecast_version_filters(db, filters)
    if filters.get("source_updated_at"):
        return clauses, params
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return [*clauses, NEWEST_CORRECTION_SQL.format(where=where)], params


class ObservationAuditReader(DatasetReader):
    """List CWA observation batch audit headers without raw payloads."""

    dataset = "cwa_observation_audits"
    select_sql = """
        SELECT fetched_at, status, missing_station_ids, created_at
        FROM raw_cwa_observation_batch
        WHERE {where}
        ORDER BY {order}
        LIMIT :limit
    """

    def filters(self, query: ExplorerQuery) -> tuple[list[str], dict[str, Any]]:
        clauses, sql_params = self.db.time_window("fetched_at", query.window)
        audit_clauses, audit_params = observation_audit_filters(query.filters)
        return [*clauses, *audit_clauses], {**sql_params, **audit_params}

    def project_page(
        self, query: ExplorerQuery, rows: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        items = []
        for row in rows:
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
    select_sql = """
        SELECT dataset_id, issued_at, source_updated_at, fetched_at, status,
               missing_geocodes, created_at
        FROM raw_cwa_forecast_release
        WHERE {where}
        ORDER BY {order}
        LIMIT :limit
    """

    def filters(self, query: ExplorerQuery) -> tuple[list[str], dict[str, Any]]:
        clauses, sql_params = self.db.time_window("issued_at", query.window)
        audit_clauses, audit_params = forecast_audit_filters(query.filters)
        return [*clauses, *audit_clauses], {**sql_params, **audit_params}

    def project_page(
        self, query: ExplorerQuery, rows: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        items = []
        for row in rows:
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
