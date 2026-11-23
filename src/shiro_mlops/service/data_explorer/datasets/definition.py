"""Declarative Data Explorer dataset definitions: one `Dataset` value per 資料集.

A dataset states its relation, time column, keyset sort, filters, projection, gap and status
policies once; the list, cursor, series and status seams derive their SQL, bound filters,
accepted parameters and missing slots from it, so a filter declared here cannot be
silently dropped by one of them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

from shiro_mlops.service.data_explorer.errors import ExplorerQueryError
from shiro_mlops.service.data_explorer.series import SeriesOptions, series_flag_conflicts
from shiro_mlops.service.data_explorer.timefmt import parse_api_storage_time

if TYPE_CHECKING:
    from shiro_mlops.service.data_explorer.db import ExplorerDb

Clauses = tuple[list[str], dict[str, Any]]
Row = dict[str, Any]


class Page(Protocol):
    """What a page projection may read beyond its own rows."""

    def missing_members(self, slot: datetime) -> list[str]:
        """The gap members the request window holds no row for at `slot`."""


PageProjector = Callable[[Page, list[Row]], list[dict[str, Any]]]


@dataclass(frozen=True, kw_only=True)
class Filter:
    """A request filter: `name` is the query parameter, the cursor key and the SQL bind name.

    `in_series` is whether the dataset's series endpoint accepts it as well as the list.
    `narrows_gaps` is whether it also narrows the list's missing slots: only rows it keeps
    fill a slot, and on the gap members column the expected members become its value.
    """

    name: str
    in_series: bool = True
    narrows_gaps: bool = False

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


@dataclass(frozen=True)
class GapMembers:
    """Members every slot expects, such as the four regions or the allowlisted stations.

    `expected` is called per request, so a settings-backed allowlist stays current. With
    `listed`, each absent member is its own gap `<slot>:<member>`; otherwise a slot lacking
    any expected member is one gap.
    """

    column: str
    expected: Callable[[], tuple[str, ...]]
    listed: bool = False


@dataclass(frozen=True, kw_only=True)
class GapPolicy:
    """Which slots of a list window are missing: each due `cadence` slot no row fills.

    A slot is due once it has happened and `slot_lag` has passed since it started. A row
    fills the slot it falls in, or with `exact_instant` only the slot it is stamped at.
    """

    exact_instant: bool = False
    members: GapMembers | None = None
    slot_lag: timedelta = timedelta(0)


@dataclass(frozen=True, kw_only=True)
class FreshnessSource:
    """Where status reads a dataset's newest source and ingestion instants.

    `relation` is what the read selects from, as in `Dataset.relation`. `order` is the
    newest-first ordering that picks the row, `source_column` alone if empty.
    """

    relation: str
    source_column: str
    ingested_column: str = "created_at"
    order: tuple[str, ...] = ()
    pinned: tuple[Pinned, ...] = ()


@dataclass(frozen=True)
class LastCompletedHours:
    """Status completeness: the dataset's gaps over the last `hours` completed hours."""

    hours: int


@dataclass(frozen=True)
class TrailingWindow:
    """Status completeness: gaps over `span` back from the newest row, from the oldest row in it."""

    span: timedelta


@dataclass(frozen=True)
class LatestSlot:
    """Status completeness: the gap members the newest slot lacks; `incomplete_href` lists them."""

    incomplete_href: str


@dataclass(frozen=True)
class AlwaysComplete:
    """Status completeness: complete whenever rows exist, since the member count varies.

    Status also reports how many rows share the newest instant.
    """


@dataclass(frozen=True, kw_only=True)
class AuditHeader:
    """The newest audit header a dataset's completeness is read from.

    `ids_column` holds the header's missing identifiers, the only record of whether its
    batch or release is complete.
    """

    table: str
    order: tuple[str, ...]
    ids_column: str


@dataclass(frozen=True)
class LatestAudit:
    """Status completeness: the newest audit header's missing identifiers.

    `flags_stale_release` adds the serving hint that the newest release is stale.
    """

    header: AuditHeader
    flags_stale_release: bool = False


StatusPolicy = LastCompletedHours | TrailingWindow | LatestSlot | AlwaysComplete | LatestAudit


class VersionResolver(Protocol):
    """Resolves which forecast version list and series requests read when none is named."""

    def restore(self, params: dict[str, Any], cursor_filters: dict[str, Any]) -> dict[str, Any]:
        """Re-apply the version a cursor was issued for, without touching the database."""

    def pin(
        self, db: ExplorerDb, params: dict[str, Any], cursor_filters: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Return list parameters with the version to read made explicit."""

    def plan_series(
        self, db: ExplorerDb, options: SeriesOptions, params: dict[str, str]
    ) -> tuple[SeriesOptions, dict[str, str]]:
        """Return series options and parameters with the version to chart made explicit."""


@dataclass(frozen=True, kw_only=True)
class Dataset:
    """Everything the explorer knows about one dataset.

    `relation` is what every list, series and gap read selects from: a table name, or a
    parenthesised derived relation with an alias when a column is judged rather than
    stored. `sort` is the newest-first keyset; its first column is `time_column`, and every sort
    column holding an instant is in `instant_columns` so cursors carry it at microsecond
    precision. `list_columns` is the list SELECT, which must include every sort column.
    `project` turns one page of rows into response items, and `gaps` declares which slots
    the list reports missing. `status_policy` and `freshness` declare how `GET /data/status`
    judges completeness and where it reads the newest row (by default the dataset's own
    relation and time column). `series` declares the chart series endpoint, and `resolve_version`
    resolves the forecast version both list and series read. Inconsistent declarations
    raise `ValueError`.
    """

    id: str
    label: str
    href: str
    # SYNC(frontend/apps/engineering-console/src/components/data-explorer/catalog.ts): maxDays and cadenceSeconds per dataset.
    cadence: timedelta
    max_days: int
    relation: str
    time_column: str
    sort: tuple[str, ...]
    instant_columns: frozenset[str]
    list_columns: tuple[str, ...]
    project: PageProjector
    status_policy: StatusPolicy
    pinned: tuple[Pinned, ...] = ()
    filters: tuple[Filter, ...] = ()
    gaps: GapPolicy | None = None
    freshness: FreshnessSource | None = None
    series: SeriesOptions | None = None
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

    @property
    def freshness_source(self) -> FreshnessSource:
        if self.freshness is not None:
            return self.freshness
        return FreshnessSource(
            relation=self.relation, source_column=self.time_column, pinned=self.pinned
        )

    def series_clauses(self, db: ExplorerDb, filters: Mapping[str, Any]) -> Clauses:
        """Pinned clauses plus the present filters the series endpoint accepts."""
        return self._clauses(db, filters, [item for item in self.filters if item.in_series])

    def gap_clauses(self, db: ExplorerDb, filters: Mapping[str, Any]) -> Clauses:
        """Pinned clauses plus the present filters that narrow the gap scope."""
        return self._clauses(db, filters, [item for item in self.filters if item.narrows_gaps])

    def expected_gap_members(self, filters: Mapping[str, Any]) -> tuple[str, ...]:
        """Gap members each slot expects; a narrowing members filter expects only its value."""
        if self.gaps is None or self.gaps.members is None:
            return ()
        members = self.gaps.members
        for item in self.filters:
            value = filters.get(item.name)
            if item.narrows_gaps and item.name == members.column and value not in (None, ""):
                return (str(value),)
        return members.expected()

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

    def project(page: Page, rows: list[Row]) -> list[dict[str, Any]]:
        del page
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
    if dataset.gaps is None:
        problems.extend(
            f"{item.name} narrows gaps but the dataset declares no gap policy"
            for item in dataset.filters
            if item.narrows_gaps
        )
    if dataset.series is not None:
        problems.extend(series_flag_conflicts(dataset.series))
        if (
            dataset.gaps is not None
            and dataset.series.gap_fill
            and dataset.gaps.slot_lag != dataset.series.slot_lag
        ):
            problems.append("gaps and series must share slot_lag")
    return problems
