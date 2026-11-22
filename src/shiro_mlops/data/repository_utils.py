"""Shared database repository utility functions for datetime and payload serialization."""

import json
from datetime import datetime
from typing import Any

import pandas as pd

from shiro_mlops.core.datetime_utils import taiwan_local_to_utc, utc_to_taiwan_datetime


def to_python_datetime(value: Any) -> datetime:
    """Normalize pandas/SQLAlchemy timestamps to timezone-naive Python datetime."""
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("UTC").tz_localize(None)
    return timestamp.to_pydatetime()


def taiwan_instant_to_utc(value: datetime | None) -> datetime | None:
    """Convert a Taiwan-local datetime to a timezone-naive UTC datetime."""
    if value is None:
        return None
    return to_python_datetime(taiwan_local_to_utc(pd.Series([value])).iloc[0])


def utc_instant_to_taiwan(value: Any) -> datetime | None:
    """Convert a UTC database timestamp to a timezone-naive Taiwan-local datetime."""
    if value is None or pd.isna(value):
        return None
    return to_python_datetime(utc_to_taiwan_datetime(pd.Series([value])).iloc[0])


def serialize_raw_payload(payload: Any) -> str:
    """Serialize a source payload to JSON text for JSONB or SQLite TEXT storage.

    String payloads such as XML responses become JSON string literals, so the
    stored text is always valid JSON and round-trips through
    ``deserialize_raw_payload``.
    """
    return json.dumps(payload, ensure_ascii=False)


def deserialize_raw_payload(payload: Any) -> Any:
    """Deserialize raw API payload from JSON text or pass through parsed objects."""
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError("raw_payload must contain valid JSON") from exc
    return payload


def resolve_snapshot_source_time(
    source_time_raw: datetime | None,
    observed_at_raw: datetime | None,
    default_observed_at: datetime,
) -> datetime:
    """Resolve snapshot source timestamp with fallback to observation timestamp."""
    return (
        utc_instant_to_taiwan(source_time_raw)
        or utc_instant_to_taiwan(observed_at_raw)
        or default_observed_at
    )
