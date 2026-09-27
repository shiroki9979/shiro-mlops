"""Shared keyset pagination for typed Data Explorer list queries."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from shiro_mlops.service.data_explorer.cursor import CursorError, encode_cursor
from shiro_mlops.service.data_explorer.query import ExplorerQuery
from shiro_mlops.service.data_explorer.schemas import ListEnvelope
from shiro_mlops.service.data_explorer.specs import DATASET_SPECS
from shiro_mlops.service.data_explorer.timefmt import format_taiwan_time, to_sql_utc
from shiro_mlops.service.data_explorer.values import to_taiwan

CURSOR_TIME_COLS = {
    "time",
    "observed_at",
    "fetched_at",
    "issued_at",
    "source_updated_at",
    "valid_from",
    "valid_to",
    "ingested_at",
}

RowFetcher = Callable[[ExplorerQuery, dict[str, Any] | None, int], list[dict[str, Any]]]
PageProjector = Callable[
    [ExplorerQuery, list[dict[str, Any]]], tuple[list[dict[str, Any]], list[str]]
]


def paginate_raw_list(
    query: ExplorerQuery, fetch_rows: RowFetcher, project_page: PageProjector
) -> ListEnvelope:
    """Take the cursor from the last visible database row before display projection."""
    sort = DATASET_SPECS[query.dataset]["sort"]
    rows = fetch_rows(query, query.cursor_key(), query.limit + 1)
    visible = rows[: query.limit]
    has_more = len(rows) > query.limit
    next_cursor = (
        encode_cursor(
            dataset=query.dataset,
            filters=query.filters,
            key=raw_cursor_key(visible[-1], sort),
        )
        if has_more and visible
        else None
    )
    items, missing = project_page(query, visible)
    if len(items) != len(visible):
        raise ValueError("Page projection changed row count")
    return ListEnvelope(
        items=items, next_cursor=next_cursor, has_more=has_more, missing_slots=missing
    )


def raw_cursor_key(row: dict[str, Any], columns: tuple[str, ...]) -> dict[str, Any]:
    """Serialize full-precision sort values without using display timestamps."""
    return {
        column: (
            format_taiwan_time(to_taiwan(row[column]), timespec="microseconds")
            if column in CURSOR_TIME_COLS or column.endswith("_at")
            else row[column]
        )
        for column in columns
    }


def sort_order(columns: tuple[str, ...], dialect_name: str | None = None) -> str:
    """Build newest-first ordering from the same trusted key declaration."""
    return ", ".join(f"{_cursor_operand(column, column, dialect_name)} DESC" for column in columns)


def apply_cursor(
    clauses: list[str],
    cursor: dict[str, Any] | None,
    columns: tuple[str, ...],
    *,
    dialect_name: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Append a newest-first keyset predicate to SQL WHERE clauses."""
    params: dict[str, Any] = {}
    if not cursor:
        return " AND ".join(clauses), params
    parts: list[str] = []
    for index, column in enumerate(columns):
        equal = " AND ".join(
            f"{_cursor_operand(item, item, dialect_name)} = "
            f"{_cursor_operand(f':k_{item}', item, dialect_name)}"
            for item in columns[:index]
        )
        comparison = (
            f"{_cursor_operand(column, column, dialect_name)} < "
            f"{_cursor_operand(f':k_{column}', column, dialect_name)}"
        )
        parts.append(f"({equal} AND {comparison})" if equal else comparison)
        params[f"k_{column}"] = cursor[column]
    clauses.append("(" + " OR ".join(parts) + ")")
    return " AND ".join(clauses), params


def _cursor_operand(value: str, column: str, dialect_name: str | None) -> str:
    """Normalize SQLite UTC timestamps before keyset comparison."""
    is_time = column in CURSOR_TIME_COLS or column.endswith("_at")
    return sqlite_time_key(value) if dialect_name == "sqlite" and is_time else value


def sqlite_time_key(value: str) -> str:
    """Compare UTC strings at six-digit precision across aware and naive SQLite rows."""
    return (
        f"(strftime('%Y-%m-%d %H:%M:%S', {value}) || '.' || "
        f"substr((CASE WHEN substr({value}, 20, 1) = '.' "
        f"THEN substr({value}, 21, 6) ELSE '' END) || '000000', 1, 6))"
    )


def sql_cursor_key(key: dict[str, Any], columns: tuple[str, ...]) -> dict[str, Any]:
    """Convert a public cursor key into SQL-comparable values."""
    converted: dict[str, Any] = {}
    for column in columns:
        if column not in key or key[column] is None:
            raise CursorError("Invalid cursor key")
        value = key[column]
        is_time = column in CURSOR_TIME_COLS or column.endswith("_at")
        if not is_time and not isinstance(value, str):
            raise CursorError("Invalid cursor key")
        try:
            converted[column] = to_sql_utc(value) if is_time else value
        except (TypeError, ValueError, OverflowError) as exc:
            raise CursorError("Invalid cursor key") from exc
    return converted
