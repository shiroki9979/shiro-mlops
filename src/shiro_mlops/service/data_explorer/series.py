"""Bounded chart series: bucketing, point limits, and gap-fill shared by every dataset.

A dataset joins the series surface by declaring a `SeriesSpec`; field and group names
resolve only to the trusted SQL fragments in that spec, never to request strings.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

import pandas as pd
from sqlalchemy.engine import Engine

from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.errors import ExplorerQueryError
from shiro_mlops.service.data_explorer.query import TimeWindow, resolve_window
from shiro_mlops.service.data_explorer.schemas import Series, SeriesPoint, SeriesResponse
from shiro_mlops.service.data_explorer.specs import DATASET_SPECS
from shiro_mlops.service.data_explorer.timefmt import format_taiwan_time, now_taiwan
from shiro_mlops.service.data_explorer.values import to_float, to_taiwan

SERIES_MAX_DAYS = 92
MAX_POINTS_PER_SERIES = 1_200
MAX_TOTAL_POINTS = 10_000


class Bucket(StrEnum):
    """Requested time granularity; `auto` resolves to the finest one within the limits."""

    AUTO = "auto"
    RAW = "raw"
    HOUR = "1h"
    DAY = "1d"


class Agg(StrEnum):
    """Time aggregation applied inside each `1h` or `1d` bucket."""

    AVG = "avg"
    MIN = "min"
    MAX = "max"


RESOLVED_BUCKETS = (Bucket.RAW, Bucket.HOUR, Bucket.DAY)
BUCKET_FREQUENCY = {Bucket.HOUR: "h", Bucket.DAY: "D"}
COMMON_SERIES_PARAMS = frozenset({"start", "end", "fields", "bucket", "agg"})

SeriesFilters = Callable[[Mapping[str, str]], tuple[list[str], dict[str, Any]]]


@dataclass(frozen=True)
class SeriesField:
    """A whitelisted numeric column: trusted SQL expression plus display unit."""

    sql: str
    unit: str


@dataclass(frozen=True)
class SeriesSpec:
    """Everything a dataset supplies to expose a chart series endpoint.

    `filters` turns the dataset's own validated filter values into extra WHERE clauses;
    the time window, bucketing, limits and gap-fill come from this module.
    """

    dataset: str
    table: str
    time_column: str
    fields: Mapping[str, SeriesField]
    group_columns: tuple[str, ...]
    filter_keys: frozenset[str]
    filters: SeriesFilters
    gap_fill: bool = True

    @property
    def cadence(self) -> timedelta:
        return timedelta(seconds=DATASET_SPECS[self.dataset]["cadence"])


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
    """Validated series query: window, field names, bucket, aggregation, filters."""

    window: TimeWindow
    fields: tuple[str, ...]
    bucket: Bucket
    agg: Agg
    filters: Mapping[str, str]

    @classmethod
    def build(
        cls,
        spec: SeriesSpec,
        query_params: Mapping[str, str],
        *,
        fields: list[str] | None,
        bucket: Bucket,
        agg: Agg,
    ) -> SeriesRequest:
        """Reject undeclared parameters, then resolve the window under the series limit."""
        unknown = sorted(set(query_params) - COMMON_SERIES_PARAMS - spec.filter_keys)
        if unknown:
            raise ExplorerQueryError(f"unsupported series parameters: {', '.join(unknown)}")
        window = resolve_window(query_params.get("start"), query_params.get("end"), SERIES_MAX_DAYS)
        filters = {
            key: value
            for key, value in query_params.items()
            if key in spec.filter_keys and value != ""
        }
        chosen = tuple(dict.fromkeys(fields)) if fields else tuple(spec.fields)
        return cls(window=window, fields=chosen, bucket=bucket, agg=agg, filters=filters)


class SeriesReader:
    """Read one dataset's bounded series through its `SeriesSpec`."""

    def __init__(self, engine: Engine, spec: SeriesSpec) -> None:
        self.db = ExplorerDb(engine)
        self.spec = spec

    def read(self, request: SeriesRequest) -> SeriesResponse:
        where, params = self._where(request)
        keys = self._series_keys(where, params)
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
        clauses, params = self.db.time_window(self.spec.time_column, request.window)
        extra_clauses, extra_params = self.spec.filters(request.filters)
        return " AND ".join([*clauses, *extra_clauses]), {**params, **extra_params}

    def _series_keys(self, where: str, params: dict[str, Any]) -> list[tuple[str, ...]]:
        groups = self.spec.group_columns
        if not groups:
            found = self.db.fetch_one(
                f"SELECT 1 AS present FROM {self.spec.table} WHERE {where} LIMIT 1", params
            )
            return [()] if found else []
        rows = self.db.fetch(
            f"SELECT DISTINCT {', '.join(groups)} FROM {self.spec.table} WHERE {where}", params
        )
        return sorted(tuple(str(row[column]) for column in groups) for row in rows)

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
        per_series = len(expected_bucket_starts(window, bucket, self.spec.cadence))
        return per_series <= MAX_POINTS_PER_SERIES and per_series * series_count <= MAX_TOTAL_POINTS

    def _points_sql(self, request: SeriesRequest, bucket: Bucket, where: str) -> str:
        groups = list(self.spec.group_columns)
        fields = [self.spec.fields[name] for name in request.fields]
        if bucket is Bucket.RAW:
            time_sql = self.spec.time_column
            values = [f"{field.sql} AS v{index}" for index, field in enumerate(fields)]
            tail = ""
        else:
            time_sql = self.db.bucket_start(self.spec.time_column, bucket.value)
            function = request.agg.value.upper()
            values = [f"{function}({field.sql}) AS v{index}" for index, field in enumerate(fields)]
            tail = f" GROUP BY {', '.join([time_sql, *groups])}"
        selected = ", ".join([f"{time_sql} AS bucket_at", *groups, *values])
        return f"SELECT {selected} FROM {self.spec.table} WHERE {where}{tail}"

    def _assemble(
        self,
        request: SeriesRequest,
        bucket: Bucket,
        keys: list[tuple[str, ...]],
        rows: list[dict[str, Any]],
    ) -> list[Series]:
        groups = self.spec.group_columns
        by_key: dict[tuple[str, ...], list[dict[str, Any]]] = {key: [] for key in keys}
        for row in rows:
            by_key[tuple(str(row[column]) for column in groups)].append(row)
        expected = self._fill_slots(request.window, bucket)
        series = []
        for index, name in enumerate(request.fields):
            field = self.spec.fields[name]
            for key, key_rows in by_key.items():
                observed = {
                    to_taiwan(row["bucket_at"]): to_float(row[f"v{index}"]) for row in key_rows
                }
                series.append(
                    Series(
                        field=name,
                        unit=field.unit,
                        group=dict(zip(groups, key, strict=True)),
                        points=self._points(observed, expected, bucket),
                    )
                )
        return series

    def _fill_slots(self, window: TimeWindow, bucket: Bucket) -> list[datetime]:
        if not self.spec.gap_fill:
            return []
        last_due = min(window.end, now_taiwan())
        return [
            start
            for start in expected_bucket_starts(window, bucket, self.spec.cadence)
            if start <= last_due
        ]

    def _points(
        self,
        observed: dict[datetime, float | None],
        expected: list[datetime],
        bucket: Bucket,
    ) -> list[SeriesPoint]:
        covered = {self._slot_of(moment, bucket) for moment in observed}
        merged: dict[datetime, float | None] = {
            slot: None for slot in expected if slot not in covered
        }
        merged.update(observed)
        return [
            SeriesPoint(t=format_taiwan_time(moment, timespec="auto"), v=value)
            for moment, value in sorted(merged.items())
        ]

    def _slot_of(self, moment: datetime, bucket: Bucket) -> datetime:
        if bucket is not Bucket.RAW:
            return moment
        return pd.Timestamp(moment).floor(self.spec.cadence).to_pydatetime()


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
