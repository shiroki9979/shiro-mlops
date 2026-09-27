"""SQL access helper for Data Explorer readers and status collaborators."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.service.data_explorer.errors import DatabaseUnavailableError
from shiro_mlops.service.data_explorer.pagination import apply_cursor, sort_order, sqlite_time_key
from shiro_mlops.service.data_explorer.query import ExplorerQuery, TimeWindow
from shiro_mlops.service.data_explorer.specs import DATASET_SPECS

__all__ = ["DatabaseUnavailableError", "ExplorerDb"]


class ExplorerDb:
    """Run parameterized reads against the operational TimescaleDB engine."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def time_operand(self, value: str) -> str:
        dialect = getattr(getattr(self.engine, "dialect", None), "name", None)
        return sqlite_time_key(value) if dialect == "sqlite" else value

    def time_window(self, column: str, window: TimeWindow) -> tuple[list[str], dict[str, Any]]:
        start, end = window.as_utc()
        operand = self.time_operand(column)
        return [
            f"{operand} >= {self.time_operand(':start_time')}",
            f"{operand} <= {self.time_operand(':end_time')}",
        ], {"start_time": start, "end_time": end}

    def time_equals(self, column: str, parameter: str) -> str:
        return f"{self.time_operand(column)} = {self.time_operand(':' + parameter)}"

    def page_sql(
        self, query: ExplorerQuery, clauses: list[str], cursor: dict[str, Any] | None
    ) -> tuple[str, str, dict[str, Any]]:
        sort = DATASET_SPECS[query.dataset]["sort"]
        dialect = getattr(getattr(self.engine, "dialect", None), "name", None)
        where, params = apply_cursor(clauses, cursor, sort, dialect_name=dialect)
        return where, sort_order(sort, dialect), params

    def fetch(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(text(query), params or {}).mappings()]

    def fetch_one(self, query: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        rows = self.fetch(query, params)
        return rows[0] if rows else None

    def scalar(self, query: str) -> Any:
        with self.engine.connect() as conn:
            return conn.execute(text(query)).scalar()
