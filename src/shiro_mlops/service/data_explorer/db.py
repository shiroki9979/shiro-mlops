"""SQL access helper for Data Explorer readers and status collaborators."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.service.data_explorer.errors import DatabaseUnavailableError

__all__ = ["DatabaseUnavailableError", "ExplorerDb"]


class ExplorerDb:
    """Run parameterized reads against the operational TimescaleDB engine."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def fetch(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(text(query), params or {}).mappings()]

    def latest_row(self, query: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        rows = self.fetch(query, params)
        return rows[0] if rows else None

    def scalar(self, query: str) -> Any:
        with self.engine.connect() as conn:
            return conn.execute(text(query)).scalar()
