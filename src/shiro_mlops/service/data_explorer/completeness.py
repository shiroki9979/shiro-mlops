"""Dataset completeness policies for Data Explorer lists and status."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

import pandas as pd

from shiro_mlops.core.config import settings
from shiro_mlops.data.hourly_actual_load import (
    REGIONAL_SNAPSHOT_SUM_SOURCE,
    recent_completed_hours,
)
from shiro_mlops.data.taipower_regional_supply_demand import REGIONAL_SUPPLY_DEMAND_REGIONS
from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.query import TimeWindow
from shiro_mlops.service.data_explorer.timefmt import format_taiwan_time, now_taiwan
from shiro_mlops.service.data_explorer.values import row_time


def gaps_until_now(window: TimeWindow, find_gaps: Callable[[TimeWindow], list[str]]) -> list[str]:
    """Run a list gap finder only over the part of the window that has already happened."""
    elapsed_end = min(window.end, now_taiwan())
    if elapsed_end < window.start:
        return []
    return find_gaps(TimeWindow(window.start, elapsed_end))


def hourly_gaps(db: ExplorerDb, window: TimeWindow, subject: str | None) -> list[str]:
    """Return expected hourly slots missing from the persisted load series."""
    clauses, params = db.time_window("time", window)
    clauses.append("source = :source")
    params["source"] = REGIONAL_SNAPSHOT_SUM_SOURCE
    if subject:
        clauses.append("subject = :subject")
        params["subject"] = subject
    rows = db.fetch(
        f"SELECT DISTINCT time FROM raw_taipower_load WHERE {' AND '.join(clauses)}",
        params,
    )
    present = {row_time(row, "time").replace(minute=0, second=0, microsecond=0) for row in rows}
    start = pd.Timestamp(window.start).ceil("h")
    last_completed = recent_completed_hours(now_taiwan(), 1).start
    expected = pd.date_range(start, min(window.end, last_completed), freq="h")
    return [
        format_taiwan_time(ts.to_pydatetime())
        for ts in expected
        if ts.to_pydatetime() not in present
    ]


def observation_gaps(db: ExplorerDb, window: TimeWindow, station_id: str | None) -> list[str]:
    """Return expected hourly observation slots missing from allowlisted stations."""
    allowlist = list(settings.cwa_locations.values())
    station_ids = [station_id] if station_id else [item.station_id for item in allowlist]
    clauses, params = db.time_window("observed_at", window)
    rows = db.fetch(
        "SELECT observed_at, station_id FROM raw_cwa_station_observation "
        f"WHERE {' AND '.join(clauses)}",
        params,
    )
    present = {
        (
            row_time(row, "observed_at").replace(minute=0, second=0, microsecond=0),
            row["station_id"],
        )
        for row in rows
    }
    start = pd.Timestamp(window.start).ceil("h")
    expected_hours = pd.date_range(start, window.end, freq="h")
    missing = []
    for hour in expected_hours:
        for sid in station_ids:
            if (hour.to_pydatetime(), sid) not in present:
                missing.append(f"{format_taiwan_time(hour.to_pydatetime())}:{sid}")
    return missing


def ten_minute_gaps(db: ExplorerDb, window: TimeWindow) -> list[str]:
    """Return expected 10-minute slots missing from national supply-demand snapshots."""
    clauses, params = db.time_window("observed_at", window)
    rows = db.fetch(
        "SELECT DISTINCT observed_at FROM raw_taipower_supply_demand_snapshot "
        f"WHERE {' AND '.join(clauses)}",
        params,
    )
    present = {row_time(row, "observed_at") for row in rows}
    start = pd.Timestamp(window.start).ceil("10min")
    expected = pd.date_range(start, window.end, freq="10min")
    return [
        format_taiwan_time(ts.to_pydatetime())
        for ts in expected
        if ts.to_pydatetime() not in present
    ]


def regional_slot_map(db: ExplorerDb, window: TimeWindow) -> dict[datetime, set[str]]:
    """Group persisted regional snapshots by observation slot."""
    clauses, params = db.time_window("observed_at", window)
    rows = db.fetch(
        "SELECT observed_at, region FROM raw_taipower_regional_supply_demand_snapshot "
        f"WHERE {' AND '.join(clauses)}",
        params,
    )
    grouped: dict[datetime, set[str]] = {}
    for row in rows:
        grouped.setdefault(row_time(row, "observed_at"), set()).add(row["region"])
    return grouped


def regional_gaps(db: ExplorerDb, window: TimeWindow) -> list[str]:
    """Return expected 10-minute slots holding fewer than all four regions, zero included."""
    slot_regions = regional_slot_map(db, window)
    expected_regions = set(REGIONAL_SUPPLY_DEMAND_REGIONS)
    start = pd.Timestamp(window.start).ceil("10min")
    expected = pd.date_range(start, window.end, freq="10min")
    return [
        format_taiwan_time(ts.to_pydatetime())
        for ts in expected
        if slot_regions.get(ts.to_pydatetime(), set()) != expected_regions
    ]


def missing_regional_identifiers(present: set[str]) -> list[str]:
    """Return allowlisted regions absent from one observation slot."""
    return [name for name in REGIONAL_SUPPLY_DEMAND_REGIONS if name not in present]


def audit_missing_identifiers(
    audit: dict[str, Any] | None,
    field: str,
    *,
    incomplete_placeholder: str | None = None,
) -> list[str]:
    """Return audit missing ids; incomplete headers without ids use a placeholder."""
    if audit is None:
        return []
    missing = [str(item) for item in audit.get(field, [])]
    if incomplete_placeholder and audit.get("status") == "incomplete" and not missing:
        return [incomplete_placeholder]
    return missing
