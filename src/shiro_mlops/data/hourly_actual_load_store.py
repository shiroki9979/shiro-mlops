"""The owner of ``raw_taipower_load``: nationwide hourly actual load (ADR-0008).

Elsewhere in ``src/``, ``scripts/`` and ``lab/`` only schema init and migration, the Data
Explorer's declarative hourly load dataset and the forecast track-record join in
``ForecastTrackRecordStore.fetch_pairs`` (``src/shiro_mlops/data/forecast_track_record.py``)
touch the table; the last two select the derived rows by binding
``REGIONAL_SNAPSHOT_SUM_SOURCE`` from this module.
Every row this store writes carries the derived source, and every derived hour it reads
selects only that source, so d015046-era rows (NULL source) and other sources never
mix into the derived series. Two reads look past the source: the accumulation counts
legacy rows only to report them, and rederivation's check for occupied hours sees rows
of any source so that it never overwrites one.
Callers pass and receive Taiwan-local hours in a ``datetime`` column;
the stored column name ``time`` stays inside this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.core.constants import DATETIME_COL, LOAD_MW_COL, NATIONWIDE_SUBJECT
from shiro_mlops.core.storage_time import (
    from_storage_time,
    from_storage_time_or_none,
    from_storage_time_series,
    half_open_window,
    to_storage_time,
    window_before,
)
from shiro_mlops.data.hourly_actual_load import (
    ONE_HOUR,
    HourlyLoadAccumulation,
    HourWindow,
    catch_up_window,
    derive_hourly_actual_load,
    floor_to_hour,
    uncovered_gap,
)
from shiro_mlops.data.taipower_regional_supply_demand_repository import (
    TaipowerRegionalSupplyDemandRepository,
)

REGIONAL_SNAPSHOT_SUM_SOURCE = "regional_snapshot_sum"

_INSERT_DERIVED_HOURS = """
    INSERT INTO raw_taipower_load (time, subject, load_mw, source)
    VALUES (:time, :subject, :load_mw, :source)
    ON CONFLICT (time, subject)
"""


@dataclass(frozen=True)
class HourlyLoadObservation:
    """One derived hour: its Taiwan-local start and the hour's mean load in MW."""

    hour: datetime
    load_mw: float


@dataclass(frozen=True)
class ScheduledDerivationPolicy:
    """How far a scheduled derivation reaches and how many samples make a valid hour."""

    recompute_hours: int
    max_catchup_hours: int
    min_samples: int


@dataclass(frozen=True)
class ScheduledDerivation:
    """What one scheduled derivation covered, skipped, and wrote.

    ``uncovered_gap`` holds hours after the latest derived hour that lie beyond the
    catch-up limit and were not derived; ``hourly_load`` holds the derived hours with
    their ``datetime``, ``load_mw`` and ``sample_count``.
    """

    window: HourWindow
    uncovered_gap: HourWindow | None
    snapshot_count: int
    written_hours: int
    hourly_load: pd.DataFrame


class HourlyActualLoadStore:
    """Derived nationwide hourly actual load persisted in ``raw_taipower_load``."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._regional_snapshots = TaipowerRegionalSupplyDemandRepository(
            engine=engine, auto_init=False
        )

    def derive_scheduled(
        self, evaluated_at: datetime, policy: ScheduledDerivationPolicy
    ) -> ScheduledDerivation:
        """Derive and write the completed hours a schedule tick at ``evaluated_at`` covers.

        The window is the recent ``recompute_hours`` plus every hour after the latest
        derived hour the tick could have seen, capped at ``max_catchup_hours``; hours
        derived after the tick do not move it, so re-running an old tick is repeatable.
        """
        latest = self.latest_observation(floor_to_hour(evaluated_at) - ONE_HOUR)
        latest_hour = None if latest is None else latest.hour
        window = catch_up_window(
            evaluated_at,
            latest_hour,
            recent_hours=policy.recompute_hours,
            max_catchup_hours=policy.max_catchup_hours,
        )
        snapshots = self._regional_snapshots.fetch_by_source_time(window.start, window.end)
        hourly_load = derive_hourly_actual_load(
            snapshots, completed_before=window.end, min_samples=policy.min_samples
        )
        return ScheduledDerivation(
            window=window,
            uncovered_gap=uncovered_gap(latest_hour, window),
            snapshot_count=len(snapshots),
            written_hours=self.write(hourly_load),
            hourly_load=hourly_load,
        )

    def rederive(
        self, window: HourWindow, *, min_samples: int, dry_run: bool = False
    ) -> pd.DataFrame:
        """Derive the hours in ``window`` that stored snapshots support and no row occupies.

        Unlike the schedule this never overwrites: an hour holding any row, whatever its
        source, is left as it is (ADR-0008 Notes). Returns the hours written, or with
        ``dry_run`` the hours a run would write, with ``datetime``, ``load_mw`` and
        ``sample_count``.
        """
        snapshots = self._regional_snapshots.fetch_by_source_time(window.start, window.end)
        derived = derive_hourly_actual_load(
            snapshots, completed_before=window.end, min_samples=min_samples
        )
        occupied = derived[DATETIME_COL].isin(self._occupied_hours(window))
        unoccupied = derived[~occupied].reset_index(drop=True)
        if dry_run:
            return unoccupied
        return self._write_unoccupied(unoccupied)

    def _write_unoccupied(self, hourly_load: pd.DataFrame) -> pd.DataFrame:
        """Insert derived nationwide hours that hold no row yet; return the hours inserted.

        The insert itself skips an occupied hour, so a row another writer stores after
        ``rederive`` looked for free hours is never overwritten either.
        """
        records = _derived_load_records(hourly_load, NATIONWIDE_SUBJECT)
        statement = text(f"{_INSERT_DERIVED_HOURS} DO NOTHING")
        with self._engine.begin() as conn:
            inserted = [conn.execute(statement, record).rowcount == 1 for record in records]
        inserted_rows = pd.Series(inserted, index=hourly_load.index, dtype=bool)
        return hourly_load.loc[inserted_rows].reset_index(drop=True)

    # WHY-NOT(_occupied_hours): 不篩推算來源；舊口徑（source 為 NULL）與其他來源的列也算已佔用，
    # 補推不得覆寫，舊列依 docs/how-to/remove-legacy-d015046-load-rows.md 清除
    def _occupied_hours(self, window: HourWindow) -> list[datetime]:
        """Nationwide hours in ``window`` that already hold a row, whatever its source."""
        condition = half_open_window("time", window.start, window.end)
        query = text(
            f"SELECT time FROM raw_taipower_load WHERE subject = :subject AND {condition.sql}"
        )
        params = {"subject": NATIONWIDE_SUBJECT, **condition.params}
        with self._engine.connect() as conn:
            stored = conn.execute(query, params).scalars().all()
        return [from_storage_time(value, column="time") for value in stored]

    def write(self, hourly_load: pd.DataFrame, *, subject: str = NATIONWIDE_SUBJECT) -> int:
        """Upsert derived hours from ``datetime`` and ``load_mw`` columns; return the row count.

        A rewritten hour takes the new value and the derived source, so recomputing an
        hour after late samples arrive updates it in place.
        """
        records = _derived_load_records(hourly_load, subject)
        if not records:
            return 0
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    f"""
                    {_INSERT_DERIVED_HOURS} DO UPDATE SET
                        load_mw = EXCLUDED.load_mw,
                        source = EXCLUDED.source
                    """
                ),
                records,
            )
        return len(records)

    def latest_observation(
        self, at_or_before: datetime, *, subject: str = NATIONWIDE_SUBJECT
    ) -> HourlyLoadObservation | None:
        """The newest derived hour starting at or before ``at_or_before``, or ``None``."""
        query = text(
            """
            SELECT time, load_mw
            FROM raw_taipower_load
            WHERE subject = :subject AND source = :source AND time <= :at_or_before
            ORDER BY time DESC
            LIMIT 1
            """
        )
        params = {
            "subject": subject,
            "source": REGIONAL_SNAPSHOT_SUM_SOURCE,
            "at_or_before": to_storage_time(at_or_before),
        }
        with self._engine.connect() as conn:
            row = conn.execute(query, params).one_or_none()
        if row is None:
            return None
        return HourlyLoadObservation(
            hour=from_storage_time(row.time, column="time"), load_mw=float(row.load_mw)
        )

    def series(
        self, *, start: datetime | None = None, end: datetime, subject: str = NATIONWIDE_SUBJECT
    ) -> pd.DataFrame:
        """Derived hours in the Taiwan-local window ``[start, end)``, oldest first.

        Without ``start`` the series begins at the earliest derived hour. The frame
        holds ``datetime`` and ``load_mw``, the columns ``write`` takes.
        """
        window = (
            window_before("time", end) if start is None else half_open_window("time", start, end)
        )
        query = text(
            f"""
            SELECT time, load_mw
            FROM raw_taipower_load
            WHERE subject = :subject AND source = :source AND {window.sql}
            ORDER BY time
            """
        )
        params: dict[str, Any] = {
            "subject": subject,
            "source": REGIONAL_SNAPSHOT_SUM_SOURCE,
            **window.params,
        }
        with self._engine.connect() as conn:
            stored = pd.read_sql_query(query, con=conn, params=params)
        return pd.DataFrame(
            {
                DATETIME_COL: from_storage_time_series(stored["time"]),
                LOAD_MW_COL: stored[LOAD_MW_COL].astype(float),
            }
        )

    def accumulation(
        self, at_or_before: datetime | None = None, *, subject: str = NATIONWIDE_SUBJECT
    ) -> HourlyLoadAccumulation:
        """Derived hours starting at or before ``at_or_before`` beside every legacy row.

        Without ``at_or_before`` every derived hour counts. Legacy rows count whatever
        their hour or subject, since any one of them blocks training (ADR-0008).
        """
        derived = "subject = :subject AND source = :source"
        params: dict[str, object] = {"subject": subject, "source": REGIONAL_SNAPSHOT_SUM_SOURCE}
        if at_or_before is not None:
            derived += " AND time <= :at_or_before"
            params["at_or_before"] = to_storage_time(at_or_before)
        query = text(
            f"""
            SELECT
                COUNT(*) AS valid_hours,
                MAX(time) AS latest_time,
                (SELECT COUNT(*) FROM raw_taipower_load WHERE source IS NULL) AS legacy_rows
            FROM raw_taipower_load
            WHERE {derived}
            """
        )
        with self._engine.connect() as conn:
            row = conn.execute(query, params).one()
        return HourlyLoadAccumulation(
            valid_hours=int(row.valid_hours),
            legacy_rows=int(row.legacy_rows),
            latest_hour=from_storage_time_or_none(row.latest_time),
        )


def _derived_load_records(hourly_load: pd.DataFrame, subject: str) -> list[dict[str, object]]:
    """Storage-form rows for derived hours, each carrying the derived source."""
    if DATETIME_COL not in hourly_load.columns:
        raise KeyError(
            f"Hourly load must hold its Taiwan-local hours in {DATETIME_COL!r}, "
            "not the storage column 'time'"
        )
    return [
        {
            "time": to_storage_time(pd.Timestamp(hour)),
            "subject": subject,
            "load_mw": float(load_mw),
            "source": REGIONAL_SNAPSHOT_SUM_SOURCE,
        }
        for hour, load_mw in zip(hourly_load[DATETIME_COL], hourly_load[LOAD_MW_COL], strict=True)
    ]
