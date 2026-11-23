"""The CWA weather store: canonical station observations and township forecast vintages.

One observation batch, its header and station rows, is written in one transaction, and
so is every product of one forecast ingestion run. Callers pass and receive
observation, issue and validity instants in Taiwan-local time.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, NamedTuple

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from shiro_mlops.core.config import settings
from shiro_mlops.core.constants import LOCATION_COL, RELATIVE_HUMIDITY_COL, TEMPERATURE_COL
from shiro_mlops.core.storage_time import (
    from_storage_time,
    from_storage_time_series,
    to_storage_time,
    to_storage_time_or_none,
)
from shiro_mlops.data.cwa_client import (
    CWAForecastRelease,
    CWAObservationBatch,
    resolve_cwa_location,
)
from shiro_mlops.data.repository_utils import serialize_raw_payload

FORECAST_ROW_COLUMNS = [
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
]
FORECAST_TIME_COLUMNS = ("issued_at", "source_updated_at", "valid_from", "valid_to")


class ForecastVersion(NamedTuple):
    """Identity of one forecast vintage, comparable across the release and forecast tables.

    Both tables store the instants as aware UTC; the identity holds them read back as
    Taiwan-local naive datetimes, so every stored form of one instant yields one key.
    """

    dataset_id: str
    issued_at: datetime
    source_updated_at: datetime


@dataclass(frozen=True)
class _WindowBound:
    """One side of a forecast validity window and the neighbouring point beyond it."""

    param: str
    column: str
    operator: str
    neighbor_aggregate: str
    neighbor_operator: str


_VALID_START = _WindowBound(
    param="valid_start",
    column="valid_to",
    operator=">=",
    neighbor_aggregate="MAX",
    neighbor_operator="<",
)
_VALID_END = _WindowBound(
    param="valid_end",
    column="valid_from",
    operator="<=",
    neighbor_aggregate="MIN",
    neighbor_operator=">",
)


@dataclass(frozen=True)
class _ForecastRowFilter:
    """Canonical forecast row filters; issue cutoffs with a geocode select vintages point-in-time."""

    geocode: str | None
    dataset_id: str | None
    issued_before: datetime | None
    source_updated_before: datetime | None
    valid_start: datetime | None
    valid_end: datetime | None
    include_adjacent_points: bool

    @property
    def selects_versions(self) -> bool:
        return self.geocode is not None and self.issued_before is not None

    def row_conditions(self) -> tuple[list[str], dict[str, Any]]:
        clauses, params = self.release_conditions()
        if self.geocode is not None:
            clauses.append("geocode = :geocode")
            params["geocode"] = self.geocode
        for bound, value in ((_VALID_START, self.valid_start), (_VALID_END, self.valid_end)):
            if value is not None:
                clauses.append(_forecast_window_filter(bound, self.include_adjacent_points))
                params[bound.param] = value
        return clauses, params

    def release_conditions(self) -> tuple[list[str], dict[str, Any]]:
        """Conditions shared by forecast rows and their release headers."""
        clauses = ["1=1"]
        params: dict[str, Any] = {}
        if self.dataset_id is not None:
            clauses.append("dataset_id = :dataset_id")
            params["dataset_id"] = self.dataset_id
        if self.issued_before is not None:
            clauses.append("issued_at <= :issued_before")
            params["issued_before"] = self.issued_before
        if self.source_updated_before is not None:
            clauses.append("source_updated_at <= :source_updated_before")
            params["source_updated_before"] = self.source_updated_before
        return clauses, params


def _forecast_window_filter(bound: _WindowBound, include_adjacent_points: bool) -> str:
    """Keep interpolation endpoints from the same location and forecast vintage."""
    within_window = f"{bound.column} {bound.operator} :{bound.param}"
    if not include_adjacent_points:
        return within_window
    return f"""({within_window} OR (
        forecast.valid_from = forecast.valid_to AND forecast.valid_from = (
            SELECT {bound.neighbor_aggregate}(neighbor.valid_from)
            FROM raw_cwa_township_forecast AS neighbor
            WHERE neighbor.dataset_id = forecast.dataset_id
              AND neighbor.geocode = forecast.geocode
              AND neighbor.issued_at = forecast.issued_at
              AND neighbor.source_updated_at = forecast.source_updated_at
              AND neighbor.valid_from = neighbor.valid_to
              AND neighbor.valid_from {bound.neighbor_operator} :{bound.param}
        )
    ))"""


def _forecast_version_key(row: pd.Series) -> ForecastVersion:
    """Build the forecast-vintage identity of a release header or forecast row."""
    return ForecastVersion(
        str(row["dataset_id"]),
        from_storage_time(row["issued_at"], column="issued_at"),
        from_storage_time(row["source_updated_at"], column="source_updated_at"),
    )


def _select_forecast_versions(
    headers: pd.DataFrame,
    available_versions: pd.DataFrame,
) -> set[ForecastVersion]:
    """Select, per forecast dataset, the newest release holding rows for the geocode.

    Release completeness is judged across the whole allowlist, so an ``incomplete``
    release still serves any geocode it does hold.
    """
    if headers.empty:
        return set()
    available = {_forecast_version_key(row) for _, row in available_versions.iterrows()}
    selected: set[ForecastVersion] = set()
    for _, releases in headers.groupby("dataset_id"):
        ordered = releases.sort_values(["issued_at", "source_updated_at"], ascending=False)
        for _, release in ordered.iterrows():
            version = _forecast_version_key(release)
            if version in available:
                selected.add(version)
                break
    return selected


def _read_forecast_rows(conn: Connection, filters: _ForecastRowFilter) -> pd.DataFrame:
    clauses, params = filters.row_conditions()
    query = f"""
        SELECT dataset_id, issued_at, source_updated_at, valid_from, valid_to, geocode,
               location_name, temperature_c, dew_point_c, apparent_temperature_c,
               relative_humidity_pct, probability_of_precipitation_pct, wind_speed_m_s,
               wind_direction, created_at
        FROM raw_cwa_township_forecast AS forecast
        WHERE {" AND ".join(clauses)}
        ORDER BY valid_from ASC, valid_to ASC, geocode ASC,
                 issued_at DESC, source_updated_at DESC
    """
    return pd.read_sql_query(text(query), conn, params=params)


def _read_selected_versions(conn: Connection, filters: _ForecastRowFilter) -> set[ForecastVersion]:
    """The vintage each dataset serves at the cutoff, among those holding rows for the geocode."""
    clauses, params = filters.release_conditions()
    headers = pd.read_sql_query(
        text(
            f"""
            SELECT dataset_id, issued_at, source_updated_at
            FROM raw_cwa_forecast_release
            WHERE {" AND ".join(clauses)}
            """
        ),
        conn,
        params=params,
    )
    available_versions = pd.read_sql_query(
        text(
            """
            SELECT DISTINCT dataset_id, issued_at, source_updated_at
            FROM raw_cwa_township_forecast
            WHERE geocode = :geocode
            """
        ),
        conn,
        params={"geocode": filters.geocode},
    )
    return _select_forecast_versions(headers, available_versions)


def _in_versions(frame: pd.DataFrame, versions: set[ForecastVersion]) -> pd.DataFrame:
    selected = [_forecast_version_key(row) in versions for _, row in frame.iterrows()]
    return frame.loc[pd.Series(selected, index=frame.index, dtype=bool)]


def _forecast_rows_in_taiwan_time(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=FORECAST_ROW_COLUMNS)
    for column in FORECAST_TIME_COLUMNS:
        frame[column] = from_storage_time_series(frame[column])
    return frame


class CWAWeatherStore:
    """Canonical CWA station observations and township forecast vintages."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def upsert_cwa_observation_batch(self, batch: CWAObservationBatch) -> int:
        """Persist one canonical CWA observation batch and its typed children atomically."""
        header = {
            "fetched_at": to_storage_time(batch.fetched_at),
            "status": batch.status,
            "missing_station_ids": serialize_raw_payload(list(batch.missing_station_ids)),
            "raw_payload": serialize_raw_payload(batch.raw_payload),
        }
        observation_records = [
            {
                "observed_at": to_storage_time(observation.observed_at),
                "station_id": observation.station_id,
                "station_name": observation.station_name,
                "town_code": observation.town_code,
                "temperature_c": observation.temperature_c,
                "relative_humidity_pct": observation.relative_humidity_pct,
                "air_pressure_hpa": observation.air_pressure_hpa,
                "precipitation_mm": observation.precipitation_mm,
                "wind_speed_m_s": observation.wind_speed_m_s,
                "wind_direction_deg": observation.wind_direction_deg,
            }
            for observation in batch.observations
        ]
        header_stmt = text(
            """
            INSERT INTO raw_cwa_observation_batch
                (fetched_at, status, missing_station_ids, raw_payload)
            VALUES (:fetched_at, :status, :missing_station_ids, :raw_payload)
            ON CONFLICT (fetched_at) DO UPDATE SET
                status = EXCLUDED.status,
                missing_station_ids = EXCLUDED.missing_station_ids,
                raw_payload = EXCLUDED.raw_payload
            """
        )
        child_stmt = text(
            """
            INSERT INTO raw_cwa_station_observation (
                observed_at, station_id, station_name, town_code,
                temperature_c, relative_humidity_pct, air_pressure_hpa,
                precipitation_mm, wind_speed_m_s, wind_direction_deg
            ) VALUES (
                :observed_at, :station_id, :station_name, :town_code,
                :temperature_c, :relative_humidity_pct, :air_pressure_hpa,
                :precipitation_mm, :wind_speed_m_s, :wind_direction_deg
            )
            ON CONFLICT (observed_at, station_id) DO UPDATE SET
                station_name = EXCLUDED.station_name,
                town_code = EXCLUDED.town_code,
                temperature_c = COALESCE(EXCLUDED.temperature_c, raw_cwa_station_observation.temperature_c),
                relative_humidity_pct = COALESCE(EXCLUDED.relative_humidity_pct, raw_cwa_station_observation.relative_humidity_pct),
                air_pressure_hpa = EXCLUDED.air_pressure_hpa,
                precipitation_mm = EXCLUDED.precipitation_mm,
                wind_speed_m_s = EXCLUDED.wind_speed_m_s,
                wind_direction_deg = EXCLUDED.wind_direction_deg
            """
        )
        with self._engine.begin() as conn:
            conn.execute(header_stmt, header)
            if observation_records:
                conn.execute(child_stmt, observation_records)
        return len(observation_records)

    def fetch_cwa_station_observations(
        self,
        start_time: datetime | str | None = None,
        end_time: datetime | str | None = None,
        station_id: str | None = None,
    ) -> pd.DataFrame:
        """Fetch canonical CWA station observations in Taiwan local time."""
        clauses = ["1=1"]
        params: dict[str, Any] = {}
        if start_time is not None:
            clauses.append("observed_at >= :start_time")
            params["start_time"] = to_storage_time(pd.Timestamp(start_time))
        if end_time is not None:
            clauses.append("observed_at <= :end_time")
            params["end_time"] = to_storage_time(pd.Timestamp(end_time))
        if station_id is not None:
            clauses.append("station_id = :station_id")
            params["station_id"] = station_id
        query = f"""
            SELECT observed_at, station_id, station_name, town_code,
                   temperature_c, relative_humidity_pct, air_pressure_hpa,
                   precipitation_mm, wind_speed_m_s, wind_direction_deg, created_at
            FROM raw_cwa_station_observation
            WHERE {" AND ".join(clauses)}
            ORDER BY observed_at ASC, station_id ASC
        """
        with self._engine.connect() as conn:
            frame = pd.read_sql_query(text(query), conn, params=params)
        if frame.empty:
            return pd.DataFrame(
                columns=[
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
                ]
            )
        frame["observed_at"] = from_storage_time_series(frame["observed_at"])
        return frame

    def upsert_cwa_forecast_releases(self, releases: list[CWAForecastRelease]) -> int:
        """Persist all products from one forecast ingestion run in one transaction."""
        with self._engine.begin() as conn:
            return sum(self._upsert_cwa_forecast_release(conn, release) for release in releases)

    def _upsert_cwa_forecast_release(self, conn: Connection, release: CWAForecastRelease) -> int:
        header = {
            "dataset_id": release.dataset_id,
            "issued_at": to_storage_time(release.issued_at),
            "source_updated_at": to_storage_time(release.source_updated_at),
            "fetched_at": to_storage_time(release.fetched_at),
            "status": release.status,
            "missing_geocodes": serialize_raw_payload(list(release.missing_geocodes)),
            "raw_payload": serialize_raw_payload(release.raw_payload),
        }
        child_records = [
            {
                "dataset_id": release.dataset_id,
                "issued_at": to_storage_time(release.issued_at),
                "source_updated_at": to_storage_time(release.source_updated_at),
                "valid_from": to_storage_time(point.valid_from),
                "valid_to": to_storage_time(point.valid_to),
                "geocode": point.geocode,
                "location_name": point.location_name,
                "temperature_c": point.temperature_c,
                "dew_point_c": point.dew_point_c,
                "apparent_temperature_c": point.apparent_temperature_c,
                "relative_humidity_pct": point.relative_humidity_pct,
                "probability_of_precipitation_pct": point.probability_of_precipitation_pct,
                "wind_speed_m_s": point.wind_speed_m_s,
                "wind_direction": point.wind_direction,
            }
            for point in release.forecasts
        ]
        header_stmt = text(
            """
            INSERT INTO raw_cwa_forecast_release (
                dataset_id, issued_at, source_updated_at, fetched_at,
                status, missing_geocodes, raw_payload
            ) VALUES (
                :dataset_id, :issued_at, :source_updated_at, :fetched_at,
                :status, :missing_geocodes, :raw_payload
            )
            ON CONFLICT (dataset_id, issued_at, source_updated_at) DO UPDATE SET
                fetched_at = EXCLUDED.fetched_at,
                status = EXCLUDED.status,
                missing_geocodes = EXCLUDED.missing_geocodes,
                raw_payload = EXCLUDED.raw_payload
            """
        )
        child_stmt = text(
            """
            INSERT INTO raw_cwa_township_forecast (
                dataset_id, issued_at, source_updated_at, valid_from, valid_to, geocode,
                location_name, temperature_c, dew_point_c, apparent_temperature_c,
                relative_humidity_pct, probability_of_precipitation_pct, wind_speed_m_s,
                wind_direction
            ) VALUES (
                :dataset_id, :issued_at, :source_updated_at, :valid_from, :valid_to, :geocode,
                :location_name, :temperature_c, :dew_point_c, :apparent_temperature_c,
                :relative_humidity_pct, :probability_of_precipitation_pct, :wind_speed_m_s,
                :wind_direction
            )
            ON CONFLICT (
                dataset_id, issued_at, source_updated_at, valid_from, valid_to, geocode
            ) DO UPDATE SET
                location_name = EXCLUDED.location_name,
                temperature_c = EXCLUDED.temperature_c,
                dew_point_c = EXCLUDED.dew_point_c,
                apparent_temperature_c = EXCLUDED.apparent_temperature_c,
                relative_humidity_pct = EXCLUDED.relative_humidity_pct,
                probability_of_precipitation_pct = EXCLUDED.probability_of_precipitation_pct,
                wind_speed_m_s = EXCLUDED.wind_speed_m_s,
                wind_direction = EXCLUDED.wind_direction
            """
        )
        conn.execute(header_stmt, header)
        if child_records:
            conn.execute(child_stmt, child_records)
        return len(child_records)

    def fetch_cwa_forecast_rows(
        self,
        *,
        geocode: str | None = None,
        dataset_id: str | None = None,
        issued_before: datetime | str | None = None,
        source_updated_before: datetime | str | None = None,
        valid_start: datetime | str | None = None,
        valid_end: datetime | str | None = None,
        include_adjacent_points: bool = False,
    ) -> pd.DataFrame:
        """Fetch canonical forecast rows, optionally constrained by point-in-time cutoff.

        Cutoffs and window bounds are Taiwan-local instants or their text; ``pd.Timestamp``
        parses the text and turns an omitted bound into ``NaT``, which binds no condition.
        """
        filters = _ForecastRowFilter(
            geocode=geocode,
            dataset_id=dataset_id,
            issued_before=to_storage_time_or_none(pd.Timestamp(issued_before)),
            source_updated_before=to_storage_time_or_none(pd.Timestamp(source_updated_before)),
            valid_start=to_storage_time_or_none(pd.Timestamp(valid_start)),
            valid_end=to_storage_time_or_none(pd.Timestamp(valid_end)),
            include_adjacent_points=include_adjacent_points,
        )
        with self._engine.connect() as conn:
            frame = _read_forecast_rows(conn, filters)
            if filters.selects_versions:
                frame = _in_versions(frame, _read_selected_versions(conn, filters))
        return _forecast_rows_in_taiwan_time(frame)

    def fetch_weather_range(
        self,
        start_time: datetime | str | None = None,
        end_time: datetime | str | None = None,
        reference_point: str | None = None,
    ) -> pd.DataFrame:
        """Fetch historical CWA station observations for one weather reference point.

        Parameters
        ----------
        start_time : datetime | str | None
            Start of time filter range (inclusive).
        end_time : datetime | str | None
            End of time filter range (inclusive).
        reference_point : str | None
            Optional weather reference point alias from the CWA ingestion catalog;
            the result's ``location`` column carries that alias.

        Returns
        -------
        pd.DataFrame
            Sorted DataFrame of weather observation records.
        """
        station_id = (
            resolve_cwa_location(settings.cwa_locations, reference_point).station_id
            if reference_point is not None
            else None
        )
        canonical = self.fetch_cwa_station_observations(
            start_time=start_time,
            end_time=end_time,
            station_id=station_id,
        )
        result = canonical.rename(
            columns={
                "observed_at": "time",
                "temperature_c": TEMPERATURE_COL,
                "relative_humidity_pct": RELATIVE_HUMIDITY_COL,
            }
        )
        aliases_by_station = {
            value.station_id: value.alias for value in settings.cwa_locations.values()
        }
        result[LOCATION_COL] = result["station_id"].map(aliases_by_station)
        if result.empty:
            result["time"] = pd.to_datetime(result["time"])
        return result[
            [
                "time",
                "station_id",
                LOCATION_COL,
                TEMPERATURE_COL,
                RELATIVE_HUMIDITY_COL,
                "created_at",
            ]
        ]
