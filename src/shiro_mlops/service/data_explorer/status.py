"""Independent availability, freshness, completeness, and overall status."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Availability = Literal["available", "empty", "unavailable"]
FreshnessState = Literal["fresh", "warning", "unknown"]
Completeness = Literal["complete", "incomplete", "unknown"]
Overall = Literal["healthy", "warning", "critical", "unknown"]

# 超過兩個預期週期未更新才視為過期。
MISSED_CYCLE_WARNING = 2


@dataclass(frozen=True)
class DatasetFreshness:
    """Freshness label plus independent ingestion and source ages."""

    state: FreshnessState
    ingestion_age_seconds: int | None
    source_age_seconds: int | None


def evaluate_freshness(
    *,
    cadence_seconds: int,
    as_of: datetime,
    latest_source_at: datetime | None,
    latest_ingested_at: datetime | None,
) -> DatasetFreshness:
    """Evaluate freshness from cadence; keep ingestion age distinct from source age."""
    if latest_source_at is None or latest_ingested_at is None:
        return DatasetFreshness("unknown", None, None)
    source_age = int((as_of - latest_source_at).total_seconds())
    ingestion_age = int((as_of - latest_ingested_at).total_seconds())
    threshold = cadence_seconds * MISSED_CYCLE_WARNING
    state: FreshnessState = "warning" if source_age > threshold else "fresh"
    return DatasetFreshness(state, ingestion_age, source_age)


def derive_overall(
    availability: Availability,
    freshness: FreshnessState,
    completeness: Completeness,
) -> Overall:
    """Derive a single severity from independent status dimensions."""
    if availability == "unavailable":
        return "critical"
    if availability == "empty":
        return "warning"
    if freshness == "warning" or completeness == "incomplete":
        return "warning"
    if availability == "available" and freshness == "fresh" and completeness == "complete":
        return "healthy"
    return "unknown"
