"""Repository managing persistence and queries for Taipower supply-demand snapshots."""

import logging
import math
from datetime import date, datetime

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.core.database import ensure_timescale_hypertables, get_timescale_engine
from shiro_mlops.data.repository_utils import (
    deserialize_raw_payload,
    serialize_raw_payload,
    taiwan_instant_to_utc,
    utc_instant_to_taiwan,
)
from shiro_mlops.data.taipower_supply_demand import TaipowerSupplyDemandSnapshot

logger = logging.getLogger(__name__)


class TaipowerSupplyDemandRepository:
    """Repository dedicated to Taipower nationwide supply-demand snapshots."""

    def __init__(
        self,
        engine: Engine | None = None,
        auto_init: bool = True,
    ) -> None:
        """Initialize repository with SQLAlchemy engine.

        Parameters
        ----------
        engine : Engine | None
            Optional pre-configured SQLAlchemy Engine. Defaults to timescale engine.
        auto_init : bool
            Whether to ensure tables and hypertables exist on initialization. Defaults to True.
        """
        self.engine = engine if engine is not None else get_timescale_engine()
        if auto_init:
            ensure_timescale_hypertables(self.engine)

    def upsert(self, snapshot: TaipowerSupplyDemandSnapshot) -> int:
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
            "observed_at": taiwan_instant_to_utc(snapshot.observed_at),
            "source_publish_time": taiwan_instant_to_utc(snapshot.source_publish_time),
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
            "real_hr_peak_time": taiwan_instant_to_utc(snapshot.real_hr_peak_time),
            "raw_payload": serialize_raw_payload(snapshot.raw_payload),
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

    def fetch(self, observed_at: datetime) -> TaipowerSupplyDemandSnapshot | None:
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
        params = {"observed_at": taiwan_instant_to_utc(observed_at)}

        with self.engine.connect() as conn:
            row = conn.execute(query, params).mappings().first()

        if row is None:
            return None

        raw_payload = deserialize_raw_payload(row["raw_payload"])

        yday_value = row["yday_date"]
        yday_date: date | None
        if yday_value is None or pd.isna(yday_value):
            yday_date = None
        elif isinstance(yday_value, date) and not isinstance(yday_value, datetime):
            yday_date = yday_value
        else:
            yday_date = pd.Timestamp(yday_value).date()

        return TaipowerSupplyDemandSnapshot(
            observed_at=utc_instant_to_taiwan(row["observed_at"]) or observed_at,
            curr_load_wan_kw=float(row["curr_load_wan_kw"]),
            curr_util_rate_pct=float(row["curr_util_rate_pct"]),
            source_publish_time=utc_instant_to_taiwan(row["source_publish_time"]),
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
            real_hr_peak_time=utc_instant_to_taiwan(row["real_hr_peak_time"]),
            raw_payload=raw_payload,
        )
