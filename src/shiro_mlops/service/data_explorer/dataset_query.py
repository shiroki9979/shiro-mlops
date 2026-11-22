"""Read any Data Explorer dataset's list page, chart series or status from its `Dataset` definition."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from functools import cached_property
from typing import Any

import pandas as pd
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from shiro_mlops.data.hourly_actual_load import recent_completed_hours
from shiro_mlops.data.weather_resolution import forecast_is_stale
from shiro_mlops.service.data_explorer.cursor import decode_cursor_filters
from shiro_mlops.service.data_explorer.datasets import DATASETS
from shiro_mlops.service.data_explorer.datasets.definition import (
    AlwaysComplete,
    AuditHeader,
    Dataset,
    FreshnessSource,
    GapPolicy,
    LastCompletedHours,
    LatestAudit,
    LatestSlot,
    Row,
    TrailingWindow,
)
from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.errors import DatabaseUnavailableError
from shiro_mlops.service.data_explorer.pagination import paginate_raw_list, sort_order
from shiro_mlops.service.data_explorer.query import ExplorerQuery, TimeWindow
from shiro_mlops.service.data_explorer.schemas import (
    DatasetStatus,
    ListEnvelope,
    SeriesResponse,
    StatusResponse,
)
from shiro_mlops.service.data_explorer.series import Agg, Bucket, SeriesReader, SeriesRequest
from shiro_mlops.service.data_explorer.status import derive_overall, evaluate_freshness
from shiro_mlops.service.data_explorer.timefmt import format_taiwan_time, now_taiwan
from shiro_mlops.service.data_explorer.values import json_list, row_time


def validate_cursor(dataset: Dataset, params: dict[str, Any]) -> dict[str, Any] | None:
    """Validate the whole cursor before any database read; return the filters it binds."""
    cursor = params.get("cursor")
    if not cursor:
        return None
    cursor_filters = decode_cursor_filters(str(cursor), dataset=dataset.id)
    query_params = (
        dataset.resolve_version.restore(params, cursor_filters)
        if dataset.resolve_version is not None
        else params
    )
    ExplorerQuery.from_params(dataset, query_params, cursor_filters=cursor_filters).cursor_key()
    return cursor_filters


class DatasetQuery:
    """List pages of any dataset newest first, with a cursor bound to its declared filters,
    read its bounded chart series, and judge every dataset's status."""

    def __init__(self, engine: Engine) -> None:
        self.db = ExplorerDb(engine)

    def list(self, dataset: Dataset, params: dict[str, Any]) -> ListEnvelope:
        cursor_filters = validate_cursor(dataset, params)
        try:
            query_params = (
                dataset.resolve_version.pin(self.db, params, cursor_filters)
                if dataset.resolve_version is not None
                else params
            )
            query = ExplorerQuery.from_params(dataset, query_params, cursor_filters=cursor_filters)
            return paginate_raw_list(query, self._fetch_rows, self._project_page)
        except SQLAlchemyError as exc:
            raise DatabaseUnavailableError(str(exc)) from exc

    def series(
        self,
        dataset: Dataset,
        params: dict[str, str],
        *,
        fields: list[str] | None,
        bucket: Bucket,
        agg: Agg | None = None,
    ) -> SeriesResponse:
        """Read the dataset's series; its version resolver may pin the version first."""
        if dataset.series is None:
            raise ValueError(f"dataset {dataset.id} declares no series")
        options = dataset.series
        if dataset.resolve_version is not None:
            options, params = dataset.resolve_version.plan_series(self.db, options, params)
        request = SeriesRequest.build(
            dataset, options, params, fields=fields, bucket=bucket, agg=agg
        )
        return SeriesReader(self.db, dataset, options).read(request)

    def status(self, as_of: datetime | None = None) -> StatusResponse:
        """Availability, freshness and completeness of every dataset, in `DATASETS` order."""
        clock = as_of or now_taiwan()
        try:
            return StatusResponse(
                datasets=[self._status(dataset, clock) for dataset in DATASETS.values()]
            )
        except SQLAlchemyError as exc:
            raise DatabaseUnavailableError(str(exc)) from exc

    def _fetch_rows(
        self, query: ExplorerQuery, cursor: dict[str, Any] | None, limit: int
    ) -> list[Row]:
        dataset = query.dataset
        clauses, params = self.db.time_window(dataset.time_column, query.window)
        filter_clauses, filter_params = dataset.clauses(self.db, query.filters)
        where, order, cursor_params = self.db.page_sql(
            [*clauses, *filter_clauses], cursor, dataset.sort
        )
        sql = (
            f"SELECT {', '.join(dataset.list_columns)} FROM {dataset.table} "
            f"WHERE {where} ORDER BY {order} LIMIT :limit"
        )
        return self.db.fetch(sql, {**params, **filter_params, **cursor_params, "limit": limit})

    def _project_page(
        self, query: ExplorerQuery, rows: list[Row]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        items = query.dataset.project(_WindowPage(self.db, query), rows)
        return items, self._list_gaps(query)

    def _list_gaps(self, query: ExplorerQuery) -> list[str]:
        """Missing slots of the whole window that have already happened, ascending."""
        dataset, gaps = query.dataset, query.dataset.gaps
        if gaps is None:
            return []
        now = now_taiwan()
        elapsed_end = min(query.window.end, now)
        if elapsed_end < query.window.start:
            return []
        return _missing_slots(
            self.db,
            dataset,
            gaps,
            TimeWindow(query.window.start, elapsed_end),
            query.filters,
            due_by=now - gaps.slot_lag,
        )

    def _status(self, dataset: Dataset, as_of: datetime) -> DatasetStatus:
        latest = _latest_row(self.db, dataset.freshness_source)
        policy = dataset.status_policy
        missing: list[str] = []
        match policy:
            case LastCompletedHours(hours=hours) if latest is not None:
                completed = recent_completed_hours(as_of, hours)
                window = TimeWindow(completed.start, completed.end - timedelta(hours=1))
                missing = self._status_gaps(dataset, window)
            case TrailingWindow(span=span) if latest is not None:
                newest = row_time(latest, "source_at")
                earliest = self._earliest(dataset, TimeWindow(newest - span, newest))
                if earliest is not None:
                    missing = self._status_gaps(dataset, TimeWindow(earliest, newest))
            case LatestSlot() if latest is not None:
                missing = self._missing_members(dataset, row_time(latest, "source_at"))
            case LatestAudit(header=header):
                missing = _audit_missing_identifiers(_latest_audit(self.db, header), header)
        status = _compose_status(dataset, as_of, latest, missing)
        match policy:
            case LatestSlot(incomplete_href=href) if missing:
                status.href = href
            case AlwaysComplete():
                status.record_count = self._newest_instant_count(dataset) if latest else 0
            case LatestAudit(flags_stale_release=True) if latest is not None:
                status.latest_release_stale = forecast_is_stale(
                    row_time(latest, "source_at"), as_of
                )
        return status

    def _status_gaps(self, dataset: Dataset, window: TimeWindow) -> list[str]:
        gaps = _require_gaps(dataset)
        return _missing_slots(self.db, dataset, gaps, window, {})

    def _missing_members(self, dataset: Dataset, slot: datetime) -> list[str]:
        gaps = _require_gaps(dataset)
        present = _present_members(self.db, dataset, gaps, TimeWindow(slot, slot), {})
        return _absent_members(dataset, gaps, present.get(slot, set()), {})

    def _earliest(self, dataset: Dataset, window: TimeWindow) -> datetime | None:
        clauses, params = self.db.time_window(dataset.time_column, window)
        row = self.db.fetch_one(
            f"SELECT MIN({dataset.time_column}) AS earliest "
            f"FROM {dataset.table} WHERE {' AND '.join(clauses)}",
            params,
        )
        if row is None or row["earliest"] is None:
            return None
        return row_time(row, "earliest")

    def _newest_instant_count(self, dataset: Dataset) -> int:
        column, table = dataset.time_column, dataset.table
        count = self.db.scalar(
            f"SELECT COUNT(*) FROM {table} WHERE {column} = (SELECT MAX({column}) FROM {table})"
        )
        return int(count or 0)


class _WindowPage:
    """The request window a page projection may consult, read lazily and once per page."""

    def __init__(self, db: ExplorerDb, query: ExplorerQuery) -> None:
        self.db = db
        self.query = query

    @cached_property
    def _present(self) -> dict[datetime, set[str]]:
        gaps = _require_gaps(self.query.dataset)
        return _present_members(
            self.db, self.query.dataset, gaps, self.query.window, self.query.filters
        )

    def missing_members(self, slot: datetime) -> list[str]:
        gaps = _require_gaps(self.query.dataset)
        found = self._present.get(slot, set())
        return _absent_members(self.query.dataset, gaps, found, self.query.filters)


def _require_gaps(dataset: Dataset) -> GapPolicy:
    if dataset.gaps is None:
        raise ValueError(f"dataset {dataset.id} declares no gap policy")
    return dataset.gaps


def _missing_slots(
    db: ExplorerDb,
    dataset: Dataset,
    gaps: GapPolicy,
    window: TimeWindow,
    filters: Mapping[str, Any],
    *,
    due_by: datetime | None = None,
) -> list[str]:
    """Each expected slot from the first at or after `window.start` that no row fills."""
    present = _present_members(db, dataset, gaps, window, filters)
    last = window.end if due_by is None else min(window.end, due_by)
    first = pd.Timestamp(window.start).ceil(dataset.cadence)
    missing: list[str] = []
    for timestamp in pd.date_range(first, last, freq=dataset.cadence):
        slot = timestamp.to_pydatetime()
        label = format_taiwan_time(slot)
        if gaps.members is None:
            if slot not in present:
                missing.append(label)
            continue
        absent = _absent_members(dataset, gaps, present.get(slot, set()), filters)
        if gaps.members.listed:
            missing.extend(f"{label}:{member}" for member in absent)
        elif absent:
            missing.append(label)
    return missing


def _present_members(
    db: ExplorerDb,
    dataset: Dataset,
    gaps: GapPolicy,
    window: TimeWindow,
    filters: Mapping[str, Any],
) -> dict[datetime, set[str]]:
    """The slots rows fill inside the window, each with the gap members present in it."""
    clauses, params = db.time_window(dataset.time_column, window)
    scope_clauses, scope_params = dataset.gap_clauses(db, filters)
    member = gaps.members.column if gaps.members is not None else None
    columns = dataset.time_column if member is None else f"{dataset.time_column}, {member}"
    rows = db.fetch(
        f"SELECT DISTINCT {columns} FROM {dataset.table} "
        f"WHERE {' AND '.join([*clauses, *scope_clauses])}",
        {**params, **scope_params},
    )
    present: dict[datetime, set[str]] = {}
    for row in rows:
        moment = row_time(row, dataset.time_column)
        slot = (
            moment
            if gaps.exact_instant
            else pd.Timestamp(moment).floor(dataset.cadence).to_pydatetime()
        )
        members = present.setdefault(slot, set())
        if member is not None:
            members.add(str(row[member]))
    return present


def _absent_members(
    dataset: Dataset, gaps: GapPolicy, found: set[str], filters: Mapping[str, Any]
) -> list[str]:
    """Expected members missing from one slot; a narrowing member filter expects only its value."""
    if gaps.members is None:
        return []
    expected = gaps.members.expected()
    for item in dataset.filters:
        value = filters.get(item.name)
        if item.narrows_gaps and item.name == gaps.members.column and value not in (None, ""):
            expected = (str(value),)
    return [member for member in expected if member not in found]


def _latest_row(db: ExplorerDb, source: FreshnessSource) -> Row | None:
    clauses = [item.sql for item in source.pinned]
    params: dict[str, Any] = {}
    for item in source.pinned:
        params.update(item.params)
    where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
    order = sort_order(source.order or (source.source_column,))
    return db.fetch_one(
        f"SELECT {source.source_column} AS source_at, {source.ingested_column} AS ingested_at "
        f"FROM {source.table} {where}ORDER BY {order} LIMIT 1",
        params,
    )


def _latest_audit(db: ExplorerDb, header: AuditHeader) -> Row | None:
    return db.fetch_one(
        f"SELECT status, {header.ids_column} AS missing_ids FROM {header.table} "
        f"ORDER BY {sort_order(header.order)} LIMIT 1"
    )


def _audit_missing_identifiers(audit: Row | None, header: AuditHeader) -> list[str]:
    if audit is None:
        return []
    missing = [str(item) for item in json_list(audit["missing_ids"])]
    if audit["status"] == "incomplete" and not missing:
        return [header.incomplete_placeholder]
    return missing


def _compose_status(
    dataset: Dataset, as_of: datetime, latest: Row | None, missing: list[str]
) -> DatasetStatus:
    cadence_seconds = int(dataset.cadence.total_seconds())
    if latest is None:
        freshness = evaluate_freshness(
            cadence_seconds=cadence_seconds,
            as_of=as_of,
            latest_source_at=None,
            latest_ingested_at=None,
        )
        return DatasetStatus(
            id=dataset.id,
            label=dataset.label,
            availability="empty",
            freshness=freshness.state,
            completeness="unknown",
            overall=derive_overall("empty", freshness.state, "unknown"),
            href=dataset.href,
        )
    source_at = row_time(latest, "source_at")
    ingested_at = row_time(latest, "ingested_at")
    freshness = evaluate_freshness(
        cadence_seconds=cadence_seconds,
        as_of=as_of,
        latest_source_at=source_at,
        latest_ingested_at=ingested_at,
    )
    completeness = "incomplete" if missing else "complete"
    return DatasetStatus(
        id=dataset.id,
        label=dataset.label,
        availability="available",
        freshness=freshness.state,
        completeness=completeness,
        overall=derive_overall("available", freshness.state, completeness),
        latest_source_at=format_taiwan_time(source_at),
        latest_ingested_at=format_taiwan_time(ingested_at),
        ingestion_age_seconds=freshness.ingestion_age_seconds,
        source_age_seconds=freshness.source_age_seconds,
        missing_identifiers=missing,
        missing_slot_count=len(missing),
        href=dataset.href,
    )
