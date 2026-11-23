"""Freshness, completeness and overall severity of a dataset that has rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
    cadence_seconds: int,
    as_of: datetime,
    latest_source_at: datetime,
    latest_ingested_at: datetime,
) -> DatasetFreshness:
    """Evaluate freshness from cadence; keep ingestion age distinct from source age."""
    source_age = int((as_of - latest_source_at).total_seconds())
    ingestion_age = int((as_of - latest_ingested_at).total_seconds())
    threshold = cadence_seconds * MISSED_CYCLE_WARNING
    state: FreshnessState = "warning" if source_age > threshold else "fresh"
    return DatasetFreshness(state, ingestion_age, source_age)


def derive_overall(freshness: FreshnessState, completeness: Completeness) -> Overall:
    """Derive a single severity from freshness and completeness."""
    if freshness == "warning" or completeness == "incomplete":
        return "warning"
    return "healthy"
