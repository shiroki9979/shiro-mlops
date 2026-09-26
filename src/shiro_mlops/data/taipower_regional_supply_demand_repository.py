"""Repository managing persistence and queries for Taipower regional supply-demand snapshots."""

import logging
from datetime import datetime
from typing import Any

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
from shiro_mlops.data.taipower_regional_supply_demand import (
    REGIONAL_SUPPLY_DEMAND_REGIONS,
    TaipowerRegionalSupplyDemandSnapshot,
)

logger = logging.getLogger(__name__)


class TaipowerRegionalSupplyDemandRepository:
    """Repository dedicated to Taipower regional supply-demand snapshots."""

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
            try:
                ensure_timescale_hypertables(self.engine)
            except Exception as e:
                logger.warning("Could not auto-initialize hypertables: %s", e)

    def upsert(self, snapshots: list[TaipowerRegionalSupplyDemandSnapshot]) -> int:
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
                    "observed_at": taiwan_instant_to_utc(snapshot.observed_at),
                    "region": snapshot.region,
                    "source_time": taiwan_instant_to_utc(snapshot.source_time),
                    "generation_wan_kw": snapshot.generation_wan_kw,
                    "load_wan_kw": float(snapshot.load_wan_kw),
                    "raw_payload": serialize_raw_payload(snapshot.raw_payload),
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

    def fetch(self, observed_at: datetime) -> list[TaipowerRegionalSupplyDemandSnapshot]:
        """Fetch regional snapshots for a Taiwan-local observation slot."""
        query = text(
            f"""
            {_SELECT_SNAPSHOT_COLUMNS}
            WHERE observed_at = :observed_at
            """
        )
        params = {"observed_at": taiwan_instant_to_utc(observed_at)}

        with self.engine.connect() as conn:
            rows = conn.execute(query, params).mappings().all()

        # 以北中南東固定順序回傳，避免字碼排序打亂領域慣用順序。
        region_order = {
            region: index for index, region in enumerate(REGIONAL_SUPPLY_DEMAND_REGIONS)
        }
        snapshots = [_row_to_snapshot(row) for row in rows]
        unknown_rank = len(REGIONAL_SUPPLY_DEMAND_REGIONS)
        snapshots.sort(key=lambda item: region_order.get(item.region, unknown_rank))
        return snapshots

    def fetch_by_source_time(
        self, start_time: datetime, end_time: datetime
    ) -> list[TaipowerRegionalSupplyDemandSnapshot]:
        """Fetch snapshots whose Taiwan-local source_time is in [start_time, end_time)."""
        query = text(
            f"""
            {_SELECT_SNAPSHOT_COLUMNS}
            WHERE source_time >= :start_time AND source_time < :end_time
            ORDER BY source_time ASC, observed_at ASC, region ASC
            """
        )
        params = {
            "start_time": taiwan_instant_to_utc(start_time),
            "end_time": taiwan_instant_to_utc(end_time),
        }

        with self.engine.connect() as conn:
            rows = conn.execute(query, params).mappings().all()
        return [_row_to_snapshot(row) for row in rows]


_SELECT_SNAPSHOT_COLUMNS = """
    SELECT
        observed_at,
        region,
        source_time,
        generation_wan_kw,
        load_wan_kw,
        raw_payload
    FROM raw_taipower_regional_supply_demand_snapshot
"""


def _row_to_snapshot(row: Any) -> TaipowerRegionalSupplyDemandSnapshot:
    """Map a database row back to a Taiwan-local typed snapshot.

    Both timestamps are NOT NULL in the schema; a missing one means corrupted
    storage, and substituting a query bound would silently mislabel the sample.
    """
    return TaipowerRegionalSupplyDemandSnapshot(
        observed_at=_required_instant(row, "observed_at"),
        region=str(row["region"]),
        source_time=_required_instant(row, "source_time"),
        generation_wan_kw=(
            None if row["generation_wan_kw"] is None else float(row["generation_wan_kw"])
        ),
        load_wan_kw=float(row["load_wan_kw"]),
        raw_payload=deserialize_raw_payload(row["raw_payload"]),
    )


def _required_instant(row: Any, column: str) -> datetime:
    value = utc_instant_to_taiwan(row[column])
    if value is None:
        raise ValueError(
            f"raw_taipower_regional_supply_demand_snapshot row for region {row['region']!r} "
            f"has no {column} (observed_at={row['observed_at']!r}, "
            f"source_time={row['source_time']!r})"
        )
    return value
