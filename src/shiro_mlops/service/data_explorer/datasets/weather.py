"""CWA weather datasets: station observations and township forecasts with version pinning."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, NamedTuple

from shiro_mlops.core.config import settings
from shiro_mlops.service.data_explorer.datasets.audits import (
    FORECAST_RELEASE_AUDIT,
    FORECAST_RELEASES,
    OBSERVATION_BATCH_AUDIT,
)
from shiro_mlops.service.data_explorer.datasets.definition import (
    Clauses,
    Dataset,
    Exact,
    Flag,
    GapMembers,
    GapPolicy,
    InstantEquals,
    LatestAudit,
    Row,
    each,
)
from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.series import SeriesField, SeriesOptions
from shiro_mlops.service.data_explorer.timefmt import format_taiwan_time
from shiro_mlops.service.data_explorer.values import (
    format_row_time,
    is_truthy,
    row_time,
    to_float,
)

HOURLY = timedelta(hours=1)


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

OBSERVATION_SERIES = SeriesOptions(
    fields={
        field.value: SeriesField(sql=field.value, unit=unit)
        for field, unit in OBSERVATION_FIELD_UNITS.items()
    },
    group_columns=("station_id",),
    default_fields=(ObservationSeriesField.TEMPERATURE_C.value,),
)
"""Stations are never combined, so there is no `group_by`: one series per station."""


def _observation_item(row: Row) -> dict[str, Any]:
    return {
        "observed_at": format_row_time(row, "observed_at"),
        "station_id": row["station_id"],
        "station_name": row["station_name"],
        "town_code": row["town_code"],
        "temperature_c": to_float(row["temperature_c"]),
        "relative_humidity_pct": to_float(row["relative_humidity_pct"]),
        "air_pressure_hpa": to_float(row["air_pressure_hpa"]),
        "precipitation_mm": to_float(row["precipitation_mm"]),
        "wind_speed_m_s": to_float(row["wind_speed_m_s"]),
        "wind_direction_deg": to_float(row["wind_direction_deg"]),
        "ingested_at": format_row_time(row, "created_at"),
    }


def _allowlisted_station_ids() -> tuple[str, ...]:
    return tuple(item.station_id for item in settings.cwa_locations.values())


CWA_OBSERVATIONS = Dataset(
    id="cwa_observations",
    label="CWA 測站觀測",
    href="/data/weather/observations",
    cadence=HOURLY,
    max_days=31,
    relation="raw_cwa_station_observation",
    time_column="observed_at",
    sort=("observed_at", "station_id"),
    instant_columns=frozenset({"observed_at"}),
    list_columns=(
        "observed_at",
        "station_id",
        "station_name",
        "town_code",
        "temperature_c",
        "relative_humidity_pct",
        "air_pressure_hpa",
        "precipitation_mm",
        "wind_speed_m_s",
        "wind_direction_deg",
        "created_at",
    ),
    project=each(_observation_item),
    status_policy=LatestAudit(OBSERVATION_BATCH_AUDIT),
    filters=(Exact(name="station_id", narrows_gaps=True),),
    gaps=GapPolicy(
        members=GapMembers(column="station_id", expected=_allowlisted_station_ids, listed=True)
    ),
    series=OBSERVATION_SERIES,
)


class PinnedForecastVersion(NamedTuple):
    """A forecast vintage the explorer pins across pages; instants are Taiwan-local."""

    dataset_id: str
    issued_at: datetime
    source_updated_at: datetime


def latest_forecast_version(
    db: ExplorerDb, dataset_id: str | None, *, preferred_dataset_id: str | None = None
) -> PinnedForecastVersion | None:
    """Return the newest persisted forecast release in Taiwan time, optionally for one product.

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
        ORDER BY issued_at DESC,
                 CASE WHEN dataset_id = :preferred_dataset_id THEN 0 ELSE 1 END,
                 source_updated_at DESC
        LIMIT 1
        """,
        params,
    )
    if row is None:
        return None
    return PinnedForecastVersion(
        dataset_id=row["dataset_id"],
        issued_at=row_time(row, "issued_at"),
        source_updated_at=row_time(row, "source_updated_at"),
    )


def _has_explicit_forecast_version(params: Mapping[str, Any]) -> bool:
    return bool(
        params.get("issued_at")
        or params.get("source_updated_at")
        or is_truthy(params.get("all_vintages"))
    )


def _version_filters(version: PinnedForecastVersion) -> dict[str, str]:
    """Pin a version as query filters; microseconds keep near-simultaneous releases apart."""
    return {
        "dataset_id": version.dataset_id,
        "issued_at": format_taiwan_time(version.issued_at, timespec="microseconds"),
        "source_updated_at": format_taiwan_time(version.source_updated_at, timespec="microseconds"),
    }


class LatestForecastVersion:
    """The list reads the newest release unless a version is named, and keeps it across pages."""

    def restore(self, params: dict[str, Any], cursor_filters: dict[str, Any]) -> dict[str, Any]:
        query_params = dict(params)
        if _has_explicit_forecast_version(query_params):
            return query_params
        if cursor_filters.get("issued_at") and cursor_filters.get("source_updated_at"):
            query_params.setdefault("dataset_id", cursor_filters.get("dataset_id"))
            query_params["issued_at"] = cursor_filters["issued_at"]
            query_params["source_updated_at"] = cursor_filters["source_updated_at"]
        return query_params

    def pin(
        self, db: ExplorerDb, params: dict[str, Any], cursor_filters: dict[str, Any] | None
    ) -> dict[str, Any]:
        query_params = self.restore(params, cursor_filters or {})
        # WHY-NOT(cursor_filters): a cursor resumes the filters resolved on its first page,
        # including no pinned version, so it never re-resolves the latest release.
        if cursor_filters is not None or _has_explicit_forecast_version(query_params):
            return query_params
        latest = latest_forecast_version(db, query_params.get("dataset_id"))
        if latest is not None:
            query_params.update(_version_filters(latest))
        return query_params

    def plan_series(
        self, db: ExplorerDb, options: SeriesOptions, params: dict[str, str]
    ) -> tuple[SeriesOptions, dict[str, str]]:
        """Resolve the forecast version the way the list does, so chart and table agree.

        Without an explicit version the latest release is pinned and each geocode is one
        series; unlike the list, the three-day product wins when both products share the
        newest issue. Otherwise (`all_vintages` or a version filter) one series per geocode
        and issue, drawn from the issue's newest correction unless `source_updated_at`
        names one; two releases are never merged into one line.
        """
        if _has_explicit_forecast_version(params):
            planned = replace(
                options,
                group_columns=FORECAST_VINTAGE_COLUMNS,
                filters=_forecast_vintage_series_filters,
            )
            return planned, dict(params)
        pinned = dict(params)
        latest = latest_forecast_version(
            db,
            params.get("dataset_id"),
            preferred_dataset_id=SERIES_PREFERRED_FORECAST_DATASET_ID,
        )
        if latest is not None:
            pinned.update(_version_filters(latest))
        return replace(options, filters=CWA_FORECASTS.series_clauses), pinned


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
"""Both products usually share `issued_at` and the weekly one is updated seconds later, so
picking by `source_updated_at` alone would chart the 12-hourly weekly forecast by default."""
NEWEST_CORRECTION_SQL = """
    (dataset_id, issued_at, geocode, source_updated_at) IN (
        SELECT dataset_id, issued_at, geocode, MAX(source_updated_at)
        FROM {relation}
        {where}
        GROUP BY dataset_id, issued_at, geocode
    )
"""


def _unplanned_forecast_filters(db: ExplorerDb, filters: Mapping[str, Any]) -> Clauses:
    raise RuntimeError("forecast series filters are bound by LatestForecastVersion.plan_series")


FORECAST_SERIES = SeriesOptions(
    fields={
        field.value: SeriesField(sql=field.value, unit=unit)
        for field, unit in FORECAST_FIELD_UNITS.items()
    },
    group_columns=("geocode",),
    filters=_unplanned_forecast_filters,
    gap_fill=False,
    default_fields=(ForecastSeriesField.TEMPERATURE_C.value,),
    instant_group_columns=frozenset({"issued_at"}),
    rows_share_time=True,
)
"""Forecast series template; `LatestForecastVersion.plan_series` binds its filters and grouping."""


def _forecast_item(row: Row) -> dict[str, Any]:
    return {
        "dataset_id": row["dataset_id"],
        "issued_at": format_row_time(row, "issued_at"),
        "source_updated_at": format_row_time(row, "source_updated_at"),
        "valid_from": format_row_time(row, "valid_from"),
        "valid_to": format_row_time(row, "valid_to"),
        "geocode": row["geocode"],
        "location_name": row["location_name"],
        "temperature_c": to_float(row["temperature_c"]),
        "dew_point_c": to_float(row["dew_point_c"]),
        "apparent_temperature_c": to_float(row["apparent_temperature_c"]),
        "relative_humidity_pct": to_float(row["relative_humidity_pct"]),
        "probability_of_precipitation_pct": to_float(row["probability_of_precipitation_pct"]),
        "wind_speed_m_s": to_float(row["wind_speed_m_s"]),
        "wind_direction": row["wind_direction"],
        "ingested_at": format_row_time(row, "created_at"),
    }


CWA_FORECASTS = Dataset(
    id="cwa_forecasts",
    label="CWA 鄉鎮預報",
    href="/data/weather/forecasts",
    cadence=HOURLY,
    max_days=14,
    relation="raw_cwa_township_forecast",
    time_column="valid_from",
    sort=("valid_from", "issued_at", "source_updated_at", "dataset_id", "geocode", "valid_to"),
    instant_columns=frozenset({"valid_from", "issued_at", "source_updated_at", "valid_to"}),
    list_columns=(
        "dataset_id",
        "issued_at",
        "source_updated_at",
        "valid_from",
        "valid_to",
        "geocode",
        "location_name",
        "temperature_c",
        "dew_point_c",
        "apparent_temperature_c",
        "relative_humidity_pct",
        "probability_of_precipitation_pct",
        "wind_speed_m_s",
        "wind_direction",
        "created_at",
    ),
    project=each(_forecast_item),
    status_policy=LatestAudit(FORECAST_RELEASE_AUDIT, flags_stale_release=True),
    freshness=FORECAST_RELEASES,
    filters=(
        Exact(name="dataset_id"),
        Exact(name="geocode"),
        InstantEquals(name="issued_at"),
        InstantEquals(name="source_updated_at"),
        Flag(name="all_vintages"),
    ),
    resolve_version=LatestForecastVersion(),
    series=FORECAST_SERIES,
)


def _forecast_vintage_series_filters(db: ExplorerDb, filters: Mapping[str, Any]) -> Clauses:
    """Keep each issue's newest correction; the inner query repeats the outer filters."""
    clauses, params = CWA_FORECASTS.series_clauses(db, filters)
    if filters.get("source_updated_at"):
        return clauses, params
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    newest_correction = NEWEST_CORRECTION_SQL.format(relation=CWA_FORECASTS.relation, where=where)
    return [*clauses, newest_correction], params
