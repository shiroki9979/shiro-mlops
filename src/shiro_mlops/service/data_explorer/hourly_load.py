"""Hourly electricity-load reader behind the typed ExplorerQuery seam."""

from __future__ import annotations

from typing import Any

from shiro_mlops.data.hourly_actual_load import REGIONAL_SNAPSHOT_SUM_SOURCE
from shiro_mlops.service.data_explorer.completeness import hourly_gaps
from shiro_mlops.service.data_explorer.dataset_reader import DatasetReader
from shiro_mlops.service.data_explorer.query import ExplorerQuery
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
        subject = query.filters.get("subject")
        clauses, sql_params = self.db.time_window("time", query.window)
        clauses.append("source = :source")
        sql_params["source"] = REGIONAL_SNAPSHOT_SUM_SOURCE
        if subject:
            clauses.append("subject = :subject")
            sql_params["subject"] = subject
        return clauses, sql_params

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
