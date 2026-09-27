"""Hourly electricity-load reader behind the typed ExplorerQuery seam."""

from __future__ import annotations

from typing import Any

from shiro_mlops.data.hourly_actual_load import REGIONAL_SNAPSHOT_SUM_SOURCE
from shiro_mlops.service.data_explorer.completeness import hourly_gaps
from shiro_mlops.service.data_explorer.dataset_reader import DatasetReader
from shiro_mlops.service.data_explorer.pagination import apply_cursor
from shiro_mlops.service.data_explorer.query import ExplorerQuery
from shiro_mlops.service.data_explorer.timefmt import format_taiwan_time
from shiro_mlops.service.data_explorer.values import to_taiwan


class HourlyLoadReader(DatasetReader):
    """List persisted hourly load rows newest first."""

    dataset = "hourly_load"

    def fetch_page(
        self,
        query: ExplorerQuery,
        cursor: dict[str, Any] | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        subject = query.filters.get("subject")
        clauses = ["time >= :start_time", "time <= :end_time", "source = :source"]
        sql_params: dict[str, Any] = {
            "start_time": query.window.as_utc()[0],
            "end_time": query.window.as_utc()[1],
            "source": REGIONAL_SNAPSHOT_SUM_SOURCE,
        }
        if subject:
            clauses.append("subject = :subject")
            sql_params["subject"] = subject
        where, cursor_params = apply_cursor(clauses, cursor, ("time", "subject"))
        sql_params.update(cursor_params)
        sql = f"""
            SELECT time, subject, load_mw, created_at
            FROM raw_taipower_load
            WHERE {where}
            ORDER BY time DESC, subject DESC
            LIMIT :limit
        """
        sql_params["limit"] = limit
        items = []
        for row in self.db.fetch(sql, sql_params):
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
        return items, hourly_gaps(self.db, query.window, subject)
