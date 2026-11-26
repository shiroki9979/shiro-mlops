"""Repository managing persistence and queries for Taipower unit net-generation batches."""

import logging
from datetime import datetime

from sqlalchemy import RowMapping, text
from sqlalchemy.engine import Engine

from shiro_mlops.core.database import ensure_timescale_hypertables, get_timescale_engine
from shiro_mlops.core.storage_time import from_storage_time, to_storage_time
from shiro_mlops.data.repository_utils import deserialize_raw_payload, serialize_raw_payload
from shiro_mlops.data.taipower_unit_generation import (
    TaipowerUnitGenerationBatch,
    TaipowerUnitGenerationSnapshot,
    is_valid_unit_identity,
)

logger = logging.getLogger(__name__)

_BATCH_TABLE = "raw_taipower_unit_generation_batch"
_SNAPSHOT_TABLE = "raw_taipower_unit_generation_snapshot"


class TaipowerUnitGenerationRepository:
    """Repository dedicated to Taipower generator unit net-generation batches.

    A batch is one header row holding the source response and one row per unit snapshot.
    """

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

    def upsert(self, batch: TaipowerUnitGenerationBatch) -> int:
        """Upsert a batch's header and unit snapshots in one transaction.

        The header is keyed by ``observed_at`` and each snapshot by observed_at and unit
        identity, so a rerun of the same slot updates both in place.

        Returns
        -------
        int
            Number of unit snapshots written.
        """
        for snapshot in batch.snapshots:
            _validate_unit_identity(snapshot.unit_type, "unit_type")
            _validate_unit_identity(snapshot.unit_name, "unit_name")

        header_stmt = text(
            f"""
            INSERT INTO {_BATCH_TABLE} (observed_at, raw_payload)
            VALUES (:observed_at, :raw_payload)
            ON CONFLICT (observed_at) DO UPDATE SET
                raw_payload = EXCLUDED.raw_payload
            """
        )
        snapshot_stmt = text(
            f"""
            INSERT INTO {_SNAPSHOT_TABLE} (
                observed_at,
                unit_type,
                unit_name,
                source_time,
                capacity_mw,
                net_generation_mw,
                capacity_ratio_pct,
                remark
            ) VALUES (
                :observed_at,
                :unit_type,
                :unit_name,
                :source_time,
                :capacity_mw,
                :net_generation_mw,
                :capacity_ratio_pct,
                :remark
            )
            ON CONFLICT (observed_at, unit_type, unit_name) DO UPDATE SET
                source_time = EXCLUDED.source_time,
                capacity_mw = EXCLUDED.capacity_mw,
                net_generation_mw = EXCLUDED.net_generation_mw,
                capacity_ratio_pct = EXCLUDED.capacity_ratio_pct,
                remark = EXCLUDED.remark
            """
        )
        header = {
            "observed_at": to_storage_time(batch.observed_at),
            "raw_payload": serialize_raw_payload(batch.raw_payload),
        }
        records = [
            {
                "observed_at": to_storage_time(snapshot.observed_at),
                "unit_type": snapshot.unit_type,
                "unit_name": snapshot.unit_name,
                "source_time": to_storage_time(snapshot.source_time),
                "capacity_mw": snapshot.capacity_mw,
                "net_generation_mw": snapshot.net_generation_mw,
                "capacity_ratio_pct": snapshot.capacity_ratio_pct,
                "remark": snapshot.remark,
            }
            for snapshot in batch.snapshots
        ]

        with self.engine.begin() as conn:
            conn.execute(header_stmt, header)
            conn.execute(snapshot_stmt, records)

        logger.info(
            "Upserted %s unit-generation snapshots for observed_at=%s",
            len(records),
            batch.observed_at.isoformat(),
        )
        return len(records)

    def fetch(self, observed_at: datetime) -> TaipowerUnitGenerationBatch | None:
        """Fetch the batch of a Taiwan-local observation slot, or ``None`` if none was written.

        Snapshots are sorted by unit identity. Both instants are NOT NULL in the schema; a
        NULL one means corrupted storage and raises instead of being filled from the query
        slot. A header without unit rows is corrupted storage too and raises ``ValueError``.
        """
        params = {"observed_at": to_storage_time(observed_at)}
        header_query = text(
            f"SELECT observed_at, raw_payload FROM {_BATCH_TABLE} WHERE observed_at = :observed_at"
        )
        snapshot_query = text(
            f"""
            SELECT
                observed_at,
                unit_type,
                unit_name,
                source_time,
                capacity_mw,
                net_generation_mw,
                capacity_ratio_pct,
                remark
            FROM {_SNAPSHOT_TABLE}
            WHERE observed_at = :observed_at
            """
        )

        with self.engine.connect() as conn:
            header = conn.execute(header_query, params).mappings().first()
            if header is None:
                return None
            rows = conn.execute(snapshot_query, params).mappings().all()

        return TaipowerUnitGenerationBatch(
            observed_at=from_storage_time(
                header["observed_at"], column=f"{_BATCH_TABLE}.observed_at"
            ),
            raw_payload=deserialize_raw_payload(header["raw_payload"]),
            snapshots=tuple(
                sorted(
                    (_snapshot_from_row(row) for row in rows),
                    key=lambda snapshot: (snapshot.unit_type, snapshot.unit_name),
                )
            ),
        )


def _snapshot_from_row(row: RowMapping) -> TaipowerUnitGenerationSnapshot:
    return TaipowerUnitGenerationSnapshot(
        observed_at=from_storage_time(row["observed_at"], column=f"{_SNAPSHOT_TABLE}.observed_at"),
        unit_type=str(row["unit_type"]),
        unit_name=str(row["unit_name"]),
        source_time=from_storage_time(row["source_time"], column=f"{_SNAPSHOT_TABLE}.source_time"),
        capacity_mw=None if row["capacity_mw"] is None else float(row["capacity_mw"]),
        net_generation_mw=(
            None if row["net_generation_mw"] is None else float(row["net_generation_mw"])
        ),
        capacity_ratio_pct=(
            None if row["capacity_ratio_pct"] is None else float(row["capacity_ratio_pct"])
        ),
        remark=row["remark"],
    )


def _validate_unit_identity(value: str | None, field_name: str) -> None:
    """Ensure unit identification fields are non-empty and not dummy placeholders."""
    if not is_valid_unit_identity(value):
        raise ValueError(f"Invalid {field_name} in snapshot: {value!r}")
