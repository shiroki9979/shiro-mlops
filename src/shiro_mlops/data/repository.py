"""Time-series database repository for persisting and querying raw load and weather data."""

import json
import logging
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from shiro_mlops.core.config import settings
from shiro_mlops.core.constants import (
    DATETIME_COL,
    LOAD_MW_COL,
    LOCATION_COL,
    NATIONWIDE_SUBJECT,
    RELATIVE_HUMIDITY_COL,
    SUBJECT_COL,
    TEMPERATURE_COL,
)
from shiro_mlops.core.database import ensure_timescale_hypertables, get_timescale_engine
from shiro_mlops.core.datetime_utils import taiwan_local_to_utc, utc_to_taiwan_datetime
from shiro_mlops.data.cwa_client import (
    CWAForecastRelease,
    CWAObservationBatch,
)
from shiro_mlops.data.hourly_actual_load import (
    REGIONAL_SNAPSHOT_SUM_SOURCE,
    HourlyLoadAccumulation,
)
from shiro_mlops.data.taipower_regional_supply_demand import (
    TaipowerRegionalSupplyDemandSnapshot,
)
from shiro_mlops.data.taipower_regional_supply_demand_repository import (
    TaipowerRegionalSupplyDemandRepository,
)
from shiro_mlops.data.taipower_supply_demand import TaipowerSupplyDemandSnapshot
from shiro_mlops.data.taipower_supply_demand_repository import (
    TaipowerSupplyDemandRepository,
)
from shiro_mlops.data.taipower_unit_generation import TaipowerUnitGenerationSnapshot
from shiro_mlops.data.taipower_unit_generation_repository import (
    TaipowerUnitGenerationRepository,
)

logger = logging.getLogger(__name__)


def _taiwan_instant_to_utc(value: datetime | pd.Timestamp | None) -> datetime | None:
    """Convert a Taiwan-local timestamp to a timezone-naive UTC datetime."""
    if value is None:
        return None
    converted = taiwan_local_to_utc(pd.Series([value])).iloc[0]
    return pd.Timestamp(converted).to_pydatetime()


def _serialize_raw_payload(payload: Any) -> str:
    """Serialize a source payload for JSONB or SQLite TEXT storage."""
    return json.dumps(payload, ensure_ascii=False)


def _prepare_load_df(df: pd.DataFrame, default_subject: str) -> pd.DataFrame:
    """Normalize timestamp, assign the default prediction subject, and deduplicate records."""
    if df.empty:
        return df

    work_df = df.copy()
    if DATETIME_COL in work_df.columns and "time" not in work_df.columns:
        work_df = work_df.rename(columns={DATETIME_COL: "time"})

    if "time" not in work_df.columns:
        raise KeyError("DataFrame must contain 'time' or 'datetime' column.")

    if SUBJECT_COL not in work_df.columns:
        work_df[SUBJECT_COL] = default_subject
    else:
        work_df[SUBJECT_COL] = work_df[SUBJECT_COL].fillna(default_subject)

    work_df["time"] = taiwan_local_to_utc(work_df["time"])
    return work_df.drop_duplicates(subset=["time", SUBJECT_COL], keep="last")


def _build_time_filter(
    start_time: datetime | str | None = None,
    end_time: datetime | str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Construct SQL WHERE clause conditions and parameter mappings."""
    clauses: list[str] = ["1=1"]
    params: dict[str, Any] = {}

    if start_time is not None:
        clauses.append("time >= :start_time")
        dt_start = taiwan_local_to_utc(pd.Series([start_time])).iloc[0]
        params["start_time"] = pd.to_datetime(dt_start).to_pydatetime()

    if end_time is not None:
        clauses.append("time <= :end_time")
        dt_end = taiwan_local_to_utc(pd.Series([end_time])).iloc[0]
        params["end_time"] = pd.to_datetime(dt_end).to_pydatetime()

    return " AND ".join(clauses), params


def _forecast_version_key(row: pd.Series) -> tuple[str, pd.Timestamp, pd.Timestamp]:
    """Build a comparable forecast-vintage identity from a query row."""

    def normalize(value: object) -> pd.Timestamp:
        timestamp = pd.Timestamp(value)
        return timestamp.tz_convert("UTC").tz_localize(None) if timestamp.tzinfo else timestamp

    return (
        str(row["dataset_id"]),
        normalize(row["issued_at"]),
        normalize(row["source_updated_at"]),
    )


def _select_forecast_versions(
    headers: pd.DataFrame,
    available_versions: pd.DataFrame,
) -> set[tuple[str, pd.Timestamp, pd.Timestamp]]:
    """Select a latest release or its prior complete fallback per forecast dataset."""
    if headers.empty:
        return set()
    available = {_forecast_version_key(row) for _, row in available_versions.iterrows()}
    selected: set[tuple[str, pd.Timestamp, pd.Timestamp]] = set()
    for _, releases in headers.groupby("dataset_id"):
        ordered = releases.sort_values(["issued_at", "source_updated_at"], ascending=False)
        latest = _forecast_version_key(ordered.iloc[0])
        if latest in available:
            selected.add(latest)
            continue
        for _, release in ordered.iterrows():
            version = _forecast_version_key(release)
            if release["status"] == "complete" and version in available:
                selected.add(version)
                break
    return selected


class TimeSeriesRepository:
    """Repository managing time-series persistence and queries for TimescaleDB."""

    def __init__(
        self,
        engine: Engine | None = None,
        uri: str | None = None,
        auto_init: bool = True,
    ) -> None:
        """Initialize repository with SQLAlchemy engine and ensure hypertables exist.

        Parameters
        ----------
        engine : Engine | None
            Optional pre-configured SQLAlchemy Engine.
        uri : str | None
            Optional database URI string.
        auto_init : bool
            Whether to ensure tables and hypertables exist on initialization. Defaults to True.
        """
        if engine is not None:
            self.engine = engine
        elif uri is not None:
            self.engine = get_timescale_engine(uri=uri)
        else:
            self.engine = get_timescale_engine()

        if auto_init:
            try:
                ensure_timescale_hypertables(self.engine)
            except Exception as e:
                logger.warning(
                    f"Could not automatically ensure hypertables on repository init: {e}"
                )

        self.supply_demand_repo = TaipowerSupplyDemandRepository(
            engine=self.engine, auto_init=False
        )
        self.regional_supply_demand_repo = TaipowerRegionalSupplyDemandRepository(
            engine=self.engine, auto_init=False
        )
        self.unit_generation_repo = TaipowerUnitGenerationRepository(
            engine=self.engine, auto_init=False
        )

    def upsert_taipower_load(
        self,
        df: pd.DataFrame,
        default_subject: str = NATIONWIDE_SUBJECT,
        source: str = REGIONAL_SNAPSHOT_SUM_SOURCE,
    ) -> int:
        """Upsert Taipower electricity load records into raw_taipower_load table.

        Handles composite primary key conflict on (time, subject) by updating load_mw
        and source, so a recomputed hour always carries its current provenance.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame containing 'datetime' (or 'time') and 'load_mw' columns.
        default_subject : str
            Prediction subject used when the 'subject' column is missing or null.
        source : str
            Derivation provenance stored on every row.

        Returns
        -------
        int
            Number of records upserted.
        """
        if df.empty:
            return 0

        work_df = _prepare_load_df(df, default_subject=default_subject)
        if LOAD_MW_COL not in work_df.columns:
            raise KeyError(f"DataFrame must contain '{LOAD_MW_COL}' column.")

        records: list[dict[str, Any]] = [
            {
                "time": (
                    row["time"].to_pydatetime()
                    if hasattr(row["time"], "to_pydatetime")
                    else row["time"]
                ),
                "subject": str(row[SUBJECT_COL]),
                "load_mw": float(row[LOAD_MW_COL]),
                "source": source,
            }
            for _, row in work_df.iterrows()
        ]

        upsert_stmt = text(
            """
            INSERT INTO raw_taipower_load (time, subject, load_mw, source)
            VALUES (:time, :subject, :load_mw, :source)
            ON CONFLICT (time, subject) DO UPDATE SET
                load_mw = EXCLUDED.load_mw,
                source = EXCLUDED.source
            """
        )

        with self.engine.begin() as conn:
            conn.execute(upsert_stmt, records)

        logger.info(f"Upserted {len(records)} Taipower load records into raw_taipower_load.")
        return len(records)

    def upsert_cwa_weather(
        self,
        df: pd.DataFrame,
        default_location: str | None = None,
    ) -> int:
        """Reject deprecated weather writes that do not carry source StationId provenance."""
        del df, default_location
        raise RuntimeError(
            "Legacy CWA weather writes are not supported; use upsert_cwa_observation_batch."
        )

    def upsert_cwa_observation_batch(self, batch: CWAObservationBatch) -> int:
        """Persist one canonical CWA observation batch and its typed children atomically."""
        header = {
            "fetched_at": _taiwan_instant_to_utc(batch.fetched_at),
            "status": batch.status,
            "missing_station_ids": _serialize_raw_payload(list(batch.missing_station_ids)),
            "raw_payload": _serialize_raw_payload(batch.raw_payload),
        }
        observation_records = [
            {
                "observed_at": _taiwan_instant_to_utc(observation.observed_at),
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
        with self.engine.begin() as conn:
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
            params["start_time"] = _taiwan_instant_to_utc(pd.Timestamp(start_time).to_pydatetime())
        if end_time is not None:
            clauses.append("observed_at <= :end_time")
            params["end_time"] = _taiwan_instant_to_utc(pd.Timestamp(end_time).to_pydatetime())
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
        with self.engine.connect() as conn:
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
        frame["observed_at"] = utc_to_taiwan_datetime(frame["observed_at"])
        return frame

    def upsert_cwa_forecast_release(self, release: CWAForecastRelease) -> int:
        """Persist one CWA forecast vintage and all typed township rows atomically."""
        return self.upsert_cwa_forecast_releases([release])

    def upsert_cwa_forecast_releases(self, releases: list[CWAForecastRelease]) -> int:
        """Persist all products from one forecast ingestion run in one transaction."""
        with self.engine.begin() as conn:
            return sum(self._upsert_cwa_forecast_release(conn, release) for release in releases)

    def _upsert_cwa_forecast_release(self, conn: Connection, release: CWAForecastRelease) -> int:
        header = {
            "dataset_id": release.dataset_id,
            "issued_at": _taiwan_instant_to_utc(release.issued_at),
            "source_updated_at": _taiwan_instant_to_utc(release.source_updated_at),
            "fetched_at": _taiwan_instant_to_utc(release.fetched_at),
            "status": release.status,
            "missing_geocodes": _serialize_raw_payload(list(release.missing_geocodes)),
            "raw_payload": _serialize_raw_payload(release.raw_payload),
        }
        child_records = [
            {
                "dataset_id": release.dataset_id,
                "issued_at": _taiwan_instant_to_utc(release.issued_at),
                "source_updated_at": _taiwan_instant_to_utc(release.source_updated_at),
                "valid_from": _taiwan_instant_to_utc(point.valid_from),
                "valid_to": _taiwan_instant_to_utc(point.valid_to),
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
    ) -> pd.DataFrame:
        """Fetch canonical forecast rows, optionally constrained by point-in-time cutoff."""
        clauses = ["1=1"]
        params: dict[str, Any] = {}
        if geocode is not None:
            clauses.append("geocode = :geocode")
            params["geocode"] = geocode
        if dataset_id is not None:
            clauses.append("dataset_id = :dataset_id")
            params["dataset_id"] = dataset_id
        if issued_before is not None:
            clauses.append("issued_at <= :issued_before")
            params["issued_before"] = _taiwan_instant_to_utc(
                pd.Timestamp(issued_before).to_pydatetime()
            )
        if source_updated_before is not None:
            clauses.append("source_updated_at <= :source_updated_before")
            params["source_updated_before"] = _taiwan_instant_to_utc(
                pd.Timestamp(source_updated_before).to_pydatetime()
            )
        if valid_start is not None:
            clauses.append("valid_to >= :valid_start")
            params["valid_start"] = _taiwan_instant_to_utc(
                pd.Timestamp(valid_start).to_pydatetime()
            )
        if valid_end is not None:
            clauses.append("valid_from <= :valid_end")
            params["valid_end"] = _taiwan_instant_to_utc(pd.Timestamp(valid_end).to_pydatetime())
        query = f"""
            SELECT dataset_id, issued_at, source_updated_at, valid_from, valid_to, geocode,
                   location_name, temperature_c, dew_point_c, apparent_temperature_c,
                   relative_humidity_pct, probability_of_precipitation_pct, wind_speed_m_s,
                   wind_direction, created_at
            FROM raw_cwa_township_forecast
            WHERE {" AND ".join(clauses)}
            ORDER BY valid_from ASC, valid_to ASC, geocode ASC,
                     issued_at DESC, source_updated_at DESC
        """
        with self.engine.connect() as conn:
            frame = pd.read_sql_query(text(query), conn, params=params)
            if geocode is not None and issued_before is not None:
                header_clauses = ["issued_at <= :issued_before"]
                header_params: dict[str, Any] = {"issued_before": params["issued_before"]}
                if dataset_id is not None:
                    header_clauses.append("dataset_id = :dataset_id")
                    header_params["dataset_id"] = dataset_id
                if source_updated_before is not None:
                    header_clauses.append("source_updated_at <= :source_updated_before")
                    header_params["source_updated_before"] = params["source_updated_before"]
                headers = pd.read_sql_query(
                    text(
                        f"""
                        SELECT dataset_id, issued_at, source_updated_at, status
                        FROM raw_cwa_forecast_release
                        WHERE {" AND ".join(header_clauses)}
                        """
                    ),
                    conn,
                    params=header_params,
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
                    params={"geocode": geocode},
                )
                selected_versions = _select_forecast_versions(headers, available_versions)
                frame = frame.loc[
                    frame.apply(
                        lambda row: _forecast_version_key(row) in selected_versions,
                        axis=1,
                    )
                ]
        if frame.empty:
            return pd.DataFrame(
                columns=[
                    "dataset_id",
                    "issued_at",
                    "source_updated_at",
                    "valid_from",
                    "valid_to",
                    "geocode",
                    "temperature_c",
                    "dew_point_c",
                    "apparent_temperature_c",
                    "relative_humidity_pct",
                    "probability_of_precipitation_pct",
                    "wind_speed_m_s",
                    "wind_direction",
                    "created_at",
                ]
            )
        for column in ("issued_at", "source_updated_at", "valid_from", "valid_to"):
            frame[column] = utc_to_taiwan_datetime(frame[column])
        return frame

    def fetch_load_range(
        self,
        start_time: datetime | str | None = None,
        end_time: datetime | str | None = None,
        subject: str | None = None,
        source: str | None = None,
    ) -> pd.DataFrame:
        """Fetch historical Taipower load records filtered by time range and prediction subject.

        Parameters
        ----------
        start_time : datetime | str | None
            Start of time filter range (inclusive).
        end_time : datetime | str | None
            End of time filter range (inclusive).
        subject : str | None
            Optional prediction subject filter.
        source : str | None
            Optional derivation provenance filter. Rows with NULL source never match,
            so consumers that must not mix load bases pass the derived source.

        Returns
        -------
        pd.DataFrame
            Sorted DataFrame of power load records.
        """
        where_clause, params = _build_time_filter(start_time, end_time)
        if subject is not None:
            where_clause += " AND subject = :subject"
            params["subject"] = subject
        if source is not None:
            where_clause += " AND source = :source"
            params["source"] = source
        query = f"""
            SELECT time, subject, load_mw, created_at
            FROM raw_taipower_load
            WHERE {where_clause}
            ORDER BY time ASC, subject ASC
        """
        return self._read_load_frame(query, params)

    def fetch_latest_load(
        self,
        subject: str = NATIONWIDE_SUBJECT,
        source: str = REGIONAL_SNAPSHOT_SUM_SOURCE,
        at_or_before: datetime | None = None,
    ) -> pd.DataFrame:
        """Fetch only the newest load row of one source, or an empty frame.

        Hourly consumers need the latest actual value, not the series, so the
        query stays bounded as the accumulated history grows. ``at_or_before``
        (Taiwan-local) ignores rows persisted after a point-in-time decision.
        """
        where_clause, params = _build_time_filter(None, at_or_before)
        query = f"""
            SELECT time, subject, load_mw, created_at
            FROM raw_taipower_load
            WHERE {where_clause} AND subject = :subject AND source = :source
            ORDER BY time DESC
            LIMIT 1
        """
        return self._read_load_frame(query, {**params, "subject": subject, "source": source})

    def _read_load_frame(self, query: str, params: dict[str, Any]) -> pd.DataFrame:
        with self.engine.connect() as conn:
            df = pd.read_sql_query(text(query), con=conn, params=params)

        if df.empty:
            empty_df = pd.DataFrame(columns=["time", SUBJECT_COL, "load_mw", "created_at"])
            empty_df["time"] = pd.to_datetime(empty_df["time"])
            return empty_df

        df["time"] = utc_to_taiwan_datetime(df["time"])
        return df

    def summarize_hourly_load_accumulation(
        self, subject: str = NATIONWIDE_SUBJECT
    ) -> HourlyLoadAccumulation:
        """Count derived hourly observations and legacy rows without loading the series."""
        query = text(
            """
            SELECT
                COALESCE(SUM(CASE WHEN source = :derived THEN 1 ELSE 0 END), 0) AS valid_hours,
                COALESCE(SUM(CASE WHEN source IS NULL THEN 1 ELSE 0 END), 0) AS legacy_rows,
                MAX(CASE WHEN source = :derived THEN time END) AS latest_time
            FROM raw_taipower_load
            WHERE subject = :subject
            """
        )
        params = {"derived": REGIONAL_SNAPSHOT_SUM_SOURCE, "subject": subject}
        with self.engine.connect() as conn:
            row = conn.execute(query, params).one()

        latest_hour = None
        if row.latest_time is not None:
            latest = utc_to_taiwan_datetime(pd.Series([row.latest_time])).iloc[0]
            latest_hour = latest.to_pydatetime()
        return HourlyLoadAccumulation(
            valid_hours=int(row.valid_hours),
            legacy_rows=int(row.legacy_rows),
            latest_hour=latest_hour,
        )

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
            settings.weather_reference_point(reference_point).station_id
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

    def upsert_supply_demand_snapshot(self, snapshot: TaipowerSupplyDemandSnapshot) -> int:
        """Upsert a Taipower supply-demand snapshot keyed by observed_at."""
        return self.supply_demand_repo.upsert(snapshot)

    def fetch_supply_demand_snapshot(
        self, observed_at: datetime
    ) -> TaipowerSupplyDemandSnapshot | None:
        """Fetch a supply-demand snapshot by Taiwan-local observation slot."""
        return self.supply_demand_repo.fetch(observed_at)

    def upsert_regional_supply_demand_snapshots(
        self, snapshots: list[TaipowerRegionalSupplyDemandSnapshot]
    ) -> int:
        """Upsert regional supply-demand snapshots keyed by (observed_at, region)."""
        return self.regional_supply_demand_repo.upsert(snapshots)

    def fetch_regional_supply_demand_snapshots(
        self, observed_at: datetime
    ) -> list[TaipowerRegionalSupplyDemandSnapshot]:
        """Fetch regional snapshots for a Taiwan-local observation slot."""
        return self.regional_supply_demand_repo.fetch(observed_at)

    def fetch_regional_supply_demand_snapshots_by_source_time(
        self, start_time: datetime, end_time: datetime
    ) -> list[TaipowerRegionalSupplyDemandSnapshot]:
        """Fetch regional snapshots whose Taiwan-local source_time is in [start, end)."""
        return self.regional_supply_demand_repo.fetch_by_source_time(start_time, end_time)

    def upsert_unit_generation_snapshots(
        self, snapshots: list[TaipowerUnitGenerationSnapshot]
    ) -> int:
        """Upsert unit net-generation snapshots keyed by identity and observed_at."""
        return self.unit_generation_repo.upsert(snapshots)

    def fetch_unit_generation_snapshots(
        self, observed_at: datetime
    ) -> list[TaipowerUnitGenerationSnapshot]:
        """Fetch unit net-generation snapshots for a Taiwan-local observation slot."""
        return self.unit_generation_repo.fetch(observed_at)


__all__ = [
    "TimeSeriesRepository",
    "TaipowerSupplyDemandRepository",
    "TaipowerRegionalSupplyDemandRepository",
    "TaipowerUnitGenerationRepository",
]
