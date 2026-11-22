"""SQL access helper for Data Explorer readers and status collaborators."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.service.data_explorer.errors import DatabaseUnavailableError
from shiro_mlops.service.data_explorer.pagination import apply_cursor, sort_order
from shiro_mlops.service.data_explorer.query import TimeWindow

__all__ = ["DatabaseUnavailableError", "ExplorerDb"]

TIMESCALE_BUCKET_INTERVALS = {"1h": "1 hour", "1d": "1 day"}
# WHY-NOT(SQLITE_TAIPEI_OFFSET): SQLite has no time zone database; a fixed +8 hours is exact
# because Asia/Taipei has observed no daylight saving time since 1979.
SQLITE_TAIPEI_OFFSET = "8 hours"


class ExplorerDb:
    """Run parameterized reads against the operational TimescaleDB engine."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @property
    def dialect_name(self) -> str | None:
        return getattr(getattr(self.engine, "dialect", None), "name", None)

    def time_window(self, column: str, window: TimeWindow) -> tuple[list[str], dict[str, Any]]:
        start, end = window.as_utc()
        return [f"{column} >= :start_time", f"{column} <= :end_time"], {
            "start_time": start,
            "end_time": end,
        }

    def bucket_start(self, column: str, bucket: str) -> str:
        """SQL for the UTC start of the Taipei-aligned `1h` or `1d` bucket holding `column`."""
        if self.dialect_name != "sqlite":
            interval = TIMESCALE_BUCKET_INTERVALS[bucket]
            return f"time_bucket(INTERVAL '{interval}', {column}, 'Asia/Taipei')"
        if bucket == "1h":
            return f"strftime('%Y-%m-%d %H:00:00', {column})"
        offset = SQLITE_TAIPEI_OFFSET
        return f"datetime(date({column}, '+{offset}'), '-{offset}')"

    def page_sql(
        self, clauses: list[str], cursor: dict[str, Any] | None, sort: tuple[str, ...]
    ) -> tuple[str, str, dict[str, Any]]:
        where, params = apply_cursor(clauses, cursor, sort)
        return where, sort_order(sort), params

    def fetch(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(text(query), params or {}).mappings()]

    def fetch_one(self, query: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        rows = self.fetch(query, params)
        return rows[0] if rows else None

    def scalar(self, query: str) -> Any:
        with self.engine.connect() as conn:
            return conn.execute(text(query)).scalar()
