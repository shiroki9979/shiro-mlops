"""Declarative Data Explorer dataset definitions: one `Dataset` value per 資料集.

A dataset states its table, time column, keyset sort, filters and projection once; the
list, cursor and series seams derive their SQL, bound filters and accepted parameters
from it, so a filter declared here cannot be silently dropped by one of them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Protocol

from shiro_mlops.service.data_explorer.errors import ExplorerQueryError
from shiro_mlops.service.data_explorer.timefmt import parse_api_storage_time

if TYPE_CHECKING:
    from shiro_mlops.service.data_explorer.db import ExplorerDb
    from shiro_mlops.service.data_explorer.query import ExplorerQuery

Clauses = tuple[list[str], dict[str, Any]]
Row = dict[str, Any]
PageProjector = Callable[["ExplorerDb", "ExplorerQuery", list[Row]], list[dict[str, Any]]]
GapFinder = Callable[["ExplorerDb", "ExplorerQuery"], list[str]]


@dataclass(frozen=True, kw_only=True)
class Filter:
    """A request filter: `name` is the query parameter, the cursor key and the SQL bind name.

    `in_series` is whether the dataset's series endpoint accepts it as well as the list.
    """

    name: str
    in_series: bool = True

    def clause(self, db: ExplorerDb, value: str) -> Clauses:
        """Validate `value` and return the WHERE clauses that apply it."""
        raise NotImplementedError


@dataclass(frozen=True, kw_only=True)
class Exact(Filter):
    """Equality on the column of the same name."""

    def clause(self, db: ExplorerDb, value: str) -> Clauses:
        return [f"{self.name} = :{self.name}"], {self.name: value}


@dataclass(frozen=True, kw_only=True)
class OneOf(Exact):
    """Equality restricted to a fixed value set; other values are rejected with 422."""

    values: tuple[str, ...]

    def clause(self, db: ExplorerDb, value: str) -> Clauses:
        self.validate(value)
        return super().clause(db, value)

    def validate(self, value: str) -> None:
        if value not in self.values:
            raise ExplorerQueryError(f"{self.name} must be {_choices(self.values)}")


@dataclass(frozen=True, kw_only=True)
class InstantEquals(Filter):
    """Equality on a stored instant given as an RFC 3339 timestamp."""

    def clause(self, db: ExplorerDb, value: str) -> Clauses:
        try:
            instant = parse_api_storage_time(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ExplorerQueryError(f"{self.name} must be a valid RFC 3339 timestamp") from exc
        return [f"{self.name} = :{self.name}"], {self.name: instant}


@dataclass(frozen=True, kw_only=True)
class JsonContains(Filter):
    """Membership of one identifier in a JSON array column."""

    column: str

    def clause(self, db: ExplorerDb, value: str) -> Clauses:
        return [f"CAST({self.column} AS TEXT) LIKE :{self.name}"], {self.name: f'%"{value}"%'}


@dataclass(frozen=True, kw_only=True)
class Flag(Filter):
    """A switch read by the dataset's version resolution; it adds no SQL of its own."""

    def clause(self, db: ExplorerDb, value: str) -> Clauses:
        return [], {}


@dataclass(frozen=True)
class Pinned:
    """A clause every read of the dataset carries, such as the derived load source."""

    sql: str
    params: Mapping[str, Any]


class VersionResolver(Protocol):
    """Resolves which forecast version a list request reads when none is named."""

    def restore(self, params: dict[str, Any], cursor_filters: dict[str, Any]) -> dict[str, Any]:
        """Re-apply the version a cursor was issued for, without touching the database."""

    def pin(
        self, db: ExplorerDb, params: dict[str, Any], cursor_filters: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Return list parameters with the version to read made explicit."""


@dataclass(frozen=True, kw_only=True)
class Dataset:
    """Everything the explorer knows about one dataset.

    `sort` is the newest-first keyset; its first column is `time_column`, and every sort
    column holding an instant is in `instant_columns` so cursors carry it at microsecond
    precision. `list_columns` is the list SELECT, which must include every sort column.
    `project` turns one page of rows into response items, and `list_gaps` returns the
    window's missing slots for the list. Inconsistent declarations raise `ValueError`.
    """

    id: str
    label: str
    href: str
    # SYNC(frontend/apps/engineering-console/src/components/data-explorer/catalog.ts): maxDays and cadenceSeconds per dataset.
    cadence: timedelta
    max_days: int
    table: str
    time_column: str
    sort: tuple[str, ...]
    instant_columns: frozenset[str]
    list_columns: tuple[str, ...]
    project: PageProjector
    pinned: tuple[Pinned, ...] = ()
    filters: tuple[Filter, ...] = ()
    list_gaps: GapFinder | None = None
    resolve_version: VersionResolver | None = None

    def __post_init__(self) -> None:
        problems = _declaration_problems(self)
        if problems:
            raise ValueError(f"dataset {self.id}: {'; '.join(problems)}")

    @property
    def filter_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.filters)

    @property
    def series_filter_keys(self) -> frozenset[str]:
        return frozenset(item.name for item in self.filters if item.in_series)

    def clauses(self, db: ExplorerDb, filters: Mapping[str, Any]) -> Clauses:
        """Pinned clauses plus every declared filter present in `filters`."""
        return self._clauses(db, filters, self.filters)

    def series_clauses(self, db: ExplorerDb, filters: Mapping[str, Any]) -> Clauses:
        """Pinned clauses plus the present filters the series endpoint accepts."""
        return self._clauses(db, filters, [item for item in self.filters if item.in_series])

    def _clauses(
        self,
        db: ExplorerDb,
        filters: Mapping[str, Any],
        declared: list[Filter] | tuple[Filter, ...],
    ) -> Clauses:
        clauses = [item.sql for item in self.pinned]
        params: dict[str, Any] = {}
        for item in self.pinned:
            params.update(item.params)
        for item in declared:
            value = filters.get(item.name)
            if value in (None, ""):
                continue
            extra_clauses, extra_params = item.clause(db, str(value))
            clauses.extend(extra_clauses)
            params.update(extra_params)
        return clauses, params


def each(project_row: Callable[[Row], dict[str, Any]]) -> PageProjector:
    """Lift a per-row projection into a page projector."""

    def project(db: ExplorerDb, query: ExplorerQuery, rows: list[Row]) -> list[dict[str, Any]]:
        del db, query
        return [project_row(row) for row in rows]

    return project


def _choices(values: tuple[str, ...]) -> str:
    if len(values) == 2:
        return f"{values[0]} or {values[1]}"
    return f"one of {', '.join(values)}"


def _declaration_problems(dataset: Dataset) -> list[str]:
    problems = []
    if not dataset.sort or dataset.sort[0] != dataset.time_column:
        problems.append("sort must start with time_column")
    if dataset.time_column not in dataset.instant_columns:
        problems.append("time_column must be an instant column")
    missing = [column for column in dataset.sort if column not in dataset.list_columns]
    if missing:
        problems.append(f"list_columns must select sort columns {', '.join(missing)}")
    if len(set(dataset.filter_names)) != len(dataset.filter_names):
        problems.append("filter names must be unique")
    return problems
