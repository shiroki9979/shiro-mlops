"""Freshness, completeness and overall severity of a dataset that has rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

FreshnessState = Literal["fresh", "warning"]
Completeness = Literal["complete", "incomplete"]
Overall = Literal["healthy", "warning"]

# 超過兩個預期週期未更新才視為過期。
MISSED_CYCLE_WARNING = 2


@dataclass(frozen=True)
class DatasetFreshness:
    """Freshness label plus independent ingestion and source ages."""

    state: FreshnessState
    ingestion_age_seconds: int
    source_age_seconds: int


def evaluate_freshness(
    *,
    update_interval: timedelta,
    as_of: datetime,
    latest_source_at: datetime,
    latest_ingested_at: datetime,
    arrival_lag: timedelta,
) -> DatasetFreshness:
    """Evaluate freshness from the source's update interval; keep ingestion and source age apart.

    `arrival_lag`, how long after its instant a row is expected stored, is added to the
    threshold, so only missed cycles count, not the wait for the newest one.
    """
    source_age = int((as_of - latest_source_at).total_seconds())
    ingestion_age = int((as_of - latest_ingested_at).total_seconds())
    threshold = update_interval * MISSED_CYCLE_WARNING + arrival_lag
    state: FreshnessState = "warning" if source_age > threshold.total_seconds() else "fresh"
    return DatasetFreshness(state, ingestion_age, source_age)


def derive_overall(freshness: FreshnessState, completeness: Completeness) -> Overall:
    """Derive a single severity from freshness and completeness."""
    if freshness == "warning" or completeness == "incomplete":
        return "warning"
    return "healthy"
