"""Read any Data Explorer dataset's list page or chart series from its `Dataset` definition."""

from __future__ import annotations

from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from shiro_mlops.service.data_explorer.cursor import decode_cursor_filters
from shiro_mlops.service.data_explorer.datasets.definition import Dataset, Row
from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.errors import DatabaseUnavailableError
from shiro_mlops.service.data_explorer.pagination import paginate_raw_list
from shiro_mlops.service.data_explorer.query import ExplorerQuery
from shiro_mlops.service.data_explorer.schemas import ListEnvelope, SeriesResponse
from shiro_mlops.service.data_explorer.series import Agg, Bucket, SeriesReader, SeriesRequest


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
    and read its bounded chart series."""

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
        dataset = query.dataset
        items = dataset.project(self.db, query, rows)
        gaps = dataset.list_gaps(self.db, query) if dataset.list_gaps is not None else []
        return items, gaps
