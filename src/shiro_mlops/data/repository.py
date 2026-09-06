"""Time-series database repository for persisting and querying raw load and weather data."""

import json
import logging
import math
from datetime import date, datetime
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
    REGIONAL_SUPPLY_DEMAND_REGIONS,
    TaipowerRegionalSupplyDemandSnapshot,
)
from shiro_mlops.data.taipower_supply_demand import TaipowerSupplyDemandSnapshot
from shiro_mlops.data.taipower_unit_generation import TaipowerUnitGenerationSnapshot

logger = logging.getLogger(__name__)


def _to_python_datetime(value: Any) -> datetime:
    """Normalize pandas/SQLAlchemy timestamps to timezone-naive Python datetime."""
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("UTC").tz_localize(None)
    return timestamp.to_pydatetime()


def _taiwan_instant_to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return _to_python_datetime(taiwan_local_to_utc(pd.Series([value])).iloc[0])


def _utc_instant_to_taiwan(value: Any) -> datetime | None:
    if value is None or pd.isna(value):
        return None
    return _to_python_datetime(utc_to_taiwan_datetime(pd.Series([value])).iloc[0])


def _serialize_raw_payload(payload: Any) -> str:
    """Serialize raw API payload to JSON text for database column storage."""
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, ensure_ascii=False)


def _deserialize_raw_payload(payload: Any) -> Any:
    """Deserialize raw API payload from JSON text or pass through parsed objects."""
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError("raw_payload must contain valid JSON") from exc
    return payload


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
        if (
            snapshot.curr_load_wan_kw is None
            or pd.isna(snapshot.curr_load_wan_kw)
            or math.isnan(snapshot.curr_load_wan_kw)
            or math.isinf(snapshot.curr_load_wan_kw)
        ):
            raise ValueError(f"Invalid curr_load_wan_kw in snapshot: {snapshot.curr_load_wan_kw!r}")
        if (
            snapshot.curr_util_rate_pct is None
            or pd.isna(snapshot.curr_util_rate_pct)
            or math.isnan(snapshot.curr_util_rate_pct)
            or math.isinf(snapshot.curr_util_rate_pct)
        ):
            raise ValueError(
                f"Invalid curr_util_rate_pct in snapshot: {snapshot.curr_util_rate_pct!r}"
            )

        record = {
            "observed_at": _taiwan_instant_to_utc(snapshot.observed_at),
            "source_publish_time": _taiwan_instant_to_utc(snapshot.source_publish_time),
            "curr_load_wan_kw": float(snapshot.curr_load_wan_kw),
            "curr_util_rate_pct": float(snapshot.curr_util_rate_pct),
            "fore_maxi_sply_capacity_wan_kw": snapshot.fore_maxi_sply_capacity_wan_kw,
            "fore_peak_dema_load_wan_kw": snapshot.fore_peak_dema_load_wan_kw,
            "fore_peak_resv_capacity_wan_kw": snapshot.fore_peak_resv_capacity_wan_kw,
            "fore_peak_resv_rate_pct": snapshot.fore_peak_resv_rate_pct,
            "fore_peak_resv_indicator": snapshot.fore_peak_resv_indicator,
            "fore_peak_hour_range": snapshot.fore_peak_hour_range,
            "yday_date": snapshot.yday_date,
            "yday_maxi_sply_capacity_wan_kw": snapshot.yday_maxi_sply_capacity_wan_kw,
            "yday_peak_dema_load_wan_kw": snapshot.yday_peak_dema_load_wan_kw,
            "yday_peak_resv_capacity_wan_kw": snapshot.yday_peak_resv_capacity_wan_kw,
            "yday_peak_resv_rate_pct": snapshot.yday_peak_resv_rate_pct,
            "yday_peak_resv_indicator": snapshot.yday_peak_resv_indicator,
            "real_hr_maxi_sply_capacity_wan_kw": snapshot.real_hr_maxi_sply_capacity_wan_kw,
            "real_hr_peak_time": _taiwan_instant_to_utc(snapshot.real_hr_peak_time),
            "raw_payload": _serialize_raw_payload(snapshot.raw_payload),
        }

        upsert_stmt = text(
            """
            INSERT INTO raw_taipower_supply_demand_snapshot (
                observed_at,
                source_publish_time,
                curr_load_wan_kw,
                curr_util_rate_pct,
                fore_maxi_sply_capacity_wan_kw,
                fore_peak_dema_load_wan_kw,
                fore_peak_resv_capacity_wan_kw,
                fore_peak_resv_rate_pct,
                fore_peak_resv_indicator,
                fore_peak_hour_range,
                yday_date,
                yday_maxi_sply_capacity_wan_kw,
                yday_peak_dema_load_wan_kw,
                yday_peak_resv_capacity_wan_kw,
                yday_peak_resv_rate_pct,
                yday_peak_resv_indicator,
                real_hr_maxi_sply_capacity_wan_kw,
                real_hr_peak_time,
                raw_payload
            ) VALUES (
                :observed_at,
                :source_publish_time,
                :curr_load_wan_kw,
                :curr_util_rate_pct,
                :fore_maxi_sply_capacity_wan_kw,
                :fore_peak_dema_load_wan_kw,
                :fore_peak_resv_capacity_wan_kw,
                :fore_peak_resv_rate_pct,
                :fore_peak_resv_indicator,
                :fore_peak_hour_range,
                :yday_date,
                :yday_maxi_sply_capacity_wan_kw,
                :yday_peak_dema_load_wan_kw,
                :yday_peak_resv_capacity_wan_kw,
                :yday_peak_resv_rate_pct,
                :yday_peak_resv_indicator,
                :real_hr_maxi_sply_capacity_wan_kw,
                :real_hr_peak_time,
                :raw_payload
            )
            ON CONFLICT (observed_at) DO UPDATE SET
                source_publish_time = EXCLUDED.source_publish_time,
                curr_load_wan_kw = EXCLUDED.curr_load_wan_kw,
                curr_util_rate_pct = EXCLUDED.curr_util_rate_pct,
                fore_maxi_sply_capacity_wan_kw = EXCLUDED.fore_maxi_sply_capacity_wan_kw,
                fore_peak_dema_load_wan_kw = EXCLUDED.fore_peak_dema_load_wan_kw,
                fore_peak_resv_capacity_wan_kw = EXCLUDED.fore_peak_resv_capacity_wan_kw,
                fore_peak_resv_rate_pct = EXCLUDED.fore_peak_resv_rate_pct,
                fore_peak_resv_indicator = EXCLUDED.fore_peak_resv_indicator,
                fore_peak_hour_range = EXCLUDED.fore_peak_hour_range,
                yday_date = EXCLUDED.yday_date,
                yday_maxi_sply_capacity_wan_kw = EXCLUDED.yday_maxi_sply_capacity_wan_kw,
                yday_peak_dema_load_wan_kw = EXCLUDED.yday_peak_dema_load_wan_kw,
                yday_peak_resv_capacity_wan_kw = EXCLUDED.yday_peak_resv_capacity_wan_kw,
                yday_peak_resv_rate_pct = EXCLUDED.yday_peak_resv_rate_pct,
                yday_peak_resv_indicator = EXCLUDED.yday_peak_resv_indicator,
                real_hr_maxi_sply_capacity_wan_kw = EXCLUDED.real_hr_maxi_sply_capacity_wan_kw,
                real_hr_peak_time = EXCLUDED.real_hr_peak_time,
                raw_payload = EXCLUDED.raw_payload
            """
        )

        with self.engine.begin() as conn:
            conn.execute(upsert_stmt, record)

        logger.info(
            "Upserted supply-demand snapshot for observed_at=%s",
            snapshot.observed_at.isoformat(),
        )
        return 1

    def fetch_supply_demand_snapshot(
        self, observed_at: datetime
    ) -> TaipowerSupplyDemandSnapshot | None:
        """Fetch a supply-demand snapshot by Taiwan-local observation slot."""
        query = text(
            """
            SELECT
                observed_at,
                source_publish_time,
                curr_load_wan_kw,
                curr_util_rate_pct,
                fore_maxi_sply_capacity_wan_kw,
                fore_peak_dema_load_wan_kw,
                fore_peak_resv_capacity_wan_kw,
                fore_peak_resv_rate_pct,
                fore_peak_resv_indicator,
                fore_peak_hour_range,
                yday_date,
                yday_maxi_sply_capacity_wan_kw,
                yday_peak_dema_load_wan_kw,
                yday_peak_resv_capacity_wan_kw,
                yday_peak_resv_rate_pct,
                yday_peak_resv_indicator,
                real_hr_maxi_sply_capacity_wan_kw,
                real_hr_peak_time,
                raw_payload
            FROM raw_taipower_supply_demand_snapshot
            WHERE observed_at = :observed_at
            """
        )
        params = {"observed_at": _taiwan_instant_to_utc(observed_at)}

        with self.engine.connect() as conn:
            row = conn.execute(query, params).mappings().first()

        if row is None:
            return None

        raw_payload = _deserialize_raw_payload(row["raw_payload"])

        yday_value = row["yday_date"]
        yday_date: date | None
        if yday_value is None or pd.isna(yday_value):
            yday_date = None
        elif isinstance(yday_value, date) and not isinstance(yday_value, datetime):
            yday_date = yday_value
        else:
            yday_date = pd.Timestamp(yday_value).date()

        return TaipowerSupplyDemandSnapshot(
            observed_at=_utc_instant_to_taiwan(row["observed_at"]) or observed_at,
            curr_load_wan_kw=float(row["curr_load_wan_kw"]),
            curr_util_rate_pct=float(row["curr_util_rate_pct"]),
            source_publish_time=_utc_instant_to_taiwan(row["source_publish_time"]),
            fore_maxi_sply_capacity_wan_kw=row["fore_maxi_sply_capacity_wan_kw"],
            fore_peak_dema_load_wan_kw=row["fore_peak_dema_load_wan_kw"],
            fore_peak_resv_capacity_wan_kw=row["fore_peak_resv_capacity_wan_kw"],
            fore_peak_resv_rate_pct=row["fore_peak_resv_rate_pct"],
            fore_peak_resv_indicator=row["fore_peak_resv_indicator"],
            fore_peak_hour_range=row["fore_peak_hour_range"],
            yday_date=yday_date,
            yday_maxi_sply_capacity_wan_kw=row["yday_maxi_sply_capacity_wan_kw"],
            yday_peak_dema_load_wan_kw=row["yday_peak_dema_load_wan_kw"],
            yday_peak_resv_capacity_wan_kw=row["yday_peak_resv_capacity_wan_kw"],
            yday_peak_resv_rate_pct=row["yday_peak_resv_rate_pct"],
            yday_peak_resv_indicator=row["yday_peak_resv_indicator"],
            real_hr_maxi_sply_capacity_wan_kw=row["real_hr_maxi_sply_capacity_wan_kw"],
            real_hr_peak_time=_utc_instant_to_taiwan(row["real_hr_peak_time"]),
            raw_payload=raw_payload,
        )

    def upsert_regional_supply_demand_snapshots(
        self, snapshots: list[TaipowerRegionalSupplyDemandSnapshot]
    ) -> int:
        """Upsert regional supply-demand snapshots keyed by (observed_at, region)."""
        if not snapshots:
            return 0

        upsert_stmt = text(
            """
            INSERT INTO raw_taipower_regional_supply_demand_snapshot (
                observed_at,
                region,
                source_time,
                generation_wan_kw,
                load_wan_kw,
                raw_payload
            ) VALUES (
                :observed_at,
                :region,
                :source_time,
                :generation_wan_kw,
                :load_wan_kw,
                :raw_payload
            )
            ON CONFLICT (observed_at, region) DO UPDATE SET
                source_time = EXCLUDED.source_time,
                generation_wan_kw = EXCLUDED.generation_wan_kw,
                load_wan_kw = EXCLUDED.load_wan_kw,
                raw_payload = EXCLUDED.raw_payload
            """
        )

        records = []
        for snapshot in snapshots:
            if snapshot.region not in REGIONAL_SUPPLY_DEMAND_REGIONS:
                raise ValueError(f"Invalid region in snapshot: {snapshot.region!r}")
            if snapshot.load_wan_kw is None or pd.isna(snapshot.load_wan_kw):
                raise ValueError(f"Invalid load_wan_kw in snapshot: {snapshot.load_wan_kw!r}")

            records.append(
                {
                    "observed_at": _taiwan_instant_to_utc(snapshot.observed_at),
                    "region": snapshot.region,
                    "source_time": _taiwan_instant_to_utc(snapshot.source_time),
                    "generation_wan_kw": snapshot.generation_wan_kw,
                    "load_wan_kw": float(snapshot.load_wan_kw),
                    "raw_payload": _serialize_raw_payload(snapshot.raw_payload),
                }
            )

        with self.engine.begin() as conn:
            conn.execute(upsert_stmt, records)

        logger.info(
            "Upserted %s regional supply-demand snapshots for observed_at=%s",
            len(snapshots),
            snapshots[0].observed_at.isoformat(),
        )
        return len(snapshots)

    def fetch_regional_supply_demand_snapshots(
        self, observed_at: datetime
    ) -> list[TaipowerRegionalSupplyDemandSnapshot]:
        """Fetch regional snapshots for a Taiwan-local observation slot."""
        query = text(
            """
            SELECT
                observed_at,
                region,
                source_time,
                generation_wan_kw,
                load_wan_kw,
                raw_payload
            FROM raw_taipower_regional_supply_demand_snapshot
            WHERE observed_at = :observed_at
            """
        )
        params = {"observed_at": _taiwan_instant_to_utc(observed_at)}

        with self.engine.connect() as conn:
            rows = conn.execute(query, params).mappings().all()

        # 以北中南東固定順序回傳，避免字碼排序打亂領域慣用順序。
        region_order = {
            region: index for index, region in enumerate(REGIONAL_SUPPLY_DEMAND_REGIONS)
        }
        snapshots: list[TaipowerRegionalSupplyDemandSnapshot] = []
        for row in rows:
            raw_payload = _deserialize_raw_payload(row["raw_payload"])
            snapshots.append(
                TaipowerRegionalSupplyDemandSnapshot(
                    observed_at=_utc_instant_to_taiwan(row["observed_at"]) or observed_at,
                    region=str(row["region"]),
                    source_time=_utc_instant_to_taiwan(row["source_time"])
                    or _utc_instant_to_taiwan(row["observed_at"])
                    or observed_at,
                    generation_wan_kw=(
                        None
                        if row["generation_wan_kw"] is None
                        else float(row["generation_wan_kw"])
                    ),
                    load_wan_kw=float(row["load_wan_kw"]),
                    raw_payload=raw_payload,
                )
            )

        unknown_rank = len(REGIONAL_SUPPLY_DEMAND_REGIONS)
        snapshots.sort(key=lambda item: region_order.get(item.region, unknown_rank))
        return snapshots

    def upsert_unit_generation_snapshots(
        self, snapshots: list[TaipowerUnitGenerationSnapshot]
    ) -> int:
        """Upsert unit net-generation snapshots keyed by identity and observed_at."""
        if not snapshots:
            return 0

        upsert_stmt = text(
            """
            INSERT INTO raw_taipower_unit_generation_snapshot (
                observed_at,
                unit_type,
                unit_name,
                source_time,
                capacity_mw,
                net_generation_mw,
                capacity_ratio_pct,
                remark,
                raw_payload
            ) VALUES (
                :observed_at,
                :unit_type,
                :unit_name,
                :source_time,
                :capacity_mw,
                :net_generation_mw,
                :capacity_ratio_pct,
                :remark,
                :raw_payload
            )
            ON CONFLICT (observed_at, unit_type, unit_name) DO UPDATE SET
                source_time = EXCLUDED.source_time,
                capacity_mw = EXCLUDED.capacity_mw,
                net_generation_mw = EXCLUDED.net_generation_mw,
                capacity_ratio_pct = EXCLUDED.capacity_ratio_pct,
                remark = EXCLUDED.remark,
                raw_payload = EXCLUDED.raw_payload
            """
        )

        records = []
        for snapshot in snapshots:
            if (
                not snapshot.unit_type
                or not str(snapshot.unit_type).strip()
                or str(snapshot.unit_type).strip().lower() in ("none", "null", "-", "n/a")
            ):
                raise ValueError(f"Invalid unit_type in snapshot: {snapshot.unit_type!r}")
            if (
                not snapshot.unit_name
                or not str(snapshot.unit_name).strip()
                or str(snapshot.unit_name).strip().lower() in ("none", "null", "-", "n/a")
            ):
                raise ValueError(f"Invalid unit_name in snapshot: {snapshot.unit_name!r}")

            records.append(
                {
                    "observed_at": _taiwan_instant_to_utc(snapshot.observed_at),
                    "unit_type": snapshot.unit_type,
                    "unit_name": snapshot.unit_name,
                    "source_time": _taiwan_instant_to_utc(snapshot.source_time),
                    "capacity_mw": snapshot.capacity_mw,
                    "net_generation_mw": snapshot.net_generation_mw,
                    "capacity_ratio_pct": snapshot.capacity_ratio_pct,
                    "remark": snapshot.remark,
                    "raw_payload": _serialize_raw_payload(snapshot.raw_payload),
                }
            )

        with self.engine.begin() as conn:
            conn.execute(upsert_stmt, records)

        logger.info(
            "Upserted %s unit-generation snapshots for observed_at=%s",
            len(snapshots),
            snapshots[0].observed_at.isoformat(),
        )
        return len(snapshots)

    def fetch_unit_generation_snapshots(
        self, observed_at: datetime
    ) -> list[TaipowerUnitGenerationSnapshot]:
        """Fetch unit net-generation snapshots for a Taiwan-local observation slot."""
        query = text(
            """
            SELECT
                observed_at,
                unit_type,
                unit_name,
                source_time,
                capacity_mw,
                net_generation_mw,
                capacity_ratio_pct,
                remark,
                raw_payload
            FROM raw_taipower_unit_generation_snapshot
            WHERE observed_at = :observed_at
            """
        )
        params = {"observed_at": _taiwan_instant_to_utc(observed_at)}

        with self.engine.connect() as conn:
            rows = conn.execute(query, params).mappings().all()

        snapshots: list[TaipowerUnitGenerationSnapshot] = []
        for row in rows:
            raw_payload = _deserialize_raw_payload(row["raw_payload"])
            snapshots.append(
                TaipowerUnitGenerationSnapshot(
                    observed_at=_utc_instant_to_taiwan(row["observed_at"]) or observed_at,
                    unit_type=str(row["unit_type"]),
                    unit_name=str(row["unit_name"]),
                    source_time=_utc_instant_to_taiwan(row["source_time"])
                    or _utc_instant_to_taiwan(row["observed_at"])
                    or observed_at,
                    capacity_mw=(None if row["capacity_mw"] is None else float(row["capacity_mw"])),
                    net_generation_mw=(
                        None
                        if row["net_generation_mw"] is None
                        else float(row["net_generation_mw"])
                    ),
                    capacity_ratio_pct=(
                        None
                        if row["capacity_ratio_pct"] is None
                        else float(row["capacity_ratio_pct"])
                    ),
                    remark=row["remark"],
                    raw_payload=raw_payload,
                )
            )

        snapshots.sort(key=lambda item: (item.unit_type, item.unit_name))
        return snapshots
