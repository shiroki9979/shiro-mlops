"""Repository managing persistence and queries for Taipower unit net-generation snapshots."""

import logging
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.core.database import ensure_timescale_hypertables, get_timescale_engine
from shiro_mlops.core.storage_time import from_storage_time, to_storage_time
from shiro_mlops.data.repository_utils import deserialize_raw_payload, serialize_raw_payload
from shiro_mlops.data.taipower_unit_generation import (
    TaipowerUnitGenerationSnapshot,
    is_valid_unit_identity,
)

logger = logging.getLogger(__name__)

_TABLE = "raw_taipower_unit_generation_snapshot"


class TaipowerUnitGenerationRepository:
    """Repository dedicated to Taipower generator unit net-generation snapshots."""

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

    def upsert(self, snapshots: list[TaipowerUnitGenerationSnapshot]) -> int:
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
            _validate_unit_identity(snapshot.unit_type, "unit_type")
            _validate_unit_identity(snapshot.unit_name, "unit_name")

            records.append(
                {
                    "observed_at": to_storage_time(snapshot.observed_at),
                    "unit_type": snapshot.unit_type,
                    "unit_name": snapshot.unit_name,
                    "source_time": to_storage_time(snapshot.source_time),
                    "capacity_mw": snapshot.capacity_mw,
                    "net_generation_mw": snapshot.net_generation_mw,
                    "capacity_ratio_pct": snapshot.capacity_ratio_pct,
                    "remark": snapshot.remark,
                    "raw_payload": serialize_raw_payload(snapshot.raw_payload),
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

    def fetch(self, observed_at: datetime) -> list[TaipowerUnitGenerationSnapshot]:
        """Fetch unit net-generation snapshots for a Taiwan-local observation slot.

        Both instants are NOT NULL in the schema; a NULL one means corrupted storage and
        raises instead of being filled from the query slot.
        """
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
        params = {"observed_at": to_storage_time(observed_at)}

        with self.engine.connect() as conn:
            rows = conn.execute(query, params).mappings().all()

        snapshots: list[TaipowerUnitGenerationSnapshot] = []
        for row in rows:
            raw_payload = deserialize_raw_payload(row["raw_payload"])
            snapshots.append(
                TaipowerUnitGenerationSnapshot(
                    observed_at=from_storage_time(
                        row["observed_at"], column=f"{_TABLE}.observed_at"
                    ),
                    unit_type=str(row["unit_type"]),
                    unit_name=str(row["unit_name"]),
                    source_time=from_storage_time(
                        row["source_time"], column=f"{_TABLE}.source_time"
                    ),
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


def _validate_unit_identity(value: str | None, field_name: str) -> None:
    """Ensure unit identification fields are non-empty and not dummy placeholders."""
    if not is_valid_unit_identity(value):
        raise ValueError(f"Invalid {field_name} in snapshot: {value!r}")
