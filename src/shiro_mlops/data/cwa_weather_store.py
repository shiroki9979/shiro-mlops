"""The CWA weather store: canonical station observations and township forecast vintages.

One observation batch, its header and station rows, is written in one transaction, and
so is every product of one forecast ingestion run. Callers pass and receive
observation, issue and validity instants in Taiwan-local time.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from shiro_mlops.core.constants import LOCATION_COL, RELATIVE_HUMIDITY_COL, TEMPERATURE_COL
from shiro_mlops.core.storage_time import (
    from_storage_time_series,
    to_storage_time,
    to_storage_time_or_none,
)
from shiro_mlops.data.cwa_client import (
    CWAForecastRelease,
    CWALocation,
    CWAObservationBatch,
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
    """Canonical forecast row filters; every vintage they admit is read, none is chosen."""

    geocode: str | None
    dataset_id: str | None
    issued_before: datetime | None
    source_updated_before: datetime | None
    issued_after: datetime | None
    valid_start: datetime | None
    valid_end: datetime | None
    include_adjacent_points: bool

    def row_conditions(self) -> tuple[list[str], dict[str, Any]]:
        clauses = ["1=1"]
        params: dict[str, Any] = {}
        for column, operator, name, value in (
            ("dataset_id", "=", "dataset_id", self.dataset_id),
            ("geocode", "=", "geocode", self.geocode),
            ("issued_at", "<=", "issued_before", self.issued_before),
            ("source_updated_at", "<=", "source_updated_before", self.source_updated_before),
            ("issued_at", ">=", "issued_after", self.issued_after),
        ):
            if value is not None:
                clauses.append(f"{column} {operator} :{name}")
                params[name] = value
        for bound, value in ((_VALID_START, self.valid_start), (_VALID_END, self.valid_end)):
            if value is not None:
                clauses.append(_forecast_window_filter(bound, self.include_adjacent_points))
                params[bound.param] = value
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


def _forecast_rows_in_taiwan_time(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=FORECAST_ROW_COLUMNS)
    for column in FORECAST_TIME_COLUMNS:
        frame[column] = from_storage_time_series(frame[column])
    return frame


class CWAWeatherStore:
    """Canonical CWA station observations and township forecast vintages.

    The reference point weather read takes its station and alias from the ``CWALocation``
    passed in; the store never consults the global CWA ingestion catalog.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def upsert_cwa_observation_batch(self, batch: CWAObservationBatch) -> int:
        """Persist one canonical CWA observation batch and its typed children atomically."""
        header = {
            "fetched_at": to_storage_time(batch.fetched_at),
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
                (fetched_at, missing_station_ids, raw_payload)
            VALUES (:fetched_at, :missing_station_ids, :raw_payload)
            ON CONFLICT (fetched_at) DO UPDATE SET
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
        """Persist all products from one forecast ingestion run in one transaction.

        The hourly run fetches the current version again until CWA issues the next one.
        A version already stored takes this run's ``fetched_at``, ``missing_geocodes`` and
        ``raw_payload``, so ``fetched_at`` is the latest fetch of the version; ``created_at``
        keeps its first write.
        """
        with self._engine.begin() as conn:
            return sum(self._upsert_cwa_forecast_release(conn, release) for release in releases)

    def _upsert_cwa_forecast_release(self, conn: Connection, release: CWAForecastRelease) -> int:
        header = {
            "dataset_id": release.dataset_id,
            "issued_at": to_storage_time(release.issued_at),
            "source_updated_at": to_storage_time(release.source_updated_at),
            "fetched_at": to_storage_time(release.fetched_at),
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
                missing_geocodes, raw_payload
            ) VALUES (
                :dataset_id, :issued_at, :source_updated_at, :fetched_at,
                :missing_geocodes, :raw_payload
            )
            ON CONFLICT (dataset_id, issued_at, source_updated_at) DO UPDATE SET
                fetched_at = EXCLUDED.fetched_at,
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
        issued_after: datetime | str | None = None,
        valid_start: datetime | str | None = None,
        valid_end: datetime | str | None = None,
        include_adjacent_points: bool = False,
    ) -> pd.DataFrame:
        """Fetch canonical forecast rows of every vintage the filters admit.

        The store chooses no version: which vintage supplies a value is the weather
        resolution's rule. ``issued_after`` leaves out vintages issued before it; serving
        passes the staleness limit, since an older vintage would be discarded as stale
        anyway, so a point-in-time read never scans the geocode's whole history.
        ``include_adjacent_points`` adds, per vintage, the nearest point beyond each
        window bound as an interpolation endpoint.

        Cutoffs and window bounds are Taiwan-local instants or their text; an omitted bound
        binds no condition.
        """
        filters = _ForecastRowFilter(
            geocode=geocode,
            dataset_id=dataset_id,
            issued_before=_optional_bound(issued_before),
            source_updated_before=_optional_bound(source_updated_before),
            issued_after=_optional_bound(issued_after),
            valid_start=_optional_bound(valid_start),
            valid_end=_optional_bound(valid_end),
            include_adjacent_points=include_adjacent_points,
        )
        with self._engine.connect() as conn:
            frame = _read_forecast_rows(conn, filters)
        return _forecast_rows_in_taiwan_time(frame)

    def fetch_weather_range(
        self,
        *,
        reference_point: CWALocation,
        start_time: datetime | str | None = None,
        end_time: datetime | str | None = None,
    ) -> pd.DataFrame:
        """Fetch historical CWA station observations of one weather reference point.

        Parameters
        ----------
        reference_point : CWALocation
            The weather reference point whose station is read; the result's
            ``location`` column carries its alias.
        start_time : datetime | str | None
            Start of time filter range (inclusive).
        end_time : datetime | str | None
            End of time filter range (inclusive).

        Returns
        -------
        pd.DataFrame
            Sorted DataFrame of weather observation records.
        """
        canonical = self.fetch_cwa_station_observations(
            start_time=start_time,
            end_time=end_time,
            station_id=reference_point.station_id,
        )
        result = canonical.rename(
            columns={
                "observed_at": "time",
                "temperature_c": TEMPERATURE_COL,
                "relative_humidity_pct": RELATIVE_HUMIDITY_COL,
            }
        )
        result[LOCATION_COL] = reference_point.alias
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


def _optional_bound(value: datetime | str | None) -> datetime | None:
    """A Taiwan-local cutoff or window bound, or its text, as a storage time.

    An omitted bound, and text that parses to ``NaT``, give ``None``, which binds no condition.
    """
    return None if value is None else to_storage_time_or_none(pd.Timestamp(value))
