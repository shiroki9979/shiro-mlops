"""Shared keyset pagination for typed Data Explorer list queries."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from shiro_mlops.core.storage_time import to_storage_time
from shiro_mlops.service.data_explorer.cursor import CursorError, encode_cursor
from shiro_mlops.service.data_explorer.query import ExplorerQuery
from shiro_mlops.service.data_explorer.schemas import ListEnvelope
from shiro_mlops.service.data_explorer.timefmt import format_taiwan_time, parse_api_time
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
    rows = fetch_rows(query, query.cursor_key(), query.limit + 1)
    visible = rows[: query.limit]
    has_more = len(rows) > query.limit
    next_cursor = (
        encode_cursor(
            dataset=query.dataset,
            filters=query.filters,
            key=raw_cursor_key(visible[-1], query.sort_columns),
        )
        if has_more and visible
        else None
    )
    items, missing = project_page(query, visible)
    if len(items) != len(visible):
        raise ValueError(
            f"Page projection for {query.dataset} returned {len(items)} items "
            f"for {len(visible)} rows"
        )
    return ListEnvelope(
        items=items, next_cursor=next_cursor, has_more=has_more, missing_slots=missing
    )


def is_cursor_time_column(column: str) -> bool:
    """Identify sort columns whose cursor values are serialized timestamps."""
    return column in CURSOR_TIME_COLS or column.endswith("_at")


def raw_cursor_key(row: dict[str, Any], columns: tuple[str, ...]) -> dict[str, Any]:
    """Serialize full-precision sort values without using display timestamps."""
    return {
        column: (
            format_taiwan_time(to_taiwan(row[column]), timespec="microseconds")
            if is_cursor_time_column(column)
            else row[column]
        )
        for column in columns
    }


def sort_order(columns: tuple[str, ...]) -> str:
    """Build newest-first ordering from the same trusted key declaration."""
    return ", ".join(f"{column} DESC" for column in columns)


def apply_cursor(
    clauses: list[str],
    cursor: dict[str, Any] | None,
    columns: tuple[str, ...],
) -> tuple[str, dict[str, Any]]:
    """Append a newest-first keyset predicate to SQL WHERE clauses."""
    params: dict[str, Any] = {}
    if not cursor:
        return " AND ".join(clauses), params
    parts: list[str] = []
    for index, column in enumerate(columns):
        equal = " AND ".join(f"{item} = :k_{item}" for item in columns[:index])
        comparison = f"{column} < :k_{column}"
        parts.append(f"({equal} AND {comparison})" if equal else comparison)
        params[f"k_{column}"] = cursor[column]
    clauses.append("(" + " OR ".join(parts) + ")")
    return " AND ".join(clauses), params


def sql_cursor_key(key: dict[str, Any], columns: tuple[str, ...]) -> dict[str, Any]:
    """Convert a public cursor key into SQL-comparable values."""
    converted: dict[str, Any] = {}
    for column in columns:
        value = key.get(column)
        # raw_cursor_key only emits strings; anything else was not issued by this service.
        if not isinstance(value, str):
            raise CursorError("Invalid cursor key")
        try:
            converted[column] = (
                to_storage_time(parse_api_time(value)) if is_cursor_time_column(column) else value
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise CursorError("Invalid cursor key") from exc
    return converted
