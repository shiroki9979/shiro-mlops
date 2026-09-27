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

    def fetch_rows(
        self,
        query: ExplorerQuery,
        cursor: dict[str, Any] | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        location = query.filters.get("location")
        clauses, sql_params = self.db.time_window("time", query.window)
        clauses.append("source = :source")
        sql_params["source"] = REGIONAL_SNAPSHOT_SUM_SOURCE
        if location:
            clauses.append("location = :location")
            sql_params["location"] = location
        where, order, cursor_params = self.db.page_sql(query, clauses, cursor)
        sql_params.update(cursor_params)
        sql = f"""
            SELECT time, location, load_mw, created_at
            FROM raw_taipower_load
            WHERE {where}
            ORDER BY {order}
            LIMIT :limit
        """
        sql_params["limit"] = limit
        return self.db.fetch(sql, sql_params)

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
                    "location": row["location"],
                    "load_mw": float(row["load_mw"]),
                    "ingested_at": format_taiwan_time(ingested),
                }
            )
        return items, hourly_gaps(self.db, query.window, query.filters.get("location"))
