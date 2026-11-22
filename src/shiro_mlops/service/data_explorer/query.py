"""Typed list query for Data Explorer datasets."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from shiro_mlops.core.storage_time import to_storage_time
from shiro_mlops.service.data_explorer.cursor import (
    CursorError,
    decode_cursor,
    decode_cursor_filters,
)
from shiro_mlops.service.data_explorer.errors import ExplorerQueryError
from shiro_mlops.service.data_explorer.timefmt import (
    format_taiwan_time,
    now_taiwan,
    parse_api_time,
)

if TYPE_CHECKING:
    from shiro_mlops.service.data_explorer.datasets.definition import Dataset

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
WINDOW_PARAMS = frozenset({"start", "end"})
COMMON_LIST_PARAMS = WINDOW_PARAMS | {"limit", "cursor"}


@dataclass(frozen=True)
class TimeWindow:
    """Inclusive Taiwan-local query window."""

    start: datetime
    end: datetime

    def as_utc(self) -> tuple[datetime, datetime]:
        return to_storage_time(self.start), to_storage_time(self.end)


@dataclass(frozen=True)
class ExplorerQuery:
    """Window, dataset filters, page size, and opaque cursor for one list request."""

    dataset: Dataset
    window: TimeWindow
    filters: dict[str, Any]
    limit: int
    cursor: str | None

    @classmethod
    def from_params(
        cls,
        dataset: Dataset,
        params: Mapping[str, Any],
        *,
        cursor_filters: Mapping[str, Any] | None = None,
    ) -> ExplorerQuery:
        """Build a typed query from HTTP parameters and already-decoded cursor filters."""
        cursor = params.get("cursor")
        start, end = params.get("start"), params.get("end")
        if cursor not in (None, "") and (start is None or end is None):
            if cursor_filters is None:
                cursor_filters = decode_cursor_filters(str(cursor), dataset=dataset.id)
            try:
                cursor_window = resolve_window(
                    cursor_filters["start"], cursor_filters["end"], dataset.max_days
                )
            except (KeyError, ExplorerQueryError) as exc:
                raise CursorError("Invalid cursor window") from exc
            start = start if start is not None else cursor_window.start
            end = end if end is not None else cursor_window.end
        window = resolve_window(start, end, dataset.max_days)
        limit = resolve_limit(params.get("limit"))
        filters = bound_filters(dataset, dict(params), window)
        if cursor in (None, ""):
            cursor = None
        return cls(
            dataset=dataset,
            window=window,
            filters=filters,
            limit=limit,
            cursor=None if cursor is None else str(cursor),
        )

    @property
    def sort_columns(self) -> tuple[str, ...]:
        """Newest-first keyset columns declared once per dataset."""
        return self.dataset.sort

    def cursor_key(self) -> dict[str, Any] | None:
        """Decode the opaque cursor against this query's bound filters and sort key."""
        if self.cursor is None:
            return None
        from shiro_mlops.service.data_explorer.pagination import sql_cursor_key

        raw_key = decode_cursor(self.cursor, dataset=self.dataset.id, filters=self.filters)
        return sql_cursor_key(raw_key, self.sort_columns, self.dataset.instant_columns)


def resolve_window(
    start: str | datetime | None, end: str | datetime | None, max_days: int
) -> TimeWindow:
    """Require a bounded window and reject ranges that exceed the dataset maximum."""
    clock = now_taiwan()
    try:
        parsed_end = parse_api_time(end) if end is not None else clock
        parsed_start = (
            parse_api_time(start) if start is not None else parsed_end - timedelta(hours=24)
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ExplorerQueryError("start and end must be valid RFC 3339 timestamps") from exc
    if parsed_start > parsed_end:
        raise ExplorerQueryError("start must be earlier than or equal to end")
    if parsed_end - parsed_start > timedelta(days=max_days):
        raise ExplorerQueryError(f"time range cannot exceed {max_days} days")
    return TimeWindow(parsed_start, parsed_end)


def resolve_limit(limit: int | str | None) -> int:
    """Clamp page size to the shared default and maximum."""
    if limit is None or limit == "":
        return DEFAULT_LIMIT
    try:
        parsed = int(limit)
    except (TypeError, ValueError) as exc:
        raise ExplorerQueryError("limit must be an integer") from exc
    if parsed < 1 or parsed > MAX_LIMIT:
        raise ExplorerQueryError(f"limit must be between 1 and {MAX_LIMIT}")
    return parsed


def list_request_params(dataset: Dataset) -> frozenset[str]:
    """Every query parameter the dataset's list endpoint accepts."""
    return COMMON_LIST_PARAMS | frozenset(dataset.filter_names)


def declared_params(
    query: Mapping[str, str], accepted: Collection[str], endpoint: str
) -> dict[str, str]:
    """Reject every parameter outside `accepted`, even one sent empty, then drop the empty
    values: an empty declared parameter reads as not given."""
    unknown = sorted(set(query) - set(accepted))
    if unknown:
        raise ExplorerQueryError(f"unsupported {endpoint} parameters: {', '.join(unknown)}")
    return {key: value for key, value in query.items() if value != ""}


def list_params(dataset: Dataset, query: Mapping[str, str]) -> dict[str, str]:
    """The list request's non-empty parameters, once every one is declared for its list."""
    return declared_params(query, list_request_params(dataset), "list")


def bound_filters(dataset: Dataset, params: dict[str, Any], window: TimeWindow) -> dict[str, Any]:
    """Canonical filter payload stored inside a keyset cursor: the window and every filter
    the dataset declares, so a declared filter is always bound and an undeclared one never is.
    """
    filters = {
        "start": format_taiwan_time(window.start, timespec="auto"),
        "end": format_taiwan_time(window.end, timespec="auto"),
    }
    for key in dataset.filter_names:
        value = params.get(key)
        if value not in (None, ""):
            filters[key] = str(value)
    filters["dataset"] = dataset.id
    return filters
