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
    """Typed-query adapter reused by migrated Data Explorer dataset readers."""

    dataset: str

    def __init__(self, engine: Engine) -> None:
        self.db = ExplorerDb(engine)

    def list(self, params: dict[str, Any]) -> ListEnvelope:
        if params.get("cursor"):
            decode_cursor_filters(str(params["cursor"]), dataset=self.dataset)
        query = self.build_query(params)
        try:
            return paginate_raw_list(query, self.fetch_rows, self.project_page)
        except SQLAlchemyError as exc:
            raise DatabaseUnavailableError(str(exc)) from exc

    def build_query(self, params: dict[str, Any]) -> ExplorerQuery:
        return ExplorerQuery.from_params(self.dataset, params)

    def fetch_rows(
        self, query: ExplorerQuery, cursor: dict[str, Any] | None, limit: int
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    def project_page(
        self, query: ExplorerQuery, rows: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        raise NotImplementedError
