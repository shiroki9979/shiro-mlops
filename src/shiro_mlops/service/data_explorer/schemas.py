"""Pydantic contracts for Data Explorer status and list envelopes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from shiro_mlops.service.data_explorer.status import (
    Availability,
    Completeness,
    FreshnessState,
    Overall,
)


class DatasetStatus(BaseModel):
    """Explainable operational status for one domain dataset."""

    id: str
    label: str
    availability: Availability
    freshness: FreshnessState
    completeness: Completeness
    overall: Overall
    latest_source_at: str | None = None
    latest_ingested_at: str | None = None
    ingestion_age_seconds: int | None = None
    source_age_seconds: int | None = None
    missing_identifiers: list[str] = Field(default_factory=list)
    missing_slot_count: int = 0
    record_count: int | None = None
    latest_release_stale: bool | None = Field(
        default=None,
        description=(
            "Whether the dataset's newest release was issued more than seven hours ago. "
            "A coarse dataset-level signal; it does not decide whether a single prediction "
            "request degrades, which depends on the version supplying each weather value."
        ),
    )
    href: str


class StatusResponse(BaseModel):
    """Shared dataset status payload for Monitoring and Data Explorer."""

    timezone: Literal["Asia/Taipei"] = "Asia/Taipei"
    datasets: list[DatasetStatus]


class ListEnvelope(BaseModel):
    """Shared cursor pagination envelope for typed list endpoints."""

    items: list[dict[str, Any]]
    next_cursor: str | None = None
    has_more: bool
    missing_slots: list[str] = Field(default_factory=list)
    timezone: Literal["Asia/Taipei"] = "Asia/Taipei"


class SeriesPoint(BaseModel):
    """One bucket start (RFC 3339, +08:00) and its value; `null` marks a missing bucket."""

    t: str
    v: float | None


class Series(BaseModel):
    """Time-ordered points for one whitelisted field and one group key."""

    field: str
    unit: str
    group: dict[str, str] = Field(
        default_factory=dict,
        description="Group column to value, e.g. {'subject': 'nationwide'}; empty when ungrouped.",
    )
    points: list[SeriesPoint]


class SeriesResponse(BaseModel):
    """Bounded chart series for one dataset window, with the bucket actually applied."""

    bucket: Literal["raw", "1h", "1d"]
    agg: Literal["avg", "min", "max"] | None = Field(
        description="Aggregation applied inside each bucket; null for raw, which ignores agg."
    )
    series: list[Series]
    timezone: Literal["Asia/Taipei"] = "Asia/Taipei"
