"""Bounded chart series: bucketing, point limits, and gap-fill shared by every dataset.

A dataset joins the series surface by declaring `SeriesOptions` on its `Dataset`; field
and group names resolve only to the trusted SQL fragments declared there, never to request
strings. Table, time column, cadence and accepted filters come from the `Dataset` itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import pandas as pd

from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.errors import ExplorerQueryError
from shiro_mlops.service.data_explorer.query import (
    WINDOW_PARAMS,
    TimeWindow,
    declared_params,
    resolve_window,
)
from shiro_mlops.service.data_explorer.schemas import Series, SeriesPoint, SeriesResponse
from shiro_mlops.service.data_explorer.timefmt import format_taiwan_time, now_taiwan
from shiro_mlops.service.data_explorer.values import format_row_time, row_time, to_float

if TYPE_CHECKING:
    from shiro_mlops.service.data_explorer.datasets.definition import Dataset

SERIES_MAX_DAYS = 92
MAX_POINTS_PER_SERIES = 1_200
MAX_TOTAL_POINTS = 10_000


# SYNC(frontend/apps/engineering-console/src/schemas/data-explorer.ts): BucketSchema, default first.
class Bucket(StrEnum):
    """Requested time granularity; `auto` resolves to the finest one within the limits."""

    AUTO = "auto"
    RAW = "raw"
    HOUR = "1h"
    DAY = "1d"


# SYNC(frontend/apps/engineering-console/src/schemas/data-explorer.ts): AggSchema, default first.
class Agg(StrEnum):
    """Time aggregation applied inside each `1h` or `1d` bucket."""

    AVG = "avg"
    MIN = "min"
    MAX = "max"


RESOLVED_BUCKETS = (Bucket.RAW, Bucket.HOUR, Bucket.DAY)
BUCKET_FREQUENCY = {Bucket.HOUR: "h", Bucket.DAY: "D"}
COMMON_SERIES_PARAMS = WINDOW_PARAMS | {"fields", "bucket", "agg"}
COUNT_SERIES_PARAMS = COMMON_SERIES_PARAMS - {"fields", "agg"}
GROUP_BY_PARAM = "group_by"

SeriesFilters = Callable[[ExplorerDb, Mapping[str, str]], tuple[list[str], dict[str, Any]]]


@dataclass(frozen=True)
class SeriesField:
    """A whitelisted numeric column: trusted SQL expression plus display unit."""

    sql: str
    unit: str


@dataclass(frozen=True)
class SeriesOptions:
    """How a dataset's rows become chart series; the rest comes from its `Dataset`.

    `filters` replaces the dataset's own filter clauses only where a request plan needs a
    different reading (the forecast version). The time window, bucketing, limits and
    gap-fill come from this module. `slot_lag` is how long after its timestamp a slot is
    expected to exist (an hourly load row labels the hour it summarises, so it is due only
    once that hour has ended).

    `count_rows` makes each value the number of rows in the bucket instead of a time
    aggregate of a field: `fields` and `agg` are then not request parameters, the response
    `agg` is null, and `raw` yields one point of value 1 per row, even when rows share an
    instant (CWA forecast versions share `issued_at`).

    `member_sum` first adds every member row sharing a timestamp and group (SQL `SUM`,
    which skips NULL) and only then applies the time aggregation; only additive power
    fields may set it. `group_options` maps each selectable `group_by` value to its group
    columns; without options the dataset's grouping is fixed to `group_columns`.
    `default_fields` names the fields charted when a request names none (all if empty).

    Without `gap_fill` a series carries only points that have a value, and a series with
    none is left out. `instant_group_columns` are group columns holding instants, reported
    as RFC 3339 +08:00 like point times. `rows_share_time` marks datasets where one series
    may hold several rows at a timestamp, each carrying a different subset of the fields;
    `raw` then keeps each field's value. Contradictory flags make the `Dataset` declaring
    them raise `ValueError` (see `series_flag_conflicts`).
    """

    fields: Mapping[str, SeriesField]
    group_columns: tuple[str, ...]
    filters: SeriesFilters | None = None
    gap_fill: bool = True
    slot_lag: timedelta = timedelta(0)
    count_rows: bool = False
    member_sum: bool = False
    default_fields: tuple[str, ...] = ()
    # WHY-NOT(group_options): a plain MappingProxyType default fails on Python 3.11, the CI and
    # container runtime, which treats a mappingproxy dataclass default as mutable.
    group_options: Mapping[str, tuple[str, ...]] = dataclass_field(
        default_factory=lambda: MappingProxyType({})
    )
    instant_group_columns: frozenset[str] = frozenset()
    rows_share_time: bool = False


def series_flag_conflicts(options: SeriesOptions) -> list[str]:
    """Flag combinations whose series would have no defined meaning."""
    conflicts = []
    if options.count_rows and options.member_sum:
        conflicts.append("count_rows counts rows, so it cannot sum members first")
    if options.count_rows and options.gap_fill:
        conflicts.append("count_rows cannot gap-fill: an empty bucket would read as null, not 0")
    if options.rows_share_time and (options.count_rows or options.member_sum):
        conflicts.append(
            "rows_share_time merges rows sharing a timestamp, which counting must not do "
            "and a member sum already does"
        )
    return conflicts


def series_request_params(dataset: Dataset, options: SeriesOptions) -> frozenset[str]:
    """Every query parameter the dataset's series endpoint accepts."""
    common = COUNT_SERIES_PARAMS if options.count_rows else COMMON_SERIES_PARAMS
    grouping = {GROUP_BY_PARAM} if options.group_options else set()
    return common | dataset.series_filter_keys | grouping


def series_params(
    dataset: Dataset, options: SeriesOptions, query: Mapping[str, str]
) -> dict[str, str]:
    """The series request's non-empty parameters, once every one is declared for its series."""
    return declared_params(query, series_request_params(dataset, options), "series")


class TooManyPointsError(ExplorerQueryError):
    """Raised when an explicit bucket exceeds the per-series or total point limit."""

    def __init__(self, bucket: Bucket, suggested_bucket: Bucket | None) -> None:
        super().__init__(
            f"bucket {bucket.value} exceeds {MAX_POINTS_PER_SERIES} points per series "
            f"or {MAX_TOTAL_POINTS} points in total"
        )
        self.suggested_bucket = suggested_bucket


@dataclass(frozen=True)
class SeriesRequest:
    """Validated series query: window, field names, grouping, bucket, aggregation, filters.

    `agg` is None exactly when the options count rows, whose buckets hold counts instead.
    """

    window: TimeWindow
    fields: tuple[str, ...]
    bucket: Bucket
    agg: Agg | None
    filters: Mapping[str, str]
    group_columns: tuple[str, ...]

    @classmethod
    def build(
        cls,
        dataset: Dataset,
        options: SeriesOptions,
        query_params: Mapping[str, str],
        *,
        fields: list[str] | None,
        bucket: Bucket,
        agg: Agg | None = None,
    ) -> SeriesRequest:
        """Resolve the window under the series limit from parameters `series_params` declared."""
        window = resolve_window(query_params.get("start"), query_params.get("end"), SERIES_MAX_DAYS)
        accepted = dataset.series_filter_keys
        filters = {key: value for key, value in query_params.items() if key in accepted}
        chosen = (
            tuple(dict.fromkeys(fields))
            if fields
            else options.default_fields or tuple(options.fields)
        )
        return cls(
            window=window,
            fields=chosen,
            bucket=bucket,
            agg=None if options.count_rows else agg or Agg.AVG,
            filters=filters,
            group_columns=_group_columns(options, query_params.get(GROUP_BY_PARAM)),
        )


def _group_columns(options: SeriesOptions, group_by: str | None) -> tuple[str, ...]:
    if group_by is None:
        return options.group_columns
    if group_by not in options.group_options:
        raise ExplorerQueryError(f"group_by must be one of {', '.join(options.group_options)}")
    return options.group_options[group_by]


class SeriesReader:
    """Read one dataset's bounded series through its `SeriesOptions`."""

    def __init__(self, db: ExplorerDb, dataset: Dataset, options: SeriesOptions) -> None:
        self.db = db
        self.dataset = dataset
        self.options = options

    def read(self, request: SeriesRequest) -> SeriesResponse:
        where, params = self._where(request)
        keys = self._series_keys(request.group_columns, where, params)
        bucket = self._resolve_bucket(request, series_count=len(keys) * len(request.fields))
        agg = None if bucket is Bucket.RAW else request.agg
        if not keys:
            return SeriesResponse(bucket=bucket, agg=agg, series=[])
        rows = self.db.fetch(self._points_sql(request, bucket, where), params)
        return SeriesResponse(
            bucket=bucket,
            agg=agg,
            series=self._assemble(request, bucket, keys, rows),
        )

    def _where(self, request: SeriesRequest) -> tuple[str, dict[str, Any]]:
        clauses, params = self.db.time_window(self.dataset.time_column, request.window)
        extra_clauses, extra_params = self._filter_clauses(request.filters)
        return " AND ".join([*clauses, *extra_clauses]), {**params, **extra_params}

    def _filter_clauses(self, filters: Mapping[str, str]) -> tuple[list[str], dict[str, Any]]:
        if self.options.filters is not None:
            return self.options.filters(self.db, filters)
        return self.dataset.series_clauses(self.db, filters)

    def _series_keys(
        self, groups: tuple[str, ...], where: str, params: dict[str, Any]
    ) -> list[tuple[str, ...]]:
        if not groups:
            found = self.db.fetch_one(
                f"SELECT 1 AS present FROM {self.dataset.table} WHERE {where} LIMIT 1", params
            )
            return [()] if found else []
        rows = self.db.fetch(
            f"SELECT DISTINCT {', '.join(groups)} FROM {self.dataset.table} WHERE {where}", params
        )
        return sorted({self._group_key(row, groups) for row in rows})

    def _group_key(self, row: dict[str, Any], groups: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            format_row_time(row, column, timespec="auto")
            if column in self.options.instant_group_columns
            else str(row[column])
            for column in groups
        )

    def _resolve_bucket(self, request: SeriesRequest, *, series_count: int) -> Bucket:
        fitting = [
            bucket
            for bucket in RESOLVED_BUCKETS
            if self._fits(request.window, bucket, max(series_count, 1))
        ]
        finest = fitting[0] if fitting else None
        if request.bucket is Bucket.AUTO and finest is not None:
            return finest
        if request.bucket not in fitting:
            raise TooManyPointsError(request.bucket, finest)
        return request.bucket

    def _fits(self, window: TimeWindow, bucket: Bucket, series_count: int) -> bool:
        per_series = len(expected_bucket_starts(window, bucket, self.dataset.cadence))
        return per_series <= MAX_POINTS_PER_SERIES and per_series * series_count <= MAX_TOTAL_POINTS

    def _points_sql(self, request: SeriesRequest, bucket: Bucket, where: str) -> str:
        groups = list(request.group_columns)
        source, value_sql = self._source(request, where)
        if bucket is Bucket.RAW and self.options.rows_share_time:
            time_sql = self.dataset.time_column
            values = [f"MAX({sql}) AS v{index}" for index, sql in enumerate(value_sql)]
            tail = f" GROUP BY {', '.join([time_sql, *groups])}"
        elif bucket is Bucket.RAW:
            time_sql = self.dataset.time_column
            values = [f"{sql} AS v{index}" for index, sql in enumerate(value_sql)]
            tail = ""
        else:
            time_sql = self.db.bucket_start(self.dataset.time_column, bucket.value)
            function = "COUNT" if request.agg is None else request.agg.value.upper()
            values = [f"{function}({sql}) AS v{index}" for index, sql in enumerate(value_sql)]
            tail = f" GROUP BY {', '.join([time_sql, *groups])}"
        selected = ", ".join([f"{time_sql} AS bucket_at", *groups, *values])
        return f"SELECT {selected} FROM {source}{tail}"

    def _source(self, request: SeriesRequest, where: str) -> tuple[str, list[str]]:
        """Relation the buckets read from, and the value expression of each field in it.

        With `member_sum` it is the per-timestamp, per-group member total, so the time
        aggregation runs over those totals rather than over individual members.
        """
        fields = [self.options.fields[name] for name in request.fields]
        if not self.options.member_sum:
            return f"{self.dataset.table} WHERE {where}", [item.sql for item in fields]
        keys = ", ".join([self.dataset.time_column, *request.group_columns])
        sums = ", ".join(f"SUM({item.sql}) AS m{index}" for index, item in enumerate(fields))
        members = f"SELECT {keys}, {sums} FROM {self.dataset.table} WHERE {where} GROUP BY {keys}"
        return f"({members}) AS members", [f"m{index}" for index in range(len(fields))]

    def _assemble(
        self,
        request: SeriesRequest,
        bucket: Bucket,
        keys: list[tuple[str, ...]],
        rows: list[dict[str, Any]],
    ) -> list[Series]:
        groups = request.group_columns
        by_key: dict[tuple[str, ...], list[dict[str, Any]]] = {key: [] for key in keys}
        for row in rows:
            by_key[self._group_key(row, groups)].append(row)
        expected = self._fill_slots(request.window, bucket)
        series = []
        for index, name in enumerate(request.fields):
            field = self.options.fields[name]
            for key, key_rows in by_key.items():
                observed = [
                    (
                        row_time(row, "bucket_at"),
                        to_float(row[f"v{index}"]),
                    )
                    for row in key_rows
                ]
                points = self._points(observed, expected, bucket)
                if not points:
                    continue
                series.append(
                    Series(
                        field=name,
                        unit=field.unit,
                        group=dict(zip(groups, key, strict=True)),
                        points=points,
                    )
                )
        return series

    def _fill_slots(self, window: TimeWindow, bucket: Bucket) -> list[datetime]:
        if not self.options.gap_fill:
            return []
        last_due = min(window.end, now_taiwan() - self.options.slot_lag)
        return [
            start
            for start in expected_bucket_starts(window, bucket, self.dataset.cadence)
            if start <= last_due
        ]

    def _points(
        self,
        observed: list[tuple[datetime, float | None]],
        expected: list[datetime],
        bucket: Bucket,
    ) -> list[SeriesPoint]:
        if not self.options.gap_fill:
            return _as_points([(moment, value) for moment, value in observed if value is not None])
        covered = {self._slot_of(moment, bucket) for moment, _value in observed}
        missing = [(slot, None) for slot in expected if slot not in covered]
        return _as_points([*missing, *observed])

    def _slot_of(self, moment: datetime, bucket: Bucket) -> datetime:
        if bucket is not Bucket.RAW:
            return moment
        return pd.Timestamp(moment).floor(self.dataset.cadence).to_pydatetime()


def _as_points(values: list[tuple[datetime, float | None]]) -> list[SeriesPoint]:
    return [
        SeriesPoint(t=format_taiwan_time(moment, timespec="auto"), v=value)
        for moment, value in sorted(values, key=lambda point: point[0])
    ]


def expected_bucket_starts(
    window: TimeWindow, bucket: Bucket, cadence: timedelta
) -> list[datetime]:
    """Every bucket start a fixed-cadence dataset should produce inside the window.

    `raw` follows the dataset cadence from the first slot at or after `start`; `1h` and
    `1d` start at the bucket containing `start`, so partial edge buckets are included.
    """
    start = pd.Timestamp(window.start)
    if bucket is Bucket.RAW:
        first, frequency = start.ceil(cadence), pd.Timedelta(cadence)
    else:
        frequency = BUCKET_FREQUENCY[bucket]
        first = start.floor(frequency)
    return [ts.to_pydatetime() for ts in pd.date_range(first, window.end, freq=frequency)]
