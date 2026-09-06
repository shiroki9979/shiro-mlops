"""Time-series database repository for persisting and querying raw load and weather data."""

import logging
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.core.constants import (
    DATETIME_COL,
    DEFAULT_LOCATION,
    LOAD_MW_COL,
    LOCATION_COL,
    RELATIVE_HUMIDITY_COL,
    TEMPERATURE_COL,
)
from shiro_mlops.core.database import ensure_timescale_hypertables, get_timescale_engine
from shiro_mlops.core.datetime_utils import taiwan_local_to_utc, utc_to_taiwan_datetime
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


def _prepare_timeseries_df(
    df: pd.DataFrame, default_location: str = DEFAULT_LOCATION
) -> pd.DataFrame:
    """Normalize timestamp, assign default location, and deduplicate records."""
    if df.empty:
        return df

    work_df = df.copy()
    if DATETIME_COL in work_df.columns and "time" not in work_df.columns:
        work_df = work_df.rename(columns={DATETIME_COL: "time"})

    if "time" not in work_df.columns:
        raise KeyError("DataFrame must contain 'time' or 'datetime' column.")

    if LOCATION_COL not in work_df.columns:
        work_df[LOCATION_COL] = default_location
    else:
        work_df[LOCATION_COL] = work_df[LOCATION_COL].fillna(default_location)

    work_df["time"] = taiwan_local_to_utc(work_df["time"])
    return work_df.drop_duplicates(subset=["time", LOCATION_COL], keep="last")


def _build_time_location_filter(
    start_time: datetime | str | None = None,
    end_time: datetime | str | None = None,
    location: str | None = None,
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

    if location is not None:
        clauses.append("location = :location")
        params["location"] = str(location)

    return " AND ".join(clauses), params


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

        self.supply_demand_repo = TaipowerSupplyDemandRepository(engine=self.engine)
        self.regional_supply_demand_repo = TaipowerRegionalSupplyDemandRepository(
            engine=self.engine
        )
        self.unit_generation_repo = TaipowerUnitGenerationRepository(engine=self.engine)

    def upsert_taipower_load(
        self,
        df: pd.DataFrame,
        default_location: str = DEFAULT_LOCATION,
    ) -> int:
        """Upsert Taipower electricity load records into raw_taipower_load table.

        Handles composite primary key conflict on (time, location) by updating load_mw.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame containing 'datetime' (or 'time') and 'load_mw' columns.
        default_location : str
            Fallback location identifier when 'location' column is missing or null.

        Returns
        -------
        int
            Number of records upserted.
        """
        if df.empty:
            return 0

        work_df = _prepare_timeseries_df(df, default_location=default_location)
        if LOAD_MW_COL not in work_df.columns:
            raise KeyError(f"DataFrame must contain '{LOAD_MW_COL}' column.")

        records: list[dict[str, Any]] = [
            {
                "time": (
                    row["time"].to_pydatetime()
                    if hasattr(row["time"], "to_pydatetime")
                    else row["time"]
                ),
                "location": str(row[LOCATION_COL]),
                "load_mw": float(row[LOAD_MW_COL]),
            }
            for _, row in work_df.iterrows()
        ]

        upsert_stmt = text(
            """
            INSERT INTO raw_taipower_load (time, location, load_mw)
            VALUES (:time, :location, :load_mw)
            ON CONFLICT (time, location) DO UPDATE SET
                load_mw = EXCLUDED.load_mw
            """
        )

        with self.engine.begin() as conn:
            conn.execute(upsert_stmt, records)

        logger.info(f"Upserted {len(records)} Taipower load records into raw_taipower_load.")
        return len(records)

    def upsert_cwa_weather(
        self,
        df: pd.DataFrame,
        default_location: str = DEFAULT_LOCATION,
    ) -> int:
        """Upsert CWA weather observation records into raw_cwa_weather table.

        Handles composite primary key conflict on (time, location) by updating
        temperature and relative_humidity with non-null values.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame containing 'datetime' (or 'time'), 'temperature', and 'relative_humidity'.
        default_location : str
            Fallback location identifier when 'location' column is missing or null.

        Returns
        -------
        int
            Number of records upserted.
        """
        if df.empty:
            return 0

        work_df = _prepare_timeseries_df(df, default_location=default_location)

        records: list[dict[str, Any]] = [
            {
                "time": (
                    row["time"].to_pydatetime()
                    if hasattr(row["time"], "to_pydatetime")
                    else row["time"]
                ),
                "location": str(row[LOCATION_COL]),
                "temperature": (
                    float(row[TEMPERATURE_COL])
                    if TEMPERATURE_COL in row and pd.notna(row[TEMPERATURE_COL])
                    else None
                ),
                "relative_humidity": (
                    float(row[RELATIVE_HUMIDITY_COL])
                    if RELATIVE_HUMIDITY_COL in row and pd.notna(row[RELATIVE_HUMIDITY_COL])
                    else None
                ),
            }
            for _, row in work_df.iterrows()
        ]

        upsert_stmt = text(
            """
            INSERT INTO raw_cwa_weather (time, location, temperature, relative_humidity)
            VALUES (:time, :location, :temperature, :relative_humidity)
            ON CONFLICT (time, location) DO UPDATE SET
                temperature = COALESCE(EXCLUDED.temperature, raw_cwa_weather.temperature),
                relative_humidity = COALESCE(EXCLUDED.relative_humidity, raw_cwa_weather.relative_humidity)
            """
        )

        with self.engine.begin() as conn:
            conn.execute(upsert_stmt, records)

        logger.info(f"Upserted {len(records)} CWA weather records into raw_cwa_weather.")
        return len(records)

    def fetch_load_range(
        self,
        start_time: datetime | str | None = None,
        end_time: datetime | str | None = None,
        location: str | None = None,
    ) -> pd.DataFrame:
        """Fetch historical Taipower load records filtered by time range and location.

        Parameters
        ----------
        start_time : datetime | str | None
            Start of time filter range (inclusive).
        end_time : datetime | str | None
            End of time filter range (inclusive).
        location : str | None
            Optional location filter.

        Returns
        -------
        pd.DataFrame
            Sorted DataFrame of power load records.
        """
        where_clause, params = _build_time_location_filter(start_time, end_time, location)
        query = f"""
            SELECT time, location, load_mw, created_at
            FROM raw_taipower_load
            WHERE {where_clause}
            ORDER BY time ASC, location ASC
        """

        with self.engine.connect() as conn:
            df = pd.read_sql_query(text(query), con=conn, params=params)

        if df.empty:
            empty_df = pd.DataFrame(columns=["time", "location", "load_mw", "created_at"])
            empty_df["time"] = pd.to_datetime(empty_df["time"])
            return empty_df

        df["time"] = utc_to_taiwan_datetime(df["time"])
        return df

    def fetch_weather_range(
        self,
        start_time: datetime | str | None = None,
        end_time: datetime | str | None = None,
        location: str | None = None,
    ) -> pd.DataFrame:
        """Fetch historical CWA weather records filtered by time range and location.

        Parameters
        ----------
        start_time : datetime | str | None
            Start of time filter range (inclusive).
        end_time : datetime | str | None
            End of time filter range (inclusive).
        location : str | None
            Optional location filter.

        Returns
        -------
        pd.DataFrame
            Sorted DataFrame of weather observation records.
        """
        where_clause, params = _build_time_location_filter(start_time, end_time, location)
        query = f"""
            SELECT time, location, temperature, relative_humidity, created_at
            FROM raw_cwa_weather
            WHERE {where_clause}
            ORDER BY time ASC, location ASC
        """

        with self.engine.connect() as conn:
            df = pd.read_sql_query(text(query), con=conn, params=params)

        if df.empty:
            empty_df = pd.DataFrame(
                columns=["time", "location", "temperature", "relative_humidity", "created_at"]
            )
            empty_df["time"] = pd.to_datetime(empty_df["time"])
            return empty_df

        df["time"] = utc_to_taiwan_datetime(df["time"])
        return df

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
