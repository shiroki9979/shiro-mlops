"""Shared list pipeline that binds an ExplorerQuery to a dataset page fetcher."""

from __future__ import annotations

from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from shiro_mlops.service.data_explorer.cursor import decode_cursor_filters
from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.errors import DatabaseUnavailableError
from shiro_mlops.service.data_explorer.pagination import paginate_raw_list
from shiro_mlops.service.data_explorer.query import ExplorerQuery
from shiro_mlops.service.data_explorer.schemas import ListEnvelope


class DatasetReader:
    """Typed-query adapter reused by every Data Explorer dataset reader."""

    dataset: str
    # Trusted SELECT template; {where} and {order} come from filters() and the sort spec.
    select_sql: str

    def __init__(self, engine: Engine) -> None:
        self.db = ExplorerDb(engine)

    def list(self, params: dict[str, Any]) -> ListEnvelope:
        cursor_filters = self.validate_cursor_request(params)
        query = self.build_query(params, cursor_filters)
        try:
            return paginate_raw_list(query, self.fetch_rows, self.project_page)
        except SQLAlchemyError as exc:
            raise DatabaseUnavailableError(str(exc)) from exc

    @classmethod
    def validate_cursor_request(cls, params: dict[str, Any]) -> dict[str, Any] | None:
        """Validate the complete cursor before repository initialization or reads."""
        cursor = params.get("cursor")
        if not cursor:
            return None
        cursor_filters = decode_cursor_filters(str(cursor), dataset=cls.dataset)
        query_params = cls.cursor_query_params(params, cursor_filters)
        query = ExplorerQuery.from_params(cls.dataset, query_params, cursor_filters=cursor_filters)
        query.cursor_key()
        return cursor_filters

    @classmethod
    def cursor_query_params(
        cls, params: dict[str, Any], cursor_filters: dict[str, Any]
    ) -> dict[str, Any]:
        return params

    def build_query(
        self, params: dict[str, Any], cursor_filters: dict[str, Any] | None
    ) -> ExplorerQuery:
        return ExplorerQuery.from_params(self.dataset, params, cursor_filters=cursor_filters)

    def fetch_rows(
        self, query: ExplorerQuery, cursor: dict[str, Any] | None, limit: int
    ) -> list[dict[str, Any]]:
        clauses, params = self.filters(query)
        where, order, cursor_params = self.db.page_sql(clauses, cursor, query.sort_columns)
        sql = self.select_sql.format(where=where, order=order)
        return self.db.fetch(sql, {**params, **cursor_params, "limit": limit})

    def filters(self, query: ExplorerQuery) -> tuple[list[str], dict[str, Any]]:
        raise NotImplementedError

    def project_page(
        self, query: ExplorerQuery, rows: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        raise NotImplementedError
