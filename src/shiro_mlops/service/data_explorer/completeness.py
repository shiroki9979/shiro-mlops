"""Dataset completeness policies for Data Explorer lists and status."""

from __future__ import annotations

from typing import Any

import pandas as pd

from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.query import TimeWindow
from shiro_mlops.service.data_explorer.timefmt import format_taiwan_time
from shiro_mlops.service.data_explorer.values import to_taiwan


def hourly_gaps(db: ExplorerDb, window: TimeWindow, location: str | None) -> list[str]:
    """Return expected hourly slots missing from the persisted load series."""
    clauses = ["time >= :start_time", "time <= :end_time"]
    params: dict[str, Any] = {"start_time": window.as_utc()[0], "end_time": window.as_utc()[1]}
    if location:
        clauses.append("location = :location")
        params["location"] = location
    rows = db.fetch(
        f"SELECT DISTINCT time FROM raw_taipower_load WHERE {' AND '.join(clauses)}",
        params,
    )
    present = {to_taiwan(row["time"]).replace(minute=0, second=0, microsecond=0) for row in rows}
    start = window.start.replace(minute=0, second=0, microsecond=0)
    expected = pd.date_range(start, window.end, freq="h")
    return [
        format_taiwan_time(ts.to_pydatetime())
        for ts in expected
        if ts.to_pydatetime() not in present
    ]
