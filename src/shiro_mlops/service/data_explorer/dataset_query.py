"""Read any Data Explorer dataset's list page, chart series or status from its `Dataset` definition.

Status judgement lives in `dataset_status` and gap finding in `gap_scan`.
"""

from __future__ import annotations

from datetime import datetime
from functools import cached_property
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from shiro_mlops.service.data_explorer.cursor import decode_cursor_filters
from shiro_mlops.service.data_explorer.dataset_status import judge_status
from shiro_mlops.service.data_explorer.datasets import DATASETS
from shiro_mlops.service.data_explorer.datasets.definition import Dataset, Row
from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.errors import DatabaseUnavailableError
from shiro_mlops.service.data_explorer.gap_scan import GapScan
from shiro_mlops.service.data_explorer.pagination import paginate_raw_list
from shiro_mlops.service.data_explorer.query import ExplorerQuery, reject_undeclared_list_params
from shiro_mlops.service.data_explorer.schemas import (
    ListEnvelope,
    SeriesResponse,
    StatusResponse,
)
from shiro_mlops.service.data_explorer.series import Agg, Bucket, SeriesReader, SeriesRequest
from shiro_mlops.service.data_explorer.timefmt import now_taiwan


def validate_list_request(dataset: Dataset, params: dict[str, Any]) -> dict[str, Any] | None:
    """Reject undeclared parameters, then validate the whole cursor, before any database read;
    return the filters the cursor binds."""
    reject_undeclared_list_params(dataset, params)
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
    read its bounded chart series, and report every dataset's status."""

    def __init__(self, engine: Engine) -> None:
        self.db = ExplorerDb(engine)

    def list(self, dataset: Dataset, params: dict[str, Any]) -> ListEnvelope:
        cursor_filters = validate_list_request(dataset, params)
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
                datasets=[judge_status(self.db, dataset, clock) for dataset in DATASETS.values()]
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
        if query.dataset.gaps is None:
            return []
        scan = GapScan(self.db, query.dataset, query.filters)
        return scan.due_missing_slots(query.window, now_taiwan())


class _WindowPage:
    """The request window a page projection may consult, read lazily and once per page."""

    def __init__(self, db: ExplorerDb, query: ExplorerQuery) -> None:
        self.scan = GapScan(db, query.dataset, query.filters)
        self.window = query.window

    @cached_property
    def _present(self) -> dict[datetime, set[str]]:
        return self.scan.present_members(self.window)

    def missing_members(self, slot: datetime) -> list[str]:
        return self.scan.absent_members(self._present.get(slot, set()))
