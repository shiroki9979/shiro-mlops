"""Hourly electricity-load reader behind the typed ExplorerQuery seam."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from shiro_mlops.data.hourly_actual_load import REGIONAL_SNAPSHOT_SUM_SOURCE
from shiro_mlops.service.data_explorer.completeness import hourly_gaps
from shiro_mlops.service.data_explorer.dataset_reader import DatasetReader
from shiro_mlops.service.data_explorer.query import ExplorerQuery
from shiro_mlops.service.data_explorer.series import SeriesField, SeriesSpec
from shiro_mlops.service.data_explorer.timefmt import format_taiwan_time
from shiro_mlops.service.data_explorer.values import to_taiwan


class HourlyLoadReader(DatasetReader):
    """List persisted hourly load rows newest first."""

    dataset = "hourly_load"
    select_sql = """
        SELECT time, subject, load_mw, created_at
        FROM raw_taipower_load
        WHERE {where}
        ORDER BY {order}
        LIMIT :limit
    """

    def filters(self, query: ExplorerQuery) -> tuple[list[str], dict[str, Any]]:
        clauses, sql_params = self.db.time_window("time", query.window)
        load_clauses, load_params = hourly_load_filters(query.filters)
        return [*clauses, *load_clauses], {**sql_params, **load_params}

    def project_page(
        self, query: ExplorerQuery, rows: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        items = []
        for row in rows:
            observed = to_taiwan(row["time"])
            ingested = to_taiwan(row["created_at"])
            items.append(
                {
                    "datetime": format_taiwan_time(observed),
                    "subject": row["subject"],
                    "load_mw": float(row["load_mw"]),
                    "ingested_at": format_taiwan_time(ingested),
                }
            )
        return items, hourly_gaps(self.db, query.window, query.filters.get("subject"))


def hourly_load_filters(filters: Mapping[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """Pin the derived regional-sum source and apply the optional subject filter."""
    clauses = ["source = :source"]
    params: dict[str, Any] = {"source": REGIONAL_SNAPSHOT_SUM_SOURCE}
    subject = filters.get("subject")
    if subject:
        clauses.append("subject = :subject")
        params["subject"] = subject
    return clauses, params


class HourlyLoadSeriesField(StrEnum):
    """Hourly load fields a series request may name."""

    LOAD_MW = "load_mw"


HOURLY_LOAD_SERIES = SeriesSpec(
    dataset="hourly_load",
    table="raw_taipower_load",
    time_column="time",
    fields={HourlyLoadSeriesField.LOAD_MW.value: SeriesField(sql="load_mw", unit="MW")},
    group_columns=("subject",),
    filter_keys=frozenset({"subject"}),
    filters=hourly_load_filters,
)
