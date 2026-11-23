"""Judge one dataset's availability, freshness and completeness from its `StatusPolicy`."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from shiro_mlops.data.hourly_actual_load import recent_completed_hours
from shiro_mlops.data.weather_resolution import forecast_is_stale
from shiro_mlops.service.data_explorer.datasets.definition import (
    AlwaysComplete,
    AuditHeader,
    Dataset,
    FreshnessSource,
    LastCompletedHours,
    LatestAudit,
    LatestSlot,
    Row,
    TrailingWindow,
)
from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.gap_scan import GapScan
from shiro_mlops.service.data_explorer.pagination import sort_order
from shiro_mlops.service.data_explorer.query import TimeWindow
from shiro_mlops.service.data_explorer.schemas import DatasetStatus
from shiro_mlops.service.data_explorer.status import derive_overall, evaluate_freshness
from shiro_mlops.service.data_explorer.timefmt import format_taiwan_time
from shiro_mlops.service.data_explorer.values import json_list, row_time


def judge_status(db: ExplorerDb, dataset: Dataset, as_of: datetime) -> DatasetStatus:
    """The dataset's status at `as_of`; completeness is judged only once a newest row exists."""
    latest = _latest_row(db, dataset.freshness_source)
    newest = row_time(latest, "source_at") if latest is not None else None
    scan = GapScan(db, dataset)
    match dataset.status_policy:
        case LastCompletedHours(hours=hours):
            completed = recent_completed_hours(as_of, hours)
            window = TimeWindow(completed.start, completed.end)
            missing = scan.due_missing_slots(window, as_of) if newest is not None else []
            return _compose_status(dataset, as_of, latest, missing)
        case TrailingWindow(span=span):
            missing = _trailing_gaps(db, scan, newest, span) if newest is not None else []
            return _compose_status(dataset, as_of, latest, missing)
        case LatestSlot(incomplete_href=href):
            missing = _absent_at(scan, newest) if newest is not None else []
            return _compose_status(dataset, as_of, latest, missing, href=href if missing else None)
        case AlwaysComplete():
            count = _newest_instant_count(db, dataset) if newest is not None else 0
            return _compose_status(dataset, as_of, latest, [], record_count=count)
        case LatestAudit(header=header, flags_stale_release=flags_stale_release):
            missing = _audit_missing_identifiers(_latest_audit(db, header))
            stale = (
                forecast_is_stale(newest, as_of)
                if flags_stale_release and newest is not None
                else None
            )
            return _compose_status(dataset, as_of, latest, missing, latest_release_stale=stale)


def _trailing_gaps(db: ExplorerDb, scan: GapScan, newest: datetime, span: timedelta) -> list[str]:
    earliest = _earliest(db, scan.dataset, TimeWindow(newest - span, newest))
    if earliest is None:
        return []
    return scan.missing_slots(TimeWindow(earliest, newest))


def _absent_at(scan: GapScan, slot: datetime) -> list[str]:
    present = scan.present_members(TimeWindow(slot, slot))
    return scan.absent_members(present.get(slot, set()))


def _earliest(db: ExplorerDb, dataset: Dataset, window: TimeWindow) -> datetime | None:
    clauses, params = db.time_window(dataset.time_column, window)
    row = db.fetch_one(
        f"SELECT MIN({dataset.time_column}) AS earliest "
        f"FROM {dataset.relation} WHERE {' AND '.join(clauses)}",
        params,
    )
    if row is None or row["earliest"] is None:
        return None
    return row_time(row, "earliest")


def _newest_instant_count(db: ExplorerDb, dataset: Dataset) -> int:
    column, relation = dataset.time_column, dataset.relation
    count = db.scalar(
        f"SELECT COUNT(*) FROM {relation} WHERE {column} = (SELECT MAX({column}) FROM {relation})"
    )
    return int(count or 0)


def _latest_row(db: ExplorerDb, source: FreshnessSource) -> Row | None:
    clauses = [item.sql for item in source.pinned]
    params: dict[str, Any] = {}
    for item in source.pinned:
        params.update(item.params)
    where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
    order = sort_order(source.order or (source.source_column,))
    return db.fetch_one(
        f"SELECT {source.source_column} AS source_at, {source.ingested_column} AS ingested_at "
        f"FROM {source.relation} {where}ORDER BY {order} LIMIT 1",
        params,
    )


def _latest_audit(db: ExplorerDb, header: AuditHeader) -> Row | None:
    return db.fetch_one(
        f"SELECT {header.ids_column} AS missing_ids "
        f"FROM {header.table} "
        f"ORDER BY {sort_order(header.order)} LIMIT 1"
    )


def _audit_missing_identifiers(audit: Row | None) -> list[str]:
    if audit is None:
        return []
    return [str(item) for item in json_list(audit["missing_ids"])]


def _compose_status(
    dataset: Dataset,
    as_of: datetime,
    latest: Row | None,
    missing: list[str],
    *,
    href: str | None = None,
    record_count: int | None = None,
    latest_release_stale: bool | None = None,
) -> DatasetStatus:
    """An empty dataset is `empty` with unknown completeness, whatever `missing` holds.

    `href` replaces the dataset's own link when given.
    """
    source_at = row_time(latest, "source_at") if latest is not None else None
    ingested_at = row_time(latest, "ingested_at") if latest is not None else None
    freshness = evaluate_freshness(
        cadence_seconds=int(dataset.cadence.total_seconds()),
        as_of=as_of,
        latest_source_at=source_at,
        latest_ingested_at=ingested_at,
    )
    if latest is None:
        availability, completeness, missing = "empty", "unknown", []
    else:
        availability, completeness = "available", "incomplete" if missing else "complete"
    return DatasetStatus(
        id=dataset.id,
        label=dataset.label,
        availability=availability,
        freshness=freshness.state,
        completeness=completeness,
        overall=derive_overall(availability, freshness.state, completeness),
        latest_source_at=format_taiwan_time(source_at) if source_at is not None else None,
        latest_ingested_at=format_taiwan_time(ingested_at) if ingested_at is not None else None,
        ingestion_age_seconds=freshness.ingestion_age_seconds,
        source_age_seconds=freshness.source_age_seconds,
        missing_identifiers=missing,
        missing_slot_count=len(missing),
        record_count=record_count,
        latest_release_stale=latest_release_stale,
        href=href or dataset.href,
    )
