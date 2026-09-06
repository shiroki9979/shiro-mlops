"""Repository managing persistence and queries for Taipower regional supply-demand snapshots."""

import logging
from datetime import datetime

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.core.database import ensure_timescale_hypertables, get_timescale_engine
from shiro_mlops.data.repository_utils import (
    deserialize_raw_payload,
    resolve_snapshot_source_time,
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
        params = {"observed_at": taiwan_instant_to_utc(observed_at)}

        with self.engine.connect() as conn:
            rows = conn.execute(query, params).mappings().all()

        # 以北中南東固定順序回傳，避免字碼排序打亂領域慣用順序。
        region_order = {
            region: index for index, region in enumerate(REGIONAL_SUPPLY_DEMAND_REGIONS)
        }
        snapshots: list[TaipowerRegionalSupplyDemandSnapshot] = []
        for row in rows:
            raw_payload = deserialize_raw_payload(row["raw_payload"])
            snapshots.append(
                TaipowerRegionalSupplyDemandSnapshot(
                    observed_at=utc_instant_to_taiwan(row["observed_at"]) or observed_at,
                    region=str(row["region"]),
                    source_time=resolve_snapshot_source_time(
                        row["source_time"], row["observed_at"], observed_at
                    ),
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
